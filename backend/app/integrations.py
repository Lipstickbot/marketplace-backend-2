"""Revocable, single-agent application credentials. No browser session is delegated."""
from datetime import UTC, datetime, timedelta
import hashlib
import re
import secrets
import time
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Path, Request, Response
from pydantic import BaseModel, Field, field_validator

from .business_analytics import LEGACY_SLUG, SLUG as ANALYTICS_SLUG
from .engine_models import RunInput, StoredFile
from .errors import APIError
from .execution import Engine, Store, run_agent
from .file_service import owner_filters
from .marketplace import Business, Client, Token, catalog_agent, one, validated
from .marketplace_models import Agent
from .models import InputModel, Principal, Profile

router = APIRouter(tags=["Application integrations"])
TABLE = "/rest/v1/agent_integrations"
PUBLIC = "id,user_id,company_id,agent_id,agent_slug,name,task,language,file_ids,key_prefix,expires_at,revoked_at,created_at"


class IntegrationCreate(InputModel):
    agent_slug: str = Field(pattern=r"^[a-z][a-z0-9-]{0,79}$")
    name: str = Field(min_length=1, max_length=120)
    task: str = Field(default="", max_length=2000)
    language: Literal["auto", "ru", "kk", "en"] = "auto"
    file_ids: list[UUID] = Field(default_factory=list, max_length=10)
    expires_in_days: int = Field(default=90, ge=1, le=365)

    @field_validator("file_ids")
    @classmethod
    def unique_files(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("Duplicate files")
        return value


class Integration(BaseModel):
    id: UUID
    user_id: UUID
    company_id: UUID
    agent_id: UUID
    agent_slug: str
    name: str
    task: str
    language: str
    file_ids: list[UUID]
    key_prefix: str
    expires_at: datetime
    revoked_at: datetime | None
    created_at: datetime


def owned(user):
    return {"user_id": f"eq.{user.user_id}", "company_id": f"eq.{user.company_id}"}


async def approval(client, token, user, agent):
    rows = await client.request("GET", "/rest/v1/connect_requests", token=token, operation="marketplace",
        params={"company_id": f"eq.{user.company_id}", "agent_id": f"eq.{agent.id}", "status": "eq.approved", "limit": "1"})
    if not isinstance(rows, list) or len(rows) != 1 or rows[0].get("company_id") != str(user.company_id) or rows[0].get("status") != "approved":
        raise APIError(403, "agent_not_connected", "Сначала получите одобрение подключения выбранного агента.")


@router.get("/integrations", response_model=list[Integration])
async def integrations(user: Business, store: Store):
    return await store.request("GET", TABLE, params={**owned(user), "select": PUBLIC, "order": "created_at.desc", "limit": "100"})


@router.post("/integrations", status_code=201)
async def create_integration(body: IntegrationCreate, user: Business, token: Token, client: Client, store: Store, request: Request):
    request.app.state.auth_limiter.check("integration-create:" + str(user.user_id))
    agent = await catalog_agent(client, body.agent_slug, token=token)
    if not agent.engine_slug:
        raise APIError(422, "agent_not_executable", "У агента нет исполнителя.")
    await approval(client, token, user, agent)
    for file_id in body.file_ids:
        row = await one(client, "agent_files", StoredFile, token=token, filters=owner_filters(user, file_id))
        if row.deletion_requested_at or row.purpose not in agent.accepted_file_purposes:
            raise APIError(422, "file_purpose_not_accepted", "Выберите доступные документы для этого агента.")
    key = "keme_" + secrets.token_urlsafe(32)
    payload = {**body.model_dump(mode="json", exclude={"expires_in_days"}), "user_id": str(user.user_id),
        "company_id": str(user.company_id), "agent_id": str(agent.id), "agent_slug": agent.slug, "key_prefix": key[:13],
        "key_hash": hashlib.sha256(key.encode()).hexdigest(),
        "expires_at": (datetime.now(UTC) + timedelta(days=body.expires_in_days)).isoformat()}
    rows = await store.request("POST", TABLE, body=payload)
    if not isinstance(rows, list) or len(rows) != 1:
        raise APIError(502, "integration_not_saved", "Не удалось сохранить подключение.")
    return {"integration": validated(Integration, rows[0]), "api_key": key}


@router.delete("/integrations/{integration_id}", status_code=204)
async def revoke_integration(integration_id: UUID, user: Business, store: Store):
    rows = await store.request("PATCH", TABLE, params={**owned(user), "id": f"eq.{integration_id}"},
                               body={"revoked_at": datetime.now(UTC).isoformat()})
    if not rows:
        raise APIError(404, "not_found", "Подключение не найдено.")
    return Response(status_code=204)


class ScopedReader:
    """Only the existing execution read paths, each with explicit ownership filters."""
    def __init__(self, store, user):
        self.store, self.user = store, user

    async def request(self, method, path, *, params=None, **kwargs):
        params = dict(params or {})
        if method != "GET" or path not in {"/rest/v1/agents", "/rest/v1/connect_requests", "/rest/v1/agent_files"}:
            raise APIError(403, "integration_scope", "Операция вне доступа ключа.")
        if path != "/rest/v1/agents":
            params["company_id"] = f"eq.{self.user.company_id}"
        if path == "/rest/v1/agent_files":
            params["user_id"] = f"eq.{self.user.user_id}"
        return await self.store.request(method, path, params=params)


async def integration_context(request: Request, store: Store, authorization: Annotated[str | None, Header()] = None):
    request.app.state.auth_limiter.check("integration-auth:" + (request.client.host if request.client else "unknown"))
    raw = authorization.removeprefix("Bearer ") if authorization else ""
    if not re.fullmatch(r"keme_[A-Za-z0-9_-]{43}", raw):
        raise APIError(401, "invalid_api_key", "Укажите ключ подключения Keme AI.")
    rows = await store.request("GET", TABLE, params={"key_hash": "eq." + hashlib.sha256(raw.encode()).hexdigest(),
        "revoked_at": "is.null", "expires_at": "gt." + datetime.now(UTC).isoformat(), "limit": "1"})
    if not isinstance(rows, list) or len(rows) != 1:
        raise APIError(401, "invalid_api_key", "Ключ недействителен, отозван или истёк.")
    config = validated(Integration, rows[0])
    if config.revoked_at or config.expires_at <= datetime.now(UTC):
        raise APIError(401, "invalid_api_key", "Ключ недействителен, отозван или истёк.")
    profile_rows = await store.request("GET", "/rest/v1/profiles", params={"id": f"eq.{config.user_id}", "limit": "1"})
    if not isinstance(profile_rows, list) or len(profile_rows) != 1:
        raise APIError(401, "invalid_api_key", "Владелец ключа недоступен.")
    profile = validated(Profile, profile_rows[0])
    if profile.id != config.user_id or profile.role != "business" or config.company_id != config.user_id:
        raise APIError(403, "integration_scope", "Доступ владельца изменился.")
    user = Principal(user_id=profile.id, company_id=config.company_id, role="business", email=None,
                     display_name=profile.display_name, company_name=profile.company_name)
    return config, user


Context = Annotated[tuple, Depends(integration_context)]


def require_matching_agent(agent_slug: Annotated[str, Path(pattern=r"^[a-z][a-z0-9-]{0,79}$")], context: Context):
    config, _ = context
    if config.agent_slug != agent_slug:
        raise APIError(403, "agent_url_not_allowed", "Этот ключ выдан для другого агента. Используйте его Base URL.")


@router.get("/v1/models")
@router.get("/agents/{agent_slug}/v1/models", dependencies=[Depends(require_matching_agent)])
async def models(context: Context):
    config, _ = context
    return {"object": "list", "data": [{"id": "keme/" + config.agent_slug, "object": "model", "created": int(config.created_at.timestamp()), "owned_by": "keme-ai"}]}


class ChatMessage(InputModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ChatInput(InputModel):
    model: str = Field(min_length=1, max_length=100)
    messages: list[ChatMessage] = Field(min_length=1, max_length=12)
    stream: Literal[False] = False


@router.post("/v1/chat/completions")
@router.post("/agents/{agent_slug}/v1/chat/completions", dependencies=[Depends(require_matching_agent)])
async def chat_completion(body: ChatInput, context: Context, engine: Engine, store: Store, request: Request):
    config, user = context
    if body.model != "keme/" + config.agent_slug:
        raise APIError(403, "model_not_allowed", "Ключ разрешает только выбранного агента.")
    reader = ScopedReader(store, user)
    agent = await one(reader, "agents", Agent, filters={"id": f"eq.{config.agent_id}", "status": "eq.published"})
    if agent.slug != config.agent_slug and not (
        config.agent_slug == LEGACY_SLUG and agent.slug == agent.engine_slug == ANALYTICS_SLUG
    ):
        raise APIError(403, "agent_url_not_allowed", "Этот ключ выдан для другого агента.")
    if body.messages[-1].role != "user":
        raise APIError(422, "invalid_messages", "Последнее сообщение должно быть запросом пользователя.")
    instructions = [config.task] + [m.content for m in body.messages if m.role == "system"]
    prefix = "\n".join(x for x in instructions if x)
    message = ("Задача и инструкции:\n" + prefix + "\n\nЗапрос:\n" if prefix else "") + body.messages[-1].content
    if len(message) > 8000:
        raise APIError(422, "message_too_long", "Суммарная длина инструкций и запроса — до 8000 символов.")
    history = [m.model_dump() for m in body.messages[:-1] if m.role != "system"]
    if len(history) > 10:
        raise APIError(422, "history_too_long", "История — до 10 сообщений.")
    result = await run_agent(agent.slug, RunInput(message=message, history=history,
        file_ids=config.file_ids, language=config.language), user, "", reader, engine, store, request)
    execution = result.execution
    return {"id": "chatcmpl-" + str(result.platform_run_id), "object": "chat.completion", "created": int(time.time()),
        "model": body.model, "choices": [{"index": 0, "message": {"role": "assistant", "content": execution.response}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": execution.usage.input_tokens, "completion_tokens": execution.usage.output_tokens, "total_tokens": execution.usage.total_tokens},
        "keme": {"mode": execution.mode, "status": execution.status, "audit_saved": result.audit_saved, "warnings": execution.warnings}}

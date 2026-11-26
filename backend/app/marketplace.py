import json
import re
from typing import Annotated, Literal, TypeVar
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Request
from pydantic import BaseModel, TypeAdapter, ValidationError

from .auth import current_token, gateway, require_roles
from .engine_client import EngineError
from .errors import APIError
from .marketplace_models import (Agent, AgentCreate, AgentPatch, AgentStatus, ConnectCreate, ConnectRequest,
                                 Page, Review, ReviewStatus, Submission, SubmissionCreate, SubmissionReview)
from .models import Principal
from .supabase import SupabaseGateway

router = APIRouter()
Client = Annotated[SupabaseGateway, Depends(gateway)]
Token = Annotated[str, Depends(current_token)]
Business = Annotated[Principal, Depends(require_roles("business"))]
Developer = Annotated[Principal, Depends(require_roles("developer"))]
Publisher = Annotated[Principal, Depends(require_roles("business", "developer"))]
Admin = Annotated[Principal, Depends(require_roles("admin"))]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0, le=10000)]
M = TypeVar("M", bound=BaseModel)


def validated(model: type[M], data) -> M:
    try:
        return model.model_validate(data)
    except ValidationError:
        raise APIError(502, "supabase_contract_error", "Некорректный ответ базы данных.") from None


async def page(client: SupabaseGateway, table: str, model: type[M], limit: int, offset: int,
               *, token: str | None = None, filters: dict | None = None) -> Page[M]:
    data = await client.request("GET", f"/rest/v1/{table}", token=token, operation="marketplace",
        params={"select": "*", "order": "created_at.desc,id.desc", "limit": str(limit + 1),
                "offset": str(offset), **(filters or {})})
    try:
        items = TypeAdapter(list[model]).validate_python(data)
    except ValidationError:
        raise APIError(502, "supabase_contract_error", "Некорректный ответ базы данных.") from None
    return Page(items=items[:limit], limit=limit, offset=offset, has_more=len(items) > limit)


async def one(client: SupabaseGateway, table: str, model: type[M], *, token: str | None = None,
              filters: dict) -> M:
    rows = await client.request("GET", f"/rest/v1/{table}", token=token, operation="marketplace",
                                 params={"select": "*", "limit": "1", **filters})
    if rows == []:
        raise APIError(404, "not_found", "Запись не найдена.")
    if not isinstance(rows, list) or len(rows) != 1:
        raise APIError(502, "supabase_contract_error", "Некорректный ответ базы данных.")
    return validated(model, rows[0])


async def rpc(client: SupabaseGateway, name: str, model: type[M], token: str, body: dict) -> M:
    return validated(model, await client.request("POST", f"/rest/v1/rpc/{name}", token=token,
                                                 body=body, operation="marketplace"))


@router.get("/agents", response_model=Page[Agent], tags=["Catalog"])
async def agents(client: Client, limit: Limit = 20, offset: Offset = 0,
                 category: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
                 status: Literal["published", "coming_soon"] | None = None,
                 q: Annotated[str | None, Query(min_length=1, max_length=120)] = None):
    filters = {"status": f"eq.{status}" if status else "in.(published,coming_soon)"}
    if category is not None:
        filters["category"] = f"eq.{json.dumps(category, ensure_ascii=False)}"
    if q is not None:
        # Escape regex metacharacters, then quote the PostgREST value. Unlike
        # ILIKE, imatch does not reinterpret a literal '*' as a '%' wildcard.
        filters["name"] = f"imatch.{json.dumps(re.escape(q), ensure_ascii=False)}"
    # Deliberately anonymous even if the caller supplies an admin bearer token.
    return await page(client, "agents", Agent, limit, offset, filters=filters)


@router.get("/agents/{slug}", response_model=Agent, tags=["Catalog"])
async def agent(slug: Annotated[str, Path(pattern=r"^[a-z][a-z0-9-]{0,79}$")], client: Client):
    return await one(client, "agents", Agent, filters={"slug": f"eq.{slug}", "status": "in.(published,coming_soon)"})


@router.get("/developer/agents", response_model=Page[Agent], tags=["Developer"])
async def developer_agents(user: Developer, token: Token, client: Client, limit: Limit = 20, offset: Offset = 0):
    return await page(client, "agents", Agent, limit, offset, token=token, filters={"developer_id": f"eq.{user.user_id}"})


@router.get("/connect-requests", response_model=Page[ConnectRequest], tags=["Business"])
async def connect_requests(user: Business, token: Token, client: Client, limit: Limit = 20, offset: Offset = 0,
                           status: ReviewStatus | None = None):
    filters = {"company_id": f"eq.{user.company_id}"}
    if status:
        filters["status"] = f"eq.{status}"
    return await page(client, "connect_requests", ConnectRequest, limit, offset, token=token, filters=filters)


@router.get("/connect-requests/{request_id}", response_model=ConnectRequest, tags=["Business"])
async def connect_request(request_id: UUID, user: Business, token: Token, client: Client):
    return await one(client, "connect_requests", ConnectRequest, token=token,
                     filters={"id": f"eq.{request_id}", "company_id": f"eq.{user.company_id}"})


@router.post("/connect-requests", response_model=ConnectRequest, status_code=201, tags=["Business"])
async def create_connect_request(body: ConnectCreate, user: Business, token: Token, client: Client):
    await one(client, "agents", Agent, token=token, filters={"id": f"eq.{body.agent_id}", "status": "eq.published"})
    rows = await client.request("POST", "/rest/v1/connect_requests", token=token, operation="marketplace", representation=True,
        body={"company_id": str(user.company_id), "requested_by": str(user.user_id), **body.model_dump(mode="json")})
    if not isinstance(rows, list) or len(rows) != 1:
        raise APIError(502, "supabase_contract_error", "Некорректный ответ базы данных.")
    return validated(ConnectRequest, rows[0])


@router.get("/agent-submissions", response_model=Page[Submission], tags=["Publishing"])
async def submissions(user: Publisher, token: Token, client: Client, limit: Limit = 20, offset: Offset = 0,
                      status: ReviewStatus | None = None):
    filters = {"developer_id": f"eq.{user.user_id}"}
    if status:
        filters["status"] = f"eq.{status}"
    return await page(client, "agent_submissions", Submission, limit, offset, token=token, filters=filters)


@router.get("/agent-submissions/{submission_id}", response_model=Submission, tags=["Publishing"])
async def submission(submission_id: UUID, user: Publisher, token: Token, client: Client):
    return await one(client, "agent_submissions", Submission, token=token,
                     filters={"id": f"eq.{submission_id}", "developer_id": f"eq.{user.user_id}"})


@router.post("/agent-submissions", response_model=Submission, status_code=201, tags=["Publishing"])
async def create_submission(body: SubmissionCreate, user: Publisher, token: Token, client: Client):
    rows = await client.request("POST", "/rest/v1/agent_submissions", token=token, operation="marketplace", representation=True,
                                body={"developer_id": str(user.user_id), **body.model_dump(mode="json")})
    if not isinstance(rows, list) or len(rows) != 1:
        raise APIError(502, "supabase_contract_error", "Некорректный ответ базы данных.")
    return validated(Submission, rows[0])


@router.get("/admin/agents", response_model=Page[Agent], tags=["Admin"])
async def admin_agents(user: Admin, token: Token, client: Client, limit: Limit = 20, offset: Offset = 0,
                       status: AgentStatus | None = None):
    return await page(client, "agents", Agent, limit, offset, token=token, filters={"status": f"eq.{status}"} if status else {})


@router.post("/admin/agents", response_model=Agent, status_code=201, tags=["Admin"])
async def create_agent(body: AgentCreate, user: Admin, token: Token, client: Client):
    return await rpc(client, "create_catalog_agent", Agent, token, {"p_data": body.model_dump(mode="json")})


@router.patch("/admin/agents/{agent_id}", response_model=Agent, tags=["Admin"])
async def update_agent(agent_id: UUID, body: AgentPatch, user: Admin, token: Token, client: Client):
    return await rpc(client, "update_catalog_agent", Agent, token,
                     {"p_agent_id": str(agent_id), "p_changes": body.model_dump(mode="json", exclude_unset=True)})


@router.get("/admin/connect-requests", response_model=Page[ConnectRequest], tags=["Admin"])
async def admin_connect_requests(user: Admin, token: Token, client: Client, limit: Limit = 20, offset: Offset = 0,
                                 status: ReviewStatus | None = None):
    return await page(client, "connect_requests", ConnectRequest, limit, offset, token=token,
                      filters={"status": f"eq.{status}"} if status else {})


@router.post("/admin/connect-requests/{request_id}/review", response_model=ConnectRequest, tags=["Admin"])
async def review_connection(request_id: UUID, body: Review, user: Admin, token: Token, client: Client):
    return await rpc(client, "review_connect_request", ConnectRequest, token,
                     {"p_request_id": str(request_id), "p_decision": body.decision, "p_review_note": body.review_note})


@router.get("/admin/agent-submissions", response_model=Page[Submission], tags=["Admin"])
async def admin_submissions(user: Admin, token: Token, client: Client, limit: Limit = 20, offset: Offset = 0,
                            status: ReviewStatus | None = None):
    return await page(client, "agent_submissions", Submission, limit, offset, token=token,
                      filters={"status": f"eq.{status}"} if status else {})


@router.post("/admin/agent-submissions/{submission_id}/review", response_model=Submission, tags=["Admin"])
async def review_submission(submission_id: UUID, body: SubmissionReview, user: Admin, token: Token, client: Client,
                            request: Request):
    if body.engine_slug:
        submission = await one(client, "agent_submissions", Submission, token=token,
                               filters={"id": f"eq.{submission_id}"})
        if submission.status != "pending":
            raise APIError(409, "already_reviewed", "Заявка уже рассмотрена.")
        engine = request.app.state.engine_client
        try:
            metadata = await engine.agent_metadata(body.engine_slug)
        except EngineError as exc:
            if exc.status == 404:
                raise APIError(422, "engine_agent_not_found", "Агент с таким slug не найден в AI Engine.") from None
            raise
        try:
            if not isinstance(metadata, dict) or metadata.get("slug") != body.engine_slug:
                raise ValueError
            card = AgentCreate(slug=body.publication_slug, name=submission.name, description=submission.description,
                category=submission.category, engine_slug=body.engine_slug, status="published",
                supported_languages=metadata["supported_languages"], version=metadata["version"],
                capabilities=metadata["capabilities"], accepted_file_purposes=metadata["accepted_file_purposes"],
                input_schema=metadata["input_schema"], output_schema=metadata["output_schema"])
        except (KeyError, ValueError):
            raise APIError(502, "engine_invalid_agent_metadata", "AI Engine вернул несовместимые настройки агента.") from None
        try:
            data = await client.request("POST", "/rest/v1/rpc/activate_agent_submission", operation="marketplace",
                server_only=True, body={"p_submission_id": str(submission_id), "p_actor": str(user.user_id),
                "p_review_note": body.review_note, "p_card": card.model_dump(mode="json", exclude={"developer_id"})})
        except APIError as exc:
            if exc.code == "duplicate_record":
                raise APIError(409, "agent_binding_conflict", "Адрес карточки или идентификатор AI Engine уже занят.") from None
            raise
        return validated(Submission, data)
    return await rpc(client, "review_agent_submission", Submission, token,
        {"p_submission_id": str(submission_id), "p_decision": body.decision,
         "p_review_note": body.review_note, "p_publication_slug": body.publication_slug})

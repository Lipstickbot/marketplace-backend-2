import logging
from os import getenv
from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Path, Request, Response, UploadFile
from pydantic import ValidationError

from . import architect
from .engine_client import EngineClient, EngineError
from .business_analytics import ANALYTICS_SLUGS, SLUG as ANALYTICS_SLUG, run_local, smoke as smoke_analytics
from .engine_models import EngineRunMetadata, Execution, RunInput, RunRecord, RunResponse, StoredFile
from .errors import APIError
from .file_service import FileService
from .marketplace import Business, Client, Limit, Offset, Token, catalog_agent, one, page, validated
from .marketplace_models import ConnectRequest, Page, Purpose
from .runtime_store import RuntimeStore

logger = logging.getLogger(__name__)
router = APIRouter()


def engine_client(request: Request) -> EngineClient:
    return request.app.state.engine_client


def runtime_store(request: Request) -> RuntimeStore:
    return request.app.state.runtime_store


Engine = Annotated[EngineClient, Depends(engine_client)]
Store = Annotated[RuntimeStore, Depends(runtime_store)]


async def finalize(store, user, row_id, payload) -> bool:
    try:
        rows = await store.request("PATCH", "/rest/v1/agent_runs", params={"id": f"eq.{row_id}",
            "company_id": f"eq.{user.company_id}", "user_id": f"eq.{user.user_id}"}, body=payload)
        if not isinstance(rows, list) or len(rows) != 1:
            raise APIError(503, "audit_not_saved", "Не сохранён результат журнала.")
        return True
    except APIError:
        logger.warning("agent_run_finalize_pending platform_run_id=%s", row_id)
        return False


@router.get("/engine/health", tags=["Execution"])
async def engine_health(engine: Engine):
    data = await engine.request("GET", "/health")
    if not isinstance(data, dict) or data.get("status") not in {"ok", "degraded"}:
        raise EngineError(502, "engine_invalid_response")
    return {key: data.get(key) for key in ("status", "version", "llm_mode", "llm_provider", "llm_billing", "agents")}


@router.get("/health/business-analytics", tags=["Execution"])
async def analytics_health():
    await smoke_analytics()
    return {"status": "ok", "agent": ANALYTICS_SLUG, "revision": getenv("RENDER_GIT_COMMIT")}


@router.post("/agents/{slug}/run", response_model=RunResponse, tags=["Execution"])
async def run_agent(slug: Annotated[str, Path(pattern=r"^[a-z][a-z0-9-]{0,79}$")], body: RunInput,
                    user: Business, token: Token, client: Client, engine: Engine, store: Store, request: Request):
    agent = await catalog_agent(client, slug, token=token)
    if not agent.engine_slug:
        raise APIError(422, "agent_not_executable", "У агента нет подключённого исполнителя.")
    local_analytics = agent.slug in ANALYTICS_SLUGS and agent.engine_slug == agent.slug
    local_architect = agent.engine_slug == architect.SLUG
    local = local_analytics or local_architect
    rows = await client.request("GET", "/rest/v1/connect_requests", token=token, operation="marketplace",
        params={"company_id": f"eq.{user.company_id}", "agent_id": f"eq.{agent.id}", "status": "eq.approved", "limit": "1"})
    if not isinstance(rows, list) or len(rows) != 1:
        raise APIError(403, "agent_not_connected", "Сначала получите одобрение подключения агента.")
    approved = validated(ConnectRequest, rows[0])
    if approved.company_id != user.company_id or approved.agent_id != agent.id or approved.status != "approved":
        raise APIError(403, "agent_not_connected", "Подключение агента не подтверждено.")
    store.require_configured()
    if local_architect:
        architect.require_configured(store.settings)
        architect.validate_input(body)
        request.app.state.auth_limiter.check(f"architect:{user.user_id}")
    if body.dataset and not local_analytics:
        raise APIError(422, "dataset_not_supported", "CSV и TSV доступны для агента «Бизнес-аналитик».")
    if local_analytics and body.file_ids:
        raise APIError(422, "stored_files_not_supported", "Выберите CSV или TSV прямо в форме запуска.")
    if not local:
        engine.token(user)
    files = FileService(client, store, engine)
    engine_ids = []
    for file_id in body.file_ids:
        row = await files.get(user, token, file_id)
        if row.purpose not in agent.accepted_file_purposes:
            raise APIError(422, "file_purpose_not_accepted", "Агент не принимает этот тип документа.")
        engine_ids.append(await files.synchronize(user, row))
    initial = {"company_id": str(user.company_id), "user_id": str(user.user_id), "agent_id": str(agent.id),
               "engine_slug": agent.engine_slug, "status": "running", "file_count": len(body.file_ids) + int(body.dataset is not None),
               "language": body.language if body.language != "auto" else None, "request_id": request.state.request_id}
    created = await store.request("POST", "/rest/v1/agent_runs", body=initial)
    if not isinstance(created, list) or len(created) != 1:
        raise APIError(502, "runtime_storage_invalid_response", "Не удалось зарегистрировать запуск.")
    run = validated(RunRecord, created[0])
    payload = {**body.model_dump(mode="json", exclude={"dataset"}), "file_ids": engine_ids}
    try:
        if local_analytics:
            result = await run_local(body, run.id, agent.slug)
        elif local_architect:
            result = await architect.run(body, run.id, store.settings, request.app.state.architect_http)
        else:
            raw = await engine.request("POST", f"/agents/{agent.engine_slug}/run", user, json=payload)
            try:
                result = Execution.model_validate(raw)
                if result.agent != agent.engine_slug or result.usage.total_tokens != result.usage.input_tokens + result.usage.output_tokens:
                    raise ValueError
            except (ValidationError, ValueError):
                raise EngineError(502, "engine_invalid_response", source_status=200) from None
    except EngineError as error:
        failure = {"status": "engine_unreachable" if error.code in {"engine_timeout", "engine_unreachable"} else "error",
                   "engine_run_id": error.run_id, "http_status": error.source_status, "error_code": error.code[:120]}
        if error.run_id:
            try:
                metadata = EngineRunMetadata.model_validate(await engine.request("GET", f"/runs/{error.run_id}", user, timeout=10))
                if str(metadata.id) == error.run_id and metadata.agent_slug == agent.engine_slug:
                    failure.update(status=metadata.status, agent_version=metadata.agent_version, language=metadata.language,
                        mode=metadata.llm_mode, model=metadata.model, input_tokens=metadata.input_tokens,
                        output_tokens=metadata.output_tokens, estimated_cost=metadata.estimated_cost,
                        execution_time_ms=metadata.execution_time_ms, source_count=metadata.source_count)
            except (APIError, ValidationError):
                pass  # Preserve the original failure; never retry execution.
        audit_saved = await finalize(store, user, run.id, failure)
        error.details = {"platform_run_id": str(run.id), "engine_run_id": error.run_id, "audit_saved": audit_saved}
        raise
    except APIError as error:
        audit_saved = await finalize(store, user, run.id, {"status": "rejected" if error.status < 500 else "error",
            "http_status": error.status, "error_code": error.code, "mode": "none"})
        error.details = {"platform_run_id": str(run.id), "audit_saved": audit_saved}
        raise
    audit_saved = await finalize(store, user, run.id, {"engine_run_id": None if local else str(result.run_id), "agent_version": result.agent_version,
        "status": result.status, "language": result.language, "mode": result.mode, "model": result.model,
        "input_tokens": result.usage.input_tokens, "output_tokens": result.usage.output_tokens,
        "estimated_cost": float(result.usage.estimated_cost) if result.usage.estimated_cost is not None else None,
        "execution_time_ms": result.execution_time_ms, "http_status": 200, "source_count": len(result.sources)})
    return RunResponse(platform_run_id=run.id, audit_saved=audit_saved, execution=result)


@router.get("/runs", response_model=Page[RunRecord], tags=["Execution"])
async def runs(user: Business, token: Token, client: Client, limit: Limit = 20, offset: Offset = 0):
    return await page(client, "agent_runs", RunRecord, limit, offset, token=token,
                      filters={"company_id": f"eq.{user.company_id}", "user_id": f"eq.{user.user_id}"})


@router.get("/runs/{run_id}", response_model=RunRecord, tags=["Execution"])
async def run_record(run_id: UUID, user: Business, token: Token, client: Client):
    return await one(client, "agent_runs", RunRecord, token=token,
                     filters={"id": f"eq.{run_id}", "company_id": f"eq.{user.company_id}", "user_id": f"eq.{user.user_id}"})


@router.post("/files/upload", response_model=StoredFile, status_code=201, tags=["Files"])
async def upload_file(user: Business, client: Client, engine: Engine, store: Store,
                      file: Annotated[UploadFile, File()], purpose: Annotated[Purpose, Form()]):
    return await FileService(client, store, engine).upload(user, file, purpose)


@router.get("/files", response_model=Page[StoredFile], tags=["Files"])
async def list_files(user: Business, token: Token, client: Client, limit: Limit = 20, offset: Offset = 0):
    return await page(client, "agent_files", StoredFile, limit, offset, token=token,
                      filters={"company_id": f"eq.{user.company_id}", "user_id": f"eq.{user.user_id}"})


@router.get("/files/{file_id}", response_model=StoredFile, tags=["Files"])
async def file_info(file_id: UUID, user: Business, token: Token, client: Client, store: Store, engine: Engine):
    return await FileService(client, store, engine).get(user, token, file_id)


@router.get("/files/{file_id}/download", tags=["Files"])
async def download_file(file_id: UUID, user: Business, token: Token, client: Client, store: Store, engine: Engine):
    row = await FileService(client, store, engine).get(user, token, file_id)
    if row.deletion_requested_at:
        raise APIError(409, "file_deletion_pending", "Файл ожидает удаления.")
    content = await store.request("GET", f"/storage/v1/object/{row.bucket_id}/{quote(row.object_path, safe='/')}")
    return Response(content=content, media_type=row.mime_type,
                     headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(row.original_name, safe='')}"})


@router.delete("/files/{file_id}", status_code=204, tags=["Files"])
async def delete_file(file_id: UUID, user: Business, token: Token, client: Client, store: Store, engine: Engine):
    await FileService(client, store, engine).delete(user, token, file_id)
    return Response(status_code=204)

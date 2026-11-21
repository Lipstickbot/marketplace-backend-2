from datetime import UTC, datetime
import logging
from pathlib import PurePosixPath
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import UploadFile

from .engine_client import EngineClient, EngineError
from .engine_models import StoredFile
from .errors import APIError
from .marketplace import one, validated
from .models import Principal
from .runtime_store import RuntimeStore
from .supabase import SupabaseGateway

logger = logging.getLogger(__name__)
MAX_FILE_BYTES = 10 * 1024 * 1024
MIME = {".pdf": "application/pdf", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".txt": "text/plain"}


def owner_filters(user: Principal, file_id: UUID) -> dict:
    return {"id": f"eq.{file_id}", "company_id": f"eq.{user.company_id}", "user_id": f"eq.{user.user_id}"}


class FileService:
    def __init__(self, gateway: SupabaseGateway, store: RuntimeStore, engine: EngineClient):
        self.gateway, self.store, self.engine = gateway, store, engine

    async def get(self, user: Principal, token: str, file_id: UUID) -> StoredFile:
        return await one(self.gateway, "agent_files", StoredFile, token=token, filters=owner_filters(user, file_id))

    async def synchronize(self, user: Principal, row: StoredFile) -> str:
        self.store.require_configured()
        if row.deletion_requested_at is not None:
            raise APIError(409, "file_deletion_pending", "Файл ожидает удаления.")
        if row.engine_file_id:
            try:
                await self.engine.request("GET", f"/files/{row.engine_file_id}", user)
                return str(row.engine_file_id)
            except EngineError as error:
                if error.code != "engine_file_not_found":
                    raise
        content = await self.store.request("GET", f"/storage/v1/object/{row.bucket_id}/{quote(row.object_path, safe='/')}")
        if not isinstance(content, bytes) or len(content) != row.size_bytes or len(content) > MAX_FILE_BYTES:
            raise APIError(502, "file_size_mismatch", "Размер файла в хранилище не совпадает с метаданными.")
        result = await self.engine.request("POST", "/files/upload", user, data={"purpose": row.purpose},
            files={"file": (row.original_name, content, row.mime_type)})
        try:
            engine_file_id = str(UUID(result["id"]))
        except (KeyError, TypeError, ValueError):
            raise EngineError(502, "engine_invalid_response") from None
        try:
            rows = await self.store.request("PATCH", "/rest/v1/agent_files", params=owner_filters(user, row.id),
                body={"engine_file_id": engine_file_id, "engine_synced_at": datetime.now(UTC).isoformat()})
            if not isinstance(rows, list) or len(rows) != 1:
                raise APIError(503, "file_sync_not_saved", "Не удалось сохранить связь файла с движком.")
        except APIError:
            try:
                await self.engine.request("DELETE", f"/files/{engine_file_id}", user)
            except APIError:
                logger.warning("engine_file_cleanup_pending file_id=%s", row.id)
            raise
        return engine_file_id

    async def upload(self, user: Principal, file: UploadFile, purpose: str) -> StoredFile:
        self.store.require_configured()
        self.engine.token(user)  # Fail before writing if the engine is not configured.
        original = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
        extension = PurePosixPath(original).suffix.lower()
        if extension not in MIME or not original or len(original) > 255:
            raise APIError(415, "unsupported_file_type", "Разрешены PDF, DOCX и TXT с именем до 255 символов.")
        chunks, size = [], 0
        try:
            while chunk := await file.read(65536):
                size += len(chunk)
                if size > MAX_FILE_BYTES:
                    raise APIError(413, "file_too_large", "Максимальный размер файла — 10 MiB.")
                chunks.append(chunk)
        finally:
            await file.close()
        if size == 0:
            raise APIError(422, "empty_file", "Файл пуст.")
        file_id = uuid4()
        path = f"{user.company_id}/{user.user_id}/{file_id}/document{extension}"
        await self.store.request("POST", f"/storage/v1/object/agent-files/{path}",
            content=b"".join(chunks), headers={"Content-Type": MIME[extension], "x-upsert": "false"})
        payload = {"id": str(file_id), "company_id": str(user.company_id), "user_id": str(user.user_id),
                   "object_path": path, "original_name": original, "mime_type": MIME[extension],
                   "size_bytes": size, "purpose": purpose}
        try:
            rows = await self.store.request("POST", "/rest/v1/agent_files", body=payload)
            if not isinstance(rows, list) or len(rows) != 1:
                raise APIError(502, "runtime_storage_invalid_response", "Не сохранены метаданные файла.")
            row = validated(StoredFile, rows[0])
        except APIError:
            try:
                await self.store.request("DELETE", "/storage/v1/object/agent-files", body={"prefixes": [path]})
            except APIError:
                logger.warning("storage_upload_cleanup_pending file_id=%s", file_id)
            raise
        try:
            engine_id = await self.synchronize(user, row)
        except APIError as error:
            # Keep the private original + row for safe retry or deletion.
            error.details = {"file_id": str(row.id), "original_saved": True}
            raise
        return row.model_copy(update={"engine_file_id": UUID(engine_id), "engine_synced_at": datetime.now(UTC)})

    async def delete(self, user: Principal, token: str, file_id: UUID):
        row = await self.get(user, token, file_id)
        self.store.require_configured()
        await self.store.request("PATCH", "/rest/v1/agent_files", params=owner_filters(user, file_id),
                                 body={"deletion_requested_at": datetime.now(UTC).isoformat()})
        if row.engine_file_id:
            try:
                await self.engine.request("DELETE", f"/files/{row.engine_file_id}", user)
            except EngineError as error:
                if error.code != "engine_file_not_found":
                    raise
        await self.store.request("DELETE", "/storage/v1/object/agent-files", body={"prefixes": [row.object_path]})
        await self.store.request("DELETE", "/rest/v1/agent_files", params=owner_filters(user, file_id))

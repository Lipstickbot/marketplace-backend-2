import httpx

from .config import Settings
from .errors import APIError


class RuntimeStore:
    """Server-only writes. Never uses a browser token or exposes the secret key."""
    def __init__(self, settings: Settings, client: httpx.AsyncClient):
        self.settings = settings
        self.client = client

    def require_configured(self):
        if not self.settings.supabase_secret_key:
            raise APIError(503, "runtime_storage_not_configured", "Добавьте серверный ключ Supabase в окружение бэкенда.")

    async def request(self, method, path, *, body=None, params=None, content=None, headers=None):
        self.require_configured()
        request_headers = {"apikey": self.settings.supabase_secret_key.get_secret_value(), **(headers or {})}
        if path.startswith("/rest/v1/") and method in {"POST", "PATCH"}:
            request_headers["Prefer"] = "return=representation"
        try:
            response = await self.client.request(method, self.settings.supabase_url + path,
                headers=request_headers, json=body, content=content, params=params)
        except httpx.RequestError:
            raise APIError(503, "runtime_storage_unavailable", "Не удалось сохранить служебные данные.") from None
        if response.status_code == 404 and path.startswith("/storage/") and method == "GET":
            raise APIError(404, "file_blob_not_found", "Оригинал файла отсутствует в хранилище.")
        if response.status_code >= 400:
            raise APIError(503, "runtime_storage_unavailable", "Не удалось сохранить служебные данные.")
        if not 200 <= response.status_code < 300:
            raise APIError(502, "runtime_storage_invalid_response", "Некорректный ответ хранилища.")
        if path.startswith("/storage/") and method == "GET":
            return response.content
        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            raise APIError(502, "runtime_storage_invalid_response", "Некорректный ответ хранилища.") from None

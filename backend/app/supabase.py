import httpx
from pydantic import ValidationError

from .config import Settings
from .errors import APIError, unauthorized
from .models import AuthUser, Principal, Profile, Session, SessionResponse


class SupabaseGateway:
    def __init__(self, settings: Settings, client: httpx.AsyncClient):
        self.settings = settings
        self.client = client

    async def request(self, method: str, path: str, *, token: str | None = None,
                      body: dict | None = None, params: dict | None = None,
                      operation: str = "profile", representation: bool = False):
        headers = {"apikey": self.settings.supabase_publishable_key.get_secret_value()}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if method == "PATCH" or representation:
            headers["Prefer"] = "return=representation"
        try:
            response = await self.client.request(method, self.settings.supabase_url + path,
                                                 headers=headers, json=body, params=params)
        except httpx.RequestError:
            raise APIError(503, "supabase_unavailable", "Сервис авторизации временно недоступен.") from None
        if response.status_code >= 400:
            try:
                payload = response.json()
            except ValueError:
                payload = {}
            code = payload.get("error_code", "") if isinstance(payload, dict) else ""
            if response.status_code == 429:
                retry = response.headers.get("Retry-After", "60")
                retry = retry if retry.isdecimal() and len(retry) < 8 else "60"
                raise APIError(429, "auth_rate_limited", "Слишком много попыток. Попробуйте позже.", {"Retry-After": retry})
            if operation == "marketplace":
                db_code = payload.get("code", "") if isinstance(payload, dict) else ""
                mapped = {
                    "23505": (409, "duplicate_record", "Такая запись уже существует."),
                    "23503": (422, "invalid_reference", "Связанная запись не найдена."),
                    "23514": (422, "invalid_data", "Изменение нарушает правила платформы."),
                    "23502": (422, "invalid_data", "Не заполнены обязательные поля."),
                    "22023": (422, "invalid_data", "Проверьте поля запроса."),
                    "22P02": (422, "invalid_data", "Проверьте поля запроса."),
                    "P0002": (404, "not_found", "Запись не найдена."),
                    "P0001": (409, "already_reviewed", "Заявка уже рассмотрена."),
                    "42501": (403, "role_forbidden", "Недостаточно прав для этого действия."),
                    "PGRST202": (503, "schema_not_ready", "Обновляется схема платформы. Попробуйте позже."),
                }
                if db_code == "28000":
                    raise unauthorized("session_revoked")
                if db_code in mapped:
                    raise APIError(*mapped[db_code])
                if response.status_code == 403:
                    raise APIError(403, "role_forbidden", "Недостаточно прав для этого действия.")
            if response.status_code >= 500:
                raise APIError(503, "supabase_unavailable", "Сервис авторизации временно недоступен.")
            if operation == "login" and code == "email_not_confirmed":
                raise APIError(403, "email_not_confirmed", "Подтвердите адрес электронной почты.")
            if operation == "login":
                raise unauthorized("invalid_credentials")
            if operation == "refresh":
                raise unauthorized("invalid_refresh_token")
            if operation == "oauth":
                raise APIError(400, "google_login_failed", "Не удалось завершить вход через Google. Начните вход ещё раз.")
            if operation == "signup":
                if code == "user_already_exists":
                    return {}  # Preserve signup anti-enumeration semantics.
                allowed = {
                    "weak_password": "Выберите более надёжный пароль.",
                    "email_address_invalid": "Проверьте адрес электронной почты.",
                    "signup_disabled": "Регистрация временно отключена.",
                    "captcha_failed": "Пройдите проверку CAPTCHA повторно.",
                    "email_address_not_authorized": "Отправка писем этому адресу пока не настроена.",
                }
                raise APIError(422, code if code in allowed else "signup_failed",
                               allowed.get(code, "Не удалось завершить регистрацию."))
            if response.status_code in {401, 403}:
                raise unauthorized()
            raise APIError(502, "supabase_contract_error", "Не удалось получить данные профиля.")
        if response.status_code == 204:
            return None
        if not 200 <= response.status_code < 300:
            raise APIError(502, "supabase_contract_error", "Некорректный ответ сервиса авторизации.")
        try:
            return response.json()
        except ValueError:
            raise APIError(502, "supabase_contract_error", "Некорректный ответ сервиса авторизации.") from None

    async def authenticate(self, token: str) -> Principal:
        # A network validation at Auth; never trust decoded client JWT metadata.
        data = await self.request("GET", "/auth/v1/user", token=token)
        try:
            user = AuthUser.model_validate(data)
        except ValidationError:
            raise APIError(502, "supabase_contract_error", "Некорректный ответ сервиса авторизации.") from None
        if user.is_anonymous:
            raise unauthorized()
        active = await self.request("POST", "/rest/v1/rpc/is_current_session_active", token=token, body={})
        if active is not True:
            raise unauthorized("session_revoked")
        rows = await self.request("GET", "/rest/v1/profiles", token=token,
                                  params={"id": f"eq.{user.id}", "select": "id,role,display_name,company_name", "limit": "1"})
        if rows == []:
            raise APIError(403, "profile_missing", "Профиль пользователя не найден.")
        try:
            if not isinstance(rows, list) or len(rows) != 1:
                raise ValueError
            profile = Profile.model_validate(rows[0])
            if profile.id != user.id:
                raise ValueError
        except (ValidationError, ValueError):
            raise APIError(502, "supabase_contract_error", "Некорректный профиль пользователя.") from None
        return Principal(user_id=user.id, email=user.email, role=profile.role,
                         company_id=user.id if profile.role == "business" else None,
                         display_name=profile.display_name, company_name=profile.company_name)

    async def session_response(self, data) -> SessionResponse:
        try:
            session = Session.model_validate(data)
        except ValidationError:
            raise APIError(502, "supabase_contract_error", "Некорректный ответ сервиса авторизации.") from None
        return SessionResponse(session=session, profile=await self.authenticate(session.access_token))

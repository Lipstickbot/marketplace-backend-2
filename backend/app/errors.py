class APIError(Exception):
    def __init__(self, status: int, code: str, message: str, headers: dict[str, str] | None = None,
                 details: dict | None = None):
        self.status = status
        self.code = code
        self.message = message
        self.headers = headers or {}
        self.details = details


def unauthorized(code: str = "invalid_session") -> APIError:
    return APIError(401, code, "Требуется действующая сессия.", {"WWW-Authenticate": "Bearer"})

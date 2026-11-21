from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .errors import APIError, unauthorized
from .models import PlatformRole, Principal
from .supabase import SupabaseGateway

bearer = HTTPBearer(auto_error=False)


def gateway(request: Request) -> SupabaseGateway:
    return request.app.state.gateway


async def current_token(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized("auth_required")
    token = credentials.credentials
    if len(token) > 16384 or any(c.isspace() for c in token):
        raise unauthorized()
    return token


async def current_user(token: Annotated[str, Depends(current_token)],
                       client: Annotated[SupabaseGateway, Depends(gateway)]) -> Principal:
    return await client.authenticate(token)


def require_roles(*roles: PlatformRole):
    async def check(user: Annotated[Principal, Depends(current_user)]) -> Principal:
        if user.role not in roles:
            raise APIError(403, "role_forbidden", "Недостаточно прав для этого действия.")
        return user
    return check

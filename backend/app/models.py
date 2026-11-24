from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, field_validator, model_validator

PlatformRole = Literal["business", "developer", "admin"]


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginInput(InputModel):
    email: EmailStr = Field(max_length=254)
    password: SecretStr = Field(min_length=1, max_length=1024)
    captcha_token: SecretStr | None = Field(default=None, min_length=1, max_length=4096)


class SignupInput(LoginInput):
    password: SecretStr = Field(min_length=12, max_length=128)
    role: Literal["business", "developer"] = "business"
    display_name: str = Field(default="", max_length=120)
    company_name: str = Field(default="", max_length=200)

    @field_validator("display_name", "company_name")
    @classmethod
    def trim_names(cls, value: str) -> str:
        return value.strip()


class RefreshInput(InputModel):
    refresh_token: SecretStr = Field(min_length=1, max_length=8192)


class GoogleStartInput(InputModel):
    code_challenge: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")
    redirect_to: str = Field(min_length=1, max_length=2048)


class GoogleExchangeInput(InputModel):
    auth_code: SecretStr = Field(min_length=1, max_length=2048)
    code_verifier: SecretStr = Field(min_length=43, max_length=128)

    @field_validator("code_verifier")
    @classmethod
    def validate_verifier(cls, value: SecretStr) -> SecretStr:
        import re
        if not re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", value.get_secret_value()):
            raise ValueError("Invalid PKCE verifier")
        return value


class ProfilePatch(InputModel):
    display_name: str | None = Field(default=None, max_length=120)
    company_name: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def validate_patch(self) -> "ProfilePatch":
        if not self.model_fields_set or any(getattr(self, name) is None for name in self.model_fields_set):
            raise ValueError("Provide at least one non-null profile field")
        return self


class AuthUser(BaseModel):
    id: UUID
    email: str | None = None
    is_anonymous: bool = False


class Profile(BaseModel):
    id: UUID
    role: PlatformRole
    display_name: str
    company_name: str


class Principal(BaseModel):
    user_id: UUID
    email: str | None
    role: PlatformRole
    company_id: UUID | None
    display_name: str
    company_name: str


class Session(BaseModel):
    access_token: str = Field(min_length=1)
    refresh_token: str = Field(min_length=1)
    token_type: Literal["bearer"]
    expires_in: int = Field(gt=0)
    expires_at: int | None = None


class SessionResponse(BaseModel):
    session: Session
    profile: Principal


class SignupResponse(BaseModel):
    status: Literal["confirmation_required", "signed_in"]
    session: SessionResponse | None = None

from pathlib import Path
import os
from urllib.parse import urlsplit

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class Settings(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, hide_input_in_errors=True)

    supabase_url: str
    supabase_publishable_key: SecretStr
    cors_origins: tuple[str, ...] = ("http://localhost:3000",)
    oauth_redirect_origins: tuple[str, ...] = (
        "http://localhost:3000", "http://127.0.0.1:8001", "https://keme-ai-platform.onrender.com",
    )
    auth_timeout_seconds: float = Field(default=15, gt=0, le=60)
    auth_requests_per_minute: int = Field(default=10, ge=1, le=1000)
    supabase_secret_key: SecretStr | None = None
    engine_url: str = "http://127.0.0.1:8002"
    engine_jwt_secret: SecretStr | None = None
    engine_jwt_audience: str = "ai-engine"
    engine_jwt_issuer: str = "marketplace-backend"
    engine_jwt_ttl_seconds: int = Field(default=300, ge=60, le=600)
    engine_timeout_seconds: float = Field(default=180, ge=1, le=300)
    runtime_timeout_seconds: float = Field(default=60, ge=5, le=180)
    architect_gemini_api_key: SecretStr | None = None
    architect_gemini_model: str = Field(default="gemini-3.5-flash-lite", pattern=r"^gemini-[a-z0-9][a-z0-9.-]{0,78}$")
    paylink_live_enabled: bool = False
    paylink_live_shop_id: int | None = Field(default=None, gt=0)
    paylink_live_secret_key: SecretStr | None = None
    paylink_notification_base: str | None = None

    @field_validator("supabase_url", "engine_url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if (parsed.scheme != "https" and not (local and parsed.scheme == "http")) or not parsed.hostname:
            raise ValueError("Supabase URL must use HTTPS or loopback HTTP")
        if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
            raise ValueError("Supabase URL must be a base URL without credentials")
        return value.rstrip("/")

    @field_validator("supabase_secret_key")
    @classmethod
    def validate_server_key(cls, value):
        if value is not None and not value.get_secret_value().startswith("sb_secret_"):
            raise ValueError("Use a current Supabase server secret key")
        return value

    @field_validator("paylink_notification_base")
    @classmethod
    def validate_paylink_notification_base(cls, value):
        if value is not None:
            value = cls.validate_url(value)
            if not value.startswith("https://"):
                raise ValueError("PayLink notifications require an HTTPS base URL")
        return value

    @field_validator("engine_jwt_secret")
    @classmethod
    def validate_engine_secret(cls, value):
        if value is not None and len(value.get_secret_value().encode()) < 32:
            raise ValueError("Engine secret must contain at least 32 bytes")
        return value

    @field_validator("supabase_publishable_key")
    @classmethod
    def validate_key(cls, value: SecretStr) -> SecretStr:
        # This stage needs no service/secret key and must preserve user RLS.
        if not value.get_secret_value().startswith("sb_publishable_"):
            raise ValueError("Use a current Supabase publishable key")
        return value

    @field_validator("cors_origins", "oauth_redirect_origins")
    @classmethod
    def validate_origins(cls, origins: tuple[str, ...]) -> tuple[str, ...]:
        for origin in origins:
            parsed = urlsplit(origin)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username:
                raise ValueError("CORS origins must be explicit HTTP origins")
        return origins

    @classmethod
    def from_env(cls) -> "Settings":
        root = Path(__file__).resolve().parents[2]
        values = {**dotenv_values(root / ".env"), **os.environ}
        local_secret = root / ".run" / "engine-jwt.key"
        return cls(
            supabase_url=values.get("SUPABASE_URL", ""),
            supabase_publishable_key=values.get("SUPABASE_PUBLISHABLE_KEY", ""),
            cors_origins=tuple(x.strip() for x in values.get("CORS_ORIGINS", "http://localhost:3000").split(",") if x.strip()),
            oauth_redirect_origins=tuple(x.strip() for x in values.get("OAUTH_REDIRECT_ORIGINS", "http://localhost:3000,http://127.0.0.1:8001,https://keme-ai-platform.onrender.com").split(",") if x.strip()),
            auth_timeout_seconds=values.get("AUTH_TIMEOUT_SECONDS", "15"),
            auth_requests_per_minute=values.get("AUTH_REQUESTS_PER_MINUTE", "10"),
            supabase_secret_key=values.get("SUPABASE_SECRET_KEY") or None,
            engine_url=values.get("ENGINE_URL") or "http://127.0.0.1:8002",
            engine_jwt_secret=values.get("ENGINE_JWT_SECRET") or (local_secret.read_text().strip() if local_secret.exists() else None),
            engine_jwt_audience=values.get("ENGINE_JWT_AUDIENCE") or "ai-engine",
            engine_jwt_issuer=values.get("ENGINE_JWT_ISSUER") or "marketplace-backend",
            engine_jwt_ttl_seconds=values.get("ENGINE_JWT_TTL_SECONDS") or 300,
            engine_timeout_seconds=values.get("ENGINE_TIMEOUT_SECONDS") or 180,
            runtime_timeout_seconds=values.get("RUNTIME_TIMEOUT_SECONDS") or 60,
            architect_gemini_api_key=values.get("ARCHITECT_GEMINI_API_KEY") or None,
            architect_gemini_model=values.get("ARCHITECT_GEMINI_MODEL") or "gemini-3.5-flash-lite",
            paylink_live_enabled=values.get("PAYLINK_LIVE_ENABLED") or False,
            paylink_live_shop_id=values.get("PAYLINK_LIVE_SHOP_ID") or None,
            paylink_live_secret_key=values.get("PAYLINK_LIVE_SECRET_KEY") or None,
            paylink_notification_base=values.get("PAYLINK_NOTIFICATION_BASE") or None,
        )

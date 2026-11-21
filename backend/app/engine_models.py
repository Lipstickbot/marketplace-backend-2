from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from .marketplace_models import Language, Purpose
from .models import InputModel


class HistoryItem(InputModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class RunInput(InputModel):
    message: str = Field(min_length=1, max_length=8000)
    language: Literal["ru", "kk", "en", "auto"] = "auto"
    file_ids: list[UUID] = Field(default_factory=list, max_length=10)
    options: dict = Field(default_factory=dict)
    history: list[HistoryItem] = Field(default_factory=list, max_length=10)

    @field_validator("file_ids")
    @classmethod
    def unique_files(cls, values):
        if len(values) != len(set(values)):
            raise ValueError("Duplicate file IDs are not allowed")
        return values


class Usage(BaseModel):
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    estimated_cost: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    currency: Literal["USD"]


class Source(BaseModel):
    file_id: UUID
    filename: str
    chunk_index: int = Field(ge=0)
    score: float = Field(allow_inf_nan=False)
    excerpt: str


class Execution(BaseModel):
    run_id: UUID
    agent: str
    agent_version: str
    status: Literal["success", "escalation_required", "blocked"]
    response: str
    language: Language
    sources: list[Source]
    usage: Usage
    execution_time_ms: int = Field(ge=0)
    mode: Literal["mock", "none", "openai", "groq", "gemini", "openrouter", "ollama"]
    model: str | None
    data: dict | None
    warnings: list[str]


class RunResponse(BaseModel):
    platform_run_id: UUID
    audit_saved: bool
    execution: Execution


class EngineRunMetadata(BaseModel):
    id: UUID
    agent_slug: str
    agent_version: str
    status: Literal["running", "success", "escalation_required", "blocked", "rejected", "error"]
    language: Language | None = None
    llm_mode: Literal["mock", "none", "openai", "groq", "gemini", "openrouter", "ollama"] | None = None
    model: str | None = None
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    estimated_cost: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    execution_time_ms: int = Field(ge=0)
    source_count: int = Field(default=0, ge=0)


class RunRecord(BaseModel):
    id: UUID
    engine_run_id: UUID | None
    company_id: UUID
    user_id: UUID
    agent_id: UUID
    engine_slug: str
    agent_version: str | None
    status: Literal["running", "success", "escalation_required", "blocked", "rejected", "error", "engine_unreachable"]
    language: Language | None
    mode: str | None
    model: str | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    estimated_cost: Decimal | None
    currency: str
    execution_time_ms: int | None
    http_status: int | None
    error_code: str | None
    request_id: str | None
    file_count: int
    source_count: int
    created_at: datetime
    updated_at: datetime


class StoredFile(BaseModel):
    id: UUID
    company_id: UUID
    user_id: UUID
    bucket_id: Literal["agent-files"]
    object_path: str
    original_name: str
    mime_type: str
    size_bytes: int
    purpose: Purpose
    engine_file_id: UUID | None
    engine_synced_at: datetime | None
    deletion_requested_at: datetime | None
    created_at: datetime
    updated_at: datetime

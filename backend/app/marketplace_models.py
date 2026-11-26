from datetime import datetime
from typing import Annotated, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl, StringConstraints, field_validator, model_validator

from .models import InputModel

Slug = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{0,79}$")]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
Category = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
AgentStatus = Literal["draft", "published", "coming_soon", "archived"]
ReviewStatus = Literal["pending", "approved", "rejected"]
Purpose = Literal["brief", "knowledge_base", "resume", "job_description"]
Language = Literal["ru", "kk", "en"]
T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    limit: int
    offset: int
    has_more: bool


class Agent(BaseModel):
    id: UUID
    slug: str
    name: str
    description: str
    category: str
    status: AgentStatus
    developer_id: UUID | None
    engine_slug: str | None
    version: str | None
    supported_languages: list[Language]
    capabilities: list[str]
    accepted_file_purposes: list[Purpose]
    input_schema: dict
    output_schema: dict
    created_at: datetime
    updated_at: datetime


class AgentCreate(InputModel):
    slug: Slug
    name: Name
    description: str = Field(default="", max_length=10000)
    category: Category
    status: AgentStatus = "draft"
    developer_id: UUID | None = None
    engine_slug: Slug | None = None
    version: str | None = Field(default=None, max_length=80)
    supported_languages: list[Language] = Field(default_factory=lambda: ["ru", "kk", "en"], min_length=1, max_length=3)
    capabilities: list[Annotated[str, StringConstraints(min_length=1, max_length=120)]] = Field(default_factory=list, max_length=50)
    accepted_file_purposes: list[Purpose] = Field(default_factory=list, max_length=4)
    input_schema: dict = Field(default_factory=dict)
    output_schema: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def executable_publication(self):
        if self.status == "published" and not self.engine_slug:
            raise ValueError("Published agents require an engine_slug")
        return self


class AgentPatch(InputModel):
    slug: Slug | None = None
    name: Name | None = None
    description: str | None = Field(default=None, max_length=10000)
    category: Category | None = None
    status: AgentStatus | None = None
    developer_id: UUID | None = None
    engine_slug: Slug | None = None
    version: str | None = Field(default=None, max_length=80)
    supported_languages: list[Language] | None = Field(default=None, min_length=1, max_length=3)
    capabilities: list[Annotated[str, StringConstraints(min_length=1, max_length=120)]] | None = Field(default=None, max_length=50)
    accepted_file_purposes: list[Purpose] | None = Field(default=None, max_length=4)
    input_schema: dict | None = None
    output_schema: dict | None = None

    @model_validator(mode="after")
    def valid_patch(self):
        nullable = {"developer_id", "engine_slug", "version"}
        if not self.model_fields_set or any(getattr(self, key) is None for key in self.model_fields_set - nullable):
            raise ValueError("Provide non-null editable fields")
        return self


class ConnectCreate(InputModel):
    agent_id: UUID
    message: str = Field(default="", max_length=4000)


class ConnectRequest(BaseModel):
    id: UUID
    company_id: UUID
    requested_by: UUID
    agent_id: UUID
    message: str
    status: ReviewStatus
    reviewed_by: UUID | None
    reviewed_at: datetime | None
    review_note: str | None
    created_at: datetime
    updated_at: datetime


class SubmissionCreate(InputModel):
    name: Name
    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10000)]
    category: Category
    repository_url: HttpUrl | None = Field(default=None, max_length=2048)

    @field_validator("repository_url")
    @classmethod
    def https_repository(cls, value):
        if value is not None and (value.scheme != "https" or value.username or value.password):
            raise ValueError("Repository URL must use HTTPS without credentials")
        return value


class Submission(BaseModel):
    id: UUID
    developer_id: UUID
    name: str
    description: str
    category: str
    repository_url: str | None
    status: ReviewStatus
    published_agent_id: UUID | None
    reviewed_by: UUID | None
    reviewed_at: datetime | None
    review_note: str | None
    created_at: datetime
    updated_at: datetime


class Review(InputModel):
    decision: Literal["approved", "rejected"]
    review_note: str | None = Field(default=None, max_length=4000)


class SubmissionReview(Review):
    publication_slug: Slug | None = None
    engine_slug: Slug | None = None

    @model_validator(mode="after")
    def publication_fields(self):
        if self.decision == "approved" and self.publication_slug is None:
            self.publication_slug = self.engine_slug
        if (self.decision == "approved") != (self.publication_slug is not None) or (
            self.decision == "rejected" and self.engine_slug is not None
        ):
            raise ValueError("Publication and engine slugs are only for approval")
        return self

from typing import Literal

from db.models import RequestStatus
from db.repositories.analytics import Endpoint, RequestMetadata, RequestSummary
from pydantic import BaseModel, ConfigDict


class AnalyticsRequestItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    endpoint: Endpoint
    created: int
    model: str
    status: RequestStatus
    stream: bool
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    duration_ms: int
    time_to_first_token_ms: int | None
    generation_duration_ms: int | None
    load_duration_ms: int | None
    finish_reason: str | None
    error_type: str | None
    error_code: str | None

    @classmethod
    def from_metadata(cls, record: RequestMetadata) -> AnalyticsRequestItem:
        known = [
            tokens
            for tokens in (record.prompt_tokens, record.completion_tokens)
            if tokens is not None
        ]
        return cls(
            id=record.external_id,
            endpoint=record.endpoint,
            created=int(record.created_at.timestamp()),
            model=record.model,
            status=record.status,
            stream=record.stream,
            prompt_tokens=record.prompt_tokens,
            completion_tokens=record.completion_tokens,
            total_tokens=sum(known) if known else None,
            duration_ms=record.duration_ms,
            time_to_first_token_ms=record.time_to_first_token_ms,
            generation_duration_ms=record.generation_duration_ms,
            load_duration_ms=record.load_duration_ms,
            finish_reason=record.finish_reason,
            error_type=record.error_type,
            error_code=record.error_code,
        )


class AnalyticsRequestList(BaseModel):
    model_config = ConfigDict(extra="ignore")

    object: Literal["list"]
    data: list[AnalyticsRequestItem]
    first_id: str | None
    last_id: str | None
    has_more: bool


class AnalyticsRequestSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")

    request_count: int
    error_count: int
    prompt_tokens: int
    completion_tokens: int
    avg_duration_ms: float | None
    avg_time_to_first_token_ms: float | None
    avg_generation_duration_ms: float | None

    @classmethod
    def from_summary(cls, summary: RequestSummary) -> AnalyticsRequestSummary:
        return cls(**vars(summary))

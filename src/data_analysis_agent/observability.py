"""Lightweight request-scoped timing and provider-usage observations."""

from __future__ import annotations

import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
from typing import Callable, Iterator, Literal, ParamSpec, TypeVar


LLMCallStatus = Literal["success", "error"]


@dataclass(frozen=True)
class StageObservation:
    """Measured latency for one actually executed pipeline stage."""

    stage: str
    latency_ms: float


@dataclass(frozen=True)
class LLMCallObservation:
    """Compact metadata for one provider call without prompt or response data."""

    stage: str
    model: str
    latency_ms: float
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    status: LLMCallStatus


@dataclass(frozen=True)
class RequestObservability:
    """Request-scoped timings, outcome metadata, and provider usage."""

    request_id: str
    total_latency_ms: float
    route: str | None
    final_status: str
    validation_status: str
    stages: tuple[StageObservation, ...]
    llm_calls: tuple[LLMCallObservation, ...]
    total_prompt_tokens: int | None
    total_completion_tokens: int | None
    total_tokens: int | None


@dataclass
class _RequestCollector:
    request_id: str
    started_at: float
    stages: list[StageObservation] = field(default_factory=list)
    llm_calls: list[LLMCallObservation] = field(default_factory=list)


_CURRENT_COLLECTOR: ContextVar[_RequestCollector | None] = ContextVar(
    "data_analysis_agent_observability_collector",
    default=None,
)
_CURRENT_STAGE: ContextVar[str | None] = ContextVar(
    "data_analysis_agent_observability_stage",
    default=None,
)


@contextmanager
def start_observability_request() -> Iterator[_RequestCollector]:
    """Activate an isolated collector for one product-level request."""

    collector = _RequestCollector(
        request_id=str(uuid.uuid4()),
        started_at=time.perf_counter(),
    )
    token = _CURRENT_COLLECTOR.set(collector)
    try:
        yield collector
    finally:
        _CURRENT_COLLECTOR.reset(token)


@contextmanager
def observe_stage(stage: str) -> Iterator[None]:
    """Measure one executed stage, or behave as a no-op without a request."""

    collector = _CURRENT_COLLECTOR.get()
    if collector is None:
        yield
        return

    started_at = time.perf_counter()
    stage_token = _CURRENT_STAGE.set(stage)
    try:
        yield
    finally:
        latency_ms = max(0.0, (time.perf_counter() - started_at) * 1000.0)
        collector.stages.append(StageObservation(stage, latency_ms))
        _CURRENT_STAGE.reset(stage_token)


_P = ParamSpec("_P")
_R = TypeVar("_R")


def observed_stage(
    stage: str,
) -> Callable[[Callable[_P, _R]], Callable[_P, _R]]:
    """Decorate one component boundary with request-scoped stage timing."""

    def decorate(function: Callable[_P, _R]) -> Callable[_P, _R]:
        @wraps(function)
        def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _R:
            with observe_stage(stage):
                return function(*args, **kwargs)

        return wrapped

    return decorate


def observability_is_active() -> bool:
    """Return whether the current context has an active request collector."""

    return _CURRENT_COLLECTOR.get() is not None


def current_observability_stage() -> str | None:
    """Return the currently executing measured stage, if any."""

    return _CURRENT_STAGE.get()


def record_llm_call(observation: LLMCallObservation) -> None:
    """Append provider metadata to the active request, or no-op when inactive."""

    collector = _CURRENT_COLLECTOR.get()
    if collector is not None:
        collector.llm_calls.append(observation)


def finalize_observability(
    collector: _RequestCollector,
    *,
    route: str | None,
    final_status: str,
    validation_status: str,
) -> RequestObservability:
    """Freeze an active collector into its public request contract."""

    llm_calls = tuple(collector.llm_calls)
    return RequestObservability(
        request_id=collector.request_id,
        total_latency_ms=max(
            0.0,
            (time.perf_counter() - collector.started_at) * 1000.0,
        ),
        route=route,
        final_status=final_status,
        validation_status=validation_status,
        stages=tuple(collector.stages),
        llm_calls=llm_calls,
        total_prompt_tokens=_aggregate_tokens(llm_calls, "prompt_tokens"),
        total_completion_tokens=_aggregate_tokens(
            llm_calls,
            "completion_tokens",
        ),
        total_tokens=_aggregate_tokens(llm_calls, "total_tokens"),
    )


def _aggregate_tokens(
    calls: tuple[LLMCallObservation, ...],
    field_name: Literal["prompt_tokens", "completion_tokens", "total_tokens"],
) -> int | None:
    if not calls:
        return None
    values = tuple(getattr(call, field_name) for call in calls)
    if any(value is None for value in values):
        return None
    return sum(value for value in values if value is not None)

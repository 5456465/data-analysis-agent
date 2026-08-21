"""Minimal HTTP adapter over the existing product-level Agent entry point."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from data_analysis_agent.deepseek_provider import DeepSeekTextToSQLModel
from data_analysis_agent.execution_trace import build_execution_trace
from data_analysis_agent.final_answer_service import (
    FinalAnswerResult,
    answer_question_for_user,
)
from data_analysis_agent.sql_generator import TextToSQLModel


DEFAULT_DATABASE_PATH = Path("data/processed/olist.duckdb")

app = FastAPI(title="Data Analysis Agent API", version="0.1.0")


class HealthResponse(BaseModel):
    """Stable liveness response without external dependency checks."""

    status: Literal["ok"]
    service: Literal["data-analysis-agent"]


class AnalyzeRequest(BaseModel):
    """One English natural-language analysis question."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(strict=True)

    @field_validator("question")
    @classmethod
    def validate_question(cls, question: str) -> str:
        normalized = question.strip()
        if not normalized:
            raise ValueError("question must be a non-empty string.")
        return normalized


class TraceStepResponse(BaseModel):
    """JSON-safe view of one existing execution-trace step."""

    stage: str
    status: str
    summary: str
    details: dict[str, str]


class AnalyzeEvidence(BaseModel):
    """Compact actual execution evidence without prompts or evaluation data."""

    generated_sql: str | None
    repaired_sql: str | None
    planner_sql: str | None
    python_columns: tuple[str, ...]
    trace: tuple[TraceStepResponse, ...]


class AnalyzeResponse(BaseModel):
    """Stable machine-oriented response for a completed Agent call."""

    status: Literal["success", "blocked"]
    answer: str
    route: Literal["sql_only", "sql_then_python"] | None
    validation: Literal["valid", "valid_with_warnings", "invalid"]
    analysis_tool: Literal["describe", "correlation", "calculate_growth"] | None
    warnings: tuple[str, ...]
    evidence: AnalyzeEvidence


def create_model() -> TextToSQLModel:
    """Create the configured provider only while handling an analysis request."""

    return DeepSeekTextToSQLModel()


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Return process liveness without invoking the Agent or its dependencies."""

    return HealthResponse(status="ok", service="data-analysis-agent")


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(request: AnalyzeRequest) -> AnalyzeResponse:
    """Run the existing product workflow once and map its result to JSON."""

    if not DEFAULT_DATABASE_PATH.is_file():
        raise HTTPException(
            status_code=500,
            detail="Analysis database is unavailable.",
        )

    try:
        model = create_model()
        final_result = answer_question_for_user(
            DEFAULT_DATABASE_PATH,
            request.question,
            model,
        )
        return _build_analyze_response(final_result)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Analysis service failed.",
        ) from None


def _build_analyze_response(final_result: FinalAnswerResult) -> AnalyzeResponse:
    result = final_result.validated_result.result
    decision = result.route_decision
    sql_answer = result.sql_answer_result
    plan = result.analysis_plan
    trace = build_execution_trace(final_result)
    return AnalyzeResponse(
        status=final_result.synthesis.status,
        answer=final_result.synthesis.answer,
        route=decision.route,
        validation=final_result.validated_result.validation.status,
        analysis_tool=decision.python_operation,
        warnings=final_result.synthesis.warnings,
        evidence=AnalyzeEvidence(
            generated_sql=(
                sql_answer.generated_sql if sql_answer is not None else None
            ),
            repaired_sql=(
                sql_answer.repaired_sql if sql_answer is not None else None
            ),
            planner_sql=plan.sql if plan is not None else None,
            python_columns=plan.python_columns if plan is not None else (),
            trace=tuple(
                TraceStepResponse(
                    stage=step.stage,
                    status=step.status,
                    summary=step.summary,
                    details=dict(step.details),
                )
                for step in trace.steps
            ),
        ),
    )

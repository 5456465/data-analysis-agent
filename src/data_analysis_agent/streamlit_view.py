"""Pure view helpers for the minimal Streamlit workbench."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from data_analysis_agent.execution_trace import ExecutionTrace
from data_analysis_agent.final_answer_service import FinalAnswerResult
from data_analysis_agent.python_analysis import GrowthPeriod, GrowthResult


DEFAULT_DATABASE_PATH = Path("data/processed/olist.duckdb")
EXAMPLE_QUESTIONS = (
    "2017 年取消了多少订单？",
    "商品成交金额最高的前 5 个商品类别是什么？",
    "商品成交金额每个月的环比变化怎么样？",
)

_TRACE_STAGE_LABELS = {
    "routing": "路由判断",
    "planning": "分析规划",
    "sql_generation": "SQL 生成",
    "sql_repair": "SQL 修复",
    "sql_execution": "SQL 执行",
    "python_analysis": "Python 分析",
    "validation": "结果校验",
    "answer_synthesis": "答案生成",
}
_TRACE_STATUS_LABELS = {
    "success": "成功",
    "warning": "警告",
    "error": "失败",
    "skipped": "跳过",
}


@dataclass(frozen=True)
class StatusSummary:
    """Existing pipeline status labels prepared for compact UI display."""

    route: str
    validation: str
    tool: str


@dataclass(frozen=True)
class GrowthChartData:
    """Ordered period/value evidence copied from an existing GrowthResult."""

    periods: tuple[GrowthPeriod, ...]
    values: tuple[float, ...]


@dataclass(frozen=True)
class AnalysisDetails:
    """Minimal actual SQL and Python-plan evidence for UI rendering."""

    generated_sql: str | None
    repaired_sql: str | None
    planner_sql: str | None
    python_operation: str | None
    python_columns: tuple[str, ...]


def build_status_summary(final_result: FinalAnswerResult) -> StatusSummary:
    """Map existing route, validation, and operation values to UI labels."""

    if not isinstance(final_result, FinalAnswerResult):
        raise TypeError("final_result must be a FinalAnswerResult instance.")

    result = final_result.validated_result.result
    route = result.route_decision.route
    route_label = {
        "sql_only": "仅 SQL",
        "sql_then_python": "SQL → Python",
        None: "N/A",
    }.get(route, str(route))
    validation = final_result.validated_result.validation.status
    validation_label = {
        "valid": "通过",
        "valid_with_warnings": "有警告",
        "invalid": "未通过",
    }[validation]
    operation = result.route_decision.python_operation
    tool_label = {
        "calculate_growth": "环比计算",
        "describe": "描述性统计",
        "correlation": "相关性分析",
        None: "SQL",
    }.get(operation, str(operation))
    return StatusSummary(
        route=route_label,
        validation=validation_label,
        tool=tool_label,
    )


def format_execution_trace_for_display(trace: ExecutionTrace) -> str:
    """Format trace stage/status labels in Chinese without changing its contract."""

    if not isinstance(trace, ExecutionTrace):
        raise TypeError("trace must be an ExecutionTrace instance.")

    blocks: list[str] = []
    for step in trace.steps:
        stage = _TRACE_STAGE_LABELS.get(step.stage, step.stage)
        status = _TRACE_STATUS_LABELS.get(step.status, step.status)
        lines = [f"{stage} [{status}]", f"  summary: {step.summary}"]
        lines.extend(f"  {key}: {value}" for key, value in step.details)
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"


def extract_growth_chart_data(
    final_result: FinalAnswerResult,
) -> GrowthChartData | None:
    """Return unmodified ordered period/value evidence for a growth chart."""

    if not isinstance(final_result, FinalAnswerResult):
        raise TypeError("final_result must be a FinalAnswerResult instance.")

    python_result = final_result.validated_result.result.python_result
    payload = python_result.result if python_result is not None else None
    if not isinstance(payload, GrowthResult) or not payload.points:
        return None
    return GrowthChartData(
        periods=tuple(point.period for point in payload.points),
        values=tuple(point.value for point in payload.points),
    )


def extract_analysis_details(final_result: FinalAnswerResult) -> AnalysisDetails:
    """Extract actual execution evidence without copying result rows."""

    if not isinstance(final_result, FinalAnswerResult):
        raise TypeError("final_result must be a FinalAnswerResult instance.")

    result = final_result.validated_result.result
    sql_answer = result.sql_answer_result
    plan = result.analysis_plan
    return AnalysisDetails(
        generated_sql=(
            sql_answer.generated_sql if sql_answer is not None else None
        ),
        repaired_sql=(
            sql_answer.repaired_sql if sql_answer is not None else None
        ),
        planner_sql=plan.sql if plan is not None else None,
        python_operation=plan.python_operation if plan is not None else None,
        python_columns=plan.python_columns if plan is not None else (),
    )


def synthesis_is_blocked(final_result: FinalAnswerResult) -> bool:
    """Return the existing synthesis disposition without reinterpretation."""

    return final_result.synthesis.status == "blocked"


def primary_answer_text(final_result: FinalAnswerResult) -> str:
    """Prefer an available narrative while preserving deterministic fallback."""

    if not isinstance(final_result, FinalAnswerResult):
        raise TypeError("final_result must be a FinalAnswerResult instance.")

    narrative = final_result.natural_language_answer
    if narrative is not None and narrative.answer is not None:
        return narrative.answer
    return final_result.synthesis.answer


def synthesis_warnings(final_result: FinalAnswerResult) -> tuple[str, ...]:
    """Return synthesis warnings unchanged for UI display."""

    return final_result.synthesis.warnings

"""Generate SQL preparation plans for controlled Python analysis.

This module does not execute SQL or Python. Future orchestration must also
reject truncated SQL results before passing rows to the Python analysis tool.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from data_analysis_agent.metric_catalog import format_business_semantics_context
from data_analysis_agent.observability import observed_stage
from data_analysis_agent.schema import DatabaseSchema
from data_analysis_agent.sql_generator import TextToSQLModel, format_schema_context


PythonPlanOperation = Literal["describe", "correlation", "calculate_growth"]
PythonAnalysisPlanStatus = Literal["success", "error"]
PythonAnalysisPlanErrorCode = Literal[
    "invalid_argument",
    "invalid_model_output",
    "model_error",
    "unsupported_operation",
    "invalid_analysis_plan",
]

_SUPPORTED_OPERATIONS = frozenset(
    {"describe", "correlation", "calculate_growth"}
)
_DESCRIBE_FUNCTIONS = frozenset(
    {
        "avg",
        "max",
        "mean",
        "median",
        "min",
        "quantile_cont",
        "quantile_disc",
        "std",
        "stddev",
        "stddev_pop",
        "stddev_samp",
        "var_pop",
        "var_samp",
        "variance",
    }
)
_CORRELATION_FUNCTIONS = frozenset(
    {"corr", "correlation", "covar_pop", "covar_samp", "covariance"}
)
_GROWTH_FUNCTIONS = frozenset({"lag", "lead"})
_GROWTH_DERIVED_IDENTIFIERS = frozenset(
    {
        "absolute_change",
        "growth_rate",
        "growth",
        "growth_percentage",
        "change",
        "decline",
        "mom",
        "mom_change",
        "mom_growth",
        "month_over_month_change",
        "month_over_month_growth",
        "percentage_change",
        "percentage_growth",
        "percent_change",
        "percent_growth",
        "period_over_period_change",
        "period_over_period_growth",
        "previous_value",
    }
)
_FUNCTION_CALL_PATTERN = re.compile(r"\b([a-z_][a-z0-9_]*)\s*\(", re.IGNORECASE)
_IDENTIFIER_PATTERN = re.compile(r"\b([a-z_][a-z0-9_]*)\b", re.IGNORECASE)
_ORDER_BY_PATTERN = re.compile(r"\border\s+by\b", re.IGNORECASE)
_SELECT_PROJECTION_PATTERN = re.compile(
    r"\bselect\b(.*?)\bfrom\b",
    re.IGNORECASE | re.DOTALL,
)
_PREVIOUS_VALUE_PATTERN = re.compile(
    r"\b(?:prev|previous)(?:_value)?\b|\b(?:prev|previous)\s*\.",
    re.IGNORECASE,
)
_ARITHMETIC_PATTERN = re.compile(r"[+*/-]")
_SQL_NON_CODE_PATTERN = re.compile(
    r"'(?:''|[^'])*'|--[^\n]*(?:\n|$)|/\*.*?\*/",
    re.DOTALL,
)


@dataclass(frozen=True)
class PythonAnalysisPlanError:
    """Structured error returned when a valid analysis plan is unavailable."""

    code: PythonAnalysisPlanErrorCode
    message: str


@dataclass(frozen=True)
class PythonAnalysisPlan:
    """SQL retrieval contract for one later controlled Python operation."""

    question: str
    python_operation: str
    sql: str | None
    python_columns: tuple[str, ...]
    status: PythonAnalysisPlanStatus
    error: PythonAnalysisPlanError | None


def build_python_analysis_plan_prompt(
    question: str,
    schema: DatabaseSchema,
    python_operation: PythonPlanOperation,
) -> str:
    """Build the grounded English prompt for one SQL-to-Python plan."""

    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be a non-empty string.")
    if not isinstance(schema, DatabaseSchema):
        raise TypeError("schema must be a DatabaseSchema instance.")
    if python_operation not in _SUPPORTED_OPERATIONS:
        raise ValueError(f"Unsupported Python operation: {python_operation!r}")

    if python_operation == "correlation":
        operation_rules = (
            "- Return exactly two numeric series for Pearson correlation.\n"
            "- python_columns must contain exactly two distinct SQL output column names.\n"
            "- SQL must not call CORR, covariance, regression, or another function "
            "that calculates the final relationship."
        )
    elif python_operation == "calculate_growth":
        operation_rules = (
            "- SQL must return one chronologically ordered row per requested period.\n"
            "- SQL prepares a period-value series at the requested time grain.\n"
            "- python_columns must contain exactly two distinct SQL output column names.\n"
            "- The first Python column is the period column.\n"
            "- The second Python column is the aggregated numeric metric.\n"
            "- SQL may aggregate the business metric using SUM, AVG, COUNT, or "
            "another appropriate aggregate and GROUP BY the period.\n"
            "- SQL must preserve the business metric's actual fact population.\n"
            "- Missing fact rows must not automatically become numeric zero.\n"
            "- Do not manufacture zero-valued periods with LEFT JOIN plus COALESCE "
            "unless the business semantics explicitly require zero filling.\n"
            "- The numeric metric column should represent valid metric observations.\n"
            "- A NULL metric observation means missing, not numeric zero.\n"
            "- If a join can produce a period whose aggregated metric is NULL because "
            "no metric facts exist, prefer filtering that missing metric observation "
            "out rather than manufacturing a zero value.\n"
            "- No specific JOIN type is required; choose an appropriate join population, "
            "WHERE, HAVING, or fact-table-driven aggregation for the metric.\n"
            "- SQL must not use LAG, LEAD, current-versus-previous arithmetic, or "
            "calculate period-over-period, month-over-month, percentage change, "
            "absolute_change, previous_value, or growth_rate.\n"
            "- Python calculate_growth owns previous_value, absolute_change, and "
            "growth_rate."
        )
    else:
        operation_rules = (
            "- Return raw numeric values for one or more columns.\n"
            "- python_columns must contain at least one distinct SQL output column name.\n"
            "- SQL must not call AVG, STDDEV, MEDIAN, MIN, MAX, quantile, variance, "
            "or another function that calculates the requested descriptive statistics."
        )

    return f"""You prepare one DuckDB SQL result for a controlled Python analysis operation.

The SQL step only retrieves, joins, filters, projects, and reasonably shapes tabular data. Python performs the final analysis. Do not perform the requested Python operation in SQL.

General SQL rules:
- Use only tables, views, and columns present in the schema context.
- Generate exactly one read-only SELECT or WITH ... SELECT query.
- Do not invent tables or source columns.
- Do not read external files or use external resources.
- Alias every analysis output so each python_columns value exactly matches a column name returned by the SQL query.
- Do not execute SQL or Python and do not answer the user's question.

Requested Python operation: {python_operation}
Operation-specific rules:
{operation_rules}

Return exactly one JSON object in one of these forms:
{{"status":"success","sql":"SELECT ...","python_columns":["column_name"]}}
{{"status":"error","error":"Reason a reliable analysis plan cannot be generated."}}

Business semantics context:
{format_business_semantics_context()}

Schema context:
{format_schema_context(schema)}

User question:
{question}
"""


@observed_stage("planning")
def generate_python_analysis_plan(
    question: str,
    schema: DatabaseSchema,
    python_operation: str,
    model: TextToSQLModel,
) -> PythonAnalysisPlan:
    """Generate and validate one SQL preparation plan without executing it."""

    if not isinstance(question, str) or not question.strip():
        return _error_plan(
            question,
            python_operation,
            "invalid_argument",
            "question must be a non-empty string.",
        )
    if not isinstance(schema, DatabaseSchema):
        return _error_plan(
            question,
            python_operation,
            "invalid_argument",
            "schema must be a DatabaseSchema instance.",
        )
    if not isinstance(python_operation, str) or not python_operation.strip():
        return _error_plan(
            question,
            python_operation,
            "invalid_argument",
            "python_operation must be a non-empty string.",
        )
    if python_operation not in _SUPPORTED_OPERATIONS:
        return _error_plan(
            question,
            python_operation,
            "unsupported_operation",
            f"Unsupported Python operation: {python_operation}",
        )
    if not callable(model):
        return _error_plan(
            question,
            python_operation,
            "invalid_argument",
            "model must be callable.",
        )

    prompt = build_python_analysis_plan_prompt(
        question,
        schema,
        python_operation,
    )
    try:
        model_output = model(prompt)
    except Exception as exc:
        return _error_plan(
            question,
            python_operation,
            "model_error",
            str(exc),
        )

    try:
        payload = _parse_model_output(model_output)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        return _error_plan(
            question,
            python_operation,
            "invalid_model_output",
            str(exc),
        )

    status = payload.get("status")
    if status == "error":
        message = payload.get("error")
        if not isinstance(message, str) or not message.strip():
            return _error_plan(
                question,
                python_operation,
                "invalid_model_output",
                "Error model output must contain a non-empty error string.",
            )
        return _error_plan(
            question,
            python_operation,
            "invalid_analysis_plan",
            message,
        )
    if status != "success":
        return _error_plan(
            question,
            python_operation,
            "invalid_model_output",
            "Model output status must be 'success' or 'error'.",
        )

    if "sql" not in payload:
        return _error_plan(
            question,
            python_operation,
            "invalid_model_output",
            "Successful model output must contain sql.",
        )
    sql = payload["sql"]
    if not isinstance(sql, str) or not sql.strip():
        return _error_plan(
            question,
            python_operation,
            "invalid_model_output",
            "sql must be a non-empty string.",
        )

    if "python_columns" not in payload:
        return _error_plan(
            question,
            python_operation,
            "invalid_model_output",
            "Successful model output must contain python_columns.",
        )
    columns = payload["python_columns"]
    if not isinstance(columns, list) or any(
        not isinstance(column, str) or not column.strip() for column in columns
    ):
        return _error_plan(
            question,
            python_operation,
            "invalid_model_output",
            "python_columns must be a JSON array of non-empty strings.",
        )
    python_columns = tuple(columns)

    plan_error = _validate_analysis_contract(
        sql,
        python_columns,
        python_operation,
    )
    if plan_error is not None:
        return _error_plan(
            question,
            python_operation,
            "invalid_analysis_plan",
            plan_error,
        )

    return PythonAnalysisPlan(
        question=question,
        python_operation=python_operation,
        sql=sql,
        python_columns=python_columns,
        status="success",
        error=None,
    )


def _validate_analysis_contract(
    sql: str,
    python_columns: tuple[str, ...],
    python_operation: str,
) -> str | None:
    if not python_columns:
        return "python_columns must contain at least one column."
    if len(python_columns) != len(set(python_columns)):
        return "python_columns must contain distinct column names."
    if python_operation in {"correlation", "calculate_growth"} and len(
        python_columns
    ) != 2:
        return f"{python_operation} requires exactly two python_columns."

    function_names = _sql_function_names(sql)
    if python_operation == "correlation":
        forbidden = function_names & _CORRELATION_FUNCTIONS
        forbidden.update(
            name for name in function_names if name.startswith("regr_")
        )
    elif python_operation == "describe":
        forbidden = function_names & _DESCRIBE_FUNCTIONS
    else:
        forbidden = function_names & _GROWTH_FUNCTIONS
        growth_identifiers = _sql_identifiers(sql) & _GROWTH_DERIVED_IDENTIFIERS
        forbidden.update(growth_identifiers)

        if _contains_previous_value_arithmetic(sql):
            return (
                "calculate_growth SQL must prepare values and must not perform "
                "current-versus-previous arithmetic."
            )

        if not _has_order_by(sql):
            return (
                "calculate_growth SQL must return the period-value series in "
                "chronological order with ORDER BY."
            )

    if forbidden:
        functions = ", ".join(sorted(forbidden))
        return (
            "SQL must prepare raw values and must not perform the final "
            f"{python_operation} operation; forbidden SQL term(s): {functions}."
        )
    return None


def _sql_function_names(sql: str) -> set[str]:
    sql_code = _SQL_NON_CODE_PATTERN.sub(" ", sql)
    return {
        match.group(1).lower()
        for match in _FUNCTION_CALL_PATTERN.finditer(sql_code)
    }


def _sql_identifiers(sql: str) -> set[str]:
    sql_code = _SQL_NON_CODE_PATTERN.sub(" ", sql)
    return {
        match.group(1).lower()
        for match in _IDENTIFIER_PATTERN.finditer(sql_code)
    }


def _has_order_by(sql: str) -> bool:
    sql_code = _SQL_NON_CODE_PATTERN.sub(" ", sql)
    return _ORDER_BY_PATTERN.search(sql_code) is not None


def _contains_previous_value_arithmetic(sql: str) -> bool:
    sql_code = _SQL_NON_CODE_PATTERN.sub(" ", sql)
    for projection in _SELECT_PROJECTION_PATTERN.findall(sql_code):
        if _PREVIOUS_VALUE_PATTERN.search(
            projection
        ) and _ARITHMETIC_PATTERN.search(projection):
            return True
    return False


def _parse_model_output(output: object) -> dict[str, object]:
    if isinstance(output, str):
        parsed = json.loads(output)
    elif isinstance(output, Mapping):
        parsed = dict(output)
    else:
        raise TypeError("Model output must be a JSON object or JSON object string.")

    if not isinstance(parsed, dict):
        raise ValueError("Model output must decode to a JSON object.")
    return parsed


def _error_plan(
    question: object,
    python_operation: object,
    code: PythonAnalysisPlanErrorCode,
    message: str,
) -> PythonAnalysisPlan:
    return PythonAnalysisPlan(
        question=question if isinstance(question, str) else repr(question),
        python_operation=(
            python_operation
            if isinstance(python_operation, str)
            else repr(python_operation)
        ),
        sql=None,
        python_columns=(),
        status="error",
        error=PythonAnalysisPlanError(code=code, message=message),
    )

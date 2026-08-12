"""Data Analysis Agent package."""

from data_analysis_agent.gold_questions import GOLD_QUESTIONS, GoldQuestion
from data_analysis_agent.schema import (
    ColumnSchema,
    DatabaseSchema,
    SchemaObject,
    inspect_schema,
)
from data_analysis_agent.sql_executor import (
    DEFAULT_MAX_ROWS,
    SQLExecutionError,
    SQLResult,
    run_readonly_sql,
)


__all__ = [
    "ColumnSchema",
    "DatabaseSchema",
    "DEFAULT_MAX_ROWS",
    "GOLD_QUESTIONS",
    "GoldQuestion",
    "SQLExecutionError",
    "SQLResult",
    "SchemaObject",
    "inspect_schema",
    "run_readonly_sql",
]

__version__ = "0.1.0"

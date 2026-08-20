"""Data Analysis Agent package."""

from data_analysis_agent.deepseek_provider import (
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    DeepSeekTextToSQLModel,
)
from data_analysis_agent.gold_questions import GOLD_QUESTIONS, GoldQuestion
from data_analysis_agent.metric_catalog import (
    BUSINESS_SEMANTICS_V1,
    BusinessSemanticRule,
    format_business_semantics_context,
)
from data_analysis_agent.question_service import QuestionAnswerResult, answer_question
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
from data_analysis_agent.sql_generator import (
    SQLGenerationError,
    SQLGenerationResult,
    build_text_to_sql_prompt,
    format_schema_context,
    generate_sql,
)
from data_analysis_agent.sql_repair import (
    SQLRepairError,
    SQLRepairResult,
    build_sql_repair_prompt,
    repair_sql,
)


__all__ = [
    "BUSINESS_SEMANTICS_V1",
    "BusinessSemanticRule",
    "ColumnSchema",
    "DatabaseSchema",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_MODEL",
    "DEFAULT_MAX_ROWS",
    "DeepSeekTextToSQLModel",
    "GOLD_QUESTIONS",
    "GoldQuestion",
    "QuestionAnswerResult",
    "SQLExecutionError",
    "SQLGenerationError",
    "SQLGenerationResult",
    "SQLResult",
    "SQLRepairError",
    "SQLRepairResult",
    "SchemaObject",
    "answer_question",
    "build_text_to_sql_prompt",
    "build_sql_repair_prompt",
    "format_business_semantics_context",
    "format_schema_context",
    "generate_sql",
    "inspect_schema",
    "repair_sql",
    "run_readonly_sql",
]

__version__ = "0.1.0"

"""Data Analysis Agent package."""

from data_analysis_agent.analysis_planner import (
    PythonAnalysisPlan,
    PythonAnalysisPlanError,
    build_python_analysis_plan_prompt,
    generate_python_analysis_plan,
)
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
from data_analysis_agent.multi_tool_service import (
    ANALYSIS_MAX_ROWS,
    MultiToolQuestionError,
    MultiToolQuestionResult,
    answer_question_with_tools,
)
from data_analysis_agent.python_analysis import (
    ColumnDescription,
    CorrelationResult,
    PythonAnalysisError,
    PythonAnalysisRequest,
    PythonAnalysisResult,
    run_python_analysis,
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
from data_analysis_agent.tool_router import (
    ToolRouteDecision,
    ToolRoutingError,
    build_tool_routing_prompt,
    route_question,
)


__all__ = [
    "BUSINESS_SEMANTICS_V1",
    "ANALYSIS_MAX_ROWS",
    "BusinessSemanticRule",
    "ColumnSchema",
    "ColumnDescription",
    "CorrelationResult",
    "DatabaseSchema",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_MODEL",
    "DEFAULT_MAX_ROWS",
    "DeepSeekTextToSQLModel",
    "GOLD_QUESTIONS",
    "GoldQuestion",
    "MultiToolQuestionError",
    "MultiToolQuestionResult",
    "QuestionAnswerResult",
    "PythonAnalysisPlan",
    "PythonAnalysisPlanError",
    "PythonAnalysisError",
    "PythonAnalysisRequest",
    "PythonAnalysisResult",
    "SQLExecutionError",
    "SQLGenerationError",
    "SQLGenerationResult",
    "SQLResult",
    "SQLRepairError",
    "SQLRepairResult",
    "SchemaObject",
    "ToolRouteDecision",
    "ToolRoutingError",
    "answer_question",
    "answer_question_with_tools",
    "build_python_analysis_plan_prompt",
    "build_text_to_sql_prompt",
    "build_sql_repair_prompt",
    "build_tool_routing_prompt",
    "format_business_semantics_context",
    "format_schema_context",
    "generate_sql",
    "generate_python_analysis_plan",
    "inspect_schema",
    "repair_sql",
    "route_question",
    "run_python_analysis",
    "run_readonly_sql",
]

__version__ = "0.1.0"

"""Minimal Streamlit workbench for the Data Analysis Agent."""

from __future__ import annotations

import streamlit as st

from data_analysis_agent.deepseek_provider import DeepSeekTextToSQLModel
from data_analysis_agent.execution_trace import (
    build_execution_trace,
    format_execution_trace,
)
from data_analysis_agent.final_answer_service import (
    FinalAnswerResult,
    answer_question_for_user,
)
from data_analysis_agent.streamlit_view import (
    DEFAULT_DATABASE_PATH,
    extract_analysis_details,
    synthesis_is_blocked,
    synthesis_warnings,
)


def main() -> None:
    """Render the single-question Streamlit analysis workbench."""

    st.title("Data Analysis Agent")
    st.caption("Ask an English business question about the Olist dataset.")
    question = st.text_area("Question")

    if not st.button("Run analysis"):
        return
    if not question.strip():
        st.warning("Enter an English business question before running analysis.")
        return
    if not DEFAULT_DATABASE_PATH.is_file():
        st.error(f"DuckDB database does not exist: {DEFAULT_DATABASE_PATH}")
        return

    try:
        model = DeepSeekTextToSQLModel()
        final_result = answer_question_for_user(
            DEFAULT_DATABASE_PATH,
            question.strip(),
            model,
        )
        _render_result(final_result)
    except Exception as exc:
        st.error(
            f"Analysis failed ({type(exc).__name__}). "
            "Check local configuration and try again."
        )


def _render_result(final_result: FinalAnswerResult) -> None:
    st.subheader("Final Answer")
    if synthesis_is_blocked(final_result):
        st.error(final_result.synthesis.answer)
    else:
        st.text(final_result.synthesis.answer)

    for warning in synthesis_warnings(final_result):
        st.warning(warning)

    validation = final_result.validated_result.validation
    with st.expander("Validation"):
        st.write(f"Status: {validation.status}")
        for issue in validation.issues:
            st.write(f"{issue.severity} | {issue.code} | {issue.message}")

    trace = build_execution_trace(final_result)
    with st.expander("Execution Trace"):
        st.text(format_execution_trace(trace))

    details = extract_analysis_details(final_result)
    with st.expander("SQL / Analysis Details"):
        if details.generated_sql is not None:
            st.write("Generated SQL")
            st.code(details.generated_sql, language="sql")
        if details.repaired_sql is not None:
            st.write("Repaired SQL")
            st.code(details.repaired_sql, language="sql")
        if details.planner_sql is not None:
            st.write("Planner SQL")
            st.code(details.planner_sql, language="sql")
        if details.python_operation is not None:
            st.write(f"Python operation: {details.python_operation}")
        if details.python_columns:
            st.write(f"Python columns: {', '.join(details.python_columns)}")


if __name__ == "__main__":
    main()

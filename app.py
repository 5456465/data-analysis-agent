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
    EXAMPLE_QUESTIONS,
    build_status_summary,
    extract_analysis_details,
    extract_growth_chart_data,
    synthesis_is_blocked,
    synthesis_warnings,
)


def main() -> None:
    """Render the single-question Streamlit analysis workbench."""

    st.title("Data Analysis Agent")
    st.caption(
        "Ask business questions about the Olist e-commerce dataset. The agent "
        "selects tools, generates safe SQL, performs controlled analysis, "
        "validates results, and exposes execution evidence."
    )
    capability_columns = st.columns(3)
    for column, label in zip(
        capability_columns,
        ("Safe SQL", "Multi-tool Analysis", "Result Validation"),
        strict=True,
    ):
        column.caption(label)

    st.write("Try an example")
    example_columns = st.columns(3)
    for column, example in zip(example_columns, EXAMPLE_QUESTIONS, strict=True):
        column.button(
            example,
            on_click=_select_example,
            args=(example,),
            use_container_width=True,
        )

    question = st.text_area("Question", key="question_input")

    if not st.button("Run analysis"):
        return
    if not question.strip():
        st.warning("Enter an English business question before running analysis.")
        return
    if not DEFAULT_DATABASE_PATH.is_file():
        st.error(f"DuckDB database does not exist: {DEFAULT_DATABASE_PATH}")
        return

    try:
        with st.spinner("Running analysis..."):
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


def _select_example(question: str) -> None:
    """Fill the question widget without starting an analysis."""

    st.session_state.question_input = question


def _render_result(final_result: FinalAnswerResult) -> None:
    summary = build_status_summary(final_result)
    status_columns = st.columns(3)
    status_columns[0].metric("Route", summary.route)
    status_columns[1].metric("Validation", summary.validation)
    status_columns[2].metric("Analysis Tool", summary.tool)

    st.subheader("Final Answer")
    if synthesis_is_blocked(final_result):
        st.error(final_result.synthesis.answer)
    else:
        st.text(final_result.synthesis.answer)

    chart_data = extract_growth_chart_data(final_result)
    if chart_data is not None:
        st.subheader("Trend")
        st.line_chart(
            {
                "period": list(chart_data.periods),
                "value": list(chart_data.values),
            },
            x="period",
            y="value",
        )

    for warning in synthesis_warnings(final_result):
        st.warning(warning)

    st.subheader("Analysis Evidence")
    trace = build_execution_trace(final_result)
    with st.expander("Execution Trace"):
        st.text(format_execution_trace(trace))

    validation = final_result.validated_result.validation
    with st.expander("Validation"):
        st.write(f"Status: {validation.status}")
        for issue in validation.issues:
            st.write(f"{issue.severity} | {issue.code} | {issue.message}")

    details = extract_analysis_details(final_result)
    with st.expander("SQL & Tool Details"):
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

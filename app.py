"""Minimal Streamlit workbench for the Data Analysis Agent."""

from __future__ import annotations

import streamlit as st

from data_analysis_agent.deepseek_provider import DeepSeekTextToSQLModel
from data_analysis_agent.execution_trace import build_execution_trace
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
    format_execution_trace_for_display,
    synthesis_is_blocked,
    synthesis_warnings,
)


def main() -> None:
    """Render the single-question Streamlit analysis workbench."""

    st.title("智能数据分析 Agent")
    st.caption(
        "使用自然语言询问 Olist 电商数据中的业务问题。Agent 会自动选择工具、"
        "生成安全 SQL、执行受控分析、验证结果并展示执行证据。"
    )
    capability_columns = st.columns(3)
    for column, label in zip(
        capability_columns,
        ("安全 SQL", "多工具分析", "结果校验"),
        strict=True,
    ):
        column.caption(label)

    st.write("试试示例")
    example_columns = st.columns(3)
    for column, example in zip(example_columns, EXAMPLE_QUESTIONS, strict=True):
        column.button(
            example,
            on_click=_select_example,
            args=(example,),
            use_container_width=True,
        )

    question = st.text_area("业务问题", key="question_input")

    if not st.button("开始分析"):
        return
    if not question.strip():
        st.warning("请输入业务问题后再开始分析。")
        return
    if not DEFAULT_DATABASE_PATH.is_file():
        st.error(f"DuckDB 数据库不存在：{DEFAULT_DATABASE_PATH}")
        return

    try:
        with st.spinner("正在分析..."):
            model = DeepSeekTextToSQLModel()
            final_result = answer_question_for_user(
                DEFAULT_DATABASE_PATH,
                question.strip(),
                model,
                locale="zh-CN",
            )
        _render_result(final_result)
    except Exception as exc:
        st.error(
            f"分析失败（{type(exc).__name__}）。请检查本地配置后重试。"
        )


def _select_example(question: str) -> None:
    """Fill the question widget without starting an analysis."""

    st.session_state.question_input = question


def _render_result(final_result: FinalAnswerResult) -> None:
    summary = build_status_summary(final_result)
    status_columns = st.columns(3)
    for column, label, value in zip(
        status_columns,
        ("执行路径", "结果校验", "分析工具"),
        (summary.route, summary.validation, summary.tool),
        strict=True,
    ):
        column.caption(label)
        column.markdown(f"**{value}**")

    st.subheader("分析结果")
    if synthesis_is_blocked(final_result):
        st.error(final_result.synthesis.answer)
    else:
        st.text(final_result.synthesis.answer)

    chart_data = extract_growth_chart_data(final_result)
    if chart_data is not None:
        st.subheader("趋势")
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

    st.subheader("分析证据")
    trace = build_execution_trace(final_result)
    with st.expander("执行过程"):
        st.text(format_execution_trace_for_display(trace))

    validation = final_result.validated_result.validation
    with st.expander("结果校验"):
        st.write(f"状态：{validation.status}")
        for issue in validation.issues:
            st.write(f"{issue.severity} | {issue.code} | {issue.message}")

    details = extract_analysis_details(final_result)
    with st.expander("SQL 与工具详情"):
        if details.generated_sql is not None:
            st.write("生成 SQL")
            st.code(details.generated_sql, language="sql")
        if details.repaired_sql is not None:
            st.write("修复后 SQL")
            st.code(details.repaired_sql, language="sql")
        if details.planner_sql is not None:
            st.write("Planner SQL")
            st.code(details.planner_sql, language="sql")
        if details.python_operation is not None:
            st.write(f"Python 操作：{details.python_operation}")
        if details.python_columns:
            st.write(f"Python 输入列：{', '.join(details.python_columns)}")


if __name__ == "__main__":
    main()

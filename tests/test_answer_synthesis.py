from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from data_analysis_agent.answer_synthesis import AnswerSynthesis, synthesize_answer
from data_analysis_agent.multi_tool_service import (
    MultiToolQuestionError,
    MultiToolQuestionResult,
)
from data_analysis_agent.python_analysis import (
    ColumnDescription,
    CorrelationResult,
    GrowthPoint,
    GrowthResult,
    PythonAnalysisResult,
)
from data_analysis_agent.result_validation import ResultValidation, ValidationIssue
from data_analysis_agent.sql_executor import SQLResult
from data_analysis_agent.tool_router import ToolRouteDecision
from data_analysis_agent.validated_question_service import ValidatedQuestionResult


def _sql_result(
    columns: tuple[str, ...] = ("value",),
    rows: tuple[tuple[object, ...], ...] = ((99441,),),
    *,
    executed_sql: str = "SELECT value",
) -> SQLResult:
    return SQLResult(
        executed_sql=executed_sql,
        columns=columns,
        rows=rows,
        returned_row_count=len(rows),
        truncated=False,
        status="success",
        error=None,
    )


def _multi_tool_result(
    *,
    route: str = "sql_only",
    operation: str | None = None,
    sql_result: SQLResult | None = None,
    python_payload: object | None = None,
    status: str = "success",
    question: str = "test question",
) -> MultiToolQuestionResult:
    python_result = (
        PythonAnalysisResult(
            operation=operation or "unknown",
            status="success",
            result=python_payload,
            error=None,
        )
        if route == "sql_then_python"
        else None
    )
    return MultiToolQuestionResult(
        question=question,
        route_decision=ToolRouteDecision(
            question=question,
            route=route,
            python_operation=operation,
            reason="internal router reason",
            status="success",
            error=None,
        ),
        status=status,
        sql_answer_result=None,
        analysis_plan=None,
        sql_result=sql_result or _sql_result(),
        python_result=python_result,
        error=(
            None
            if status == "success"
            else MultiToolQuestionError("sql_execution_error", "query failed")
        ),
    )


def _validated(
    result: MultiToolQuestionResult,
    *,
    status: str = "valid",
    issues: tuple[ValidationIssue, ...] = (),
) -> ValidatedQuestionResult:
    return ValidatedQuestionResult(
        result=result,
        validation=ResultValidation(status=status, issues=issues),
    )


def _growth_result() -> GrowthResult:
    return GrowthResult(
        points=(
            GrowthPoint("2020-01", 10.0, None, None, None),
            GrowthPoint("2020-02", 15.0, 10.0, 5.0, 0.5),
            GrowthPoint("2020-04", 12.0, None, None, None),
        ),
        period_count=3,
    )


def test_invalid_validation_blocks_answer() -> None:
    result = _multi_tool_result(status="sql_execution_error")
    validation = _validated(
        result,
        status="invalid",
        issues=(ValidationIssue("unsuccessful_pipeline", "error", "Failed."),),
    )

    synthesis = synthesize_answer(validation)

    assert synthesis.status == "blocked"
    assert "cannot be generated" in synthesis.answer
    assert "sql_execution_error" in synthesis.answer
    assert "query failed" in synthesis.answer


def test_valid_sql_scalar_is_displayed_without_recalculation() -> None:
    synthesis = synthesize_answer(_validated(_multi_tool_result()))

    assert synthesis.status == "success"
    assert synthesis.answer == "Result: 99441"


def test_sql_scalar_none_is_displayed_as_null() -> None:
    result = _multi_tool_result(sql_result=_sql_result(rows=((None,),)))

    assert synthesize_answer(_validated(result)).answer == "Result: NULL"


def test_sql_scalar_ratio_is_not_converted_to_percentage() -> None:
    result = _multi_tool_result(sql_result=_sql_result(rows=((0.123,),)))

    answer = synthesize_answer(_validated(result)).answer

    assert answer == "Result: 0.123"
    assert "%" not in answer


def test_sql_multi_row_is_a_deterministic_table() -> None:
    result = _multi_tool_result(
        sql_result=_sql_result(
            ("order_status", "order_count"),
            (("delivered", 96478), ("shipped", 1107)),
        )
    )

    answer = synthesize_answer(_validated(result)).answer

    assert answer == (
        "order_status | order_count\n"
        "delivered | 96478\n"
        "shipped | 1107"
    )


def test_sql_multi_column_header_preserves_column_order() -> None:
    result = _multi_tool_result(
        sql_result=_sql_result(("first", "second", "third"), ((1, 2, 3),))
    )

    assert synthesize_answer(_validated(result)).answer.splitlines()[0] == (
        "first | second | third"
    )


def test_empty_result_succeeds_and_preserves_warning() -> None:
    warning = ValidationIssue("empty_result", "warning", "SQLResult contains no rows.")
    result = _multi_tool_result(sql_result=_sql_result(("state",), ()))

    synthesis = synthesize_answer(
        _validated(result, status="valid_with_warnings", issues=(warning,))
    )

    assert synthesis.status == "success"
    assert synthesis.answer == "state"
    assert synthesis.warnings == ("SQLResult contains no rows.",)


def test_describe_result_displays_existing_fields() -> None:
    descriptions = (
        ColumnDescription("payment_value", 4, 12.5, 2.5, 9.0, 12.0, 17.0),
    )
    result = _multi_tool_result(
        route="sql_then_python",
        operation="describe",
        python_payload=descriptions,
    )

    answer = synthesize_answer(_validated(result)).answer

    assert answer == (
        "Column: payment_value\n"
        "Count: 4\n"
        "Mean: 12.5\n"
        "Sample std: 2.5\n"
        "Min: 9.0\n"
        "Median: 12.0\n"
        "Max: 17.0"
    )


def test_correlation_result_displays_value_and_paired_count_only() -> None:
    result = _multi_tool_result(
        route="sql_then_python",
        operation="correlation",
        python_payload=CorrelationResult("price", "freight", 0.414, 1000),
    )

    answer = synthesize_answer(_validated(result)).answer

    assert answer == "Correlation: 0.414\nPaired rows: 1000"
    assert "strong" not in answer.lower()
    assert "weak" not in answer.lower()


def test_growth_result_displays_complete_table() -> None:
    result = _multi_tool_result(
        route="sql_then_python",
        operation="calculate_growth",
        python_payload=_growth_result(),
    )

    answer = synthesize_answer(_validated(result)).answer

    assert answer.splitlines() == [
        "Period | Value | Previous | Absolute Change | Growth Rate",
        "2020-01 | 10.0 | NULL | NULL | NULL",
        "2020-02 | 15.0 | 10.0 | 5.0 | 0.5",
        "2020-04 | 12.0 | NULL | NULL | NULL",
        "Period count: 3",
    ]


def test_growth_baseline_none_is_null() -> None:
    result = _multi_tool_result(
        route="sql_then_python",
        operation="calculate_growth",
        python_payload=_growth_result(),
    )

    first_point = synthesize_answer(_validated(result)).answer.splitlines()[1]

    assert first_point == "2020-01 | 10.0 | NULL | NULL | NULL"
    assert "None" not in first_point


def test_growth_calendar_gap_none_is_preserved_as_null() -> None:
    result = _multi_tool_result(
        route="sql_then_python",
        operation="calculate_growth",
        python_payload=_growth_result(),
    )

    gap_point = synthesize_answer(_validated(result)).answer.splitlines()[3]

    assert gap_point == "2020-04 | 12.0 | NULL | NULL | NULL"


def test_growth_rate_remains_raw_ratio() -> None:
    result = _multi_tool_result(
        route="sql_then_python",
        operation="calculate_growth",
        python_payload=_growth_result(),
    )

    answer = synthesize_answer(_validated(result)).answer

    assert "2020-02 | 15.0 | 10.0 | 5.0 | 0.5" in answer
    assert "50.0" not in answer
    assert "%" not in answer


def test_growth_period_count_is_displayed_without_recalculation() -> None:
    payload = GrowthResult(points=(), period_count=7)
    result = _multi_tool_result(
        route="sql_then_python",
        operation="calculate_growth",
        python_payload=payload,
    )

    assert synthesize_answer(_validated(result)).answer.endswith("Period count: 7")


def test_unknown_python_payload_is_blocked_without_repr() -> None:
    payload = object()
    result = _multi_tool_result(
        route="sql_then_python",
        operation="unknown",
        python_payload=payload,
    )

    synthesis = synthesize_answer(_validated(result))

    assert synthesis.status == "blocked"
    assert synthesis.answer == "Unsupported result payload for answer synthesis."
    assert repr(payload) not in synthesis.answer


def test_warning_messages_are_preserved_and_errors_are_not_warnings() -> None:
    issues = (
        ValidationIssue("first", "warning", "First warning."),
        ValidationIssue("second", "warning", "Second warning."),
        ValidationIssue("error", "error", "Not a warning."),
    )

    synthesis = synthesize_answer(
        _validated(_multi_tool_result(), status="valid_with_warnings", issues=issues)
    )

    assert synthesis.warnings == ("First warning.", "Second warning.")


def test_synthesis_does_not_modify_validated_result() -> None:
    validated = _validated(_multi_tool_result())
    before = repr(validated)

    synthesis = synthesize_answer(validated)

    assert repr(validated) == before
    with pytest.raises(FrozenInstanceError):
        synthesis.answer = "changed"


def test_synthesis_does_not_call_llm_database_or_python_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("synthesis must not execute external tools")

    monkeypatch.setattr(
        "data_analysis_agent.sql_executor.run_readonly_sql",
        fail_if_called,
    )
    monkeypatch.setattr(
        "data_analysis_agent.python_analysis.run_python_analysis",
        fail_if_called,
    )
    monkeypatch.setattr(
        "data_analysis_agent.deepseek_provider.DeepSeekTextToSQLModel",
        fail_if_called,
    )

    synthesis = synthesize_answer(_validated(_multi_tool_result()))

    assert synthesis.status == "success"


def test_answer_does_not_expose_internal_metadata() -> None:
    result = _multi_tool_result(
        question="HELD-OUT METADATA SECRET",
        sql_result=_sql_result(
            executed_sql="SELECT 'REFERENCE SQL SECRET' AS value",
        ),
    )

    answer = synthesize_answer(_validated(result)).answer

    assert "HELD-OUT" not in answer
    assert "REFERENCE SQL" not in answer
    assert "internal router reason" not in answer
    assert "Prompt" not in answer
    assert ".env" not in answer


def test_default_locale_remains_english() -> None:
    answer = synthesize_answer(_validated(_multi_tool_result())).answer

    assert answer == "Result: 99441"


def test_zh_sql_scalar_uses_chinese_result_label() -> None:
    synthesis = synthesize_answer(
        _validated(_multi_tool_result()),
        locale="zh-CN",
    )

    assert synthesis.answer == "结果：99441"


def test_zh_describe_uses_chinese_labels_and_english_column_identifier() -> None:
    descriptions = (
        ColumnDescription("payment_value", 4, 12.5, 2.5, 9.0, 12.0, 17.0),
    )
    result = _multi_tool_result(
        route="sql_then_python",
        operation="describe",
        python_payload=descriptions,
    )

    answer = synthesize_answer(_validated(result), locale="zh-CN").answer

    assert answer.splitlines() == [
        "列：payment_value",
        "样本数：4",
        "均值：12.5",
        "样本标准差：2.5",
        "最小值：9.0",
        "中位数：12.0",
        "最大值：17.0",
    ]


def test_zh_correlation_uses_chinese_labels_without_interpretation() -> None:
    result = _multi_tool_result(
        route="sql_then_python",
        operation="correlation",
        python_payload=CorrelationResult("price", "freight", 0.414, 1000),
    )

    answer = synthesize_answer(_validated(result), locale="zh-CN").answer

    assert answer == "皮尔逊相关系数：0.414\n配对样本数：1000"
    assert "强" not in answer
    assert "弱" not in answer


def test_zh_growth_uses_chinese_header_and_period_count() -> None:
    result = _multi_tool_result(
        route="sql_then_python",
        operation="calculate_growth",
        python_payload=_growth_result(),
    )

    lines = synthesize_answer(_validated(result), locale="zh-CN").answer.splitlines()

    assert lines[0] == "时间 | 当前值 | 上期值 | 绝对变化 | 环比变化率"
    assert lines[-1] == "时间点数量：3"


def test_zh_growth_preserves_null_and_raw_ratio() -> None:
    result = _multi_tool_result(
        route="sql_then_python",
        operation="calculate_growth",
        python_payload=_growth_result(),
    )

    answer = synthesize_answer(_validated(result), locale="zh-CN").answer

    assert "2020-01 | 10.0 | NULL | NULL | NULL" in answer
    assert "2020-02 | 15.0 | 10.0 | 5.0 | 0.5" in answer
    assert "%" not in answer


def test_zh_invalid_validation_uses_chinese_blocked_message() -> None:
    result = _multi_tool_result(status="sql_execution_error")
    validated = _validated(
        result,
        status="invalid",
        issues=(ValidationIssue("unsuccessful_pipeline", "error", "Failed."),),
    )

    synthesis = synthesize_answer(validated, locale="zh-CN")

    assert synthesis.status == "blocked"
    assert "结果未通过有效性校验，暂时无法生成可靠答案。" in synthesis.answer
    assert "阶段：sql_execution_error" in synthesis.answer
    assert "错误：sql_execution_error: query failed" in synthesis.answer


def test_zh_unsupported_payload_uses_chinese_message() -> None:
    result = _multi_tool_result(
        route="sql_then_python",
        operation="unknown",
        python_payload=object(),
    )

    synthesis = synthesize_answer(_validated(result), locale="zh-CN")

    assert synthesis.status == "blocked"
    assert synthesis.answer == "暂不支持该结果类型的答案展示。"


def test_zh_empty_result_warning_uses_chinese_mapping() -> None:
    warning = ValidationIssue("empty_result", "warning", "SQLResult contains no rows.")
    result = _multi_tool_result(sql_result=_sql_result(("state",), ()))

    synthesis = synthesize_answer(
        _validated(result, status="valid_with_warnings", issues=(warning,)),
        locale="zh-CN",
    )

    assert synthesis.warnings == ("查询结果为空。",)
    assert warning.code == "empty_result"


def test_locales_change_only_presentation_not_structured_values() -> None:
    result = _multi_tool_result(
        route="sql_then_python",
        operation="calculate_growth",
        python_payload=_growth_result(),
    )
    validated = _validated(result)
    before = repr(validated)

    english = synthesize_answer(validated)
    chinese = synthesize_answer(validated, locale="zh-CN")

    assert repr(validated) == before
    assert "2020-02 | 15.0 | 10.0 | 5.0 | 0.5" in english.answer
    assert "2020-02 | 15.0 | 10.0 | 5.0 | 0.5" in chinese.answer

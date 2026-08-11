from __future__ import annotations

from pathlib import Path

import pandas as pd

from scripts.profile_dataset import (
    append_join_grain_section,
    build_parser,
    calculate_relation_coverage,
    parse_datetime_series,
    validate_required_columns,
)


def test_cli_defaults_to_current_raw_data_directory() -> None:
    args = build_parser().parse_args([])

    assert args.data_dir == Path("data/raw")


def test_full_report_appends_targeted_join_grain_section() -> None:
    tables = {
        "olist_order_items_dataset": pd.DataFrame(
            {
                "order_id": ["O-1", "O-1"],
                "price": ["10.00", "20.00"],
                "freight_value": ["1.00", "2.00"],
            }
        ),
        "olist_order_payments_dataset": pd.DataFrame(
            {
                "order_id": ["O-1", "O-1"],
                "payment_value": ["15.00", "18.00"],
            }
        ),
    }

    report = append_join_grain_section("# Existing audit\n", tables)

    assert report.startswith("# Existing audit\n\n")
    assert "## order_items / order_payments Join 粒度定向检查" in report
    assert "outer 订单集合预聚合后全量金额守恒 | 通过" in report


def test_validate_required_columns_reports_missing_and_unexpected_fields() -> None:
    tables = {
        "orders": pd.DataFrame(
            {"order_id": ["O-1"], "unexpected": ["value"]}
        )
    }
    required = {
        "orders": ("order_id", "customer_id"),
        "customers": ("customer_id",),
    }

    errors = validate_required_columns(tables, required)

    assert errors == [
        "orders 缺少字段: customer_id",
        "orders 存在未审阅字段: unexpected",
        "缺少表: customers",
    ]


def test_parse_datetime_series_counts_invalid_values_and_range() -> None:
    values = pd.Series(
        [
            "2016-09-04 21:15:19",
            "2018-10-17 17:30:18",
            "2018/10/17 17:30:18",
            None,
        ]
    )

    result = parse_datetime_series(values, date_format="%Y-%m-%d %H:%M:%S")

    assert result.non_null_count == 3
    assert result.valid_count == 2
    assert result.invalid_count == 1
    assert result.minimum == pd.Timestamp("2016-09-04 21:15:19")
    assert result.maximum == pd.Timestamp("2018-10-17 17:30:18")


def test_calculate_relation_coverage_preserves_string_keys_and_orphans() -> None:
    child = pd.DataFrame({"zip_prefix": ["01037", "01046", "99999", None]})
    parent = pd.DataFrame({"zip_prefix": ["01037", "01046", "01046"]})

    result = calculate_relation_coverage(
        child, "zip_prefix", parent, "zip_prefix"
    )

    assert result.child_non_null_rows == 3
    assert result.child_missing_rows == 1
    assert result.matched_rows == 2
    assert result.row_coverage == 2 / 3
    assert result.child_unique_keys == 3
    assert result.matched_unique_keys == 2
    assert result.unique_key_coverage == 2 / 3
    assert result.parent_duplicate_keys == 1
    assert result.parent_unique_keys == 2
    assert result.referenced_parent_unique_keys == 2
    assert result.parent_key_coverage == 1.0
    assert result.orphan_key_samples == ("99999",)

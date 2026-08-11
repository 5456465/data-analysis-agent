from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from scripts.check_join_grain import (
    analyze_join_grain,
    build_parser,
    render_markdown,
)


def test_join_grain_quantifies_amplification_and_conserves_preaggregated_totals() -> None:
    order_items = pd.DataFrame(
        {
            "order_id": ["O-1", "O-1", "O-2", "O-3"],
            "price": ["10.00", "20.00", "5.00", "7.00"],
            "freight_value": ["1.00", "2.00", "0.00", "0.00"],
        }
    )
    order_payments = pd.DataFrame(
        {
            "order_id": ["O-1", "O-1", "O-2", "O-4"],
            "payment_value": ["15.00", "18.00", "5.00", "9.00"],
        }
    )

    result = analyze_join_grain(order_items, order_payments)

    assert result.common_order_count == 2
    assert result.item_only_order_count == 1
    assert result.payment_only_order_count == 1
    assert result.orders_with_multiple_items == 1
    assert result.orders_with_multiple_payments == 1
    assert result.orders_with_multiple_items_and_payments == 1
    assert result.common_item_row_count == 3
    assert result.common_payment_row_count == 3
    assert result.naive_join_row_count == 5
    assert result.common_item_total_cents == 3_800
    assert result.naive_item_total_cents == 7_100
    assert result.baseline_item_total_cents == 4_500
    assert result.preaggregated_item_total_cents == 4_500
    assert result.common_payment_total_cents == 3_800
    assert result.naive_payment_total_cents == 7_100
    assert result.baseline_payment_total_cents == 4_700
    assert result.preaggregated_payment_total_cents == 4_700
    assert result.amounts_conserved_after_preaggregation is True
    assert "outer 订单集合预聚合后全量金额守恒 | 通过" in render_markdown(result)


def test_join_grain_rejects_invalid_money() -> None:
    order_items = pd.DataFrame(
        {"order_id": ["O-1"], "price": ["invalid"], "freight_value": ["1.00"]}
    )
    order_payments = pd.DataFrame(
        {"order_id": ["O-1"], "payment_value": ["1.00"]}
    )

    with pytest.raises(ValueError, match="price 包含 1 个无效金额"):
        analyze_join_grain(order_items, order_payments)


def test_join_grain_cli_defaults_to_current_raw_data_directory() -> None:
    args = build_parser().parse_args([])

    assert args.data_dir == Path("data/raw")

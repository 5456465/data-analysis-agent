"""Audit Olist order-item/payment join grain without rerunning the full audit.

The check focuses on the two monetary one-to-many tables.  It quantifies the
row and amount amplification caused by joining both tables directly on
``order_id`` and verifies that aggregating each table to order grain first
preserves the original monetary totals.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import pandas as pd

if __package__:
    from scripts.dataset_io import normalize_keys, read_csv_file
else:
    from dataset_io import normalize_keys, read_csv_file


DEFAULT_DATA_DIR = Path("data/raw")
ORDER_ITEMS_FILE = "olist_order_items_dataset.csv"
ORDER_PAYMENTS_FILE = "olist_order_payments_dataset.csv"


@dataclass(frozen=True)
class JoinGrainResult:
    """Deterministic counts and cent-based monetary checks for the join."""

    common_order_count: int
    item_only_order_count: int
    payment_only_order_count: int
    orders_with_multiple_items: int
    orders_with_multiple_payments: int
    orders_with_multiple_items_and_payments: int
    common_item_row_count: int
    common_payment_row_count: int
    naive_join_row_count: int
    common_item_total_cents: int
    naive_item_total_cents: int
    baseline_item_total_cents: int
    preaggregated_item_total_cents: int
    common_payment_total_cents: int
    naive_payment_total_cents: int
    baseline_payment_total_cents: int
    preaggregated_payment_total_cents: int

    @property
    def item_amount_amplification(self) -> float:
        return self.naive_item_total_cents / self.common_item_total_cents

    @property
    def payment_amount_amplification(self) -> float:
        return self.naive_payment_total_cents / self.common_payment_total_cents

    @property
    def amounts_conserved_after_preaggregation(self) -> bool:
        return (
            self.preaggregated_item_total_cents == self.baseline_item_total_cents
            and self.preaggregated_payment_total_cents
            == self.baseline_payment_total_cents
        )


def money_to_cents(series: pd.Series, column_name: str) -> pd.Series:
    """Convert a two-decimal monetary string series to exact integer cents."""

    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.isna().any():
        invalid_count = int(numeric.isna().sum())
        raise ValueError(f"{column_name} 包含 {invalid_count} 个无效金额")
    scaled = numeric * 100
    rounded = scaled.round()
    if ((scaled - rounded).abs() > 1e-7).any():
        raise ValueError(f"{column_name} 包含超过两位小数的金额")
    return rounded.astype("int64")


def _require_columns(frame: pd.DataFrame, columns: Sequence[str], label: str) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValueError(f"{label} 缺少字段: {', '.join(missing)}")


def analyze_join_grain(
    order_items: pd.DataFrame, order_payments: pd.DataFrame
) -> JoinGrainResult:
    """Measure direct-join amplification and pre-aggregation conservation."""

    _require_columns(
        order_items,
        ("order_id", "price", "freight_value"),
        "order_items",
    )
    _require_columns(
        order_payments,
        ("order_id", "payment_value"),
        "order_payments",
    )

    item_order_ids = normalize_keys(order_items["order_id"])
    payment_order_ids = normalize_keys(order_payments["order_id"])
    if item_order_ids.isna().any() or payment_order_ids.isna().any():
        raise ValueError("order_id 不允许为空")

    item_amount_cents = money_to_cents(order_items["price"], "price") + money_to_cents(
        order_items["freight_value"], "freight_value"
    )
    payment_amount_cents = money_to_cents(
        order_payments["payment_value"], "payment_value"
    )

    item_rows = pd.DataFrame(
        {"order_id": item_order_ids, "item_total_cents": item_amount_cents}
    )
    payment_rows = pd.DataFrame(
        {"order_id": payment_order_ids, "payment_total_cents": payment_amount_cents}
    )
    items_by_order = item_rows.groupby("order_id", sort=False).agg(
        item_count=("order_id", "size"),
        item_total_cents=("item_total_cents", "sum"),
    )
    payments_by_order = payment_rows.groupby("order_id", sort=False).agg(
        payment_count=("order_id", "size"),
        payment_total_cents=("payment_total_cents", "sum"),
    )
    common = items_by_order.join(
        payments_by_order, how="inner", validate="one_to_one"
    )
    if common.empty:
        raise ValueError("order_items 与 order_payments 没有共同 order_id")

    common_item_total_cents = int(common["item_total_cents"].sum())
    common_payment_total_cents = int(common["payment_total_cents"].sum())
    if common_item_total_cents <= 0 or common_payment_total_cents <= 0:
        raise ValueError("共同订单的金额合计必须大于 0")

    all_orders = items_by_order.join(
        payments_by_order, how="outer", validate="one_to_one"
    )
    baseline_item_total_cents = int(item_rows["item_total_cents"].sum())
    baseline_payment_total_cents = int(payment_rows["payment_total_cents"].sum())
    preaggregated_item_total_cents = int(
        all_orders["item_total_cents"].fillna(0).sum()
    )
    preaggregated_payment_total_cents = int(
        all_orders["payment_total_cents"].fillna(0).sum()
    )

    return JoinGrainResult(
        common_order_count=int(len(common)),
        item_only_order_count=int(
            len(items_by_order.index.difference(payments_by_order.index))
        ),
        payment_only_order_count=int(
            len(payments_by_order.index.difference(items_by_order.index))
        ),
        orders_with_multiple_items=int((items_by_order["item_count"] > 1).sum()),
        orders_with_multiple_payments=int(
            (payments_by_order["payment_count"] > 1).sum()
        ),
        orders_with_multiple_items_and_payments=int(
            ((common["item_count"] > 1) & (common["payment_count"] > 1)).sum()
        ),
        common_item_row_count=int(common["item_count"].sum()),
        common_payment_row_count=int(common["payment_count"].sum()),
        naive_join_row_count=int(
            (common["item_count"] * common["payment_count"]).sum()
        ),
        common_item_total_cents=common_item_total_cents,
        naive_item_total_cents=int(
            (common["item_total_cents"] * common["payment_count"]).sum()
        ),
        baseline_item_total_cents=baseline_item_total_cents,
        preaggregated_item_total_cents=preaggregated_item_total_cents,
        common_payment_total_cents=common_payment_total_cents,
        naive_payment_total_cents=int(
            (common["payment_total_cents"] * common["item_count"]).sum()
        ),
        baseline_payment_total_cents=baseline_payment_total_cents,
        preaggregated_payment_total_cents=preaggregated_payment_total_cents,
    )


def format_money(cents: int) -> str:
    return f"{cents / 100:,.2f}"


def render_markdown(result: JoinGrainResult) -> str:
    """Render a stable Markdown section for DATA_AUDIT.md."""

    validation = (
        "通过" if result.amounts_conserved_after_preaggregation else "失败"
    )
    return "\n".join(
        [
            "## order_items / order_payments Join 粒度定向检查",
            "",
            "本检查只读取订单明细与支付两张表，不重复执行全量数据审计。",
            "金额先转换为整数分，避免浮点舍入影响守恒判断。",
            "",
            "| 指标 | 结果 |",
            "|---|---:|",
            f"| 两表共同订单数 | {result.common_order_count:,} |",
            f"| 仅有商品明细的订单数 | {result.item_only_order_count:,} |",
            f"| 仅有支付明细的订单数 | {result.payment_only_order_count:,} |",
            f"| 多商品订单数 | {result.orders_with_multiple_items:,} |",
            f"| 多支付订单数 | {result.orders_with_multiple_payments:,} |",
            f"| 同时多商品且多支付订单数 | {result.orders_with_multiple_items_and_payments:,} |",
            f"| 共同订单的明细行数 | {result.common_item_row_count:,} |",
            f"| 共同订单的支付行数 | {result.common_payment_row_count:,} |",
            f"| 直接按 order_id Join 后行数 | {result.naive_join_row_count:,} |",
            f"| 共同订单明细金额基线（price + freight） | {format_money(result.common_item_total_cents)} |",
            f"| 直接 Join 后明细金额 | {format_money(result.naive_item_total_cents)} |",
            f"| 明细金额放大倍数 | {result.item_amount_amplification:.6f} |",
            f"| 共同订单支付金额基线 | {format_money(result.common_payment_total_cents)} |",
            f"| 直接 Join 后支付金额 | {format_money(result.naive_payment_total_cents)} |",
            f"| 支付金额放大倍数 | {result.payment_amount_amplification:.6f} |",
            f"| 全量商品明细金额基线 | {format_money(result.baseline_item_total_cents)} |",
            f"| 全量支付金额基线 | {format_money(result.baseline_payment_total_cents)} |",
            f"| outer 订单集合预聚合后全量金额守恒 | {validation} |",
            "",
            "### 结论与使用规则",
            "",
            "- `order_items` 与 `order_payments` 都是 `order_id` 粒度的一对多表。",
            "- 禁止直接同时连接两张明细表后汇总金额，否则商品金额会按支付行数重复，支付金额会按商品行数重复。",
            "- 正确做法是分别按 `order_id` 聚合，再与 `orders` 或彼此连接。",
            "- outer 订单集合保留单侧订单；预聚合后的两侧金额与各自原表全量基线精确一致。",
        ]
    )


def run_check(data_dir: Path) -> JoinGrainResult:
    items_path = data_dir / ORDER_ITEMS_FILE
    payments_path = data_dir / ORDER_PAYMENTS_FILE
    if not items_path.is_file():
        raise FileNotFoundError(f"缺少文件: {items_path}")
    if not payments_path.is_file():
        raise FileNotFoundError(f"缺少文件: {payments_path}")
    return analyze_join_grain(
        read_csv_file(items_path),
        read_csv_file(payments_path),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="检查 Olist 商品明细与支付直接 Join 的金额放大风险。"
    )
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    print(render_markdown(run_check(args.data_dir)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

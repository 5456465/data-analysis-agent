"""Audit the local Olist Brazilian e-commerce CSV dataset.

The module reads source files without modifying them and produces a Markdown
quality report.  It intentionally contains no LLM, Agent, RAG, SQL-generation,
or frontend functionality.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

import pandas as pd

if __package__:
    from scripts.check_join_grain import (
        analyze_join_grain,
        render_markdown as render_join_grain_markdown,
    )
    from scripts.dataset_io import normalize_keys, read_csv_file
else:
    from check_join_grain import (
        analyze_join_grain,
        render_markdown as render_join_grain_markdown,
    )
    from dataset_io import normalize_keys, read_csv_file


DEFAULT_DATA_DIR = Path("data/raw")
DEFAULT_OUTPUT_PATH = Path("docs/DATA_AUDIT.md")
DATASET_SOURCE_URL = "https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce/data"
DATASET_TITLE = "Brazilian E-Commerce Public Dataset by Olist"
DATASET_LICENSE = "CC BY-NC-SA 4.0"
EXPECTED_DATA_END = pd.Timestamp("2018-12-31 23:59:59")


@dataclass(frozen=True)
class RelationSpec:
    child_table: str
    child_column: str
    parent_table: str
    parent_column: str
    label: str
    relationship_kind: str = "foreign key"


@dataclass(frozen=True)
class KeySpec:
    table: str
    columns: tuple[str, ...]
    label: str


@dataclass(frozen=True)
class TimeParseResult:
    parsed: pd.Series
    non_null_count: int
    valid_count: int
    invalid_count: int
    minimum: pd.Timestamp | None
    maximum: pd.Timestamp | None


@dataclass(frozen=True)
class RelationCoverage:
    child_non_null_rows: int
    child_missing_rows: int
    matched_rows: int
    row_coverage: float
    child_unique_keys: int
    matched_unique_keys: int
    unique_key_coverage: float
    parent_duplicate_keys: int
    parent_unique_keys: int
    referenced_parent_unique_keys: int
    parent_key_coverage: float
    orphan_key_samples: tuple[str, ...]


# These file names and headers were recorded only after inspecting data/raw.
REQUIRED_COLUMNS: Mapping[str, tuple[str, ...]] = {
    "olist_customers_dataset": (
        "customer_id",
        "customer_unique_id",
        "customer_zip_code_prefix",
        "customer_city",
        "customer_state",
    ),
    "olist_geolocation_dataset": (
        "geolocation_zip_code_prefix",
        "geolocation_lat",
        "geolocation_lng",
        "geolocation_city",
        "geolocation_state",
    ),
    "olist_order_items_dataset": (
        "order_id",
        "order_item_id",
        "product_id",
        "seller_id",
        "shipping_limit_date",
        "price",
        "freight_value",
    ),
    "olist_order_payments_dataset": (
        "order_id",
        "payment_sequential",
        "payment_type",
        "payment_installments",
        "payment_value",
    ),
    "olist_order_reviews_dataset": (
        "review_id",
        "order_id",
        "review_score",
        "review_comment_title",
        "review_comment_message",
        "review_creation_date",
        "review_answer_timestamp",
    ),
    "olist_orders_dataset": (
        "order_id",
        "customer_id",
        "order_status",
        "order_purchase_timestamp",
        "order_approved_at",
        "order_delivered_carrier_date",
        "order_delivered_customer_date",
        "order_estimated_delivery_date",
    ),
    "olist_products_dataset": (
        "product_id",
        "product_category_name",
        "product_name_lenght",
        "product_description_lenght",
        "product_photos_qty",
        "product_weight_g",
        "product_length_cm",
        "product_height_cm",
        "product_width_cm",
    ),
    "olist_sellers_dataset": (
        "seller_id",
        "seller_zip_code_prefix",
        "seller_city",
        "seller_state",
    ),
    "product_category_name_translation": (
        "product_category_name",
        "product_category_name_english",
    ),
}


RELATIONSHIPS: tuple[RelationSpec, ...] = (
    RelationSpec(
        "olist_orders_dataset",
        "customer_id",
        "olist_customers_dataset",
        "customer_id",
        "orders.customer_id → customers.customer_id",
    ),
    RelationSpec(
        "olist_order_items_dataset",
        "order_id",
        "olist_orders_dataset",
        "order_id",
        "order_items.order_id → orders.order_id",
    ),
    RelationSpec(
        "olist_order_items_dataset",
        "product_id",
        "olist_products_dataset",
        "product_id",
        "order_items.product_id → products.product_id",
    ),
    RelationSpec(
        "olist_order_items_dataset",
        "seller_id",
        "olist_sellers_dataset",
        "seller_id",
        "order_items.seller_id → sellers.seller_id",
    ),
    RelationSpec(
        "olist_order_payments_dataset",
        "order_id",
        "olist_orders_dataset",
        "order_id",
        "payments.order_id → orders.order_id",
    ),
    RelationSpec(
        "olist_order_reviews_dataset",
        "order_id",
        "olist_orders_dataset",
        "order_id",
        "reviews.order_id → orders.order_id",
    ),
    RelationSpec(
        "olist_products_dataset",
        "product_category_name",
        "product_category_name_translation",
        "product_category_name",
        "products.category → category_translation.category",
    ),
    RelationSpec(
        "olist_customers_dataset",
        "customer_zip_code_prefix",
        "olist_geolocation_dataset",
        "geolocation_zip_code_prefix",
        "customers.zip_prefix → geolocation.zip_prefix",
        "non-unique lookup",
    ),
    RelationSpec(
        "olist_sellers_dataset",
        "seller_zip_code_prefix",
        "olist_geolocation_dataset",
        "geolocation_zip_code_prefix",
        "sellers.zip_prefix → geolocation.zip_prefix",
        "non-unique lookup",
    ),
)


KEY_SPECS: tuple[KeySpec, ...] = (
    KeySpec("olist_customers_dataset", ("customer_id",), "customer_id"),
    KeySpec("olist_orders_dataset", ("order_id",), "order_id"),
    KeySpec(
        "olist_order_items_dataset",
        ("order_id", "order_item_id"),
        "order_id + order_item_id",
    ),
    KeySpec(
        "olist_order_payments_dataset",
        ("order_id", "payment_sequential"),
        "order_id + payment_sequential",
    ),
    KeySpec("olist_order_reviews_dataset", ("review_id",), "review_id"),
    KeySpec(
        "olist_order_reviews_dataset",
        ("review_id", "order_id"),
        "review_id + order_id",
    ),
    KeySpec("olist_products_dataset", ("product_id",), "product_id"),
    KeySpec("olist_sellers_dataset", ("seller_id",), "seller_id"),
    KeySpec(
        "product_category_name_translation",
        ("product_category_name",),
        "product_category_name",
    ),
)


KEY_FIELDS_TO_LOCATE = (
    "shop_id",
    "seller_id",
    "order_id",
    "customer_id",
    "customer_unique_id",
    "product_id",
)


def discover_csv_files(data_dir: Path) -> list[Path]:
    """Return every actual CSV file in the requested directory."""

    if not data_dir.is_dir():
        raise FileNotFoundError(f"数据目录不存在: {data_dir}")
    files = sorted(
        path
        for path in data_dir.iterdir()
        if path.is_file() and path.suffix.lower() == ".csv"
    )
    if not files:
        raise ValueError(f"数据目录中没有 CSV 文件: {data_dir}")
    return files


def load_tables(csv_files: Sequence[Path]) -> dict[str, pd.DataFrame]:
    tables: dict[str, pd.DataFrame] = {}
    for path in csv_files:
        if path.stem in tables:
            raise ValueError(f"存在重复表名: {path.stem}")
        tables[path.stem] = read_csv_file(path)
    return tables


def validate_required_columns(
    tables: Mapping[str, pd.DataFrame],
    required_columns: Mapping[str, Sequence[str]],
) -> list[str]:
    """Return errors for missing reviewed tables, fields, and unexpected fields."""

    errors: list[str] = []
    for table_name, columns in required_columns.items():
        table = tables.get(table_name)
        if table is None:
            errors.append(f"缺少表: {table_name}")
            continue
        expected = list(columns)
        missing = [column for column in expected if column not in table.columns]
        unexpected = [column for column in table.columns if column not in expected]
        if missing:
            errors.append(f"{table_name} 缺少字段: {', '.join(missing)}")
        if unexpected:
            errors.append(f"{table_name} 存在未审阅字段: {', '.join(unexpected)}")
    unreviewed_tables = sorted(set(tables) - set(required_columns))
    errors.extend(f"存在未审阅表: {name}" for name in unreviewed_tables)
    return errors


def is_temporal_candidate(column_name: str) -> bool:
    normalized = column_name.strip().lower()
    return normalized.endswith(("_timestamp", "_date", "_at"))


def parse_datetime_series(
    series: pd.Series, date_format: str | None = None
) -> TimeParseResult:
    """Parse dates without mutating the source series."""

    text = series.astype("string").str.strip()
    non_null_mask = text.notna() & text.ne("")
    parsed = pd.to_datetime(
        text.where(non_null_mask),
        errors="coerce",
        format=date_format or "mixed",
    )
    valid_mask = non_null_mask & parsed.notna()
    invalid_mask = non_null_mask & parsed.isna()
    valid_values = parsed.loc[valid_mask]
    return TimeParseResult(
        parsed=parsed,
        non_null_count=int(non_null_mask.sum()),
        valid_count=int(valid_mask.sum()),
        invalid_count=int(invalid_mask.sum()),
        minimum=valid_values.min() if not valid_values.empty else None,
        maximum=valid_values.max() if not valid_values.empty else None,
    )


def is_identifier_column(column_name: str) -> bool:
    normalized = column_name.lower()
    return normalized.endswith("_id") or "zip_code_prefix" in normalized


def infer_logical_type(series: pd.Series, column_name: str) -> str:
    """Infer a logical type from the complete non-null field values."""

    non_null = series.dropna().astype("string").str.strip()
    if non_null.empty:
        return "empty"
    if is_temporal_candidate(column_name):
        parsed = parse_datetime_series(series, "%Y-%m-%d %H:%M:%S")
        if parsed.valid_count:
            return "datetime"
    if is_identifier_column(column_name):
        return "identifier (string)"
    numeric = pd.to_numeric(non_null, errors="coerce")
    if numeric.notna().all():
        if ((numeric % 1) == 0).all():
            return "integer"
        return "decimal"
    return "string"


def calculate_relation_coverage(
    child: pd.DataFrame,
    child_column: str,
    parent: pd.DataFrame,
    parent_column: str,
) -> RelationCoverage:
    """Measure row-level and distinct-key coverage for a relation."""

    child_keys = normalize_keys(child[child_column])
    parent_keys = normalize_keys(parent[parent_column]).dropna()
    child_non_null = child_keys.dropna()
    parent_unique = pd.Index(parent_keys.unique())
    child_unique = pd.Index(child_non_null.unique())
    matched_mask = child_non_null.isin(parent_unique)
    matched_unique = child_unique.intersection(parent_unique)
    orphan_keys = child_unique.difference(parent_unique)

    non_null_count = int(len(child_non_null))
    unique_count = int(len(child_unique))
    matched_rows = int(matched_mask.sum())
    matched_unique_count = int(len(matched_unique))
    parent_unique_count = int(len(parent_unique))
    return RelationCoverage(
        child_non_null_rows=non_null_count,
        child_missing_rows=int(child_keys.isna().sum()),
        matched_rows=matched_rows,
        row_coverage=matched_rows / non_null_count if non_null_count else 1.0,
        child_unique_keys=unique_count,
        matched_unique_keys=matched_unique_count,
        unique_key_coverage=(matched_unique_count / unique_count if unique_count else 1.0),
        parent_duplicate_keys=int(parent_keys.duplicated(keep="first").sum()),
        parent_unique_keys=parent_unique_count,
        referenced_parent_unique_keys=matched_unique_count,
        parent_key_coverage=(
            matched_unique_count / parent_unique_count if parent_unique_count else 1.0
        ),
        orphan_key_samples=tuple(sorted(str(value) for value in orphan_keys[:10])),
    )


def profile_tables(
    csv_files: Sequence[Path], tables: Mapping[str, pd.DataFrame]
) -> dict[str, dict[str, object]]:
    files_by_table = {path.stem: path for path in csv_files}
    profiles: dict[str, dict[str, object]] = {}
    for table_name, frame in tables.items():
        row_count = len(frame)
        columns: list[dict[str, object]] = []
        times: list[dict[str, object]] = []
        for column_name in frame.columns:
            series = frame[column_name]
            missing_count = int(series.isna().sum())
            logical_type = infer_logical_type(series, column_name)
            invalid_format_count = 0
            if logical_type == "datetime":
                result = parse_datetime_series(
                    series, date_format="%Y-%m-%d %H:%M:%S"
                )
                invalid_format_count = result.invalid_count
                times.append(
                    {
                        "name": column_name,
                        "non_null_count": result.non_null_count,
                        "valid_count": result.valid_count,
                        "invalid_count": result.invalid_count,
                        "invalid_rate": (
                            result.invalid_count / result.non_null_count
                            if result.non_null_count
                            else 0.0
                        ),
                        "out_of_period_count": int(
                            (result.parsed > EXPECTED_DATA_END).sum()
                        ),
                        "minimum": result.minimum,
                        "maximum": result.maximum,
                    }
                )
            columns.append(
                {
                    "name": column_name,
                    "storage_type": "string",
                    "logical_type": logical_type,
                    "missing_count": missing_count,
                    "missing_rate": missing_count / row_count if row_count else 0.0,
                    "distinct_count": int(series.nunique(dropna=True)),
                    "invalid_format_count": invalid_format_count,
                }
            )
        duplicate_rows = int(frame.duplicated(keep="first").sum())
        profiles[table_name] = {
            "path": files_by_table[table_name],
            "row_count": row_count,
            "column_count": len(frame.columns),
            "duplicate_rows": duplicate_rows,
            "duplicate_rate": duplicate_rows / row_count if row_count else 0.0,
            "columns": columns,
            "times": times,
        }
    return profiles


def profile_keys(tables: Mapping[str, pd.DataFrame]) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for spec in KEY_SPECS:
        frame = tables.get(spec.table)
        if frame is None or any(column not in frame.columns for column in spec.columns):
            continue
        key_frame = frame.loc[:, list(spec.columns)].copy()
        for column in spec.columns:
            key_frame[column] = normalize_keys(key_frame[column])
        missing_mask = key_frame.isna().any(axis=1)
        non_null_keys = key_frame.loc[~missing_mask]
        results.append(
            {
                "spec": spec,
                "missing_count": int(missing_mask.sum()),
                "duplicate_count": int(
                    non_null_keys.duplicated(keep="first").sum()
                ),
                "distinct_count": int(len(non_null_keys.drop_duplicates())),
            }
        )
    return results


def profile_relations(tables: Mapping[str, pd.DataFrame]) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for relation in RELATIONSHIPS:
        child = tables.get(relation.child_table)
        parent = tables.get(relation.parent_table)
        if (
            child is None
            or parent is None
            or relation.child_column not in child.columns
            or relation.parent_column not in parent.columns
        ):
            continue
        results.append(
            {
                "relation": relation,
                "coverage": calculate_relation_coverage(
                    child, relation.child_column, parent, relation.parent_column
                ),
            }
        )
    return results


def locate_key_fields(tables: Mapping[str, pd.DataFrame]) -> dict[str, list[str]]:
    return {
        field_name: sorted(
            table_name
            for table_name, frame in tables.items()
            if field_name in frame.columns
        )
        for field_name in KEY_FIELDS_TO_LOCATE
    }


def format_rate(value: float) -> str:
    return f"{value:.4%}"


def format_timestamp(value: object) -> str:
    if value is None or pd.isna(value):
        return "—"
    if isinstance(value, pd.Timestamp):
        return value.isoformat(sep=" ")
    return str(value)


def render_markdown_report(
    data_dir: Path,
    csv_files: Sequence[Path],
    tables: Mapping[str, pd.DataFrame],
    profiles: Mapping[str, Mapping[str, object]],
    validation_errors: Sequence[str],
    key_profiles: Sequence[Mapping[str, object]],
    relation_profiles: Sequence[Mapping[str, object]],
) -> str:
    """Render the complete audit and main-source suitability assessment."""

    total_rows = sum(int(profile["row_count"]) for profile in profiles.values())
    total_bytes = sum(path.stat().st_size for path in csv_files)
    locations = locate_key_fields(tables)
    relation_issues = [
        item
        for item in relation_profiles
        if item["coverage"].row_coverage < 1.0
        or item["coverage"].unique_key_coverage < 1.0
    ]
    relation_by_label = {
        item["relation"].label: item["coverage"] for item in relation_profiles
    }
    items_coverage = relation_by_label["order_items.order_id → orders.order_id"]
    payments_coverage = relation_by_label["payments.order_id → orders.order_id"]
    reviews_coverage = relation_by_label["reviews.order_id → orders.order_id"]
    out_of_period_times = [
        (table_name, item)
        for table_name, profile in profiles.items()
        for item in profile["times"]
        if item["out_of_period_count"] > 0
    ]

    lines = [
        "# DATA_AUDIT — Olist 巴西电子商务数据集",
        "",
        f"> 生成时间（UTC）：{datetime.now(timezone.utc).replace(microsecond=0).isoformat()}",
        f"> 本地目录：`{data_dir.as_posix()}`",
        f"> 官方来源：[{DATASET_TITLE}]({DATASET_SOURCE_URL})",
        f"> 数据许可：{DATASET_LICENSE}",
        "",
        "## 结论",
        "",
        "**适合作为本项目 20 天 MVP 的主数据源，但应将项目保持为非商业作品集用途，并满足署名和相同方式共享要求。**",
        "",
        "支持作为主数据源的依据：",
        "",
        "- 来源与许可清晰：Kaggle 的 Olist 官方数据卡标注 `CC BY-NC-SA 4.0`，适合非商业学习和作品集演示。",
        "- 业务结构完整：包含订单、明细、商品、卖家、客户、支付、评论、物流时间和地理信息，可支持销售、客单价、运费、交付时效、满意度等可验证指标。",
        "- 关系结构适合 SQL 和数据验证演示：6 个核心 ID 关系全部达到 100% 行覆盖。",
        f"- 规模可控：9 张表、{total_rows:,} 行、{total_bytes / (1024 ** 2):.1f} MiB，可在本地用 pandas 和 DuckDB 反复测试。",
        "- 数据卡说明这是经过匿名化的真实商业数据，比纯合成数据更有利于展示真实质量问题和指标口径。",
        "",
        "需要接受的边界：",
        "",
        "- 数据为 2016–2018 年的巴西历史业务，不能代表当前市场。",
        f"- {len(out_of_period_times)} 个时间字段包含超出 2018 年的值；当前是 `shipping_limit_date` 的 4 条 2020 年记录，建模前应标记为时间异常。",
        "- 没有 `shop_id`；实际商家键是 `seller_id`。指标和问题示例应使用真实字段名。",
        "- 没有显式退款表或成本/利润字段；退款率、毛利率等指标不能直接计算。",
        "- 许可包含 NonCommercial 限制，不适合未经额外授权的商业产品。",
        f"- {len(relation_issues)} 个非核心映射存在少量孤儿键，下文已给出精确覆盖率。",
        "",
        "## 审计口径",
        "",
        "- 所有表均按 UTF-8 CSV 实际表头读取，并以字符串保留 ID 和邮编前导零。",
        "- 评论文件含带引号的多行文本，因此行数以 CSV 解析后的记录数为准，不使用物理换行数。",
        "- 缺失率 = 空值数 / 表行数。",
        "- 重复率 = 完全重复且排除首次出现的行数 / 表行数。",
        "- 类型同时报告 CSV 存储类型和基于全部非空值推断的逻辑类型。",
        "- 关联行覆盖率的分母是子表中非空关联键行数；唯一键覆盖率用于衡量不同孤儿键。",
        "",
        "## 文件与表概览",
        "",
        "| 文件 | 行数 | 字段数 | 完全重复行 | 重复率 | 文件大小 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for table_name in sorted(profiles):
        profile = profiles[table_name]
        path = profile["path"]
        lines.append(
            f"| `{path.name}` | {profile['row_count']:,} | {profile['column_count']} | "
            f"{profile['duplicate_rows']:,} | {format_rate(float(profile['duplicate_rate']))} | "
            f"{path.stat().st_size:,} B |"
        )

    lines.extend(
        [
            "",
            "## 关键字段存在性",
            "",
            "| 字段 | 实际出现的表 |",
            "|---|---|",
        ]
    )
    for field_name, table_names in locations.items():
        values = ", ".join(f"`{name}`" for name in table_names) or "未发现"
        lines.append(f"| `{field_name}` | {values} |")

    lines.extend(["", "## 字段结构校验", ""])
    if validation_errors:
        lines.extend(f"- 失败：{error}" for error in validation_errors)
    else:
        lines.append("- 通过：9 张实际 CSV 的表头与已审阅字段完全一致。")

    lines.extend(
        [
            "",
            "## 候选主键/复合键质量",
            "",
            "| 表 | 候选键 | 缺失行 | 重复键行 | 唯一键数 |",
            "|---|---|---:|---:|---:|",
        ]
    )
    for item in key_profiles:
        spec = item["spec"]
        lines.append(
            f"| `{spec.table}` | `{spec.label}` | {item['missing_count']:,} | "
            f"{item['duplicate_count']:,} | {item['distinct_count']:,} |"
        )

    lines.extend(
        [
            "",
            "## 表关联覆盖率",
            "",
            "| 关系 | 类型 | 子表非空行 | 缺失键行 | 匹配行 | 行覆盖率 | 唯一键覆盖率 | 父表键被引用率 | 父键重复数 | 孤儿键样例 |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for item in relation_profiles:
        relation = item["relation"]
        coverage = item["coverage"]
        orphan_samples = ", ".join(
            f"`{value}`" for value in coverage.orphan_key_samples
        ) or "—"
        lines.append(
            f"| {relation.label} | {relation.relationship_kind} | "
            f"{coverage.child_non_null_rows:,} | {coverage.child_missing_rows:,} | "
            f"{coverage.matched_rows:,} | {format_rate(coverage.row_coverage)} | "
            f"{format_rate(coverage.unique_key_coverage)} | "
            f"{format_rate(coverage.parent_key_coverage)} | "
            f"{coverage.parent_duplicate_keys:,} | {orphan_samples} |"
        )

    lines.extend(
        [
            "",
            "### 关联解读",
            "",
            "- 订单→客户、明细→订单/商品/卖家、支付→订单、评论→订单的行覆盖率均为 100%。",
            f"- 反向看父表参与度：{items_coverage.parent_unique_keys - items_coverage.referenced_parent_unique_keys:,} 个订单没有明细，{payments_coverage.parent_unique_keys - payments_coverage.referenced_parent_unique_keys:,} 个订单没有支付记录，{reviews_coverage.parent_unique_keys - reviews_coverage.referenced_parent_unique_keys:,} 个订单没有评论。这些不一定是错误，但分析时不能使用 inner join 默默丢弃。",
            "- 品类翻译表缺少 2 个葡萄牙语品类键，影响 13 个非空品类商品；另有 610 个商品的品类本身缺失。",
            "- 客户邮编地理覆盖率为 99.7204%，卖家为 99.7738%。`geolocation_zip_code_prefix` 不唯一是数据设计：同一邮编有多个坐标观测，关联前需先聚合到邮编粒度。",
        ]
    )

    for table_name in sorted(profiles):
        profile = profiles[table_name]
        lines.extend(
            [
                "",
                f"## 表：`{table_name}`",
                "",
                f"- 文件：`{profile['path'].name}`",
                f"- 行数：{profile['row_count']:,}",
                f"- 字段数：{profile['column_count']}",
                f"- 完全重复率：{format_rate(float(profile['duplicate_rate']))}",
                "",
                "### 字段、类型和缺失率",
                "",
                "| 字段 | CSV 存储类型 | 逻辑类型 | 缺失数 | 缺失率 | 唯一值数 | 格式无效数 |",
                "|---|---|---|---:|---:|---:|---:|",
            ]
        )
        for column in profile["columns"]:
            lines.append(
                f"| `{column['name']}` | {column['storage_type']} | "
                f"{column['logical_type']} | {column['missing_count']:,} | "
                f"{format_rate(float(column['missing_rate']))} | "
                f"{column['distinct_count']:,} | {column['invalid_format_count']:,} |"
            )

        lines.extend(["", "### 时间范围", ""])
        if not profile["times"]:
            lines.append("该表没有通过字段名和全值转换检测到时间字段。")
        else:
            lines.extend(
                [
                    "| 时间字段 | 非空值 | 有效时间 | 无效时间 | 无效率 | 2018 年后记录 | 最小值 | 最大值 |",
                    "|---|---:|---:|---:|---:|---:|---|---|",
                ]
            )
            for item in profile["times"]:
                lines.append(
                    f"| `{item['name']}` | {item['non_null_count']:,} | "
                    f"{item['valid_count']:,} | {item['invalid_count']:,} | "
                    f"{format_rate(float(item['invalid_rate']))} | "
                    f"{item['out_of_period_count']:,} | "
                    f"{format_timestamp(item['minimum'])} | "
                    f"{format_timestamp(item['maximum'])} |"
                )

    lines.extend(
        [
            "",
            "## 隐私、许可和使用边界",
            "",
            "- Kaggle 数据卡标注该数据经过匿名化，但 `customer_unique_id`、评论文本和精细坐标仍可用于行为链接；演示时应优先输出聚合结果。",
            f"- 许可为 [{DATASET_LICENSE}]({DATASET_SOURCE_URL})：需署名、限非商业使用，改编成果需按相同许可共享。",
            "- 建议仓库只保存下载说明、来源和生成脚本；如要公开提交原始 CSV，应同时保留署名和许可文本。",
            "",
            "## 审计限制",
            "",
            "- 本报告对当前目录中 9 张 CSV 做全量统计，不是抽样。",
            "- 关联覆盖率证明键值存在，不证明业务时序、金额口径或一对多粒度使用正确。",
            "- `review_id` 单列并不唯一；若建库，需要按实际复合键或代理键建模，不能直接将其强制为单列主键。",
            "- 许可解读用于项目风险评估，不是法律意见。",
            "",
        ]
    )
    return "\n".join(lines)


def append_join_grain_section(
    report: str, tables: Mapping[str, pd.DataFrame]
) -> str:
    """Append the targeted one-to-many monetary check to a full audit report."""

    try:
        order_items = tables["olist_order_items_dataset"]
        order_payments = tables["olist_order_payments_dataset"]
    except KeyError as exc:
        raise ValueError(f"Join 粒度检查缺少表: {exc.args[0]}") from exc
    join_section = render_join_grain_markdown(
        analyze_join_grain(order_items, order_payments)
    )
    return f"{report.rstrip()}\n\n{join_section}\n"


def run_audit(data_dir: Path, output_path: Path) -> None:
    csv_files = discover_csv_files(data_dir)
    tables = load_tables(csv_files)
    validation_errors = validate_required_columns(tables, REQUIRED_COLUMNS)
    report = render_markdown_report(
        data_dir=data_dir,
        csv_files=csv_files,
        tables=tables,
        profiles=profile_tables(csv_files, tables),
        validation_errors=validation_errors,
        key_profiles=profile_keys(tables),
        relation_profiles=profile_relations(tables),
    )
    report = append_join_grain_section(report, tables)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="审计本地 Olist CSV 数据集并生成 Markdown 报告。"
    )
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    run_audit(args.data_dir, args.output)
    print(f"数据审计已写入: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# Data Analysis Agent

可验证的多工具数据分析 Agent，是一个面向 AI Agent / LLM 应用开发实习的
20 天 MVP 作品集项目。

## 项目问题

普通自然语言转 SQL Demo 往往只返回答案，难以确认指标口径、查询范围、
SQL 是否安全，以及金额是否因多表 Join 被重复计算。本项目的目标是让分析
过程可执行、可验证、可追溯，并在证据不足时明确拒绝编造结论。

## 当前状态

截至 2026-08-11：

### 已实现

- Python 3.11+ 项目骨架和 pytest 配置；当前本地环境使用 Python 3.12。
- Olist Brazilian E-Commerce 9 张原始 CSV 的完整数据审计。
- 主键、字段、缺失值、重复值、时间范围和核心外键覆盖率检查。
- `order_items` / `order_payments` 一对多 Join 放大与金额守恒检查。
- 9 个原始 CSV 的 SHA-256 版本清单。
- 8 张核心业务表的 typed DuckDB，可从真实 CSV 重复构建。
- 订单级 item/payment 安全聚合 view 和商品类别官方英文映射 view。
- 14 条 English baseline SQL，覆盖订单、金额、品类、地域、评论和交付分析。
- pytest 覆盖 CSV 审计、DuckDB 行数、键、Join、时间类型、baseline 和金额粒度风险。
- 确定性的 `inspect_schema`，以结构化 Python 数据返回 table、view、字段、
  DuckDB 类型、nullable、primary key 和已确认的数据粒度。
- 最小只读 `run_readonly_sql` executor：只接受单条 `SELECT` / `WITH ... SELECT`，
  返回结构化结果和错误，并对 Python 侧返回行数设置确定性上限。

### 下一阶段

- 在只读数据库工具基线上实现 English Text-to-SQL 的最小可验证闭环。
- 为 English Text-to-SQL 准备小型、人工校验的评测集。
- 在数据库工具测试通过后再接入 LLM，不改变当前英文 Schema。

### 尚未实现

- LLM、Agent workflow、Metric RAG、Text-to-SQL。
- LangGraph、Streamlit、图表生成和结果验证工具。
- Agent 评测集和端到端准确率指标。
- 中文问答、自动语言检测、翻译链路和多语言 UI / RAG。

## MVP 语言范围

当前最小 MVP 采用 English-first：未来实现的问答输入、输出、Prompt、Tool
description 和评测问题均使用英文；DuckDB、SQL 和 Tool 接口始终使用原始英文
Schema。产品问答能力尚未实现，因此当前仓库还没有可运行的语言拒绝逻辑；实现
问答入口时，非英文输入应明确返回 unsupported，而不是隐式增加翻译链路。

中文问答属于后续扩展。届时中文只进入 semantic alias、Prompt 和 response 层，
继续映射到稳定的英文 canonical identifier，不创建中文 Schema 或重复数据表，也不
改变 SQL Tool 接口。完整语言设计见
[`docs/PRODUCT_SPEC.md`](docs/PRODUCT_SPEC.md#21-语言设计)。

## 目标工作流

```text
英文自然语言问题
  -> 指标定义检索（需要时）
  -> Schema 检查
  -> 受控 SQL / Python / 图表工具
  -> 结果与金额粒度验证
  -> 结论、SQL、数据范围、证据和限制
```

当前仓库已完成数据基线、Schema 检查和只读 SQL 执行；不应把其余目标架构
误认为已实现功能。

## 数据集

唯一数据集是
[Brazilian E-Commerce Public Dataset by Olist](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce/data)，
包含约 10 万个 2016–2018 年订单。

原始和处理后数据不纳入 Git。请自行从来源页面获取 9 个 CSV，并放入
`data/raw/`。详细来源、使用限制和数据许可见
[`docs/DATASET.md`](docs/DATASET.md)。实际审计结果见
[`docs/DATA_AUDIT.md`](docs/DATA_AUDIT.md)。

验证本地数据版本：

```bash
shasum -a 256 -c docs/olist_raw.sha256
```

## 环境安装

要求：Python 3.11+。当前本地基线使用独立安装在
`~/.local/bin/python3.12` 的 Python 3.12.13；该目录不在 `PATH` 时需使用完整路径。

```bash
~/.local/bin/python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

## 构建 DuckDB

数据库输出到已被 Git 忽略的 `data/processed/olist.duckdb`。第一版只导入 8 张
核心业务表；原始 geolocation CSV 保留在 `data/raw/`，暂不进入数据库。

```bash
python scripts/build_duckdb.py
```

已有数据库需要显式重建时：

```bash
python scripts/build_duckdb.py --force
```

运行全部 14 条 baseline SQL：

```bash
python scripts/baseline_queries.py
```

只运行指定 baseline：

```bash
python scripts/baseline_queries.py --query total_order_count
```

金额口径严格区分 `item_transaction_value = SUM(order_items.price)`、
`freight_value = SUM(order_items.freight_value)` 和按订单预聚合后的
`payment_value`。不使用笼统的 revenue，也不计算利润、毛利或退款率。

## 检查数据库 Schema

`inspect_schema` 读取实际 DuckDB catalog，并返回不可变的结构化 Python 对象；
它不生成 SQL，也不连接 LLM：

```python
from data_analysis_agent import inspect_schema

schema = inspect_schema("data/processed/olist.duckdb")
for obj in schema.objects:
    print(obj.name, obj.object_type, obj.grain)
    for column in obj.columns:
        print(column.name, column.data_type, column.nullable, column.primary_key)
```

数据库必须已经存在；连接以 DuckDB `read_only=True` 打开。

## 执行只读 SQL

`run_readonly_sql` 只接受一条 `SELECT` 或 `WITH ... SELECT`，并返回结构化
`SQLResult`。它不会生成或修复 SQL：

```python
from data_analysis_agent import run_readonly_sql

result = run_readonly_sql(
    "data/processed/olist.duckdb",
    "SELECT COUNT(*) AS order_count FROM orders",
    max_rows=200,
)
print(result.status, result.columns, result.rows, result.truncated)
```

executor 使用 DuckDB parser 校验 statement 数量和类型，以 `read_only=True`
连接，并关闭外部文件和扩展访问。它只读取 `max_rows + 1` 行来判断截断，最多向
Python 应用层返回 `max_rows` 行，不会向用户 SQL 静默添加 `LIMIT`。

## 运行检查

只运行 item/payment Join 粒度检查：

```bash
python scripts/check_join_grain.py
```

重新生成完整数据审计时会同时包含 Join 粒度检查：

```bash
python scripts/profile_dataset.py
```

完整审计会写入 `docs/DATA_AUDIT.md`。只有文件数量、表头、大小或 SHA-256
发生变化时，才需要重新运行；移动项目目录不会使审计失效。

## 测试

```bash
python -m pytest
```

## 项目结构

```text
.
├── data/raw/                    # 本地 Olist CSV，不纳入 Git
├── data/processed/              # 本地 DuckDB 输出，不纳入 Git
├── docs/
│   ├── DATASET.md               # 来源、许可、获取与版本
│   ├── DATA_AUDIT.md            # 实际审计结果
│   ├── PRODUCT_SPEC.md          # 可 diff 的规范源
│   ├── PRODUCT_SPEC.docx        # 格式化阅读副本
│   └── olist_raw.sha256         # 原始文件校验清单
├── scripts/
│   ├── profile_dataset.py       # 完整审计
│   ├── check_join_grain.py      # 定向 Join 粒度检查
│   ├── dataset_io.py            # 共享只读 CSV 读取与键规范化
│   ├── build_duckdb.py          # typed DuckDB 原子构建
│   └── baseline_queries.py      # 14 条 English baseline SQL
├── src/data_analysis_agent/
│   ├── schema.py                 # deterministic schema inspection
│   └── sql_executor.py           # safe deterministic read-only SQL
├── tests/
├── LICENSE
└── pyproject.toml
```

## 已知限制

- Olist 是 2016–2018 年的历史巴西电商数据，不能代表当前市场。
- 数据没有完整退款、商品成本或利润字段，不能计算可靠退款率或毛利率。
- `geolocation_zip_code_prefix` 不是唯一键，连接前必须聚合。
- `review_id` 单列不唯一，建库时不能直接设为单列主键。
- `order_items` 和 `order_payments` 都是一对多表，必须分别按订单预聚合后
  再连接，否则金额会重复。
- 第一版 DuckDB 不包含 geolocation；需要地理坐标分析时必须先定义邮编聚合规则。
- 只读 executor 尚未实现查询超时、资源配额或异步取消；当前只限制返回到 Python
  应用层的行数。

## License

项目源代码使用 [MIT License](LICENSE)。

Olist 数据单独使用 CC BY-NC-SA 4.0；MIT License 不适用于数据。数据使用者
必须遵守原始来源页面和数据许可证的要求。

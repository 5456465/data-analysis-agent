# Data Analysis Agent 产品规格

## 1. 文档状态

- 版本：MVP Read-only SQL Execution v1.4
- 更新日期：2026-08-11
- 当前阶段：DuckDB、inspect_schema 与只读 SQL executor 完成
- 规范源：本 Markdown 文件
- 阅读副本：`docs/PRODUCT_SPEC.docx`

## 2. 产品定位

Data Analysis Agent 是一个面向结构化业务数据的可验证多工具分析 Agent。
当前 MVP 中用户使用英文自然语言提问，系统在受控权限下检查指标口径和 Schema，执行只读
SQL 或确定性 Python 分析，验证结果并返回可追溯证据。

项目重点是工具调用、错误恢复、结果验证和可复现评测，而不是构建企业级
BI 平台。

### 2.1 语言设计

#### 当前 MVP：English-first

| 层 | 当前约束 |
|---|---|
| Input | English only |
| Output | English only |
| Prompt | English |
| Tool name / description | English |
| Evaluation question | English first |
| DuckDB / SQL | 原始英文 Schema 与 identifier |
| Metric / dimension / semantic entity | 稳定的英文 canonical identifier |

产品问答能力尚未实现，因此“非英文输入返回 unsupported”是后续问答入口的验收
要求，不是当前已实现功能。MVP 不实现自动语言检测、自动翻译、中文 Schema、中文
字段别名、葡萄牙语评论翻译、多语言 UI 或多语言 RAG，也不为这些后续能力引入
完整 i18n 框架。

#### 内部工程语言

- Python 文件、模块、类、函数和变量使用英文。
- System Prompt、Agent Prompt、Tool 名称与 Tool description 使用英文。
- SQL 和 DuckDB 保持 Olist 原始英文表名与字段名，不创建中文 Schema 或中文表副本。
- Metric、dimension 和 semantic entity 使用英文 canonical identifier；测试代码和
  机器可读配置优先使用英文。
- SQL 层、数据库 Schema 和 Tool 接口不感知用户使用的自然语言。

仓库说明文档可以使用中文，Codex 对开发者的解释也可以使用中文；两者均不代表
产品运行时已经支持中文问答。

#### 原始数据语言

Olist 原始数据中的葡萄牙语值原样保留，不覆盖、不批量机器翻译。对于官方
`product_category_name_translation.csv`，同时保留
`product_category_name` 和 `product_category_name_english` 的映射。分析可以优先
展示官方英文标准值，但必须能够追溯到原始葡萄牙语值。

#### 后续中文扩展

中文问答只在 semantic alias、Prompt 和 response 层扩展，仍映射到现有英文
canonical schema，不改变数据库层或 SQL Tool 接口。例如以下结构只是未来语义层
的设计示例，不属于当前 MVP 实现：

```yaml
canonical_identifier: avg_order_payment
english_label: average order payment
future_chinese_aliases:
  - 平均订单支付金额
  - 平均订单金额
  - 客单价
```

未来支持中文和英文时，默认按用户输入语言返回；在代码和双语评测实际存在前，
不得声明 Chinese support 已实现。

## 3. 唯一数据集

MVP 只使用 Brazilian E-Commerce Public Dataset by Olist：

- 来源：Kaggle Olist 官方数据卡
- 许可：CC BY-NC-SA 4.0
- 时间范围：主要为 2016–2018 年历史订单
- 本地目录：`data/raw/`
- 数据版本：`docs/olist_raw.sha256`
- 审计结果：`docs/DATA_AUDIT.md`

不使用口碑、天池、UCI Online Retail、TPC-H 或模拟多平台电商数据。

## 4. 实际 DuckDB 表与粒度

数据库文件：`data/processed/olist.duckdb`。表名映射由
`scripts/build_duckdb.py` 显式维护：

| DuckDB 表 | 实际源 CSV | 主粒度 / 主键 |
|---|---|---|
| `customers` | `olist_customers_dataset.csv` | `customer_id` |
| `orders` | `olist_orders_dataset.csv` | `order_id` |
| `order_items` | `olist_order_items_dataset.csv` | `order_id + order_item_id` |
| `order_payments` | `olist_order_payments_dataset.csv` | `order_id + payment_sequential` |
| `order_reviews` | `olist_order_reviews_dataset.csv` | `review_id + order_id`；`review_id` 单列不唯一 |
| `products` | `olist_products_dataset.csv` | `product_id` |
| `sellers` | `olist_sellers_dataset.csv` | `seller_id` |
| `product_category_translation` | `product_category_name_translation.csv` | `product_category_name` |

第一版不导入 `olist_geolocation_dataset.csv`。该文件仍属于已审计原始数据，未来
需要坐标分析时必须先将非唯一邮编观测聚合到明确粒度。

## 5. 金额与 Join 规则

- `order_items` 和 `order_payments` 都是相对 `orders` 的一对多表。
- 禁止直接把两张明细表按 `order_id` 连接后汇总金额。
- 商品金额口径应先在 `order_items` 按订单聚合。
- 支付金额口径应先在 `order_payments` 按订单聚合。
- 两侧都到订单粒度后，才能与 `orders` 或彼此连接。
- 当前定向审计证明：直接 Join 会放大金额，预聚合后金额精确守恒。
- `order_item_summary` view 按 `order_id` 汇总 `item_count`、
  `item_transaction_value` 和 `freight_value`。
- `order_payment_summary` view 按 `order_id` 汇总 `payment_record_count` 和
  `payment_value`。
- `products_with_category_translation` view 同时保留原始葡萄牙语品类与官方英文映射。

### 5.1 Baseline SQL

`scripts/baseline_queries.py` 提供 14 条可独立运行的 English baseline SQL。金额
定义保持分离：

- `item_transaction_value`：order-item 粒度的 `SUM(order_items.price)`；
- `freight_value`：order-item 粒度的 `SUM(order_items.freight_value)`；
- `payment_value`：先按订单汇总支付记录，再执行订单级分析。

Baseline 不使用笼统的 revenue，也不计算数据不支持的 profit、gross margin 或
refund rate。

### 5.2 Schema inspection

`data_analysis_agent.inspect_schema` 以只读连接查询实际 DuckDB catalog，返回稳定的
结构化 Python dataclass，而不是仅返回格式化文本。输出包含：

- table / view name 和 object type；
- 按 catalog ordinal position 排列的 column name 与 DuckDB data type；
- DuckDB catalog 可可靠读取的 nullable 和 primary key 标记；
- 仅对项目已确认对象提供的最小 grain metadata。

当前 grain metadata 包含 `orders`、`order_items`、`order_payments`、
`order_item_summary` 和 `order_payment_summary`。未知粒度返回 `None`，不猜测。
该模块不生成或执行用户 SQL，不包含 LLM、RAG、Text-to-SQL 或翻译逻辑。

### 5.3 Read-only SQL execution

`data_analysis_agent.run_readonly_sql(database_path, sql, max_rows=200)` 提供最小、
确定性的查询执行边界：

- 只接受单条 `SELECT` 或 `WITH ... SELECT`；
- 先检查注释后的首关键字，再使用 DuckDB parser 校验 statement 数量和类型；
- 使用 `read_only=True` 打开 DuckDB，并关闭外部文件访问及 extension 自动安装/加载；
- 使用 `fetchmany(max_rows + 1)` 判断截断，最多向 Python 应用层返回 `max_rows` 行；
- 不向用户 SQL 静默添加 `LIMIT`，因此不改变聚合查询的业务语义；
- 返回稳定的 `SQLResult`，包含 SQL、列、行、返回行数、截断状态和结构化错误。

错误代码区分 database missing、invalid argument、unsafe SQL、multiple statements、
invalid SQL、unknown table / column 和其他 execution error。本阶段不包含 SQL 生成、
LLM repair、timeout 或资源配额。

## 6. 支持与不支持的业务问题

### 数据可支持

- 订单量、订单状态和取消订单分析
- 商品价格、运费、支付金额和支付方式分析
- 客单价，但必须明确使用商品金额还是支付金额
- 品类、卖家、客户州级分布
- 下单、审批、发货、交付时效
- 评论分数和评论覆盖率

### 数据不支持

- 可靠退款率或退款金额：没有完整退款表
- 毛利率：没有商品成本
- 当前市场判断：数据为 2016–2018 年历史场景
- 无证据的未来预测或因果结论

## 7. MVP 目标工作流

1. 接收英文自然语言问题；非英文输入在问答入口实现后明确返回 unsupported。
2. 在需要时检索指标定义。
3. 检查相关表、字段、类型和关系。
4. 生成并安全检查只读 SQL。
5. 执行 SQL；复杂统计只调用白名单 Python 函数。
6. 检查时间范围、聚合关系、空结果和金额粒度。
7. 返回结论、SQL、表字段、数据范围、验证状态和限制。

## 8. 当前实现状态

### 已实现

- Olist 文件、字段、键、缺失值、重复值、日期和关联覆盖率审计
- item/payment Join 放大与金额守恒检查
- SHA-256 数据版本清单
- Python 包骨架和单元测试
- 8 张核心表的 typed DuckDB 与 3 个可追溯 view
- 14 条 English baseline SQL
- DuckDB 行数、主键假设、Join、时间类型和金额守恒测试
- 结构化、确定性的只读 `inspect_schema` 及其 table、view、类型、错误和稳定性测试
- 单 statement、只读、行数受限的 `run_readonly_sql` 及结构化成功/错误结果

### 下一阶段：English Text-to-SQL 基线

- 建立第一批人工校验的英文问题与 gold SQL
- 在现有 Schema inspector 和只读 executor 之上接入最小 SQL 生成流程

### 后续规划

- Metric definition retrieval
- Controlled Python analysis
- Chart generation
- Result validation
- 显式工作流或 LangGraph
- Streamlit Demo
- 可复现 Agent 评测

规划项在代码和测试实际存在前，不得在 README 或简历中声明为已完成。

## 9. 安全与可靠性

- 数据库层使用 `read_only=True`，只接受单条 `SELECT` / `WITH ... SELECT`，
  拒绝写操作、多语句和非 allowlist statement。
- 原始 CSV、数据库、Parquet、日志、`.env` 和虚拟环境不得进入 Git。
- 不使用公司、实习单位或个人隐私数据。
- 无数据、指标歧义或验证失败时不得编造确定性结论。
- 工具调用、重试次数、SQL、数据范围和验证状态必须可追溯。

## 10. 许可证边界

- 项目源代码：MIT License，见根目录 `LICENSE`。
- Olist 数据：CC BY-NC-SA 4.0，与代码许可证分离。
- 原始和处理后数据不随源代码仓库分发。

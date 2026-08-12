# Data Analysis Agent 产品规格

## 1. 文档状态

- 版本：v1.5
- 更新日期：2026-08-12
- 当前阶段：Deterministic agent foundation + English Core Gold Set completed; next stage is minimal English LLM Text-to-SQL generation.
- 规范源：本 Markdown 文件
- 阅读副本：`docs/PRODUCT_SPEC.docx`

## 2. 产品定位

Data Analysis Agent 的产品定位是 **Verifiable Multi-Tool Business Data Analysis Agent**，
即面向结构化业务数据的可验证多工具分析 Agent。
当前 MVP 中用户使用英文自然语言提问，系统在受控权限下检查指标口径和 Schema，执行只读
SQL 或确定性 Python 分析，验证结果并返回可追溯证据。

核心分析闭环是 `understand → retrieve metric context → inspect data → choose tools →
execute → repair → validate → explain`。项目重点是 controlled tool execution、business
metric correctness、error recovery、result validation、traceability 和 quantitative
evaluation，而不是单纯的 Text-to-SQL Demo 或企业级 BI 平台。

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
当前数据输入链路明确为 `Olist CSV → typed DuckDB`，不声明支持 Parquet。Parquet 和
multiple data-source support 均属于 post-MVP 扩展。

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

### 5.1 Baseline Query 与 Business Metric 的边界

`scripts/baseline_queries.py` 提供 14 条可独立运行的 English baseline SQL。金额
定义保持分离：

- `item_transaction_value`：order-item 粒度的 `SUM(order_items.price)`；
- `freight_value`：order-item 粒度的 `SUM(order_items.freight_value)`；
- `payment_value`：先按订单汇总支付记录，再执行订单级分析。

Baseline 不使用笼统的 revenue，也不计算数据不支持的 profit、gross margin 或
refund rate。

Baseline Query 与 Metric Catalog 是两层概念：

- Baseline Query 是人工验证的数据事实和 evaluation reference；Metric Catalog 是产品
  正式使用的业务指标语义。
- 两者可以对应，但不要求定义完全相同；不允许为了匹配 Metric Catalog 静默修改既有
  baseline 的含义。
- `average_payment_value_per_order` baseline 先将有 payment record 的订单聚合到 order
  grain，再求订单支付金额的平均值；它不等同于排除 `canceled` / `unavailable` 后的
  valid-order AOV。
- `total_item_transaction_value` baseline 是 `SUM(order_items.price)`，不包含 freight 或
  payment，也不声明为 revenue 或 profit。
- 未来定义 `avg_order_payment`、`valid_merchandise_value` 等 canonical metric 时，必须
  明确过滤条件；如果语义不同，应新增对应 baseline，而不是改变旧 baseline。

### 5.2 Metric Catalog / Retrieval

MVP 建立至少 6 个 canonical business metrics。每个 metric 至少包含：

- `canonical_identifier`
- `english_label`
- `aliases` / `keywords`
- `definition`
- `formula`
- `filters`
- `time_granularity`
- `source_tables`
- `limitations` / `notes`

`search_metric_definition` 第一版优先使用确定性的 catalog、alias 和 keyword retrieval。
embedding / vector retrieval 只作为未来的 Metric RAG 增强方案，在指标、业务文档和
glossary 规模明显扩大后再考虑；不为 6–10 个指标强制引入 vector database。检索不到
可靠定义或存在口径冲突时，系统必须说明歧义或请求确认，不得猜测公式。

### 5.3 Schema inspection

`data_analysis_agent.inspect_schema` 以只读连接查询实际 DuckDB catalog，返回稳定的
结构化 Python dataclass，而不是仅返回格式化文本。输出包含：

- table / view name 和 object type；
- 按 catalog ordinal position 排列的 column name 与 DuckDB data type；
- DuckDB catalog 可可靠读取的 nullable 和 primary key 标记；
- 仅对项目已确认对象提供的最小 grain metadata。

当前 grain metadata 包含 `orders`、`order_items`、`order_payments`、
`order_item_summary` 和 `order_payment_summary`。未知粒度返回 `None`，不猜测。
该模块不生成或执行用户 SQL，不包含 LLM、RAG、Text-to-SQL 或翻译逻辑。

### 5.4 Read-only SQL execution

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

### 5.5 Controlled Python analysis

保留 Python Analysis Tool，但 SQL 能自然、可靠完成的聚合或窗口计算必须留在 SQL，
不为了展示 multi-tool 强行转入 Python。Python Tool 只处理 SQL 查询结果上的二次分析，
例如 anomaly detection、change decomposition、distribution analysis 和不适合由 SQL
承担的统计后处理。MVP 至少实现 2 个真正有区别的受控 Python functions；模型不得执行
任意 Python code。

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

## 7. MVP 目标工作流与编排边界

1. 接收英文自然语言问题；非英文输入在问答入口实现后明确返回 unsupported。
2. 在需要时检索指标定义。
3. 检查相关表、字段、类型和关系。
4. simple lookup / basic aggregation 走 `schema → SQL → execute → validate`。
5. complex diagnostic / multi-step analysis 才进入 `plan_tools`，再按需调用 SQL、受控
   Python 或图表工具。
6. 检查时间范围、聚合关系、空结果和金额粒度；可恢复错误进入有限 repair。
7. 返回结论、SQL、表字段、数据范围、验证状态和限制。

`plan_tools` 是 conditional workflow node，不是所有任务的 mandatory step。MVP 保持
single Agent + explicit workflow/state。最终 workflow integration 阶段优先考虑
LangGraph，以承载 state、conditional routing、retry、repair 和 trace，但当前阶段不提前
引入。LangChain 不是产品硬性要求，仅在 model、tool 或 structured-output abstraction
确实有收益时采用。Multi-Agent 不属于 MVP；MCP 属于 post-MVP extension，当前本地
DuckDB + Python tools 不存在真实 MCP 边界。

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
- **English Core Gold Set v0.1**：16 questions，其中 14 answerable、2 unanswerable；
  覆盖 basic queries、aggregation、multi-table、delivery analysis、grain-sensitive
  questions 和 unsupported questions；用于验证问题理解、合理的 tables、正确 grain、
  metric 语义和最终查询结果，不要求模型生成逐字符相同的 SQL
- 完整 pytest：63 passed

### 下一阶段：Minimal English LLM Text-to-SQL generation

- 在现有 Schema inspector、只读 executor 和 English Core Gold Set v0.1 之上接入最小
  English LLM Text-to-SQL generation

### 后续规划

- Metric Catalog / deterministic retrieval
- Controlled Python analysis
- Chart generation
- Result validation
- 显式工作流或 LangGraph
- Streamlit Demo
- 将完整 evaluation set 逐步扩展到至少 30 条；扩展随 metric semantics、trend、
  MoM / YoY、diagnostic、tool routing、repair、adversarial / boundary cases 的实现推进，
  不机械扩充当前 16 道题
- embedding / vector Metric RAG、MCP、Parquet 与 multiple data-source support 均为
  post-MVP extension

规划项在代码和测试实际存在前，不得在 README 或简历中声明为已完成。

## 9. 安全与可靠性

- 数据库层使用 `read_only=True`，只接受单条 `SELECT` / `WITH ... SELECT`，
  拒绝写操作、多语句和非 allowlist statement。
- executor 不改写 SQL；通过 `fetchmany(max_rows + 1)` 最多返回 `max_rows` 行，并用
  `truncated` 表示是否仍有更多结果，保留原 SQL 以支持 reproducibility、tracing 和
  auditing。
- query timeout / resource quota 当前尚未实现，属于 reliability hardening / later MVP
  task，不得描述为现有 executor 能力。
- 原始 CSV、数据库、Parquet、日志、`.env` 和虚拟环境不得进入 Git。
- 不使用公司、实习单位或个人隐私数据。
- 无数据、指标歧义或验证失败时不得编造确定性结论。
- 工具调用、重试次数、SQL、数据范围和验证状态必须可追溯。

## 10. 许可证边界

- 项目源代码：MIT License，见根目录 `LICENSE`。
- Olist 数据：CC BY-NC-SA 4.0，与代码许可证分离。
- 原始和处理后数据不随源代码仓库分发。

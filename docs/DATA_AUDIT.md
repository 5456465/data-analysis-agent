# DATA_AUDIT — Olist 巴西电子商务数据集

> 生成时间（UTC）：2026-08-06T09:18:48+00:00

## 结论

**适合作为本项目 20 天 MVP 的主数据源，但应将项目保持为非商业作品集用途，并满足署名和相同方式共享要求。**

支持作为主数据源的依据：

- 来源与许可清晰：Kaggle 的 Olist 官方数据卡标注 `CC BY-NC-SA 4.0`，适合非商业学习和作品集演示。
- 业务结构完整：包含订单、明细、商品、卖家、客户、支付、评论、物流时间和地理信息，可支持销售、客单价、运费、交付时效、满意度等可验证指标。
- 关系结构适合 SQL 和数据验证演示：6 个核心 ID 关系全部达到 100% 行覆盖。
- 规模可控：9 张表、1,550,922 行、120.3 MiB，可在本地用 pandas 和 DuckDB 反复测试。
- 数据卡说明这是经过匿名化的真实商业数据，比纯合成数据更有利于展示真实质量问题和指标口径。

需要接受的边界：

- 数据为 2016–2018 年的巴西历史业务，不能代表当前市场。
- 1 个时间字段包含超出 2018 年的值；当前是 `shipping_limit_date` 的 4 条 2020 年记录，建模前应标记为时间异常。
- 没有 `shop_id`；实际商家键是 `seller_id`。指标和问题示例应使用真实字段名。
- 没有显式退款表或成本/利润字段；退款率、毛利率等指标不能直接计算。
- 许可包含 NonCommercial 限制，不适合未经额外授权的商业产品。
- 3 个非核心映射存在少量孤儿键，下文已给出精确覆盖率。

## 审计口径

- 所有表均按 UTF-8 CSV 实际表头读取，并以字符串保留 ID 和邮编前导零。
- 评论文件含带引号的多行文本，因此行数以 CSV 解析后的记录数为准，不使用物理换行数。
- 缺失率 = 空值数 / 表行数。
- 重复率 = 完全重复且排除首次出现的行数 / 表行数。
- 类型同时报告 CSV 存储类型和基于全部非空值推断的逻辑类型。
- 关联行覆盖率的分母是子表中非空关联键行数；唯一键覆盖率用于衡量不同孤儿键。

## 文件与表概览

| 文件 | 行数 | 字段数 | 完全重复行 | 重复率 | 文件大小 |
|---|---:|---:|---:|---:|---:|
| `olist_customers_dataset.csv` | 99,441 | 5 | 0 | 0.0000% | 9,033,957 B |
| `olist_geolocation_dataset.csv` | 1,000,163 | 5 | 261,831 | 26.1788% | 61,273,883 B |
| `olist_order_items_dataset.csv` | 112,650 | 7 | 0 | 0.0000% | 15,438,671 B |
| `olist_order_payments_dataset.csv` | 103,886 | 5 | 0 | 0.0000% | 5,777,138 B |
| `olist_order_reviews_dataset.csv` | 99,224 | 7 | 0 | 0.0000% | 14,451,670 B |
| `olist_orders_dataset.csv` | 99,441 | 8 | 0 | 0.0000% | 17,654,914 B |
| `olist_products_dataset.csv` | 32,951 | 9 | 0 | 0.0000% | 2,379,446 B |
| `olist_sellers_dataset.csv` | 3,095 | 4 | 0 | 0.0000% | 174,703 B |
| `product_category_name_translation.csv` | 71 | 2 | 0 | 0.0000% | 2,613 B |

## 关键字段存在性

| 字段 | 实际出现的表 |
|---|---|
| `shop_id` | 未发现 |
| `seller_id` | `olist_order_items_dataset`, `olist_sellers_dataset` |
| `order_id` | `olist_order_items_dataset`, `olist_order_payments_dataset`, `olist_order_reviews_dataset`, `olist_orders_dataset` |
| `customer_id` | `olist_customers_dataset`, `olist_orders_dataset` |
| `customer_unique_id` | `olist_customers_dataset` |
| `product_id` | `olist_order_items_dataset`, `olist_products_dataset` |

## 字段结构校验

- 通过：9 张实际 CSV 的表头与已审阅字段完全一致。

## 候选主键/复合键质量

| 表 | 候选键 | 缺失行 | 重复键行 | 唯一键数 |
|---|---|---:|---:|---:|
| `olist_customers_dataset` | `customer_id` | 0 | 0 | 99,441 |
| `olist_orders_dataset` | `order_id` | 0 | 0 | 99,441 |
| `olist_order_items_dataset` | `order_id + order_item_id` | 0 | 0 | 112,650 |
| `olist_order_payments_dataset` | `order_id + payment_sequential` | 0 | 0 | 103,886 |
| `olist_order_reviews_dataset` | `review_id` | 0 | 814 | 98,410 |
| `olist_order_reviews_dataset` | `review_id + order_id` | 0 | 0 | 99,224 |
| `olist_products_dataset` | `product_id` | 0 | 0 | 32,951 |
| `olist_sellers_dataset` | `seller_id` | 0 | 0 | 3,095 |
| `product_category_name_translation` | `product_category_name` | 0 | 0 | 71 |

## 表关联覆盖率

| 关系 | 类型 | 子表非空行 | 缺失键行 | 匹配行 | 行覆盖率 | 唯一键覆盖率 | 父表键被引用率 | 父键重复数 | 孤儿键样例 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| orders.customer_id → customers.customer_id | foreign key | 99,441 | 0 | 99,441 | 100.0000% | 100.0000% | 100.0000% | 0 | — |
| order_items.order_id → orders.order_id | foreign key | 112,650 | 0 | 112,650 | 100.0000% | 100.0000% | 99.2206% | 0 | — |
| order_items.product_id → products.product_id | foreign key | 112,650 | 0 | 112,650 | 100.0000% | 100.0000% | 100.0000% | 0 | — |
| order_items.seller_id → sellers.seller_id | foreign key | 112,650 | 0 | 112,650 | 100.0000% | 100.0000% | 100.0000% | 0 | — |
| payments.order_id → orders.order_id | foreign key | 103,886 | 0 | 103,886 | 100.0000% | 100.0000% | 99.9990% | 0 | — |
| reviews.order_id → orders.order_id | foreign key | 99,224 | 0 | 99,224 | 100.0000% | 100.0000% | 99.2277% | 0 | — |
| products.category → category_translation.category | foreign key | 32,341 | 610 | 32,328 | 99.9598% | 97.2603% | 100.0000% | 0 | `pc_gamer`, `portateis_cozinha_e_preparadores_de_alimentos` |
| customers.zip_prefix → geolocation.zip_prefix | non-unique lookup | 99,441 | 0 | 99,163 | 99.7204% | 98.9529% | 78.0279% | 981,148 | `02140`, `06930`, `07412`, `07430`, `07729`, `07784`, `08342`, `08980`, `11547`, `12332` |
| sellers.zip_prefix → geolocation.zip_prefix | non-unique lookup | 3,095 | 0 | 3,088 | 99.7738% | 99.6883% | 11.7749% | 981,148 | `02285`, `07412`, `37708`, `71551`, `72580`, `82040`, `91901` |

### 关联解读

- 订单→客户、明细→订单/商品/卖家、支付→订单、评论→订单的行覆盖率均为 100%。
- 反向看父表参与度：775 个订单没有明细，1 个订单没有支付记录，768 个订单没有评论。这些不一定是错误，但分析时不能使用 inner join 默默丢弃。
- 品类翻译表缺少 2 个葡萄牙语品类键，影响 13 个非空品类商品；另有 610 个商品的品类本身缺失。
- 客户邮编地理覆盖率为 99.7204%，卖家为 99.7738%。`geolocation_zip_code_prefix` 不唯一是数据设计：同一邮编有多个坐标观测，关联前需先聚合到邮编粒度。

## 表：`olist_customers_dataset`

- 文件：`olist_customers_dataset.csv`
- 行数：99,441
- 字段数：5
- 完全重复率：0.0000%

### 字段、类型和缺失率

| 字段 | CSV 存储类型 | 逻辑类型 | 缺失数 | 缺失率 | 唯一值数 | 格式无效数 |
|---|---|---|---:|---:|---:|---:|
| `customer_id` | string | identifier (string) | 0 | 0.0000% | 99,441 | 0 |
| `customer_unique_id` | string | identifier (string) | 0 | 0.0000% | 96,096 | 0 |
| `customer_zip_code_prefix` | string | identifier (string) | 0 | 0.0000% | 14,994 | 0 |
| `customer_city` | string | string | 0 | 0.0000% | 4,119 | 0 |
| `customer_state` | string | string | 0 | 0.0000% | 27 | 0 |

### 时间范围

该表没有通过字段名和全值转换检测到时间字段。

## 表：`olist_geolocation_dataset`

- 文件：`olist_geolocation_dataset.csv`
- 行数：1,000,163
- 字段数：5
- 完全重复率：26.1788%

### 字段、类型和缺失率

| 字段 | CSV 存储类型 | 逻辑类型 | 缺失数 | 缺失率 | 唯一值数 | 格式无效数 |
|---|---|---|---:|---:|---:|---:|
| `geolocation_zip_code_prefix` | string | identifier (string) | 0 | 0.0000% | 19,015 | 0 |
| `geolocation_lat` | string | decimal | 0 | 0.0000% | 717,372 | 0 |
| `geolocation_lng` | string | decimal | 0 | 0.0000% | 717,615 | 0 |
| `geolocation_city` | string | string | 0 | 0.0000% | 8,011 | 0 |
| `geolocation_state` | string | string | 0 | 0.0000% | 27 | 0 |

### 时间范围

该表没有通过字段名和全值转换检测到时间字段。

## 表：`olist_order_items_dataset`

- 文件：`olist_order_items_dataset.csv`
- 行数：112,650
- 字段数：7
- 完全重复率：0.0000%

### 字段、类型和缺失率

| 字段 | CSV 存储类型 | 逻辑类型 | 缺失数 | 缺失率 | 唯一值数 | 格式无效数 |
|---|---|---|---:|---:|---:|---:|
| `order_id` | string | identifier (string) | 0 | 0.0000% | 98,666 | 0 |
| `order_item_id` | string | identifier (string) | 0 | 0.0000% | 21 | 0 |
| `product_id` | string | identifier (string) | 0 | 0.0000% | 32,951 | 0 |
| `seller_id` | string | identifier (string) | 0 | 0.0000% | 3,095 | 0 |
| `shipping_limit_date` | string | datetime | 0 | 0.0000% | 93,318 | 0 |
| `price` | string | decimal | 0 | 0.0000% | 5,968 | 0 |
| `freight_value` | string | decimal | 0 | 0.0000% | 6,999 | 0 |

### 时间范围

| 时间字段 | 非空值 | 有效时间 | 无效时间 | 无效率 | 2018 年后记录 | 最小值 | 最大值 |
|---|---:|---:|---:|---:|---:|---|---|
| `shipping_limit_date` | 112,650 | 112,650 | 0 | 0.0000% | 4 | 2016-09-19 00:15:34 | 2020-04-09 22:35:08 |

## 表：`olist_order_payments_dataset`

- 文件：`olist_order_payments_dataset.csv`
- 行数：103,886
- 字段数：5
- 完全重复率：0.0000%

### 字段、类型和缺失率

| 字段 | CSV 存储类型 | 逻辑类型 | 缺失数 | 缺失率 | 唯一值数 | 格式无效数 |
|---|---|---|---:|---:|---:|---:|
| `order_id` | string | identifier (string) | 0 | 0.0000% | 99,440 | 0 |
| `payment_sequential` | string | integer | 0 | 0.0000% | 29 | 0 |
| `payment_type` | string | string | 0 | 0.0000% | 5 | 0 |
| `payment_installments` | string | integer | 0 | 0.0000% | 24 | 0 |
| `payment_value` | string | decimal | 0 | 0.0000% | 29,077 | 0 |

### 时间范围

该表没有通过字段名和全值转换检测到时间字段。

## 表：`olist_order_reviews_dataset`

- 文件：`olist_order_reviews_dataset.csv`
- 行数：99,224
- 字段数：7
- 完全重复率：0.0000%

### 字段、类型和缺失率

| 字段 | CSV 存储类型 | 逻辑类型 | 缺失数 | 缺失率 | 唯一值数 | 格式无效数 |
|---|---|---|---:|---:|---:|---:|
| `review_id` | string | identifier (string) | 0 | 0.0000% | 98,410 | 0 |
| `order_id` | string | identifier (string) | 0 | 0.0000% | 98,673 | 0 |
| `review_score` | string | integer | 0 | 0.0000% | 5 | 0 |
| `review_comment_title` | string | string | 87,656 | 88.3415% | 4,527 | 0 |
| `review_comment_message` | string | string | 58,247 | 58.7025% | 36,159 | 0 |
| `review_creation_date` | string | datetime | 0 | 0.0000% | 636 | 0 |
| `review_answer_timestamp` | string | datetime | 0 | 0.0000% | 98,248 | 0 |

### 时间范围

| 时间字段 | 非空值 | 有效时间 | 无效时间 | 无效率 | 2018 年后记录 | 最小值 | 最大值 |
|---|---:|---:|---:|---:|---:|---|---|
| `review_creation_date` | 99,224 | 99,224 | 0 | 0.0000% | 0 | 2016-10-02 00:00:00 | 2018-08-31 00:00:00 |
| `review_answer_timestamp` | 99,224 | 99,224 | 0 | 0.0000% | 0 | 2016-10-07 18:32:28 | 2018-10-29 12:27:35 |

## 表：`olist_orders_dataset`

- 文件：`olist_orders_dataset.csv`
- 行数：99,441
- 字段数：8
- 完全重复率：0.0000%

### 字段、类型和缺失率

| 字段 | CSV 存储类型 | 逻辑类型 | 缺失数 | 缺失率 | 唯一值数 | 格式无效数 |
|---|---|---|---:|---:|---:|---:|
| `order_id` | string | identifier (string) | 0 | 0.0000% | 99,441 | 0 |
| `customer_id` | string | identifier (string) | 0 | 0.0000% | 99,441 | 0 |
| `order_status` | string | string | 0 | 0.0000% | 8 | 0 |
| `order_purchase_timestamp` | string | datetime | 0 | 0.0000% | 98,875 | 0 |
| `order_approved_at` | string | datetime | 160 | 0.1609% | 90,733 | 0 |
| `order_delivered_carrier_date` | string | datetime | 1,783 | 1.7930% | 81,018 | 0 |
| `order_delivered_customer_date` | string | datetime | 2,965 | 2.9817% | 95,664 | 0 |
| `order_estimated_delivery_date` | string | datetime | 0 | 0.0000% | 459 | 0 |

### 时间范围

| 时间字段 | 非空值 | 有效时间 | 无效时间 | 无效率 | 2018 年后记录 | 最小值 | 最大值 |
|---|---:|---:|---:|---:|---:|---|---|
| `order_purchase_timestamp` | 99,441 | 99,441 | 0 | 0.0000% | 0 | 2016-09-04 21:15:19 | 2018-10-17 17:30:18 |
| `order_approved_at` | 99,281 | 99,281 | 0 | 0.0000% | 0 | 2016-09-15 12:16:38 | 2018-09-03 17:40:06 |
| `order_delivered_carrier_date` | 97,658 | 97,658 | 0 | 0.0000% | 0 | 2016-10-08 10:34:01 | 2018-09-11 19:48:28 |
| `order_delivered_customer_date` | 96,476 | 96,476 | 0 | 0.0000% | 0 | 2016-10-11 13:46:32 | 2018-10-17 13:22:46 |
| `order_estimated_delivery_date` | 99,441 | 99,441 | 0 | 0.0000% | 0 | 2016-09-30 00:00:00 | 2018-11-12 00:00:00 |

## 表：`olist_products_dataset`

- 文件：`olist_products_dataset.csv`
- 行数：32,951
- 字段数：9
- 完全重复率：0.0000%

### 字段、类型和缺失率

| 字段 | CSV 存储类型 | 逻辑类型 | 缺失数 | 缺失率 | 唯一值数 | 格式无效数 |
|---|---|---|---:|---:|---:|---:|
| `product_id` | string | identifier (string) | 0 | 0.0000% | 32,951 | 0 |
| `product_category_name` | string | string | 610 | 1.8512% | 73 | 0 |
| `product_name_lenght` | string | integer | 610 | 1.8512% | 66 | 0 |
| `product_description_lenght` | string | integer | 610 | 1.8512% | 2,960 | 0 |
| `product_photos_qty` | string | integer | 610 | 1.8512% | 19 | 0 |
| `product_weight_g` | string | integer | 2 | 0.0061% | 2,204 | 0 |
| `product_length_cm` | string | integer | 2 | 0.0061% | 99 | 0 |
| `product_height_cm` | string | integer | 2 | 0.0061% | 102 | 0 |
| `product_width_cm` | string | integer | 2 | 0.0061% | 95 | 0 |

### 时间范围

该表没有通过字段名和全值转换检测到时间字段。

## 表：`olist_sellers_dataset`

- 文件：`olist_sellers_dataset.csv`
- 行数：3,095
- 字段数：4
- 完全重复率：0.0000%

### 字段、类型和缺失率

| 字段 | CSV 存储类型 | 逻辑类型 | 缺失数 | 缺失率 | 唯一值数 | 格式无效数 |
|---|---|---|---:|---:|---:|---:|
| `seller_id` | string | identifier (string) | 0 | 0.0000% | 3,095 | 0 |
| `seller_zip_code_prefix` | string | identifier (string) | 0 | 0.0000% | 2,246 | 0 |
| `seller_city` | string | string | 0 | 0.0000% | 611 | 0 |
| `seller_state` | string | string | 0 | 0.0000% | 23 | 0 |

### 时间范围

该表没有通过字段名和全值转换检测到时间字段。

## 表：`product_category_name_translation`

- 文件：`product_category_name_translation.csv`
- 行数：71
- 字段数：2
- 完全重复率：0.0000%

### 字段、类型和缺失率

| 字段 | CSV 存储类型 | 逻辑类型 | 缺失数 | 缺失率 | 唯一值数 | 格式无效数 |
|---|---|---|---:|---:|---:|---:|
| `product_category_name` | string | string | 0 | 0.0000% | 71 | 0 |
| `product_category_name_english` | string | string | 0 | 0.0000% | 71 | 0 |

### 时间范围

该表没有通过字段名和全值转换检测到时间字段。

## 隐私、许可和使用边界

- Kaggle 数据卡标注该数据经过匿名化，但 `customer_unique_id`、评论文本和精细坐标仍可用于行为链接；演示时应优先输出聚合结果。
- 许可为 [CC BY-NC-SA 4.0](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce/data)：需署名、限非商业使用，改编成果需按相同许可共享。
- 建议仓库只保存下载说明、来源和生成脚本；如要公开提交原始 CSV，应同时保留署名和许可文本。

## 审计限制

- 本报告对当前目录中 9 张 CSV 做全量统计，不是抽样。
- 关联覆盖率本身只证明键值存在；一对多金额风险由下方定向检查补充验证，业务时序仍需在具体指标实现中验证。
- `review_id` 单列并不唯一；若建库，需要按实际复合键或代理键建模，不能直接将其强制为单列主键。
- 许可解读用于项目风险评估，不是法律意见。

## order_items / order_payments Join 粒度定向检查

> 补充检查日期：2026-08-07  
> 可复现命令：`.venv/bin/python scripts/check_join_grain.py`

本检查只读取订单明细与支付两张表，不重复执行全量数据审计。
金额先转换为整数分，避免浮点舍入影响守恒判断。

| 指标 | 结果 |
|---|---:|
| 两表共同订单数 | 98,665 |
| 仅有商品明细的订单数 | 1 |
| 仅有支付明细的订单数 | 775 |
| 多商品订单数 | 9,803 |
| 多支付订单数 | 2,961 |
| 同时多商品且多支付订单数 | 275 |
| 共同订单的明细行数 | 112,647 |
| 共同订单的支付行数 | 103,056 |
| 直接按 order_id Join 后行数 | 117,601 |
| 共同订单明细金额基线（price + freight） | 15,843,409.78 |
| 直接 Join 后明细金额 | 16,566,543.85 |
| 明细金额放大倍数 | 1.045643 |
| 共同订单支付金额基线 | 15,846,280.17 |
| 直接 Join 后支付金额 | 20,308,134.71 |
| 支付金额放大倍数 | 1.281571 |
| 全量商品明细金额基线 | 15,843,553.24 |
| 全量支付金额基线 | 16,008,872.12 |
| outer 订单集合预聚合后全量金额守恒 | 通过 |

### 结论与使用规则

- `order_items` 与 `order_payments` 都是 `order_id` 粒度的一对多表。
- 禁止直接同时连接两张明细表后汇总金额，否则商品金额会按支付行数重复，支付金额会按商品行数重复。
- 正确做法是分别按 `order_id` 聚合，再与 `orders` 或彼此连接。
- outer 订单集合保留单侧订单；预聚合后的两侧金额与各自原表全量基线精确一致。

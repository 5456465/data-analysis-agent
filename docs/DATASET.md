# Dataset Information

## Dataset

Brazilian E-Commerce Public Dataset by Olist

## Source

[Brazilian E-Commerce Public Dataset by Olist](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce/data)

## Description

An anonymized real-world e-commerce dataset containing approximately
100,000 orders placed between 2016 and 2018.

The dataset covers customers, orders, products, sellers, payments,
delivery information, and customer reviews.

## License

CC BY-NC-SA 4.0

## Usage

This dataset is used only for non-commercial learning, research,
and portfolio demonstration.

The original and processed data files are not redistributed in this repository.

## Limitations

- The data represents a historical Brazilian e-commerce scenario.
- It does not contain product cost or gross profit.
- It does not contain complete refund records.
- Order cancellation cannot be treated as equivalent to a refund.
- Analysis results do not represent the current Brazilian market.

## Download Date

2026-08-07

## Local File Layout

Place the nine source CSV files in `data/raw/`. The directory is intentionally
ignored by Git; the dataset is not distributed under the source-code license.

The audit and the next DuckDB stage use all nine Olist tables:

- customers
- geolocation
- order items
- order payments
- order reviews
- orders
- products
- sellers
- product category translation

## Version and Integrity

`docs/olist_raw.sha256` records the SHA-256 digest of every audited raw file.
The manifest was established on 2026-08-07 after the migration check.

Verify a local copy from the project root:

```bash
shasum -a 256 -c docs/olist_raw.sha256
```

If any file is missing or its digest changes, treat it as a new data version
and rerun the full data audit before rebuilding DuckDB. Moving the project
directory alone does not invalidate the audit.

## License Separation

Project source code is licensed under the repository's MIT `LICENSE` file.
That license does not apply to Olist data. Dataset users must separately
comply with CC BY-NC-SA 4.0 and the source platform's terms.

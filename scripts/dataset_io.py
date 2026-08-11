"""Shared, read-only CSV helpers for dataset audit scripts."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def read_csv_file(path: Path) -> pd.DataFrame:
    """Read a CSV as nullable strings, preserving identifier leading zeros."""

    try:
        return pd.read_csv(
            path,
            encoding="utf-8-sig",
            dtype="string",
            low_memory=False,
        )
    except UnicodeDecodeError as exc:
        raise ValueError(f"CSV 不是可读取的 UTF-8 文件: {path}") from exc
    except pd.errors.ParserError as exc:
        raise ValueError(f"CSV 结构无法解析: {path}") from exc


def normalize_keys(series: pd.Series) -> pd.Series:
    """Trim key strings and represent empty keys as missing values."""

    normalized = series.astype("string").str.strip()
    return normalized.mask(normalized.eq(""), pd.NA)

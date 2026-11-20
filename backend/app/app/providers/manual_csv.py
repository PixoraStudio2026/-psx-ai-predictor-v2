"""Validated manual-import provider; timestamps are normalised to Asia/Karachi local time.

Naive timestamps are interpreted as PSX local time. Explicitly zoned timestamps are
converted to Asia/Karachi. The database stores timezone-naive local timestamps for
compatibility with the existing SQLite schema.
"""
from pathlib import Path
import re
import pandas as pd
import numpy as np

REQUIRED = ["symbol", "timestamp", "open", "high", "low", "close", "volume"]
SYMBOL_RE = re.compile(r"^[A-Z0-9&._-]{2,24}$")


def _psx_local_timestamp(value):
    try:
        stamp = pd.Timestamp(value)
        if pd.isna(stamp):
            return pd.NaT
        if stamp.tzinfo is not None:
            stamp = stamp.tz_convert("Asia/Karachi").tz_localize(None)
        return stamp
    except (TypeError, ValueError, OverflowError):
        return pd.NaT


def read_csv(path: str | Path, max_rows: int = 500_000) -> pd.DataFrame:
    if max_rows < 1:
        raise ValueError("max_rows must be positive")
    frame = pd.read_csv(path, nrows=max_rows + 1)
    if len(frame) > max_rows:
        raise ValueError("CSV exceeds maximum row count")
    missing = set(REQUIRED) - set(frame.columns)
    if missing:
        raise ValueError(f"Missing columns: {sorted(missing)}")
    frame = frame[REQUIRED].copy()
    frame["symbol"] = frame.symbol.astype(str).str.strip().str.upper()
    frame["timestamp"] = pd.to_datetime(frame.timestamp.map(_psx_local_timestamp), errors="coerce")
    for col in REQUIRED[2:]:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    if frame.isna().any().any():
        raise ValueError("CSV contains missing or invalid rows")
    numeric = frame[["open", "high", "low", "close", "volume"]].to_numpy(dtype=float)
    if not np.isfinite(numeric).all():
        raise ValueError("CSV contains infinite or non-finite numeric values")
    if not frame.symbol.map(lambda value: bool(SYMBOL_RE.fullmatch(value))).all():
        raise ValueError("CSV contains an invalid PSX symbol")
    if frame.duplicated(["symbol", "timestamp"]).any():
        raise ValueError("CSV contains duplicate symbol/timestamp rows")
    if (frame[["open", "high", "low", "close"]] <= 0).any().any() or (frame.volume < 0).any():
        raise ValueError("Invalid price or volume values")
    if (frame.high < frame[["open", "close", "low"]].max(axis=1)).any() or (frame.low > frame[["open", "close", "high"]].min(axis=1)).any():
        raise ValueError("OHLC consistency check failed")
    return frame.sort_values(["symbol", "timestamp"]).reset_index(drop=True)

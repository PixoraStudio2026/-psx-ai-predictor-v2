from sqlalchemy import select, desc
from .models import MarketBar, ModelRun
import pandas as pd

def bars_frame(db, symbol, interval=None):
    q = select(MarketBar).where(MarketBar.symbol == symbol.upper()).order_by(MarketBar.timestamp)
    if interval:
        q = q.where(MarketBar.interval == interval)
    rows = db.scalars(q).all()
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame([{"timestamp": r.timestamp, "open": r.open, "high": r.high,
        "low": r.low, "close": r.close, "volume": r.volume, "source": r.source,
        "simulated": r.simulated, "training_eligible": r.training_eligible, "interval": r.interval} for r in rows])

def latest_model(db, symbol, horizon):
    return db.scalar(select(ModelRun).where(ModelRun.symbol == symbol.upper(),
        ModelRun.horizon == horizon, ModelRun.promoted.is_(True))
        .order_by(desc(ModelRun.trained_at)))


def passes_liquidity_and_quality(frame, min_avg_traded_value=1_000_000,
                                 max_zero_volume_ratio=0.25):
    if frame.empty or len(frame) < 40:
        return False, "Insufficient history"
    recent = frame.tail(20)
    if recent[["open","high","low","close","volume"]].isna().any().any():
        return False, "Missing OHLCV values"
    if (recent[["open","high","low","close"]] <= 0).any().any() or (recent["volume"] < 0).any():
        return False, "Invalid OHLCV values"
    if (recent["volume"] == 0).mean() > max_zero_volume_ratio:
        return False, "Too many zero-volume bars"
    max_single_bar_move = 0.50 if str(recent.iloc[-1].get("interval", "1d")) == "1d" else 0.25
    largest_move = recent["close"].pct_change().abs().max()
    if pd.notna(largest_move) and float(largest_move) > max_single_bar_move:
        return False, "Extreme single-bar return; verify source data and corporate-action adjustments"
    traded_value = recent["close"] * recent["volume"]
    if float(traded_value.median()) < min_avg_traded_value:
        return False, "Insufficient median traded value"
    if (recent["high"] < recent[["open","close","low"]].max(axis=1)).any():
        return False, "Inconsistent high prices"
    if (recent["low"] > recent[["open","close","high"]].min(axis=1)).any():
        return False, "Inconsistent low prices"
    return True, "Passed basic liquidity and data-quality checks"

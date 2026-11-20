from sqlalchemy import String, Integer, Float, DateTime, Boolean, Text, func, UniqueConstraint, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base

class MarketBar(Base):
    __tablename__ = "market_bars"
    __table_args__ = (UniqueConstraint("symbol","timestamp","interval",name="uq_bar"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(24), index=True)
    timestamp: Mapped[object] = mapped_column(DateTime, index=True)
    interval: Mapped[str] = mapped_column(String(12), default="1d")
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(120), default="UNKNOWN")
    simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    training_eligible: Mapped[bool] = mapped_column(Boolean, default=False)

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[object] = mapped_column(DateTime, server_default=func.now())
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    virtual_cash_start: Mapped[float] = mapped_column(Float, default=1_000_000.0)

class WatchlistItem(Base):
    __tablename__ = "watchlist"
    __table_args__ = (UniqueConstraint("owner_id", "symbol", name="uq_watchlist_owner_symbol"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(24), index=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    created_at: Mapped[object] = mapped_column(DateTime, server_default=func.now())

class PaperTrade(Base):
    __tablename__ = "paper_trades"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(24), index=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    side: Mapped[str] = mapped_column(String(8))
    quantity: Mapped[float] = mapped_column(Float)
    price: Mapped[float] = mapped_column(Float)
    transaction_cost: Mapped[float] = mapped_column(Float, default=0.0)
    note: Mapped[str | None] = mapped_column(String(240), nullable=True)
    created_at: Mapped[object] = mapped_column(DateTime, server_default=func.now())

class PriceAlert(Base):
    __tablename__ = "price_alerts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(24), index=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    target_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    alert_type: Mapped[str] = mapped_column(String(12), default="price")
    target_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    reference_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    direction: Mapped[str] = mapped_column(String(8))
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class NewsArticle(Base):
    __tablename__ = "news_articles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str | None] = mapped_column(String(24), index=True, nullable=True)
    title: Mapped[str] = mapped_column(String(300))
    source: Mapped[str] = mapped_column(String(160))
    url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    published_at: Mapped[object] = mapped_column(DateTime, index=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

class ModelRun(Base):
    __tablename__ = "model_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(24), index=True)
    horizon: Mapped[int] = mapped_column(Integer)
    model_path: Mapped[str] = mapped_column(String(300))
    model_version: Mapped[str] = mapped_column(String(80))
    brier_score: Mapped[float] = mapped_column(Float)
    accuracy: Mapped[float] = mapped_column(Float)
    test_samples: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(120))
    trained_at: Mapped[object] = mapped_column(DateTime, server_default=func.now())
    trained_through: Mapped[object | None] = mapped_column(DateTime, nullable=True, index=True)
    metrics_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    promoted: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

class Prediction(Base):
    __tablename__ = "predictions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(24), index=True)
    horizon: Mapped[int] = mapped_column(Integer)
    probability_positive: Mapped[float] = mapped_column(Float)
    reference_close: Mapped[float] = mapped_column(Float)
    data_as_of: Mapped[object] = mapped_column(DateTime)
    model_version: Mapped[str] = mapped_column(String(80))
    source: Mapped[str] = mapped_column(String(120))
    simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    actual_positive: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    realized_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    evaluated_at: Mapped[object | None] = mapped_column(DateTime, nullable=True)
    expected_gross_return_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_net_return_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    potential_upside_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    potential_downside_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_level: Mapped[str | None] = mapped_column(String(16), nullable=True)
    market_regime: Mapped[str | None] = mapped_column(String(24), nullable=True)
    news_sentiment: Mapped[str | None] = mapped_column(String(16), nullable=True)


class FundamentalSnapshot(Base):
    __tablename__ = "fundamental_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(24), index=True)
    as_of: Mapped[object] = mapped_column(DateTime, index=True)
    source: Mapped[str] = mapped_column(String(160))
    currency: Mapped[str] = mapped_column(String(8), default="PKR")
    eps: Mapped[float | None] = mapped_column(Float, nullable=True)
    pe_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    book_value_per_share: Mapped[float | None] = mapped_column(Float, nullable=True)
    dividend_yield: Mapped[float | None] = mapped_column(Float, nullable=True)
    debt_to_equity: Mapped[float | None] = mapped_column(Float, nullable=True)
    revenue_growth: Mapped[float | None] = mapped_column(Float, nullable=True)
    earnings_growth: Mapped[float | None] = mapped_column(Float, nullable=True)


class StockProfile(Base):
    __tablename__ = "stock_profiles"
    symbol: Mapped[str] = mapped_column(String(24), primary_key=True)
    company_name: Mapped[str] = mapped_column(String(200))
    sector: Mapped[str | None] = mapped_column(String(120), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source: Mapped[str] = mapped_column(String(160))
    updated_at: Mapped[object] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

class TrainingAttempt(Base):
    __tablename__ = "training_attempts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(24), index=True)
    horizon: Mapped[int] = mapped_column(Integer)
    model_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    reason: Mapped[str] = mapped_column(String(500))
    metrics_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(120))
    trained_through: Mapped[object | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[object] = mapped_column(DateTime, server_default=func.now())

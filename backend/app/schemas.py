from pydantic import BaseModel, Field, field_validator, ConfigDict
import re

SYMBOL_PATTERN = re.compile(r"^[A-Z0-9&._-]{2,24}$")
class SymbolIn(BaseModel):
    symbol: str = Field(min_length=2,max_length=24)
    @field_validator("symbol")
    @classmethod
    def clean(cls,v):
        v=v.strip().upper()
        if not SYMBOL_PATTERN.fullmatch(v): raise ValueError("Invalid PSX symbol")
        return v
class TradeIn(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    symbol: str = Field(min_length=2,max_length=24)
    side: str
    quantity: float = Field(gt=0, le=1e12)
    price: float = Field(gt=0, le=1e12)
    note: str | None = Field(default=None,max_length=240)
    @field_validator("symbol")
    @classmethod
    def clean(cls,v):
        v=v.strip().upper()
        if not SYMBOL_PATTERN.fullmatch(v): raise ValueError("Invalid PSX symbol")
        return v
    @field_validator("side")
    @classmethod
    def side_ok(cls,v):
        v=v.lower()
        if v not in {"buy","sell"}: raise ValueError("side must be buy or sell")
        return v
class AlertIn(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    symbol: str = Field(min_length=2,max_length=24)
    alert_type: str = "price"
    target_price: float | None = Field(default=None,gt=0,le=1e12)
    target_pct: float | None = Field(default=None,gt=0,le=500)
    direction: str
    @field_validator("symbol")
    @classmethod
    def clean(cls,v):
        v=v.strip().upper()
        if not SYMBOL_PATTERN.fullmatch(v): raise ValueError("Invalid PSX symbol")
        return v
    @field_validator("direction")
    @classmethod
    def direction_ok(cls,v):
        v=v.lower()
        if v not in {"above","below"}: raise ValueError("direction must be above or below")
        return v
    @field_validator("alert_type")
    @classmethod
    def type_ok(cls,v):
        v=v.lower()
        if v not in {"price","percent"}: raise ValueError("alert_type must be price or percent")
        return v
    @field_validator("target_price")
    @classmethod
    def price_required_for_price_alert(cls,v,info):
        if info.data.get("alert_type","price")=="price" and v is None: raise ValueError("target_price is required for price alerts")
        return v
    @field_validator("target_pct")
    @classmethod
    def pct_required_for_percent_alert(cls,v,info):
        if info.data.get("alert_type")=="percent" and v is None: raise ValueError("target_pct is required for percentage alerts")
        return v
class NewsIn(BaseModel):
    symbol: str | None = Field(default=None, max_length=24)
    title: str = Field(min_length=4,max_length=300)
    source: str = Field(min_length=2,max_length=160)
    url: str | None = Field(default=None, max_length=1000)
    published_at: str
    summary: str | None = Field(default=None, max_length=5000)
    @field_validator("symbol")
    @classmethod
    def valid_symbol(cls,v):
        if v is None: return v
        v=v.strip().upper()
        import re
        if not re.fullmatch(r"[A-Z0-9&._-]{2,24}",v): raise ValueError("Invalid symbol")
        return v
    @field_validator("url")
    @classmethod
    def safe_url(cls,v):
        if v is None or not v.strip(): return None
        from urllib.parse import urlparse
        parsed=urlparse(v.strip())
        if parsed.scheme not in {"http","https"} or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("URL must be a valid http(s) URL without embedded credentials")
        return v.strip()



class FundamentalIn(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    symbol: str = Field(min_length=2, max_length=24)
    as_of: str
    source: str = Field(min_length=2, max_length=160)
    currency: str = Field(default="PKR", min_length=3, max_length=8)
    eps: float | None = None
    pe_ratio: float | None = None
    book_value_per_share: float | None = None
    dividend_yield: float | None = None
    debt_to_equity: float | None = None
    revenue_growth: float | None = None
    earnings_growth: float | None = None
    @field_validator("symbol")
    @classmethod
    def clean_symbol(cls, v):
        v=v.strip().upper()
        if not SYMBOL_PATTERN.fullmatch(v): raise ValueError("Invalid PSX symbol")
        return v
    @field_validator("source")
    @classmethod
    def clean_source(cls, v): return v.strip()


class StockProfileIn(BaseModel):
    symbol: str = Field(min_length=2, max_length=24)
    company_name: str = Field(min_length=2, max_length=200)
    sector: str | None = Field(default=None, max_length=120)
    industry: str | None = Field(default=None, max_length=120)
    source: str = Field(min_length=2, max_length=160)
    @field_validator("symbol")
    @classmethod
    def clean_symbol(cls,v):
        v=v.strip().upper()
        if not SYMBOL_PATTERN.fullmatch(v): raise ValueError("Invalid PSX symbol")
        return v
    @field_validator("company_name", "source")
    @classmethod
    def clean_text(cls,v): return v.strip()

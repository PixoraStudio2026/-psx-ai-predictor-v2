from datetime import datetime, timezone
import hmac, time, re, json
from collections import OrderedDict, deque
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Header, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from io import BytesIO
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import select, desc, func, text
from .config import settings
from .database import Base, engine, get_db
from .models import MarketBar, WatchlistItem, PaperTrade, PriceAlert, NewsArticle, ModelRun, Prediction, FundamentalSnapshot, User, StockProfile, TrainingAttempt
from .auth import hash_password, verify_password, create_access_token, read_access_token
from .schemas import SymbolIn, TradeIn, AlertIn, NewsIn, FundamentalIn, StockProfileIn
from pydantic import BaseModel, Field
from .market import bars_frame, latest_model, passes_liquidity_and_quality
from .ml import load_model, predict_latest
from .reports import build_daily_pdf
from .config import settings

Base.metadata.create_all(bind=engine)
_scheduler = None

@asynccontextmanager
async def lifespan(application):
    global _scheduler
    if settings.enable_scheduler:
        from apscheduler.schedulers.background import BackgroundScheduler
        from zoneinfo import ZoneInfo
        from scripts.retrain_all import run as run_retraining
        _scheduler = BackgroundScheduler(timezone=ZoneInfo("Asia/Karachi"))
        _scheduler.add_job(run_retraining, "cron", hour=settings.retrain_hour,
                           minute=settings.retrain_minute, id="controlled_retraining",
                           replace_existing=True, max_instances=1, coalesce=True)
        _scheduler.start()
    try:
        yield
    finally:
        if _scheduler:
            _scheduler.shutdown(wait=False)
            _scheduler = None

app=FastAPI(title="PSX AI Predictor",version="1.0.0",description="Educational market research and paper-trading simulator. No broker execution.", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list,
    allow_credentials=False, allow_methods=["GET","POST","DELETE"], allow_headers=["Authorization","Content-Type"])

def require_admin(authorization: str | None = Header(default=None)):
    configured = settings.admin_api_token
    if len(configured) < 32:
        raise HTTPException(503, "Administrative operations are disabled: configure ADMIN_API_TOKEN with at least 32 characters.")
    supplied = authorization.removeprefix("Bearer ").strip() if authorization else ""
    if not hmac.compare_digest(supplied, configured):
        raise HTTPException(401, "Valid administrator bearer token required.")
    return True

_request_times = OrderedDict()
@app.middleware("http")
async def security_middleware(request: Request, call_next):
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > settings.max_request_bytes:
        return JSONResponse({"detail":"Request body too large."}, status_code=413)
    # In the bundled deployment, the API is internal-only behind Nginx, which overwrites X-Real-IP.
    key = request.headers.get("x-real-ip") or (request.client.host if request.client else "unknown")
    now = time.monotonic()
    bucket = _request_times.setdefault(key, deque())
    _request_times.move_to_end(key)
    while len(_request_times) > 10000:
        _request_times.popitem(last=False)
    while bucket and now - bucket[0] > 60:
        bucket.popleft()
    if len(bucket) >= settings.rate_limit_per_minute:
        return JSONResponse({"detail":"Rate limit exceeded."}, status_code=429)
    bucket.append(now)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    response.headers["Cache-Control"] = "no-store"
    return response

# Lightweight SQLite upgrade for existing installations.
with engine.begin() as conn:
    if engine.dialect.name == "sqlite":
        cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(model_runs)").fetchall()]
        if cols and "promoted" not in cols:
            conn.exec_driver_sql("ALTER TABLE model_runs ADD COLUMN promoted BOOLEAN NOT NULL DEFAULT 1")
        bar_cols=[r[1] for r in conn.exec_driver_sql("PRAGMA table_info(market_bars)").fetchall()]
        if bar_cols and "training_eligible" not in bar_cols:
            conn.exec_driver_sql("ALTER TABLE market_bars ADD COLUMN training_eligible BOOLEAN NOT NULL DEFAULT 0")
        if cols and "trained_through" not in cols:
            conn.exec_driver_sql("ALTER TABLE model_runs ADD COLUMN trained_through DATETIME")
        if cols and "metrics_json" not in cols:
            conn.exec_driver_sql("ALTER TABLE model_runs ADD COLUMN metrics_json TEXT")
        user_cols=[r[1] for r in conn.exec_driver_sql("PRAGMA table_info(users)").fetchall()]
        if user_cols and "virtual_cash_start" not in user_cols:
            conn.exec_driver_sql("ALTER TABLE users ADD COLUMN virtual_cash_start FLOAT NOT NULL DEFAULT 1000000.0")
        for table in ["watchlist", "paper_trades", "price_alerts"]:
            tcols=[r[1] for r in conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()]
            if tcols and "owner_id" not in tcols:
                conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN owner_id INTEGER REFERENCES users(id)")
            if table == "paper_trades" and tcols and "transaction_cost" not in tcols:
                conn.exec_driver_sql("ALTER TABLE paper_trades ADD COLUMN transaction_cost FLOAT NOT NULL DEFAULT 0")
            if table == "price_alerts" and tcols:
                if "alert_type" not in tcols: conn.exec_driver_sql("ALTER TABLE price_alerts ADD COLUMN alert_type VARCHAR(12) NOT NULL DEFAULT 'price'")
                if "target_pct" not in tcols: conn.exec_driver_sql("ALTER TABLE price_alerts ADD COLUMN target_pct FLOAT")
                if "reference_price" not in tcols: conn.exec_driver_sql("ALTER TABLE price_alerts ADD COLUMN reference_price FLOAT")
        pcols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(predictions)").fetchall()]
        if pcols:
            if "actual_positive" not in pcols:
                conn.exec_driver_sql("ALTER TABLE predictions ADD COLUMN actual_positive BOOLEAN")
            if "realized_return" not in pcols:
                conn.exec_driver_sql("ALTER TABLE predictions ADD COLUMN realized_return FLOAT")
            if "evaluated_at" not in pcols:
                conn.exec_driver_sql("ALTER TABLE predictions ADD COLUMN evaluated_at DATETIME")
            for name, sqltype in [("expected_gross_return_pct","FLOAT"),("estimated_net_return_pct","FLOAT"),("potential_upside_pct","FLOAT"),("potential_downside_pct","FLOAT"),("risk_level","VARCHAR(16)"),("market_regime","VARCHAR(24)"),("news_sentiment","VARCHAR(16)")]:
                if name not in pcols: conn.exec_driver_sql(f"ALTER TABLE predictions ADD COLUMN {name} {sqltype}")


class RegisterIn(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=10, max_length=256)

class LoginIn(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=1, max_length=256)

class ResearchQuestion(BaseModel):
    question: str = Field(min_length=3, max_length=1200)

class UserContext:
    def __init__(self, user: User | None): self.user = user

def optional_user(authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    if not authorization or not authorization.startswith("Bearer "): return UserContext(None)
    token=authorization[7:].strip()
    if settings.admin_api_token and hmac.compare_digest(token, settings.admin_api_token): return UserContext(None)
    uid=read_access_token(token)
    if uid is None: return UserContext(None)
    user=db.get(User,uid)
    return UserContext(user if user and user.is_active else None)

def require_user(context: UserContext = Depends(optional_user)):
    if not context.user: raise HTTPException(401,"Sign in to access your private workspace.")
    return context.user

@app.post("/api/auth/register")
def register(payload: RegisterIn, db: Session = Depends(get_db)):
    email=payload.email.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+",email): raise HTTPException(400,"Enter a valid email address.")
    if len(settings.auth_secret) < 32: raise HTTPException(503,"Account registration is disabled until AUTH_SECRET is configured with at least 32 characters.")
    if db.scalar(select(User.id).where(User.email==email)): raise HTTPException(409,"An account with this email already exists.")
    try: encoded=hash_password(payload.password)
    except ValueError as exc: raise HTTPException(400,str(exc))
    user=User(email=email,password_hash=encoded); db.add(user); db.commit(); db.refresh(user)
    try: token=create_access_token(user.id)
    except RuntimeError as exc: raise HTTPException(503,str(exc))
    return {"access_token":token,"token_type":"bearer","expires_in_minutes":settings.auth_token_minutes,"user":{"id":user.id,"email":user.email}}

@app.post("/api/auth/login")
def login(payload: LoginIn, db: Session = Depends(get_db)):
    user=db.scalar(select(User).where(User.email==payload.email.strip().lower()))
    if not user or not user.is_active or not verify_password(payload.password,user.password_hash): raise HTTPException(401,"Invalid email or password.")
    try: token=create_access_token(user.id)
    except RuntimeError as exc: raise HTTPException(503,str(exc))
    return {"access_token":token,"token_type":"bearer","expires_in_minutes":settings.auth_token_minutes,"user":{"id":user.id,"email":user.email}}

@app.get("/api/auth/me")
def whoami(user: User = Depends(require_user)):
    return {"id":user.id,"email":user.email}

@app.get("/")
def root(): return {"app":"PSX AI Predictor","status":"running","mode":"educational_paper_simulation"}
@app.get("/api/health")
def health():
    try:
        with engine.connect() as connection: connection.execute(text("SELECT 1"))
        return {"ok":True,"environment":settings.app_env,"database":"connected"}
    except Exception:
        raise HTTPException(503,"Database health check failed.")
@app.get("/api/market/overview")
def overview(db:Session=Depends(get_db)):
    symbols=db.query(MarketBar.symbol).distinct().all()
    latest=db.query(MarketBar).order_by(desc(MarketBar.timestamp)).first()
    interval_latest={}
    for interval in ["1d", "15m", "1h", "5m"]:
        item=db.scalars(select(MarketBar).where(MarketBar.interval==interval).order_by(desc(MarketBar.timestamp)).limit(1)).first()
        if item:
            interval_latest[interval]={"as_of":item.timestamp.isoformat(),"source":item.source,"simulated":bool(item.simulated),"training_eligible":bool(item.training_eligible)}
    return {"available":bool(latest),"symbols_loaded":len(symbols),"as_of":latest.timestamp.isoformat() if latest else None,
            "source":latest.source if latest else None,"simulated":latest.simulated if latest else None,
            "timezone":"Asia/Karachi (PSX local time)","intervals":interval_latest,
            "data_status":"simulated" if latest and latest.simulated else ("imported" if latest else "unavailable"),"training_eligible":bool(latest.training_eligible) if latest else False,"message":"Data is simulated; do not interpret as PSX market information." if latest and latest.simulated else ("Imported data; live/delayed status is not verified." if latest else "No market dataset imported.")}

@app.get("/api/stocks")
def stocks(q:str="",db:Session=Depends(get_db)):
    syms=[x[0] for x in db.query(MarketBar.symbol).distinct().all()]
    profiles={r.symbol:r.company_name for r in db.scalars(select(StockProfile)).all()}
    return {"items":[{"symbol":s,"company_name":profiles.get(s)} for s in sorted(syms) if q.upper() in s.upper() or q.upper() in profiles.get(s,"").upper()]}
@app.get("/api/stocks/{symbol}")
def stock_detail(symbol:str, interval:str="1d", db:Session=Depends(get_db)):
    if interval not in {"1d", "15m", "5m", "1h"}: raise HTTPException(400,"Unsupported interval.")
    d=bars_frame(db,symbol,interval=interval)
    if d.empty: raise HTTPException(404,"No imported data for this symbol.")
    from .features import make_features
    last=d.iloc[-1]; f=make_features(d).iloc[-1]; recent=d.tail(20)
    sma_spread=float(f.get("sma_ratio",0) or 0)
    regime="uptrend" if sma_spread>0.01 else ("downtrend" if sma_spread< -0.01 else "sideways")
    fundamental=db.scalars(select(FundamentalSnapshot).where(FundamentalSnapshot.symbol==symbol.upper()).order_by(desc(FundamentalSnapshot.as_of)).limit(1)).first()
    profile=db.get(StockProfile,symbol.upper())
    tech={k:(None if pd.isna(f.get(k)) else float(f.get(k))) for k in ["rsi_14","macd","sma_10","sma_30","volatility_10"]}
    tech.update({"regime_proxy":regime,"support_20":float(recent.low.min()),"resistance_20":float(recent.high.max())})
    fund=({k:(getattr(fundamental,k).isoformat() if k=="as_of" else getattr(fundamental,k)) for k in ["as_of","source","currency","eps","pe_ratio","book_value_per_share","dividend_yield","debt_to_equity","revenue_growth","earnings_growth"]} if fundamental else None)
    return {"symbol":symbol.upper(),"company_name":profile.company_name if profile else None,"sector":profile.sector if profile else None,"close":float(last.close),"timestamp":last.timestamp.isoformat(),"source":last.source,"simulated":bool(last.simulated),"technical":tech,"fundamentals":fund,"history":d.tail(120)[["timestamp","close","volume"]].to_dict("records"),"limitations":"Fundamentals appear only when imported from a verified source. Regime proxy is stock-specific, not a PSX-wide market regime."}

@app.get("/api/stocks/{symbol}/compare")
def compare(symbol:str,with_symbol:str,interval:str="1d",db:Session=Depends(get_db)):
    if interval not in {"1d", "15m", "5m", "1h"}: raise HTTPException(400,"Unsupported interval.")
    out=[]
    for s in [symbol,with_symbol]:
        d=bars_frame(db,s,interval=interval)
        if d.empty: raise HTTPException(404,f"No imported data for {s}")
        start=float(d.iloc[0].close); end=float(d.iloc[-1].close)
        out.append({"symbol":s.upper(),"first_close":start,"last_close":end,"period_return_pct":(end/start-1)*100,"bars":len(d)})
    return {"comparison":out,"note":"Historical comparison is descriptive, not a forecast."}

@app.get("/api/predictions")
def predictions(horizon: str = "both", db: Session = Depends(get_db)):
    if horizon not in {"both", "intraday", "next_day"}:
        raise HTTPException(400, "horizon must be both, intraday, or next_day")
    horizons = [1] if horizon == "next_day" else ([0] if horizon == "intraday" else [1, 0])
    result = []
    from .features import make_features
    symbols = [x[0] for x in db.query(MarketBar.symbol).distinct().all()]
    for symbol in symbols:
        for h in horizons:
            model_run = latest_model(db, symbol, h)
            if not model_run:
                continue
            interval = "15m" if h == 0 else "1d"
            frame = bars_frame(db, symbol, interval=interval)
            if frame.empty or bool(frame.iloc[-1].simulated) or not frame.training_eligible.all():
                continue
            quality_ok, quality_reason = passes_liquidity_and_quality(
                frame, settings.min_avg_traded_value, settings.max_zero_volume_ratio)
            if not quality_ok:
                continue
            try:
                bundle = load_model(model_run.model_path)
                probability, row = predict_latest(frame, bundle)
                if model_run.test_samples < settings.model_min_test_samples or model_run.brier_score > settings.model_max_brier:
                    continue
                empirical = (frame.close.shift(-1) / frame.close - 1).dropna().tail(250)
                pos, neg = empirical[empirical > 0], empirical[empirical < 0]
                up_mean = float(pos.mean()) if len(pos) else 0.0
                down_mean = float(neg.mean()) if len(neg) else 0.0
                gross = probability * up_mean + (1-probability) * down_mean
                volatility = float(empirical.std()) if len(empirical)>2 else 0.0
                high_cut, moderate_cut = ((.01,.005) if h==0 else (.04,.02))
                risk = "high" if volatility >= high_cut else ("moderate" if volatility >= moderate_cut else "lower")
                fr = make_features(frame).iloc[-1]
                profile=db.get(StockProfile,symbol)
                latest_fundamental=db.scalars(select(FundamentalSnapshot).where(FundamentalSnapshot.symbol==symbol, FundamentalSnapshot.as_of<=row.timestamp).order_by(desc(FundamentalSnapshot.as_of)).limit(1)).first()
                latest_news=db.scalars(select(NewsArticle).where(NewsArticle.symbol==symbol, NewsArticle.published_at<=row.timestamp).order_by(desc(NewsArticle.published_at)).limit(5)).all()
                fundamental_summary=({"as_of":latest_fundamental.as_of.isoformat(),"source":latest_fundamental.source,"eps":latest_fundamental.eps,"pe_ratio":latest_fundamental.pe_ratio,"dividend_yield":latest_fundamental.dividend_yield,"debt_to_equity":latest_fundamental.debt_to_equity} if latest_fundamental else None)
                pos_words={"growth","profit","surge","record","upgrade","approval","dividend","expansion","strong","improve"}
                neg_words={"loss","decline","drop","fraud","default","downgrade","penalty","weak","warning","debt"}
                news_score=0
                for article in latest_news:
                    words=set(re.findall(r"[a-z]+",(article.title+" "+(article.summary or "")).lower()))
                    news_score += len(words & pos_words)-len(words & neg_words)
                news_label=("positive" if news_score>0 else ("negative" if news_score<0 else "neutral")) if latest_news else None
                factors=[]
                for key in ["rsi_14","macd","sma_ratio","volume_ratio"]:
                    if pd.notna(fr.get(key)): factors.append(f"{key}={float(fr[key]):.4f}")
                metrics = json.loads(model_run.metrics_json) if model_run.metrics_json else {}
                validation = metrics.get("external_candidate", metrics)
                validation_samples = int(validation.get("test_samples", model_run.test_samples))
                validation_brier = float(validation.get("brier_score", model_run.brier_score))
                calibration_error = validation.get("calibration_error_10_bins")
                if validation_samples >= 250 and validation_brier <= 0.16 and calibration_error is not None and calibration_error <= 0.05:
                    model_confidence, confidence_reason = "higher", "Large recent validation sample with comparatively low Brier score and calibration error; still uncertain."
                elif validation_samples >= 100 and validation_brier <= 0.20 and calibration_error is not None and calibration_error <= 0.08:
                    model_confidence, confidence_reason = "moderate", "Moderate validation evidence; confidence describes evidence quality, not the chance of a positive return."
                else:
                    model_confidence, confidence_reason = "low", "Validation sample or calibration evidence is limited; treat the probability cautiously."
                result.append({
                    "symbol": symbol, "company_name": profile.company_name if profile else None, "horizon": h,
                    "horizon_label": "Intraday (next 15-minute bar)" if h == 0 else "Next trading day",
                    "probability_positive": round(probability, 4),
                    "probability_negative": round(1-probability, 4),
                    "model_confidence": model_confidence, "confidence_reason": confidence_reason,
                    "validation_samples": validation_samples, "validation_brier_score": validation_brier,
                    "calibration_error": calibration_error,
                    "data_source": str(row.source), "data_timestamp": row.timestamp.isoformat(),
                    "expected_gross_return_pct": round(gross*100,3),
                    "estimated_net_return_pct": round((gross-2*settings.transaction_cost_rate)*100,3),
                    "simulated_round_trip_cost_pct": round(2*settings.transaction_cost_rate*100,3),
                    "return_estimate_method": "Probability-weighted empirical next-bar return distribution; not a trained return-regression model.",
                    "risk_method": "Heuristic based on recent return volatility thresholds; not a validated risk model.",
                    "potential_upside_pct": round(float(pos.quantile(.90))*100,3) if len(pos) else None,
                    "potential_downside_pct": round(float(neg.quantile(.10))*100,3) if len(neg) else None,
                    "risk_level": risk, "evidence_grade": "limited sample" if model_run.test_samples<60 else "minimum sample passed",
                    "technical_factors": factors, "fundamental_factors": fundamental_summary,
                    "news_sentiment": news_label, "news_items_considered": len(latest_news),
                    "market_regime": "stock-specific " + ("uptrend" if float(fr.get("sma_ratio",0) or 0)>.01 else ("downtrend" if float(fr.get("sma_ratio",0) or 0)<-.01 else "sideways")),
                    "supporting_reason": "Calibrated probability combined with recent empirical return distribution; imported fundamentals/news are included only when available.",
                    "opposing_reason": "Historical return distributions and volatility may change; uncertainty remains.",
                    "reference_close": float(row.close),
                    "as_of": row.timestamp.isoformat(), "model_version": model_run.model_version,
                    "source": str(row.source), "data_source": str(row.source),
                    "model_training_source": model_run.source, "data_status": "imported",
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                })
                exists = db.scalar(select(Prediction.id).where(
                    Prediction.symbol == symbol, Prediction.horizon == h,
                    Prediction.data_as_of == row.timestamp,
                    Prediction.model_version == model_run.model_version))
                if not exists:
                    db.add(Prediction(symbol=symbol, horizon=h,
                        probability_positive=probability, reference_close=float(row.close),
                        data_as_of=row.timestamp, model_version=model_run.model_version,
                        source=str(row.source), simulated=False, expected_gross_return_pct=gross*100,
                        estimated_net_return_pct=(gross-2*settings.transaction_cost_rate)*100,
                        potential_upside_pct=float(pos.quantile(.90))*100 if len(pos) else None,
                        potential_downside_pct=float(neg.quantile(.10))*100 if len(neg) else None, risk_level=risk,
                        market_regime=("uptrend" if float(fr.get("sma_ratio",0) or 0)>.01 else ("downtrend" if float(fr.get("sma_ratio",0) or 0)<-.01 else "sideways")),news_sentiment=news_label))
                    db.commit()
            except Exception:
                continue
    result.sort(key=lambda x: x["probability_positive"], reverse=True)
    return {"items": result[:10], "status": "available" if result else "no_qualified_candidates",
            "message": "Statistical educational estimates only. Results are withheld when data or model gates fail."}

@app.get("/api/models/training-history")
def training_history(db: Session = Depends(get_db)):
    rows=db.scalars(select(TrainingAttempt).order_by(desc(TrainingAttempt.created_at)).limit(200)).all()
    return {"items":[{"symbol":r.symbol,"horizon":r.horizon,"model_version":r.model_version,"status":r.status,"reason":r.reason,"metrics":json.loads(r.metrics_json) if r.metrics_json else {},"source":r.source,"trained_through":r.trained_through.isoformat() if r.trained_through else None,"created_at":r.created_at.isoformat() if r.created_at else None} for r in rows]}

@app.get("/api/predictions/accuracy")
def accuracy(db:Session=Depends(get_db)):
    rows=db.scalars(select(ModelRun).order_by(desc(ModelRun.trained_at))).all()
    return {"items":[{"symbol":r.symbol,"horizon":r.horizon,"version":r.model_version,"accuracy":r.accuracy,"brier_score":r.brier_score,"test_samples":r.test_samples,"source":r.source,"trained_at":r.trained_at.isoformat(),"trained_through":r.trained_through.isoformat() if r.trained_through else None,"metrics":json.loads(r.metrics_json) if r.metrics_json else {}} for r in rows]}

@app.get("/api/predictions/realized-performance")
def realized_performance(db: Session = Depends(get_db)):
    rows = db.scalars(select(Prediction).where(Prediction.actual_positive.is_not(None))).all()
    if not rows:
        return {"evaluated_predictions": 0, "accuracy": None, "brier_score": None,
                "message": "No predictions have matured against subsequent imported market bars yet."}
    import numpy as np
    from sklearn.metrics import precision_score, recall_score, roc_auc_score
    from .ml import expected_calibration_error

    def metrics_for(items):
        actual = np.array([1 if r.actual_positive else 0 for r in items])
        probs = np.array([r.probability_positive for r in items])
        predicted = (probs >= .5).astype(int)
        result = {"samples": len(items), "accuracy": float(np.mean(predicted == actual)),
            "brier_score": float(np.mean((probs-actual)**2)),
            "precision": float(precision_score(actual,predicted,zero_division=0)),
            "recall": float(recall_score(actual,predicted,zero_division=0)),
            "calibration_error_10_bins": expected_calibration_error(actual,probs),
            "mean_realized_return": float(np.mean([x.realized_return for x in items]))}
        if len(np.unique(actual)) > 1: result["roc_auc"] = float(roc_auc_score(actual,probs))
        return result

    groups={}
    for r in rows:
        horizon_name = "intraday" if r.horizon == 0 else "next_day"
        for key in [f"{r.symbol}|{horizon_name}", f"horizon:{horizon_name}", f"regime:{r.market_regime or 'unknown'}"]:
            groups.setdefault(key,[]).append(r)
    return {"evaluated_predictions": len(rows), **metrics_for(rows),
            "breakdown":[{"group":key, **metrics_for(items)} for key,items in sorted(groups.items())],
            "message":"Measured from subsequent eligible imported bars; results are historical and may not generalise."}

@app.get("/api/predictions/history")
def prediction_history(db:Session=Depends(get_db)):
    rows=db.scalars(select(Prediction).order_by(desc(Prediction.data_as_of)).limit(200)).all()
    return {"items":[{"symbol":r.symbol,"horizon":r.horizon,"probability_positive":r.probability_positive,"reference_close":r.reference_close,"as_of":r.data_as_of.isoformat(),"version":r.model_version,"source":r.source,"simulated":r.simulated,"actual_positive":r.actual_positive,"realized_return":r.realized_return,"evaluated_at":r.evaluated_at.isoformat() if r.evaluated_at else None,"expected_gross_return_pct":r.expected_gross_return_pct,"estimated_net_return_pct":r.estimated_net_return_pct,"potential_upside_pct":r.potential_upside_pct,"potential_downside_pct":r.potential_downside_pct,"risk_level":r.risk_level,"market_regime":r.market_regime,"news_sentiment":r.news_sentiment} for r in rows]}

@app.get("/api/profiles/{symbol}")
def get_stock_profile(symbol: str, db: Session = Depends(get_db)):
    row=db.get(StockProfile,symbol.upper())
    if not row: raise HTTPException(404,"No company profile has been imported for this symbol.")
    return {"symbol":row.symbol,"company_name":row.company_name,"sector":row.sector,"industry":row.industry,"source":row.source,"updated_at":row.updated_at.isoformat() if row.updated_at else None}

@app.post("/api/admin/profiles", dependencies=[Depends(require_admin)])
def save_stock_profile(payload: StockProfileIn, db: Session = Depends(get_db)):
    row=db.get(StockProfile,payload.symbol)
    if row:
        for key,value in payload.model_dump().items(): setattr(row,key,value)
    else: row=StockProfile(**payload.model_dump()); db.add(row)
    db.commit(); return {"saved":True,"symbol":payload.symbol}

@app.get("/api/fundamentals/{symbol}")
def fundamentals(symbol: str, db: Session = Depends(get_db)):
    rows=db.scalars(select(FundamentalSnapshot).where(FundamentalSnapshot.symbol==symbol.upper()).order_by(desc(FundamentalSnapshot.as_of)).limit(20)).all()
    return {"items":[{"as_of":r.as_of.isoformat(),"source":r.source,"currency":r.currency,"eps":r.eps,"pe_ratio":r.pe_ratio,"book_value_per_share":r.book_value_per_share,"dividend_yield":r.dividend_yield,"debt_to_equity":r.debt_to_equity,"revenue_growth":r.revenue_growth,"earnings_growth":r.earnings_growth} for r in rows],"note":"Only source-attributed imported snapshots are returned; no figures are inferred."}

@app.post("/api/admin/fundamentals", dependencies=[Depends(require_admin)])
def add_fundamentals(payload: FundamentalIn, db: Session = Depends(get_db)):
    try: dt=datetime.fromisoformat(payload.as_of.replace("Z","+00:00")).replace(tzinfo=None)
    except ValueError: raise HTTPException(400,"as_of must be ISO-8601")
    values=payload.model_dump(exclude={"as_of"})
    for value in values.values():
        if isinstance(value,(int,float)) and value is not None and abs(value)>1e12: raise HTTPException(400,"Fundamental value outside accepted bounds")
    row=FundamentalSnapshot(as_of=dt,**values); db.add(row); db.commit(); db.refresh(row)
    return {"saved":True,"id":row.id,"symbol":row.symbol}

@app.get("/api/news")
def news(symbol:str|None=None,db:Session=Depends(get_db)):
    q=select(NewsArticle).order_by(desc(NewsArticle.published_at)).limit(100)
    if symbol: q=q.where(NewsArticle.symbol==symbol.upper())
    rows=db.scalars(q).all()
    positive={"growth","profit","surge","record","upgrade","approval","dividend","expansion","strong","improve"}
    negative={"loss","decline","drop","fraud","default","downgrade","penalty","weak","warning","debt"}
    items=[]
    for r in rows:
        words=set(re.findall(r"[a-z]+",(r.title+" "+(r.summary or "")).lower()))
        score=len(words & positive)-len(words & negative)
        items.append({"symbol":r.symbol,"title":r.title,"source":r.source,"url":r.url,"published_at":r.published_at.isoformat(),"summary":r.summary,"lexical_sentiment":"positive" if score>0 else ("negative" if score<0 else "neutral"),"sentiment_method":"keyword heuristic; not an NLP model"})
    return {"items":items,"note":"Manually imported news only. Sentiment is a simple keyword heuristic, not verified financial interpretation."}
@app.post("/api/news", dependencies=[Depends(require_admin)])
def add_news(payload:NewsIn,db:Session=Depends(get_db)):
    try: dt=datetime.fromisoformat(payload.published_at.replace("Z","+00:00")).replace(tzinfo=None)
    except ValueError: raise HTTPException(400,"published_at must be ISO-8601")
    row=NewsArticle(symbol=payload.symbol.upper() if payload.symbol else None,title=payload.title,source=payload.source,url=payload.url,published_at=dt,summary=payload.summary)
    db.add(row);db.commit();return {"saved":True,"id":row.id}

@app.get("/api/watchlist")
def watchlist(context: UserContext = Depends(optional_user), db:Session=Depends(get_db)):
    if not context.user: return {"items":[],"requires_account":True}
    rows=db.scalars(select(WatchlistItem).where(WatchlistItem.owner_id==context.user.id).order_by(WatchlistItem.symbol)).all()
    return {"items":[{"symbol":r.symbol} for r in rows]}
@app.post("/api/watchlist")
def add_watchlist(p:SymbolIn, owner:User=Depends(require_user), db:Session=Depends(get_db)):
    q=select(WatchlistItem).where(WatchlistItem.symbol==p.symbol, WatchlistItem.owner_id==owner.id)
    if db.scalar(q): return {"symbol":p.symbol,"created":False}
    db.add(WatchlistItem(symbol=p.symbol,owner_id=owner.id));db.commit();return {"symbol":p.symbol,"created":True}
@app.delete("/api/watchlist/{symbol}")
def del_watchlist(symbol:str, owner:User=Depends(require_user), db:Session=Depends(get_db)):
    q=select(WatchlistItem).where(WatchlistItem.symbol==symbol.upper(),WatchlistItem.owner_id==owner.id)
    row=db.scalar(q)
    if not row: raise HTTPException(404,"Not found")
    db.delete(row);db.commit();return {"deleted":True}

@app.get("/api/portfolio")
def portfolio(context: UserContext = Depends(optional_user),db:Session=Depends(get_db)):
    if not context.user: return {"mode":"paper_only","positions":{},"estimated_market_value":0,"net_cash_flow":0,"unrealized_value_less_cost":0,"trades":[],"requires_account":True}
    user=context.user
    rows=db.scalars(select(PaperTrade).where(PaperTrade.owner_id==user.id).order_by(desc(PaperTrade.id))).all()
    positions={}; cash_flow=0.0; total_fees=0.0
    for r in rows:
        p=positions.setdefault(r.symbol,{"quantity":0.0,"cash_flow":0.0})
        sign=1 if r.side=="buy" else -1; p["quantity"]+=sign*r.quantity
        gross=r.quantity*r.price
        flow=-(gross+r.transaction_cost) if r.side=="buy" else (gross-r.transaction_cost)
        p["cash_flow"]+=flow; cash_flow+=flow; total_fees+=r.transaction_cost
    market_value=0.0
    for symbol,pos in positions.items():
        latest=db.scalar(select(MarketBar).where(MarketBar.symbol==symbol,MarketBar.simulated.is_(False)).order_by(desc(MarketBar.timestamp)).limit(1))
        pos["latest_price"]=latest.close if latest else None
        pos["market_value"]=pos["quantity"]*latest.close if latest else None
        if latest: market_value+=pos["market_value"]
    starting_cash=user.virtual_cash_start
    return {"mode":"paper_only","starting_virtual_cash":starting_cash,"cash_balance":starting_cash+cash_flow,"positions":positions,"estimated_market_value":market_value,"net_cash_flow":cash_flow,"simulated_transaction_costs":total_fees,"total_equity":starting_cash+cash_flow+market_value,"unrealized_value_less_cost":market_value+cash_flow,"trades":[{"id":r.id,"symbol":r.symbol,"side":r.side,"quantity":r.quantity,"price":r.price,"transaction_cost":r.transaction_cost,"note":r.note,"created_at":r.created_at.isoformat() if r.created_at else None} for r in rows]}
@app.post("/api/portfolio/simulated-trade")
def trade(p:TradeIn, owner:User=Depends(require_user),db:Session=Depends(get_db)):
    owner_id=owner.id
    existing=db.scalars(select(PaperTrade).where(PaperTrade.owner_id==owner_id,PaperTrade.symbol==p.symbol)).all()
    held=sum((r.quantity if r.side=="buy" else -r.quantity) for r in existing)
    fee=p.quantity*p.price*settings.transaction_cost_rate
    if p.side=="sell" and p.quantity>held+1e-9:
        raise HTTPException(400,"Paper sale exceeds the available simulated position.")
    all_trades=db.scalars(select(PaperTrade).where(PaperTrade.owner_id==owner.id)).all()
    cash_flow=sum((-(r.quantity*r.price+r.transaction_cost) if r.side=="buy" else (r.quantity*r.price-r.transaction_cost)) for r in all_trades)
    cash_balance=owner.virtual_cash_start+cash_flow
    if p.side=="buy" and p.quantity*p.price+fee>cash_balance:
        raise HTTPException(400,"Insufficient virtual cash for this simulated purchase.")
    row=PaperTrade(**p.model_dump(),owner_id=owner_id,transaction_cost=fee);db.add(row);db.commit();db.refresh(row)
    return {"id":row.id,"mode":"paper_only","message":"Simulation ledger updated. No real transaction was made."}

@app.get("/api/alerts")
def alerts(context: UserContext = Depends(optional_user),db:Session=Depends(get_db)):
    if not context.user: return {"items":[],"requires_account":True}
    rows=db.scalars(select(PriceAlert).where(PriceAlert.owner_id==context.user.id).order_by(desc(PriceAlert.id))).all()
    items=[]
    for r in rows:
        latest=db.scalar(select(MarketBar).where(MarketBar.symbol==r.symbol,MarketBar.simulated.is_(False)).order_by(desc(MarketBar.timestamp)).limit(1))
        threshold=r.target_price if r.alert_type=="price" else (r.reference_price*(1+r.target_pct/100) if r.direction=="above" else r.reference_price*(1-r.target_pct/100))
        triggered=bool(latest and threshold is not None and ((r.direction=="above" and latest.close>=threshold) or (r.direction=="below" and latest.close<=threshold)))
        items.append({"id":r.id,"symbol":r.symbol,"alert_type":r.alert_type,"target_price":threshold,"target_pct":r.target_pct,"reference_price":r.reference_price,"direction":r.direction,"active":r.active,"latest_price":latest.close if latest else None,"triggered_by_latest_import":triggered,"latest_data_as_of":latest.timestamp.isoformat() if latest else None})
    return {"items":items,"note":"Trigger status is evaluated against latest imported price; no push notification is sent."}
@app.post("/api/alerts")
def add_alert(p:AlertIn, owner:User=Depends(require_user),db:Session=Depends(get_db)):
    latest=db.scalar(select(MarketBar).where(MarketBar.symbol==p.symbol,MarketBar.simulated.is_(False)).order_by(desc(MarketBar.timestamp)).limit(1))
    if p.alert_type=="percent" and not latest: raise HTTPException(400,"Import a reference price before creating a percentage-change alert.")
    threshold=p.target_price if p.alert_type=="price" else (latest.close*(1+p.target_pct/100) if p.direction=="above" else latest.close*(1-p.target_pct/100))
    row=PriceAlert(symbol=p.symbol,target_price=threshold,alert_type=p.alert_type,target_pct=p.target_pct,reference_price=latest.close if p.alert_type=="percent" else None,direction=p.direction,owner_id=owner.id);db.add(row);db.commit();db.refresh(row)
    return {"id":row.id,"message":"Alert saved. Thresholds are evaluated against imported prices when requested; no push notification is sent."}
@app.delete("/api/alerts/{alert_id}")
def remove_alert(alert_id:int, owner:User=Depends(require_user),db:Session=Depends(get_db)):
    row=db.scalar(select(PriceAlert).where(PriceAlert.id==alert_id,PriceAlert.owner_id==owner.id))
    if not row: raise HTTPException(404,"Alert not found")
    db.delete(row);db.commit();return {"deleted":True}

@app.post("/api/research/chat")
def research_chat(payload: ResearchQuestion, db:Session=Depends(get_db)):
    """A deterministic, database-grounded assistant; no external LLM is implied."""
    q=payload.question.strip().upper()
    syms=[x[0] for x in db.query(MarketBar.symbol).distinct().all() if x[0] in q]
    if not syms:
        return {"answer":"I can explain indicators and summarise records stored in this application. Include an imported symbol for company-specific data. This assistant does not access live data or external news.","sources":[],"assistant_type":"grounded_rule_based"}
    s=syms[0]; d=bars_frame(db,s)
    if d.empty: return {"answer":f"No stored data is available for {s}.","sources":[],"assistant_type":"grounded_rule_based"}
    last=d.iloc[-1]
    from .features import make_features
    feat=make_features(d).iloc[-1]
    profile=db.get(StockProfile,s)
    fund=db.scalars(select(FundamentalSnapshot).where(FundamentalSnapshot.symbol==s).order_by(desc(FundamentalSnapshot.as_of)).limit(1)).first()
    article_count=db.scalar(select(func.count(NewsArticle.id)).where(NewsArticle.symbol==s)) or 0
    parts=[f"Stored record for {s}"+(f" ({profile.company_name})" if profile else "")+f": latest close PKR {float(last.close):.4f} at {last.timestamp}. Source: {last.source}. Data is {'simulated' if bool(last.simulated) else 'imported; not verified as live'}. "]
    rsi=feat.get("rsi_14")
    if pd.notna(rsi):
        interpretation="relatively high" if rsi>=70 else ("relatively low" if rsi<=30 else "between common 30/70 reference levels")
        parts.append(f"RSI(14) is {float(rsi):.1f}, {interpretation}; RSI is a momentum indicator and not a standalone signal. ")
    macd=feat.get("macd")
    if pd.notna(macd): parts.append(f"MACD is {float(macd):.4f}; its interpretation depends on trend and timeframe. ")
    parts.append(f"Fundamental snapshot: {'available from '+fund.source+' as of '+fund.as_of.isoformat() if fund else 'not imported'}. Related stored news articles: {article_count}. ")
    parts.append("This is a factual summary of stored records, not a forecast, recommendation, or live market view.")
    return {"answer":"".join(parts),"sources":[{"table":"market_bars","symbol":s,"timestamp":last.timestamp.isoformat(),"source":last.source}],"assistant_type":"grounded_rule_based"}

@app.post("/api/admin/retrain", dependencies=[Depends(require_admin)])
def admin_retrain():
    from scripts.retrain_all import run as run_retraining
    return run_retraining()

@app.post("/api/admin/import-csv", dependencies=[Depends(require_admin)])
async def admin_import_csv(file: UploadFile = File(...), source: str = "MANUAL_IMPORT",
                           interval: str = "1d", simulated: bool = False, training_eligible: bool = False,
                           db: Session = Depends(get_db)):
    if interval not in {"1d", "15m", "5m", "1h"}:
        raise HTTPException(400, "Unsupported interval.")
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(400, "Upload a CSV file.")
    raw = await file.read(settings.max_request_bytes + 1)
    if len(raw) > settings.max_request_bytes:
        raise HTTPException(413, "CSV exceeds upload size limit.")
    try:
        from .providers.manual_csv import read_csv
        frame = read_csv(BytesIO(raw), max_rows=50000)
        if not source.strip() or len(source) > 120:
            raise ValueError("Invalid source label.")
        count = 0
        for row in frame.to_dict("records"):
            exists = db.scalar(select(MarketBar.id).where(MarketBar.symbol == row["symbol"],
                MarketBar.timestamp == row["timestamp"].to_pydatetime(), MarketBar.interval == interval))
            if exists: continue
            db.add(MarketBar(symbol=row["symbol"], timestamp=row["timestamp"].to_pydatetime(),
                interval=interval, open=float(row["open"]), high=float(row["high"]),
                low=float(row["low"]), close=float(row["close"]), volume=float(row["volume"]),
                source=source.strip(), simulated=simulated, training_eligible=(training_eligible and not simulated)))
            count += 1
        db.commit()
        return {"imported":count,"source":source,"interval":interval,"simulated":simulated,
                "training_eligible":(training_eligible and not simulated),"data_status":"simulated" if simulated else "imported"}
    except Exception as exc:
        db.rollback()
        raise HTTPException(400, f"CSV import rejected: {str(exc)[:240]}")

@app.get("/api/reports/daily")
def daily_report(db:Session=Depends(get_db)):
    path=build_daily_pdf(db)
    return FileResponse(path,media_type="application/pdf",filename="psx-ai-predictor-daily-report.pdf")


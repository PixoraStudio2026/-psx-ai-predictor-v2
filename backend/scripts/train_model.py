import argparse, sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.database import SessionLocal, Base, engine
from app.market import bars_frame, passes_liquidity_and_quality, latest_model
from app.ml import train_walk_forward
from app.models import ModelRun, TrainingAttempt
from app.config import settings

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--symbol",required=True)
    p.add_argument("--interval",choices=["1d","15m"],default="1d")
    p.add_argument("--horizon",type=int,choices=[1],default=1,help="One next available bar; choose interval with --interval.")
    a=p.parse_args()
    Base.metadata.create_all(engine); db=SessionLocal()
    try:
        d=bars_frame(db,a.symbol,a.interval)
        if not d.empty:
            from datetime import timedelta
            cutoff=d["timestamp"].max()-timedelta(days=365*settings.training_window_years)
            d=d[d["timestamp"]>=cutoff].copy()
        if d.empty: raise SystemExit("No data found for symbol/interval")
        db_horizon=0 if a.interval=="15m" else 1
        if latest_model(db,a.symbol,db_horizon):
            raise SystemExit("A deployed model already exists. Use scripts/retrain_all.py so the candidate is evaluated on a new untouched holdout before promotion.")
        if d["simulated"].any(): raise SystemExit("Synthetic data cannot train or publish models.")
        if not d["training_eligible"].all(): raise SystemExit("Data is not attested as authorised and eligible for model training.")
        ok, reason=passes_liquidity_and_quality(d,settings.min_avg_traded_value,settings.max_zero_volume_ratio)
        if not ok: raise SystemExit(f"Data-quality/liquidity gate failed: {reason}")
        result=train_walk_forward(d,a.symbol,a.horizon,source=str(d.iloc[-1]["source"]))
        m=result["metrics"]
        if m["test_samples"] < settings.model_min_test_samples or m["brier_score"] > settings.model_max_brier or m["brier_score"] >= m["baseline_brier"]:
            Path(result["path"]).unlink(missing_ok=True)
            raise SystemExit("Candidate rejected: failed sample-size or Brier-vs-naive baseline gates.")
        db.add(TrainingAttempt(symbol=a.symbol.upper(),horizon=db_horizon,model_version=result["version"],status="promoted",reason="Initial model passed chronological holdout and naive-baseline gates; no incumbent existed.",metrics_json=json.dumps(m),source=result["source"],trained_through=d.iloc[-1]["timestamp"]))
        db.add(ModelRun(symbol=a.symbol.upper(),horizon=db_horizon,
            model_path=result["path"],model_version=result["version"],
            brier_score=m["brier_score"],accuracy=m["accuracy"],
            test_samples=m["test_samples"],source=result["source"],promoted=True,trained_through=d.iloc[-1]["timestamp"],metrics_json=json.dumps(m)))
        db.commit(); print(result)
    finally: db.close()
if __name__=="__main__": main()

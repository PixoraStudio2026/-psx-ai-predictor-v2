"""Scheduled, guarded retraining for imported (never synthetic) market bars."""
import sys, logging, json
from pathlib import Path
from datetime import datetime, timedelta
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select, func
from app.config import settings
from app.database import SessionLocal, Base, engine
from app.models import MarketBar, ModelRun, TrainingAttempt
from app.market import bars_frame
from app.ml import train_walk_forward, load_model, evaluate_on_frame, make_binary_target
from app.outcomes import evaluate_matured_predictions

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("psx-retraining")

def eligible(frame):
    if frame.empty or frame["simulated"].any() or not frame["training_eligible"].all(): return False
    if len(frame) < 220: return False
    if frame[["open","high","low","close","volume"]].isna().any().any(): return False
    if (frame[["open","high","low","close"]] <= 0).any().any() or (frame["volume"] < 0).any(): return False
    return True

def run():
    Base.metadata.create_all(engine)
    db = SessionLocal()
    promoted, rejected = [], []
    try:
        outcome_summary = evaluate_matured_predictions(db)
        log.info("Prediction outcomes: %s", outcome_summary)
        symbols = [r[0] for r in db.query(MarketBar.symbol).distinct().all()]
        for symbol in symbols:
            for interval, db_horizon in (("1d", 1), ("15m", 0)):
                frame = bars_frame(db, symbol, interval)
                if not frame.empty:
                    cutoff = frame["timestamp"].max() - timedelta(days=365 * settings.training_window_years)
                    frame = frame[frame["timestamp"] >= cutoff].copy()
                if not eligible(frame):
                    continue
                previous = db.scalar(select(ModelRun).where(
                    ModelRun.symbol == symbol, ModelRun.horizon == db_horizon,
                    ModelRun.promoted.is_(True)).order_by(ModelRun.trained_at.desc()))
                newest = frame.iloc[-1]["timestamp"]
                candidate_frame=frame
                external_holdout_start=None
                if previous:
                    last_trained=previous.trained_through
                    if last_trained is None:
                        # Legacy models lack a trustworthy data watermark. Conservatively
                        # treat every currently imported row as already seen by the incumbent.
                        previous.trained_through=newest
                        db.commit()
                        continue
                    if getattr(last_trained,"tzinfo",None):
                        last_trained=last_trained.replace(tzinfo=None)
                    if last_trained is not None and newest<=last_trained:
                        continue
                    new_data=frame if last_trained is None else frame[frame["timestamp"]>last_trained]
                    new_bars=len(new_data)
                    if new_bars<settings.minimum_new_bars_for_retrain:
                        continue
                    # Reserve a genuinely new, untouched block that the incumbent has never seen.
                    holdout_bars=max(settings.model_min_test_samples+1,31)
                    if len(new_data)<=holdout_bars:
                        continue
                    external_holdout_start=new_data.iloc[-holdout_bars]["timestamp"]
                    candidate_frame=frame[frame["timestamp"]<external_holdout_start].copy()
                if not eligible(candidate_frame):
                    continue
                result=None
                try:
                    result = train_walk_forward(candidate_frame, symbol, 1, str(candidate_frame.iloc[-1]["source"]), refit_all=bool(previous))
                    metrics = result["metrics"]
                    passes = (metrics["test_samples"] >= settings.model_min_test_samples
                        and metrics["brier_score"] <= settings.model_max_brier
                        and metrics["brier_score"] < metrics["baseline_brier"])
                    if not passes:
                        Path(result["path"]).unlink(missing_ok=True)
                        reason="Candidate failed internal chronological sample/Brier/naive-baseline gates"
                        db.add(TrainingAttempt(symbol=symbol,horizon=db_horizon,model_version=result["version"],status="rejected",reason=reason,metrics_json=json.dumps(metrics),source=result["source"],trained_through=newest))
                        db.commit()
                        rejected.append({"symbol":symbol,"interval":interval,"reason":reason,"metrics":metrics})
                        continue
                    if previous:
                        incumbent_bundle=load_model(previous.model_path)
                        training_target=make_binary_target(candidate_frame["close"],1).dropna()
                        baseline_probability=float(training_target.mean())
                        candidate_external=evaluate_on_frame(frame,load_model(result["path"]),1,external_holdout_start,baseline_probability)
                        incumbent_external=evaluate_on_frame(frame,incumbent_bundle,1,external_holdout_start,baseline_probability)
                        metrics["external_candidate"]=candidate_external
                        metrics["external_incumbent"]=incumbent_external
                        external_pass=(candidate_external["test_samples"]>=settings.model_min_test_samples
                            and candidate_external["brier_score"]<=settings.model_max_brier
                            and candidate_external["brier_score"]<candidate_external["baseline_brier"]
                            and candidate_external["brier_score"]<=incumbent_external["brier_score"]+0.005)
                        if not external_pass:
                            Path(result["path"]).unlink(missing_ok=True)
                            reason="Candidate failed untouched new-data comparison against incumbent and naive baseline"
                            db.add(TrainingAttempt(symbol=symbol,horizon=db_horizon,model_version=result["version"],status="rejected",reason=reason,metrics_json=json.dumps(metrics),source=result["source"],trained_through=newest))
                            db.commit()
                            rejected.append({"symbol":symbol,"interval":interval,"reason":reason,"metrics":metrics})
                            continue
                    deployed_metrics=metrics.get("external_candidate",metrics)
                    db.add(TrainingAttempt(symbol=symbol,horizon=db_horizon,model_version=result["version"],status="promoted",reason="Candidate passed configured quality and promotion gates",metrics_json=json.dumps(metrics),source=result["source"],trained_through=newest))
                    db.add(ModelRun(symbol=symbol, horizon=db_horizon, model_path=result["path"],
                        model_version=result["version"], brier_score=deployed_metrics["brier_score"],
                        accuracy=deployed_metrics["accuracy"], test_samples=deployed_metrics["test_samples"],
                        source=result["source"], promoted=True, trained_through=newest, metrics_json=json.dumps(metrics)))
                    db.commit()
                    promoted.append({"symbol":symbol,"interval":interval,"version":result["version"],"metrics":metrics})
                    log.info("Promoted %s %s %s", symbol, interval, result["version"])
                except Exception as exc:
                    db.rollback()
                    if result and result.get("path"):
                        Path(result["path"]).unlink(missing_ok=True)
                    try:
                        db.add(TrainingAttempt(symbol=symbol,horizon=db_horizon,model_version=None,status="failed",reason=str(exc)[:500],metrics_json=None,source=str(frame.iloc[-1]["source"]) if not frame.empty else "UNKNOWN",trained_through=frame.iloc[-1]["timestamp"] if not frame.empty else None))
                        db.commit()
                    except Exception: db.rollback()
                    log.warning("Skipped %s %s: %s", symbol, interval, exc)
        return {"promoted":promoted,"rejected":rejected,"outcomes":outcome_summary,"finished_at":datetime.utcnow().isoformat()+"Z"}
    finally:
        db.close()

if __name__ == "__main__":
    print(run())

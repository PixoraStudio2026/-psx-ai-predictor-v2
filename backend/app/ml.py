from pathlib import Path
from uuid import uuid4
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.isotonic import IsotonicRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import (accuracy_score, brier_score_loss, precision_score,
                             recall_score, roc_auc_score, balanced_accuracy_score)
from .features import make_features, FEATURES

MODEL_DIR = Path("models")
MODEL_DIR.mkdir(exist_ok=True)

def make_binary_target(close: pd.Series, horizon: int = 1) -> pd.Series:
    if horizon < 1:
        raise ValueError("horizon must be a positive number of bars")
    future = close.shift(-horizon)
    return (future > close).where(future.notna())


def expected_calibration_error(y_true, probabilities, bins=10):
    y=np.asarray(y_true); p=np.asarray(probabilities); edges=np.linspace(0,1,bins+1); total=len(y)
    if total==0: return float("nan")
    error=0.0
    for lo,hi in zip(edges[:-1],edges[1:]):
        mask=(p>=lo) & (p<(hi if hi<1 else hi+1e-12))
        if mask.any(): error += float(mask.mean()) * abs(float(y[mask].mean())-float(p[mask].mean()))
    return float(error)

def purged_chronological_slices(n: int, horizon: int = 1):
    """Train/calibration/test slices with horizon rows purged at both boundaries."""
    train_end=int(n*.60); cal_end=int(n*.80)
    train_stop=train_end-horizon; cal_stop=cal_end-horizon
    if min(train_stop,cal_stop-train_end,n-cal_end)<30:
        raise ValueError("Insufficient observations after purging horizon-overlap rows at split boundaries.")
    return slice(0,train_stop),slice(train_end,cal_stop),slice(cal_end,n)

def train_walk_forward(frame: pd.DataFrame, symbol: str, horizon: int = 1,
                       source: str = "UNKNOWN", refit_all: bool = False):
    """Chronological train/calibration/final-test; never labels unknown future rows."""
    if horizon < 1:
        raise ValueError("horizon must be a positive number of bars")
    d = make_features(frame)
    d["target"] = make_binary_target(d["close"], horizon)
    d = d.dropna(subset=FEATURES + ["target"]).copy()
    if len(d) < 180:
        raise ValueError("At least 180 usable chronological observations are required.")
    X, y = d[FEATURES], d["target"].astype(int)
    n = len(d)
    train_slice, cal_slice, test_slice=purged_chronological_slices(n,horizon)
    train_stop=train_slice.stop
    if y.iloc[train_slice].nunique() < 2 or y.iloc[cal_slice].nunique() < 2:
        raise ValueError("Purged training and calibration periods must each contain both outcome classes.")
    model = Pipeline([
        ("impute", SimpleImputer(strategy="median")),
        ("scale", StandardScaler()),
        ("model", RandomForestClassifier(n_estimators=300, min_samples_leaf=5,
            max_features="sqrt", class_weight="balanced_subsample",
            random_state=42, n_jobs=-1))
    ])
    model.fit(X.iloc[train_slice], y.iloc[train_slice])
    cal_raw = model.predict_proba(X.iloc[cal_slice])[:, 1]
    calibrator = IsotonicRegression(out_of_bounds="clip").fit(
        cal_raw, y.iloc[cal_slice])
    test_raw = model.predict_proba(X.iloc[test_slice])[:, 1]
    probs = np.clip(calibrator.predict(test_raw), 0, 1)
    yt = y.iloc[test_slice].to_numpy()
    pred = (probs >= .5).astype(int)
    metrics = {
        "accuracy": float(accuracy_score(yt, pred)),
        "brier_score": float(brier_score_loss(yt, probs)),
        "precision": float(precision_score(yt, pred, zero_division=0)),
        "recall": float(recall_score(yt, pred, zero_division=0)),
        "balanced_accuracy": float(balanced_accuracy_score(yt, pred)),
        "calibration_error_10_bins": expected_calibration_error(yt, probs, bins=10),
        "test_samples": int(len(yt)),
        "positive_rate": float(np.mean(yt)),
        "baseline_brier": float(brier_score_loss(yt, np.full(len(yt), float(y.iloc[train_slice].mean())))),
        "test_start": d.iloc[test_slice.start]["timestamp"].isoformat(),
        "test_end": d.iloc[-1]["timestamp"].isoformat(),
    }
    if len(np.unique(yt)) > 1:
        metrics["roc_auc"] = float(roc_auc_score(yt, probs))
    # For incumbent updates, an additional untouched new-data holdout is evaluated
    # by the retraining orchestrator. In that mode the final estimator can consume
    # all pre-holdout rows; the external holdout, not this internal diagnostic split,
    # is the promotion gate for the deployed refitted model.
    if refit_all:
        model.fit(X, y)
    version = f"{symbol.upper()}_h{horizon}_{uuid4().hex[:10]}"
    path = MODEL_DIR / f"{version}.joblib"
    joblib.dump({"model": model, "calibrator": calibrator,
        "features": FEATURES, "version": version, "metrics": metrics,
        "source": source, "horizon": horizon}, path)
    return {"version": version, "path": str(path), "metrics": metrics,
            "source": source}

def load_model(path: str):
    return joblib.load(path)

def predict_latest(frame: pd.DataFrame, model_bundle: dict):
    d = make_features(frame).dropna(subset=model_bundle["features"])
    if d.empty:
        raise ValueError("Insufficient recent data to calculate model features.")
    row = d.iloc[[-1]]
    raw = model_bundle["model"].predict_proba(row[model_bundle["features"]])[:, 1]
    probability = float(np.clip(model_bundle["calibrator"].predict(raw)[0], 0, 1))
    return probability, d.iloc[-1]


def evaluate_on_frame(frame: pd.DataFrame, model_bundle: dict, horizon: int = 1,
                      start_timestamp=None, baseline_probability: float | None = None):
    """Evaluate a frozen model on a later, explicitly bounded untouched time window."""
    d=make_features(frame)
    d["target"]=make_binary_target(d["close"],horizon)
    if start_timestamp is not None: d=d[d["timestamp"]>=start_timestamp]
    d=d.dropna(subset=model_bundle["features"]+["target"]).copy()
    if len(d)<1: raise ValueError("No labelled observations in external holdout window.")
    raw=model_bundle["model"].predict_proba(d[model_bundle["features"]])[:,1]
    probs=np.clip(model_bundle["calibrator"].predict(raw),0,1)
    actual=d["target"].astype(int).to_numpy()
    predicted=(probs>=.5).astype(int)
    result={"brier_score":float(brier_score_loss(actual,probs)),"accuracy":float(accuracy_score(actual,predicted)),"precision":float(precision_score(actual,predicted,zero_division=0)),"recall":float(recall_score(actual,predicted,zero_division=0)),"balanced_accuracy":float(balanced_accuracy_score(actual,predicted)),"calibration_error_10_bins":expected_calibration_error(actual,probs,bins=10),"test_samples":int(len(actual)),"test_start":d.iloc[0]["timestamp"].isoformat(),"test_end":d.iloc[-1]["timestamp"].isoformat()}
    if len(np.unique(actual))>1: result["roc_auc"]=float(roc_auc_score(actual,probs))
    if baseline_probability is not None: result["baseline_brier"]=float(brier_score_loss(actual,np.full(len(actual),baseline_probability)))
    return result


def evaluate_on_latest_holdout(frame: pd.DataFrame, model_bundle: dict, horizon: int = 1):
    """Evaluate an incumbent on the same most-recent chronological holdout as a candidate."""
    d = make_features(frame)
    d["target"] = make_binary_target(d["close"], horizon)
    d = d.dropna(subset=FEATURES + ["target"]).copy()
    if len(d) < 180:
        raise ValueError("Insufficient observations for common holdout evaluation.")
    start = int(len(d) * .80)
    holdout = d.iloc[start:]
    if len(holdout) < 30:
        raise ValueError("Common holdout is too small.")
    raw = model_bundle["model"].predict_proba(holdout[FEATURES])[:, 1]
    probs = np.clip(model_bundle["calibrator"].predict(raw), 0, 1)
    actual = holdout["target"].astype(int).to_numpy()
    return {"brier_score": float(brier_score_loss(actual, probs)),
            "test_samples": int(len(actual)),
            "accuracy": float(accuracy_score(actual, (probs >= .5).astype(int)))}

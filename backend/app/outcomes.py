from datetime import datetime, timezone
from sqlalchemy import select
from .models import Prediction
from .market import bars_frame

def evaluate_matured_predictions(db):
    """Resolve predictions only after a subsequent eligible real bar exists."""
    pending = db.scalars(select(Prediction).where(
        Prediction.actual_positive.is_(None), Prediction.simulated.is_(False))).all()
    evaluated = 0
    for prediction in pending:
        interval = "15m" if prediction.horizon == 0 else "1d"
        frame = bars_frame(db, prediction.symbol, interval)
        if frame.empty:
            continue
        later = frame[frame["timestamp"] > prediction.data_as_of]
        if later.empty:
            continue
        outcome_bar = later.iloc[0]
        if bool(outcome_bar["simulated"]) or not bool(outcome_bar.get("training_eligible", False)):
            continue
        realized = float(outcome_bar["close"]) / float(prediction.reference_close) - 1.0
        prediction.actual_positive = bool(realized > 0)
        prediction.realized_return = realized
        prediction.evaluated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        evaluated += 1
    if evaluated:
        db.commit()
    return {"evaluated": evaluated, "pending": len(pending)-evaluated}

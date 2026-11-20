import pandas as pd
from app.ml import make_binary_target

def test_unknown_future_rows_are_not_negative_labels():
    close = pd.Series([10.0, 11.0, 9.0, 12.0])
    target = make_binary_target(close, 1)
    assert target.iloc[0] == 1
    assert target.iloc[1] == 0
    assert target.iloc[2] == 1
    assert pd.isna(target.iloc[3])

def test_horizon_requires_positive_integer():
    try:
        make_binary_target(pd.Series([1, 2]), 0)
    except ValueError:
        return
    assert False, "zero horizon must be rejected"

def test_training_eligibility_is_explicit():
    import pandas as pd
    from scripts.retrain_all import eligible
    frame=pd.DataFrame({
        "timestamp":pd.date_range("2024-01-01",periods=230),
        "open":[10.0]*230,"high":[11.0]*230,"low":[9.0]*230,
        "close":[10.0]*230,"volume":[1000.0]*230,
        "simulated":[False]*230,"training_eligible":[False]*230,
    })
    assert not eligible(frame)
    frame["training_eligible"]=True
    assert eligible(frame)
    frame.loc[0,"simulated"]=True
    assert not eligible(frame)


def test_chronological_split_purges_horizon_overlap():
    from app.ml import purged_chronological_slices
    train, calibration, test = purged_chronological_slices(500, horizon=3)
    assert train.stop + 3 == calibration.start
    assert calibration.stop + 3 == test.start
    assert train.stop < calibration.start < calibration.stop < test.start


def test_purged_chronological_slices_have_non_overlapping_boundaries():
    from app.ml import purged_chronological_slices
    train, calibration, test = purged_chronological_slices(1000, horizon=3)
    assert train.stop < calibration.start
    assert calibration.stop < test.start
    assert train.start == 0
    assert test.stop == 1000

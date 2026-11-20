from app.ml import expected_calibration_error

def test_perfectly_calibrated_single_bin_has_zero_error():
    assert expected_calibration_error([0,0,0,1],[0.25,0.25,0.25,0.25],bins=2)==0

def test_calibration_error_is_bounded():
    value=expected_calibration_error([0,0,1,1],[0.9,0.9,0.1,0.1],bins=2)
    assert 0 <= value <= 1

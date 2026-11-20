import pandas as pd
import pytest
from app.providers.manual_csv import read_csv

def test_manual_csv_validates_and_sorts(tmp_path):
    path=tmp_path/'bars.csv'
    pd.DataFrame([
        {'symbol':'ogdc','timestamp':'2026-01-02','open':101,'high':103,'low':100,'close':102,'volume':1000},
        {'symbol':'OGDC','timestamp':'2026-01-01','open':99,'high':102,'low':98,'close':101,'volume':900},
    ]).to_csv(path,index=False)
    result=read_csv(path)
    assert list(result.symbol)==['OGDC','OGDC']
    assert result.timestamp.is_monotonic_increasing

def test_manual_csv_rejects_inconsistent_ohlc(tmp_path):
    path=tmp_path/'bad.csv'
    pd.DataFrame([{'symbol':'OGDC','timestamp':'2026-01-01','open':99,'high':98,'low':98,'close':101,'volume':1000}]).to_csv(path,index=False)
    with pytest.raises(ValueError,match='OHLC'):
        read_csv(path)


def test_manual_csv_rejects_invalid_symbol(tmp_path):
    path=tmp_path/'bad-symbol.csv'
    pd.DataFrame([{'symbol':'BAD SYMBOL','timestamp':'2026-01-01','open':99,'high':102,'low':98,'close':101,'volume':1000}]).to_csv(path,index=False)
    with pytest.raises(ValueError,match='symbol'):
        read_csv(path)

def test_explicit_timezone_is_converted_to_pakistan_local_time(tmp_path):
    path=tmp_path/'zoned.csv'
    pd.DataFrame([{'symbol':'OGDC','timestamp':'2026-01-01T04:00:00Z','open':99,'high':102,'low':98,'close':101,'volume':1000}]).to_csv(path,index=False)
    result=read_csv(path)
    assert result.timestamp.iloc[0].hour == 9


def test_manual_csv_rejects_infinite_numeric_values(tmp_path):
    path=tmp_path/'infinite.csv'
    pd.DataFrame([{'symbol':'OGDC','timestamp':'2026-01-01','open':99,'high':102,'low':98,'close':101,'volume':float('inf')}]).to_csv(path,index=False)
    with pytest.raises(ValueError,match='non-finite'):
        read_csv(path)

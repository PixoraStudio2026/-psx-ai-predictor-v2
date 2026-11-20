import pandas as pd
from app.features import make_features,FEATURES
def test_feature_columns_exist():
    d=pd.DataFrame({"timestamp":pd.date_range("2024-01-01",periods=80),"close":[100+i*.2 for i in range(80)],"volume":[1000+i for i in range(80)]})
    out=make_features(d)
    assert set(FEATURES).issubset(out.columns)
    assert len(out)==80


def test_rsi_handles_zero_loss_and_flat_prices():
    rising=pd.DataFrame({'timestamp':pd.date_range('2026-01-01',periods=40),'close':[float(i+1) for i in range(40)],'volume':[100.0]*40})
    f=make_features(rising)
    assert f.rsi_14.iloc[-1] == 100.0
    flat=rising.copy(); flat['close']=100.0
    ff=make_features(flat)
    assert ff.rsi_14.iloc[-1] == 50.0


def test_quality_filter_flags_extreme_single_bar_jump():
    from app.market import passes_liquidity_and_quality
    d=pd.DataFrame({'timestamp':pd.date_range('2026-01-01',periods=45),'open':[100.0]*45,'high':[110.0]*45,'low':[90.0]*45,'close':[100.0]*44+[200.0],'volume':[20000.0]*45,'interval':['1d']*45})
    ok,reason=passes_liquidity_and_quality(d,min_avg_traded_value=1,max_zero_volume_ratio=0.5)
    assert not ok and 'corporate-action' in reason

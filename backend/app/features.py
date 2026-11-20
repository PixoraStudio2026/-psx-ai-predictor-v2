import pandas as pd
import numpy as np
FEATURES = ["return_1","return_5","sma_ratio","ema_ratio","rsi_14","macd","bb_position","volatility_10","volume_ratio","momentum_10"]
def make_features(frame: pd.DataFrame) -> pd.DataFrame:
    d=frame.sort_values("timestamp").copy()
    close=d["close"].astype(float); volume=d["volume"].astype(float)
    d["return_1"]=close.pct_change()
    d["return_5"]=close.pct_change(5)
    d["sma_10"]=close.rolling(10).mean()
    d["sma_30"]=close.rolling(30).mean()
    d["sma_ratio"]=d["sma_10"]/d["sma_30"]-1
    d["ema_12"]=close.ewm(span=12,adjust=False).mean()
    d["ema_26"]=close.ewm(span=26,adjust=False).mean()
    d["ema_ratio"]=d["ema_12"]/d["ema_26"]-1
    delta=close.diff()
    gain=delta.clip(lower=0).rolling(14).mean()
    loss=(-delta.clip(upper=0)).rolling(14).mean()
    rs=gain/loss.replace(0,np.nan)
    rsi=100-(100/(1+rs))
    rsi=rsi.mask((loss==0)&(gain>0),100.0)
    rsi=rsi.mask((gain==0)&(loss>0),0.0)
    rsi=rsi.mask((gain==0)&(loss==0),50.0)
    d["rsi_14"]=rsi
    d["macd"]=d["ema_12"]-d["ema_26"]
    mid=close.rolling(20).mean(); sd=close.rolling(20).std()
    d["bb_position"]=(close-(mid-2*sd))/(4*sd)
    d["volatility_10"]=d["return_1"].rolling(10).std()
    d["volume_ratio"]=volume/volume.rolling(20).mean()
    d["momentum_10"]=close/close.shift(10)-1
    return d.replace([np.inf,-np.inf],np.nan)

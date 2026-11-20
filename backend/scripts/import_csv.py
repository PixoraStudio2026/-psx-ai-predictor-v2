import argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.database import SessionLocal, Base, engine
from app.models import MarketBar
from app.providers.manual_csv import read_csv
def main():
    p=argparse.ArgumentParser(description="Import licensed PSX OHLCV data.")
    p.add_argument("csv"); p.add_argument("--source",required=True)
    p.add_argument("--interval",choices=["1d","15m","5m","1h"],default="1d")
    p.add_argument("--simulated",action="store_true"); p.add_argument("--training-eligible",action="store_true",help="Attest that source is real, authorised and licensed for model training")
    p.add_argument("--max-rows",type=int,default=500000)
    a=p.parse_args()
    if not a.source.strip() or len(a.source)>120: raise SystemExit("Provide a valid source label (1-120 chars).")
    d=read_csv(a.csv,max_rows=a.max_rows)
    Base.metadata.create_all(engine); db=SessionLocal(); count=0
    try:
        for r in d.to_dict("records"):
            exists=db.query(MarketBar.id).filter_by(symbol=r["symbol"],timestamp=r["timestamp"].to_pydatetime(),interval=a.interval).first()
            if exists: continue
            db.add(MarketBar(symbol=r["symbol"],timestamp=r["timestamp"].to_pydatetime(),
                interval=a.interval,open=float(r["open"]),high=float(r["high"]),low=float(r["low"]),
                close=float(r["close"]),volume=float(r["volume"]),source=a.source.strip(),simulated=a.simulated,training_eligible=(a.training_eligible and not a.simulated)))
            count+=1
        db.commit()
    finally: db.close()
    print(f"Imported {count} new rows from {a.source}; simulated={a.simulated}; training_eligible={a.training_eligible and not a.simulated}")
if __name__=="__main__": main()

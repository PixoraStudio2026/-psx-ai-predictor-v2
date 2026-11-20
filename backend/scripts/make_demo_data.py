import sys,math,random
from pathlib import Path
from datetime import datetime,timedelta
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.database import SessionLocal,Base,engine
from app.models import MarketBar
def main():
    Base.metadata.create_all(engine);db=SessionLocal();random.seed(7)
    try:
        for sym,start in [("DEMOA",42),("DEMOB",86),("DEMOC",125)]:
            price=start
            for i in range(260):
                dt=datetime(2025,1,1)+timedelta(days=i)
                price*=1+random.gauss(.0003,.018)
                op=price*(1+random.uniform(-.006,.006)); hi=max(op,price)*1.012;lo=min(op,price)*.988
                db.add(MarketBar(symbol=sym,timestamp=dt,interval="1d",open=op,high=hi,low=lo,close=price,volume=random.randint(50000,900000),source="SIMULATED",simulated=True))
        db.commit()
    finally: db.close()
    print("Inserted synthetic DEMO symbols. These are not PSX securities or prices.")
if __name__=="__main__":main()

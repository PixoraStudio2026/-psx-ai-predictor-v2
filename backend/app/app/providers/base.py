"""Provider contract. Implement only with a data vendor that authorises this use."""
from abc import ABC, abstractmethod
import pandas as pd

class MarketDataProvider(ABC):
    name: str
    data_status: str = "delayed"  # live, delayed, historical, imported

    @abstractmethod
    def fetch_ohlcv(self, symbols: list[str], interval: str, start, end) -> pd.DataFrame:
        """Return columns symbol,timestamp,open,high,low,close,volume.

        Implementations must respect vendor licensing, authentication, rate limits,
        exchange calendar and corporate-action policy. Never label a response live
        unless the vendor contract and feed actually guarantee live delivery.
        """
        raise NotImplementedError

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
class Settings(BaseSettings):
    database_url: str = "sqlite:///./psx_predictor.db"
    cors_origins: str = "http://localhost:5173"
    app_env: str = "development"
    admin_api_token: str = ""
    auth_secret: str = ""
    auth_token_minutes: int = Field(default=720, ge=15, le=43200)
    max_request_bytes: int = 2_000_000
    rate_limit_per_minute: int = Field(default=120, ge=10, le=1000)
    enable_scheduler: bool = False
    retrain_hour: int = Field(default=2, ge=0, le=23)
    retrain_minute: int = Field(default=30, ge=0, le=59)
    minimum_new_bars_for_retrain: int = Field(default=36, ge=1, le=10000)
    training_window_years: int = Field(default=5, ge=1, le=20)
    model_max_brier: float = Field(default=0.24, ge=0, le=1)
    model_min_test_samples: int = Field(default=30, ge=10, le=100000)
    transaction_cost_rate: float = Field(default=0.002, ge=0, le=0.05)
    min_avg_traded_value: float = Field(default=1000000, ge=0)
    max_zero_volume_ratio: float = Field(default=0.25, ge=0, le=1)
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    @property
    def cors_origin_list(self):
        return [x.strip() for x in self.cors_origins.split(",") if x.strip()]
settings = Settings()

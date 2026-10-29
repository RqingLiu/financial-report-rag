from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")
    voyage_api_key: SecretStr
    voyage_model: str = "voyage-4-lite"
    database_url: SecretStr = SecretStr("postgresql://localhost/financial_report_rag")
    sec_user_agent: str = "FinancialReportRAG personal research"
    embedding_budget_usd: float = 1.0
    embedding_dimension: int = 1024


def settings() -> Settings:
    return Settings()

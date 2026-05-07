from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Tender Analyzer API"
    mongodb_uri: str = ""
    mongodb_db: str = "tender_analyzer"
    pdf_storage_dir: str = "storage/tenders"
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    # Request timeout in seconds (10 minutes default — pipeline is long-running)
    request_timeout_seconds: int = 600
    api_base_url: str = "http://127.0.0.1:8000"
    cors_origins: list[str] | str = ["http://127.0.0.1:8000", "http://localhost:8000"]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, v):
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        return v


settings = Settings()

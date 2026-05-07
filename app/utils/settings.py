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
    openrouter_api_key: str = ""
    openrouter_model: str = "openai/gpt-4.1-mini"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_app_name: str = "tender-analyzer"
    openrouter_site_url: str = "http://localhost"
    # Request timeout in seconds (10 minutes default — pipeline is long-running)
    request_timeout_seconds: int = 600
    api_base_url: str = "http://127.0.0.1:8000"
    cors_origins: list[str] | str = ["http://127.0.0.1:8000", "http://localhost:8000"]
    auth_min_password_length: int = 8
    admin_approval_key: str = ""
    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    jwt_exp_hours: int = 24

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, v):
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        return v


settings = Settings()

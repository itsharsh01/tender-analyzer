from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Tender Analyzer API"
    mongodb_uri: str = ""
    mongodb_db: str = "tender_analyzer"
    pdf_storage_dir: str = "storage/pdfs"


settings = Settings()


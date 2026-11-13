from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://relay:relay_dev_password@localhost:5432/relay"
    object_storage_dir: str = "./storage"
    github_token: str = ""
    github_fixture_path: str = str(Path(__file__).resolve().parents[1] / "fixtures" / "github_payments_service.json")
    openai_api_key: str = ""
    llm_model: str = "gpt-4o-mini"

    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parents[2] / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()

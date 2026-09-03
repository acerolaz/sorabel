from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    azure_openai_api_key: str
    azure_openai_endpoint: str
    azure_openai_api_version: str = "2024-02-01"
    azure_openai_embedding_deployment: str
    azure_openai_chat_deployment: str


@lru_cache
def get_settings() -> Settings:
    # pydantic-settings populates fields from .env/environment at runtime
    return Settings()  # type: ignore[call-arg]

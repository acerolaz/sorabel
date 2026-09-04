"""Application settings, loaded from environment variables / .env via
pydantic-settings. Never hardcode credentials — see ../../.claude/rules/security.md."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    azure_openai_endpoint: str
    azure_openai_api_key: str
    azure_openai_api_version: str = "2024-08-01-preview"
    azure_openai_deployment_generator: str
    azure_openai_deployment_judge: str

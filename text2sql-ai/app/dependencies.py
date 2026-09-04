"""Shared FastAPI dependencies: builds the GenerateSqlUseCase with its concrete
Azure OpenAI + YAML-schema adapters. This is the composition root — the only place
that imports both the application layer and infrastructure adapters together."""

from __future__ import annotations

from functools import lru_cache

from fastapi import Depends
from openai import AsyncAzureOpenAI

from app.application.use_cases.generate_sql import GenerateSqlUseCase
from app.config import Settings
from app.infrastructure.azure_openai.judge_client import AzureOpenAiJudgeClient
from app.infrastructure.azure_openai.llm_client import AzureOpenAiLlmClient
from app.infrastructure.schema.repository import (
    SCHEMA_DIR,
    YamlSchemaRepository,
    load_business_rules,
    load_few_shot_examples,
)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


@lru_cache
def get_schema_repository() -> YamlSchemaRepository:
    return YamlSchemaRepository()


@lru_cache
def get_business_rules() -> dict[str, str]:
    return load_business_rules(SCHEMA_DIR)


@lru_cache
def get_few_shot_examples() -> list[dict[str, str]]:
    return load_few_shot_examples(SCHEMA_DIR)


@lru_cache
def get_azure_client() -> AsyncAzureOpenAI:
    settings = get_settings()
    return AsyncAzureOpenAI(
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        api_version=settings.azure_openai_api_version,
    )


def get_generate_sql_use_case(
    settings: Settings = Depends(get_settings),
    schema_repository: YamlSchemaRepository = Depends(get_schema_repository),
) -> GenerateSqlUseCase:
    client = get_azure_client()
    return GenerateSqlUseCase(
        schema_repository=schema_repository,
        llm=AzureOpenAiLlmClient(client, settings.azure_openai_deployment_generator),
        judge=AzureOpenAiJudgeClient(client, settings.azure_openai_deployment_judge),
        business_rules=get_business_rules(),
        few_shot_examples=get_few_shot_examples(),
    )

from functools import lru_cache
from typing import AsyncIterator

from fastapi import Depends
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.application.use_cases.answer_query import AnswerQueryUseCase
from app.application.use_cases.ingest_document import IngestDocumentUseCase
from app.config import get_settings
from app.infrastructure.azure_openai.embedding_client import AzureEmbeddingClient
from app.infrastructure.azure_openai.llm_client import AzureLlmClient
from app.infrastructure.parsers.markdown_parser import MarkdownParser
from app.infrastructure.parsers.pdf_parser import PdfParser
from app.infrastructure.postgres.bm25_repository import Bm25Repository
from app.infrastructure.postgres.document_registry import PostgresDocumentRegistry
from app.infrastructure.postgres.pgvector_repository import PgVectorRepository
from app.infrastructure.reranker.cross_encoder_reranker import CrossEncoderReranker


@lru_cache
def get_engine() -> AsyncEngine:
    return create_async_engine(get_settings().database_url)


async def get_db() -> AsyncIterator[AsyncSession]:
    session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_secondary_db() -> AsyncIterator[AsyncSession]:
    """A second, independent session/connection for the same request.

    Used so dense and sparse retrieval genuinely run concurrently instead of
    serializing on a single shared SQLAlchemy session.
    """
    session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@lru_cache
def get_reranker() -> CrossEncoderReranker:
    return CrossEncoderReranker()


@lru_cache
def get_embedding_client() -> AzureEmbeddingClient:
    return AzureEmbeddingClient(get_settings())


@lru_cache
def get_llm_client() -> AzureLlmClient:
    return AzureLlmClient(get_settings())


def get_answer_query_use_case(
    db: AsyncSession = Depends(get_db),
    lexical_db: AsyncSession = Depends(get_secondary_db),
    reranker: CrossEncoderReranker = Depends(get_reranker),
    embedding_client: AzureEmbeddingClient = Depends(get_embedding_client),
    llm_client: AzureLlmClient = Depends(get_llm_client),
) -> AnswerQueryUseCase:
    return AnswerQueryUseCase(
        embedding_port=embedding_client,
        vector_store=PgVectorRepository(db),
        lexical_search=Bm25Repository(lexical_db),
        reranker=reranker,
        llm=llm_client,
    )


def get_ingest_document_use_case(
    db: AsyncSession = Depends(get_db),
    embedding_client: AzureEmbeddingClient = Depends(get_embedding_client),
) -> IngestDocumentUseCase:
    return IngestDocumentUseCase(
        parsers={"md": MarkdownParser(), "pdf": PdfParser()},
        registry=PostgresDocumentRegistry(db),
        embedding_port=embedding_client,
        vector_store=PgVectorRepository(db),
        lexical_search=Bm25Repository(db),
    )

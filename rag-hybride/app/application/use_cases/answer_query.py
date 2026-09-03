import asyncio
from dataclasses import dataclass

from app.domain.confidence import LOW_CONFIDENCE_THRESHOLD, classify_confidence
from app.domain.fusion import RankedChunk, reciprocal_rank_fusion
from app.domain.models import Answer, Chunk, Citation
from app.domain.ports import (
    EmbeddingPort,
    LexicalSearchPort,
    LLMPort,
    RerankerPort,
    VectorStorePort,
)

RERANK_TOP_N = 10
CITATION_SCORE_FLOOR = LOW_CONFIDENCE_THRESHOLD
MAX_CITATIONS = 5
REFUSAL_TEXT = "Je ne trouve pas cette information dans le corpus."


@dataclass
class AnswerQueryUseCase:
    embedding_port: EmbeddingPort
    vector_store: VectorStorePort
    lexical_search: LexicalSearchPort
    reranker: RerankerPort
    llm: LLMPort

    async def execute(self, query: str, product_ref: str | None = None, top_k: int = 20) -> Answer:
        embedding = await self.embedding_port.embed(query)
        dense_results, sparse_results = await asyncio.gather(
            self.vector_store.search(embedding, top_k, product_ref),
            self.lexical_search.search(query, top_k, product_ref),
        )

        chunks_by_id: dict[str, Chunk] = {}
        for chunk, _rank in (*dense_results, *sparse_results):
            chunks_by_id[chunk.id] = chunk

        dense_ranked = [RankedChunk(chunk_id=chunk.id, rank=rank) for chunk, rank in dense_results]
        sparse_ranked = [
            RankedChunk(chunk_id=chunk.id, rank=rank) for chunk, rank in sparse_results
        ]
        fused = reciprocal_rank_fusion(dense_ranked, sparse_ranked)

        if not fused:
            return Answer(text=REFUSAL_TEXT, citations=[], confidence="refused")

        reranked: list[tuple[Chunk, float]] = []
        for chunk_id, _fused_score in fused[:RERANK_TOP_N]:
            chunk = chunks_by_id[chunk_id]
            score = await self.reranker.score(query, chunk.content)
            reranked.append((chunk, score))
        reranked.sort(key=lambda pair: pair[1], reverse=True)

        _best_chunk, best_score = reranked[0]
        confidence = classify_confidence(best_score)

        if confidence == "refused":
            return Answer(text=REFUSAL_TEXT, citations=[], confidence="refused")

        cited_chunks = [chunk for chunk, score in reranked if score >= CITATION_SCORE_FLOOR][
            :MAX_CITATIONS
        ]
        text = await self.llm.generate(query, cited_chunks, hedge=(confidence == "low"))
        citations = [
            Citation(
                title=c.title,
                product_ref=c.product_ref,
                published_date=c.published_date,
                document_type=c.document_type,
                url=c.source_path,
            )
            for c in cited_chunks
        ]
        return Answer(text=text, citations=citations, confidence=confidence)

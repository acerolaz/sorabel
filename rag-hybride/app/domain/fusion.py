from dataclasses import dataclass


@dataclass(frozen=True)
class RankedChunk:
    chunk_id: str
    rank: int  # 1-based


def reciprocal_rank_fusion(
    dense_results: list[RankedChunk],
    sparse_results: list[RankedChunk],
    k: int = 60,
) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for results in (dense_results, sparse_results):
        for ranked in results:
            scores[ranked.chunk_id] = scores.get(ranked.chunk_id, 0.0) + 1.0 / (k + ranked.rank)
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)

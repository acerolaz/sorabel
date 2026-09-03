import math

from sentence_transformers import CrossEncoder
from starlette.concurrency import run_in_threadpool

DEFAULT_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"


class CrossEncoderReranker:
    def __init__(self, model_name: str = DEFAULT_MODEL_NAME) -> None:
        self._model = CrossEncoder(model_name)

    async def score(self, query: str, chunk_text: str) -> float:
        return await run_in_threadpool(self._score_sync, query, chunk_text)

    def _score_sync(self, query: str, chunk_text: str) -> float:
        raw_score = self._model.predict([(query, chunk_text)])[0]
        return float(1 / (1 + math.exp(-raw_score)))

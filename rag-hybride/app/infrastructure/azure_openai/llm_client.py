import openai
from openai import AsyncAzureOpenAI

from app.config import Settings
from app.domain.errors import EmbeddingServiceError
from app.domain.models import Chunk

SYSTEM_PROMPT = (
    "Tu réponds strictement à partir des extraits fournis. "
    "N'invente jamais d'information absente des extraits. "
    "Si les extraits ne suffisent pas, dis-le explicitement."
)
HEDGE_INSTRUCTION = (
    " La pertinence des extraits est incertaine : formule une réponse prudente, "
    "en signalant explicitement le doute."
)


class AzureLlmClient:
    def __init__(self, settings: Settings) -> None:
        self._client = AsyncAzureOpenAI(
            api_key=settings.azure_openai_api_key,
            api_version=settings.azure_openai_api_version,
            azure_endpoint=settings.azure_openai_endpoint,
        )
        self._deployment = settings.azure_openai_chat_deployment

    async def generate(self, query: str, cited_chunks: list[Chunk], hedge: bool) -> str:
        context = "\n\n".join(f"[{c.product_ref}] {c.content}" for c in cited_chunks)
        system_prompt = SYSTEM_PROMPT + (HEDGE_INSTRUCTION if hedge else "")
        try:
            response = await self._client.chat.completions.create(
                model=self._deployment,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Extraits:\n{context}\n\nQuestion: {query}"},
                ],
            )
        except openai.OpenAIError as exc:
            raise EmbeddingServiceError(f"generation request failed: {exc}") from exc
        return response.choices[0].message.content or ""

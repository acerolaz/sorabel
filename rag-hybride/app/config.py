from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Racine de la solution : app/ -> rag-hybride/ -> src/
# Le .env est unique pour toute la gateway. Le chemin est résolu depuis ce
# fichier et non depuis le répertoire courant, afin que l'application et
# Alembic démarrent quel que soit le répertoire d'exécution.
_SOLUTION_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    # Racine d'abord, puis repli relatif si rag-hybride est un jour extrait
    # dans son propre dépôt.
    model_config = SettingsConfigDict(env_file=(_SOLUTION_ROOT / ".env", ".env"), extra="ignore")

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

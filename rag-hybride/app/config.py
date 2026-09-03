from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Racine de la solution : app/ -> rag-hybride/ -> src/
# Le .env est unique pour toute la gateway. Le chemin est résolu depuis ce
# fichier et non depuis le répertoire courant, afin que l'application et
# Alembic démarrent quel que soit le répertoire d'exécution.
_SOLUTION_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    # Fichier unique : la solution n'a qu'un seul .env, à la racine. Un .env
    # manquant à la racine doit faire échouer le démarrage plutôt que de se
    # replier silencieusement sur un .env local (répertoire courant), qui
    # pourrait diverger de celui utilisé par Docker Compose.
    model_config = SettingsConfigDict(env_file=_SOLUTION_ROOT / ".env", extra="ignore")

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

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# app/ -> mcp/ -> src/ : le .env est unique pour toute la solution. Le chemin
# est résolu depuis ce fichier, pas depuis le répertoire courant, afin que le
# serveur démarre quel que soit le répertoire d'exécution.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SOLUTION_ROOT = _PROJECT_ROOT.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_SOLUTION_ROOT / ".env", extra="ignore")

    mcp_env: Literal["dev", "prod"] = "dev"
    mcp_token_verifier: Literal["local", "jwks"] = "local"
    mcp_jwks_url: str = ""
    mcp_jwt_issuer: str = ""
    mcp_jwt_audience: str = ""
    mcp_dev_jwt_secret: str = ""
    mcp_access_matrix_path: str = "access_matrix.yaml"
    mcp_http_timeout_s: float = 10.0

    rag_backend: Literal["http", "stub"] = "stub"
    rag_base_url: str = ""
    text2sql_backend: Literal["http", "stub"] = "stub"
    text2sql_base_url: str = ""
    sqlapi_backend: Literal["http", "stub"] = "stub"
    sqlapi_base_url: str = ""

    def access_matrix_file(self) -> Path:
        """Chemin absolu de la matrice, relatif à la racine du projet si besoin."""
        chemin = Path(self.mcp_access_matrix_path)
        return chemin if chemin.is_absolute() else _PROJECT_ROOT / chemin


@lru_cache
def get_settings() -> Settings:
    return Settings()

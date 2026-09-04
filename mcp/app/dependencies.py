"""Composition des adapters : le seul endroit où l'application choisit une
implémentation concrète de port (spec §10).

Les valeurs par défaut sont les plus fermées : `stub` partout, jamais un backend
réel implicite. Configurer un backend `http` qui n'existe pas encore échoue au
démarrage plutôt que de laisser croire à un câblage.
"""

from app.config import Settings, get_settings
from app.domain.ports import (
    AuditLogPort,
    RagPort,
    SqlExecutionPort,
    Text2SqlPort,
    TokenVerifierPort,
)
from app.infrastructure.audit.stdout_audit_log import StdoutAuditLog
from app.infrastructure.keycloak.jwks_verifier import build_token_verifier
from app.infrastructure.stub.rag_stub import RagStub
from app.infrastructure.stub.sqlapi_stub import SqlApiStub
from app.infrastructure.stub.text2sql_stub import Text2SqlStub


def build_rag_port(settings: Settings) -> RagPort:
    """Adapter RAG : stub par défaut, client HTTP si `RAG_BACKEND=http`."""
    if settings.rag_backend == "stub":
        return RagStub()
    # Import paresseux : `RagHttpClient` est livré par la tâche 14. Le placer en
    # tête de module rendrait tout l'assemblage inimportable d'ici là, alors que
    # le défaut `RAG_BACKEND=stub` n'atteint jamais cette branche.
    # Le `type: ignore` couvre ce même décalage : il devient inutile — et
    # `mypy strict` (warn_unused_ignores) le signalera — dès que la tâche 14
    # aura livré le module, ce qui est le rappel attendu pour le retirer.
    from app.infrastructure.http.rag_client import (  # type: ignore[import-not-found]
        RagHttpClient,
    )

    client: RagPort = RagHttpClient(settings.rag_base_url, settings.mcp_http_timeout_s)
    return client


def build_text2sql_port(settings: Settings) -> Text2SqlPort:
    """Adapter de génération SQL : stub seul disponible aujourd'hui."""
    if settings.text2sql_backend == "stub":
        return Text2SqlStub()
    raise NotImplementedError("adapter HTTP text2sql-ai : le service n'existe pas encore")


def build_sqlapi_port(settings: Settings) -> SqlExecutionPort:
    """Adapter d'exécution SQL : stub seul disponible aujourd'hui."""
    if settings.sqlapi_backend == "stub":
        return SqlApiStub()
    raise NotImplementedError("adapter HTTP sorabelsql-api : le service n'existe pas encore")


def build_audit_log() -> AuditLogPort:
    """Journal d'audit (E5) : une ligne JSON par appel, sur stdout."""
    return StdoutAuditLog()


def build_verifier(settings: Settings) -> TokenVerifierPort:
    """Vérificateur de token, par sa **porte d'entrée unique** (spec §5).

    `build_token_verifier` — jamais `build_local_verifier` directement : c'est
    lui qui porte les garde-fous communs aux deux adapters (issuer et audience
    non vides, valeur de `MCP_TOKEN_VERIFIER` connue) et qui refuse de démarrer
    sinon.
    """
    return build_token_verifier(settings)


def current_settings() -> Settings:
    """Configuration du processus (mise en cache par `get_settings`)."""
    return get_settings()

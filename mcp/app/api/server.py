"""Assemblage du serveur MCP gouverné et de son application ASGI.

Deux fabriques, **aucun effet de bord à l'import** : `build_app()` construit le
vérificateur de token, qui refuse de démarrer sur une configuration non sûre
(spec §5). Évaluée au niveau module, cette construction ferait échouer la simple
collecte des tests et lierait la suite à un `.env` non versionné. Le lancement
passe donc par la fabrique :

    uvicorn app.api.server:build_app --factory   # depuis `mcp/`

Il n'y a **pas** de middleware ASGI d'identité : sous le transport HTTP
streamable avec état, un `ContextVar` posé par une middleware reste figé sur le
premier appelant de la session (fail *open* démontré par
`tests/integration/test_sdk_http_context.py`). L'identité est rederivée à chaque
`list_tools`/`call_tool` par `GovernedFastMCP`, qui reçoit ici le vérificateur.
"""

from starlette.applications import Starlette

from app.api.governance import GovernedFastMCP
from app.api.tools.rag import register_rag_tools
from app.api.tools.sql import register_sql_tools
from app.dependencies import (
    build_audit_log,
    build_rag_port,
    build_sqlapi_port,
    build_text2sql_port,
    build_verifier,
    current_settings,
)
from app.infrastructure.matrix.yaml_loader import load_access_matrix


def build_server() -> GovernedFastMCP:
    """Assemble le serveur : matrice, journal, vérificateur, tools, adapters."""
    settings = current_settings()
    server = GovernedFastMCP(
        matrix=load_access_matrix(settings.access_matrix_file()),
        audit=build_audit_log(),
        verifier=build_verifier(settings),
        name="sorabel-data-gateway",
    )
    register_rag_tools(server, build_rag_port(settings))
    register_sql_tools(server, build_text2sql_port(settings), build_sqlapi_port(settings))
    return server


def build_app() -> Starlette:
    """Application ASGI complète : transport HTTP streamable (spec D2)."""
    return build_server().streamable_http_app()

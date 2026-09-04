"""Contexte d'un appel de tool, posé et défait par `GovernedFastMCP.call_tool`.

Portée : **l'intérieur d'un seul appel**. Ces variables sont renseignées juste
après la vérification du token de *cet* appel, puis réinitialisées à sa sortie.
Elles servent à la barrière 2 (`forward_to_backend`), qui doit connaître le
périmètre résolu par la matrice et le `correlation_id` à propager aux backends,
sans que ces valeurs transitent par la signature de chaque tool.

Elles ne sont **jamais** renseignées par une middleware ASGI, et l'identité n'est
jamais lue depuis une telle middleware. Sous le transport HTTP streamable avec
état, le groupe de tâches de la session est démarré depuis la requête qui ouvre
la session : anyio copie le contexte à ce point, et la tâche qui exécute *tous*
les messages suivants hérite du contexte de la requête `initialize`. Un contexte
posé par une middleware reste donc figé sur ce premier appelant, et quiconque
rejoue le `Mcp-Session-Id` avec un autre token — ou aucun — est servi avec
l'identité initiale : un fail **open**. Ce comportement est démontré, contre un
vrai serveur, par `tests/integration/test_sdk_http_context.py`.

L'identité est en conséquence rederivée à chaque `list_tools`/`call_tool`, en
vérifiant le token porté par la requête HTTP courante, atteinte via
`request_context.request` (cf. `app/api/governance.py`).
"""

from contextvars import ContextVar

from app.domain.models import Identity, Scope

# Identité de l'appel en cours, issue du token vérifié de la requête HTTP
# courante — posée par `GovernedFastMCP.call_tool`, jamais par une middleware.
current_identity: ContextVar[Identity | None] = ContextVar("current_identity", default=None)

# Corrélation de bout en bout (spec §8), reprise de l'en-tête `X-Correlation-Id`
# ou générée à l'entrée de l'appel.
current_correlation_id: ContextVar[str] = ContextVar("current_correlation_id", default="")

# Périmètre de données autorisé, résolu par la matrice — jamais choisi par
# l'appelant (barrière 2, spec §4.2).
current_scope: ContextVar[Scope | None] = ContextVar("current_scope", default=None)

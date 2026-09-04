"""Fixtures des scénarios d'acceptance par persona (tests/acceptance).

Ces tests assemblent le serveur exactement comme `build_server` (t13) le
ferait en production — même matrice réelle (`access_matrix.yaml`), mêmes 13
tools — seuls les trois ports backend sont remplacés par leurs doublures
(spec §9.2) : aucun accès réseau réel dans ces tests.

L'identité n'est **pas** injectée en posant directement `current_identity`
(cf. `app/api/context.py`) : `GovernedFastMCP` la rederive à *chaque* appel
depuis le token porté par la requête HTTP courante (`app/api/governance.py`,
§"Où l'identité est prise, et pourquoi"). Poser seulement ce `ContextVar`
laisserait `list_tools()`/`call_tool()` hors contexte de requête, donc
`UNAUTHENTICATED` quel que soit le profil visé — exactement le fail *open*
que cette architecture a été conçue pour empêcher côté middleware ASGI, mais
qui deviendrait ici un faux négatif de test si on le contournait.

Le harnais commun (`tests/unit/harness.py`) fournit ce que ces scénarios
doivent poser pour rester fidèles à ce mécanisme : un `TokenVerifierPort`
factice (jeton → profil) et une vraie requête Starlette portant l'en-tête
`Authorization`, réutilisées ici comme dans `tests/unit/test_governance.py`
et `tests/unit/test_tool_perimeter.py`.

`gateway(profile)` rend un gestionnaire de contexte plutôt qu'un serveur nu :
`appel_http` pose `request_ctx` (`mcp.server.lowlevel.server.request_ctx`,
un `ContextVar`) via un `Token` qui ne peut être consommé que dans le
`Context` où il a été créé. Un scénario doit donc ouvrir et fermer ce
contexte dans le **même** bloc `with`, à l'intérieur de sa propre coroutine —
l'ouvrir dans la fixture et le fermer via `request.addfinalizer` (ou même
une fixture asynchrone) franchit la frontière de tâche asyncio entre la mise
en place et le nettoyage, et la remise à zéro échoue
(`ValueError: ... was created in a different Context`), vérifié en pratique.
"""

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from io import StringIO
from pathlib import Path

import pytest
from app.api.governance import GovernedFastMCP
from app.api.tools.rag import register_rag_tools
from app.api.tools.sql import register_sql_tools
from app.infrastructure.audit.stdout_audit_log import StdoutAuditLog
from app.infrastructure.matrix.yaml_loader import load_access_matrix
from app.infrastructure.stub.rag_stub import RagStub
from app.infrastructure.stub.sqlapi_stub import SqlApiStub
from app.infrastructure.stub.text2sql_stub import Text2SqlStub

from tests.unit.harness import FakeTokenVerifier, appel_http
from tests.unit.harness import entetes as _entetes

MATRICE = Path(__file__).resolve().parents[2] / "access_matrix.yaml"

#: Corrélation fixe des scénarios — aucun n'en fait un sujet d'étude
#: (contrairement à `tests/unit/test_governance.py`).
CORRELATION = "corr-acceptance"


@pytest.fixture
def journal() -> StringIO:
    return StringIO()


@pytest.fixture
def gateway(
    journal: StringIO,
) -> Callable[[str | None], AbstractContextManager[GovernedFastMCP]]:
    """Assemble le serveur comme en production, pour un profil donné.

    `profile=None` simule un client sans token : aucun jeton n'est connu du
    vérificateur, et l'en-tête `Authorization` est absent de la requête
    posée. Pour un profil donné, un unique jeton (`jeton-<profil>`) lui est
    associé — ce que ferait Keycloak pour un client de ce profil.

    Usage dans un scénario : ``with gateway("support") as serveur: ...`` —
    le corps du `with` est la séquence d'appels du client pour ce persona.
    """

    @contextmanager
    def _construire(profile: str | None) -> Iterator[GovernedFastMCP]:
        token = None if profile is None else f"jeton-{profile}"
        verifier = FakeTokenVerifier({} if token is None else {token: profile})
        server = GovernedFastMCP(
            matrix=load_access_matrix(MATRICE),
            audit=StdoutAuditLog(stream=journal),
            verifier=verifier,
            name="sorabel-data-gateway",
        )
        register_rag_tools(server, RagStub())
        register_sql_tools(server, Text2SqlStub(), SqlApiStub())

        with appel_http(_entetes(token=token, correlation=CORRELATION)):
            yield server

    return _construire

"""Barrière 1 : la matrice d'accès est appliquée avant tout dispatch (spec §4.2).

`GovernedFastMCP` surcharge les deux points d'entrée du SDK :

- `list_tools()` ne renvoie que le sous-ensemble autorisé du profil appelant —
  catalogue vide sans authentification (spec §7.1) ;
- `call_tool()` refuse en `UNAUTHENTICATED` ou `UNAUTHORIZED_TOOL` **avant**
  d'atteindre la fonction du tool.

`list_resources`, `read_resource`, `list_prompts`, `get_prompt` et
`list_resource_templates` — les autres points d'entrée hérités de `FastMCP` —
ne sont **pas** gouvernés : aujourd'hui sans effet puisque rien n'est enregistré
sur ces primitives, mais la première ressource ou le premier prompt ajouté à ce
serveur contournerait la matrice d'accès sans passer par la barrière 1.
`tests/unit/test_governance.py::test_le_serveur_n_expose_ni_ressource_ni_prompt`
sert de garde-fou de non-régression pour ce point.

**Où l'identité est prise, et pourquoi.** Elle est rederivée à *chaque* appel,
en vérifiant le token porté par la requête HTTP courante, atteinte via
`self.get_context().request_context.request`. Elle n'est jamais mémorisée pour
la durée d'une session, ni posée par une middleware ASGI : sous le transport
HTTP streamable avec état, la tâche qui exécute tous les messages d'une session
hérite du contexte de la requête qui a ouvert cette session, si bien qu'un
`ContextVar` renseigné par une middleware reste figé sur le premier appelant.
Un tiers rejouant le `Mcp-Session-Id` avec son propre token — ou sans token —
serait alors servi avec l'identité initiale : un fail *open*, démontré contre un
vrai serveur par `tests/integration/test_sdk_http_context.py` et interdit ici par
`tests/integration/test_governed_http_session.py`.
"""

import asyncio
import time
import uuid
from collections.abc import Sequence
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolRequest, ContentBlock, ServerResult
from mcp.types import Tool as MCPTool
from starlette.requests import Request

from app.api.context import current_correlation_id, current_identity, current_scope
from app.application.use_cases.authorize_tool_call import authorize_tool_call
from app.application.use_cases.list_available_tools import list_available_tools
from app.domain.access_matrix import RULE_UNAUTHENTICATED, AccessMatrix, projection_rule
from app.domain.errors import InvalidTokenError, ToolError, UnauthenticatedError
from app.domain.models import AuditEntry, Identity
from app.domain.ports import AuditLogPort, TokenVerifierPort

#: Nom sous lequel la projection du catalogue est journalisée (spec §7.1 : les
#: appels `list_tools` sont journalisés au même titre que les `call_tool`).
LIST_TOOLS = "list_tools"

#: Suffixe distinguant, au journal, un `list_tools` déclenché par le SDK lui-même
#: (validation interne de la sortie d'un `tools/call`, cf. `_marquer_call_tool`)
#: d'un `list_tools` réellement demandé par le client.
LIST_TOOLS_INTERNAL = f"{LIST_TOOLS}:internal"

#: Code d'audit d'un appel autorisé interrompu par une annulation (déconnexion
#: client, par exemple) plutôt que par une erreur du tool. Jamais rendu au
#: client — `asyncio.CancelledError` est toujours re-levée telle quelle.
CANCELLED_ERROR_CODE = "CANCELLED"

# Marque, pour la durée du traitement bas niveau d'un `tools/call`, que tout
# `list_tools()` déclenché pendant cette fenêtre est interne au SDK (cache miss
# de validation de sortie) et non une requête `tools/list` du client — posé en
# enveloppant le handler bas niveau plutôt que le corps de `call_tool` ci-dessous,
# car le SDK résout ce cache *avant* d'invoquer `call_tool` (cf. `_marquer_call_tool`).
_call_tool_en_cours: ContextVar[bool] = ContextVar("call_tool_en_cours", default=False)


def _matrix_rule(error: ToolError) -> str:
    """Règle de matrice portée par l'erreur — jamais une recopie du code d'erreur."""
    return error.matrix_rule or ""


def _error_code(exception: BaseException) -> str:
    """Code d'erreur domaine d'un échec survenu *après* l'autorisation.

    Le SDK réenveloppe toute exception levée par un tool dans **sa** `ToolError`
    (`mcp.server.fastmcp.exceptions.ToolError`), sans rapport d'héritage avec
    celle du domaine : `str(exception)` n'est alors pas le corps JSON attendu, et
    l'erreur domaine n'est atteignable que par `__cause__`. On la récupère là,
    pour que l'appel autorisé qui échoue soit journalisé avec son vrai code (E5).
    """
    if isinstance(exception, ToolError):
        return exception.error_code
    cause = exception.__cause__
    if isinstance(cause, ToolError):
        return cause.error_code
    return ToolError.error_code


class GovernedFastMCP(FastMCP[Any]):
    """FastMCP appliquant la matrice d'accès avant tout dispatch (barrière 1)."""

    def __init__(
        self,
        *args: Any,
        matrix: AccessMatrix,
        audit: AuditLogPort,
        verifier: TokenVerifierPort,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._matrix = matrix
        self._audit = audit
        self._verifier = verifier
        self._marquer_call_tool()

    def _marquer_call_tool(self) -> None:
        """Enveloppe le handler bas niveau de `tools/call` pour poser `_call_tool_en_cours`.

        Le serveur bas niveau du SDK résout `_get_cached_tool_definition()` — qui
        appelle `list_tools()` sur cache miss (`_tool_cache`, global au processus)
        — **avant** d'invoquer `call_tool()` (`lowlevel/server.py:531`). Poser le
        marqueur dans le corps de `call_tool()` ci-dessous arriverait donc trop
        tard pour ce cas ; il doit couvrir tout le traitement du `tools/call`.
        """
        original = self._mcp_server.request_handlers[CallToolRequest]

        async def avec_marqueur(requete: CallToolRequest) -> ServerResult:
            jeton = _call_tool_en_cours.set(True)
            try:
                return await original(requete)
            finally:
                _call_tool_en_cours.reset(jeton)

        self._mcp_server.request_handlers[CallToolRequest] = avec_marqueur

    async def list_tools(self) -> list[MCPTool]:
        """Catalogue projeté sur le profil appelant — vide sans token valide."""
        requete = self._current_request()
        correlation_id = self._correlation_id(requete)
        debut = time.perf_counter()
        nom = LIST_TOOLS_INTERNAL if _call_tool_en_cours.get() else LIST_TOOLS

        try:
            identity = await self._authenticate(requete, correlation_id)
        except ToolError as refus:
            self._record(nom, {}, None, correlation_id, debut, error=refus)
            return []

        projection = list_available_tools(
            self._matrix, identity, await super().list_tools(), lambda outil: outil.name
        )
        self._record(
            nom,
            {},
            identity,
            correlation_id,
            debut,
            rule=projection_rule(identity.profile),
            allow=True,
            row_count=len(projection),
        )
        return projection

    async def list_all_tools(self) -> list[MCPTool]:
        """Catalogue complet, **sans filtrage** — usage interne et tests d'exhaustivité.

        Jamais exposé au protocole : `list_tools()` reste le seul point d'entrée
        du client, et il projette. Cette méthode sert à vérifier que le registre
        contient bien les 13 tools du catalogue, indépendamment de tout profil.
        """
        return await super().list_tools()

    async def call_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> Sequence[ContentBlock] | dict[str, Any]:
        """Autorise, dispatche, journalise — dans cet ordre, sans exception."""
        requete = self._current_request()
        correlation_id = self._correlation_id(requete)
        debut = time.perf_counter()

        identity: Identity | None = None
        try:
            identity = await self._authenticate(requete, correlation_id)
            allowed = authorize_tool_call(self._matrix, identity, name, correlation_id)
        except ToolError as refus:
            self._record(name, arguments, identity, correlation_id, debut, error=refus)
            raise

        jeton_identite = current_identity.set(identity)
        jeton_correlation = current_correlation_id.set(correlation_id)
        jeton_portee = current_scope.set(allowed.scope)
        try:
            resultat = await super().call_tool(name, arguments)
        except asyncio.CancelledError:
            # `CancelledError` hérite de `BaseException` (Python 3.8+), donc pas
            # de `except Exception` ci-dessous : sans cette clause dédiée, un
            # appel autorisé interrompu par une déconnexion ne laisserait aucune
            # trace au journal. L'annulation n'est jamais avalée : elle est
            # toujours re-levée telle quelle.
            self._record(
                name,
                arguments,
                identity,
                correlation_id,
                debut,
                rule=allowed.rule,
                allow=True,
                error_code=CANCELLED_ERROR_CODE,
            )
            raise
        except Exception as echec:
            # L'autorisation a été accordée : la décision journalisée reste
            # `allow`, complétée du code d'erreur domaine de l'échec.
            self._record(
                name,
                arguments,
                identity,
                correlation_id,
                debut,
                rule=allowed.rule,
                allow=True,
                error_code=_error_code(echec),
            )
            raise
        finally:
            current_scope.reset(jeton_portee)
            current_correlation_id.reset(jeton_correlation)
            current_identity.reset(jeton_identite)

        self._record(
            name, arguments, identity, correlation_id, debut, rule=allowed.rule, allow=True
        )
        return resultat

    def _current_request(self) -> Request | None:
        """Requête HTTP qui transporte *cet* appel, ou `None` hors contexte HTTP.

        `request_context` **lève** hors du cycle d'une requête (transport stdio,
        message hors requête) au lieu de rendre `None` : l'accès est donc gardé,
        et l'absence de requête devient un refus `UNAUTHENTICATED`, jamais un
        passage silencieux.
        """
        try:
            requete = self.get_context().request_context.request
        except (ValueError, LookupError):
            return None
        return requete if isinstance(requete, Request) else None

    def _correlation_id(self, requete: Request | None) -> str:
        """Corrélation reprise de l'appelant si elle existe, générée sinon."""
        if requete is not None:
            entete = requete.headers.get("x-correlation-id", "").strip()
            if entete:
                return entete
        return str(uuid.uuid4())

    async def _authenticate(self, requete: Request | None, correlation_id: str) -> Identity:
        """Identité de l'appel courant. Lève `UnauthenticatedError` en tout autre cas.

        `TokenVerifierPort.verify` est synchrone et fait de l'E/S réseau (JWKS sur
        cache expiré) : il est délégué à un thread pour ne pas bloquer la boucle
        d'événements.
        """
        if requete is None:
            raise UnauthenticatedError(correlation_id, matrix_rule=RULE_UNAUTHENTICATED)

        schema, _, token = requete.headers.get("authorization", "").partition(" ")
        if schema.lower() != "bearer" or not token.strip():
            raise UnauthenticatedError(correlation_id, matrix_rule=RULE_UNAUTHENTICATED)

        try:
            return await asyncio.to_thread(self._verifier.verify, token.strip())
        except InvalidTokenError as invalide:
            raise UnauthenticatedError(
                correlation_id, matrix_rule=RULE_UNAUTHENTICATED
            ) from invalide

    def _record(
        self,
        tool: str,
        arguments: dict[str, Any],
        identity: Identity | None,
        correlation_id: str,
        debut: float,
        *,
        error: ToolError | None = None,
        rule: str = "",
        allow: bool = False,
        error_code: str | None = None,
        row_count: int | None = None,
    ) -> None:
        """Une entrée de journal par appel, autorisé comme refusé (E5, spec §8).

        `rule` porte toujours la règle de matrice — celle de la décision quand
        l'appel est autorisé, celle transportée par `ToolError.matrix_rule` quand
        il est refusé. Jamais le code d'erreur, qui a sa propre colonne.

        Seuls la requête et des métadonnées sont journalisés : le résultat ne
        l'est jamais (`.claude/rules/security.md`).
        """
        self._audit.record(
            AuditEntry(
                timestamp=datetime.now(timezone.utc),
                correlation_id=correlation_id,
                subject=None if identity is None else identity.subject,
                profile=None if identity is None else identity.profile,
                tool=tool,
                arguments=arguments,
                decision="allow" if allow else "deny",
                rule=rule if error is None else _matrix_rule(error),
                row_count=row_count,
                latency_ms=int((time.perf_counter() - debut) * 1000),
                error_code=error.error_code if error is not None else error_code,
            )
        )

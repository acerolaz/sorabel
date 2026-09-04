"""Une session MCP rejouée avec un autre token ne peut pas emprunter la première identité.

La tâche 1 a démontré, contre un vrai serveur, que poser l'identité dans un
`ContextVar` depuis une middleware ASGI est **fail open** : sous le transport HTTP
streamable avec état, la tâche qui exécute tous les messages d'une session hérite du
contexte de la requête qui a ouvert cette session, si bien qu'un tiers rejouant le
`Mcp-Session-Id` avec son propre token — ou sans token — est servi avec l'identité
initiale (`tests/integration/test_sdk_http_context.py`).

Ce module est le garde-fou de non-régression correspondant : il rejoue exactement
cette attaque contre `GovernedFastMCP`, qui redérive l'identité à chaque appel.

Vrai serveur `uvicorn`, vraie socket, vrais tokens signés, appels JSON-RPC bruts —
le rejeu de session est précisément ce qu'un client MCP du SDK ne sait pas faire.
"""

import asyncio
import json
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe
from typing import Any

import httpx
import jwt
import uvicorn
from app.api.context import current_correlation_id, current_identity
from app.api.governance import GovernedFastMCP
from app.domain.access_matrix import AccessMatrix, ProfileEntry
from app.domain.errors import NotFoundInCorpusError
from app.domain.models import AuditEntry, Scope
from app.infrastructure.keycloak.local_key_verifier import LocalKeyTokenVerifier
from mcp.types import LATEST_PROTOCOL_VERSION

SECRET = token_urlsafe(32)
ISSUER = "https://idp.test/realms/sorabel"
AUDIENCE = "sorabel-mcp"
#: Tool réellement présent au catalogue — `decide` refuse tout nom hors catalogue.
TOOL = "search_documents"

#: Second tool du catalogue, dont la fonction échoue systématiquement : il sert à
#: éprouver, sur le fil, une erreur levée **pendant** le dispatch — chemin
#: distinct de celui de la barrière 1, et le seul que le SDK réenveloppe.
TOOL_EN_ECHEC = "lookup_by_reference"

#: Corrélation posée par le client sur l'appel en échec. Distincte de tout ce
#: que le serveur ou le tool fabriquent : la retrouver dans le corps d'erreur
#: prouve la reprise de l'en-tête, qu'une constante partagée ne prouverait pas.
CORRELATION_CLIENT = "corr-du-client-42"


class JournalEnMemoire:
    """Doublure du port d'audit : conserve les entrées au lieu de les écrire."""

    def __init__(self) -> None:
        self.entrees: list[AuditEntry] = []

    def record(self, entry: AuditEntry) -> None:
        self.entrees.append(entry)


def _matrice() -> AccessMatrix:
    """Deux profils distincts, tous deux autorisés sur le même tool.

    Autoriser les deux est délibéré : si l'identité fuitait d'une session à
    l'autre, l'appel de mallory réussirait quand même — c'est donc le *sujet*
    rendu par le tool qui trahit l'emprunt, pas un refus d'autorisation.
    """
    portee = Scope(
        rag_collections=("datasheet",), sql_tables=("products",), masked_columns=("margin",)
    )
    accordes = frozenset({TOOL, TOOL_EN_ECHEC})
    return AccessMatrix(
        version=1,
        profiles={
            "sales": ProfileEntry(tools=accordes, scope=portee),
            "dev": ProfileEntry(tools=accordes, scope=portee),
        },
    )


def _token(sujet: str, profil: str) -> str:
    """Token signé, par ailleurs entièrement valide, pour le sujet demandé."""
    return jwt.encode(
        {
            "sub": sujet,
            "sorabel_profile": profil,
            "iss": ISSUER,
            "aud": AUDIENCE,
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        SECRET,
        algorithm="HS256",
    )


def _port_libre() -> int:
    with socket.socket() as sonde:
        sonde.bind(("127.0.0.1", 0))
        return int(sonde.getsockname()[1])


@asynccontextmanager
async def serveur_gouverne() -> AsyncIterator[tuple[str, JournalEnMemoire]]:
    """`GovernedFastMCP` servi en HTTP streamable, sans aucune middleware d'identité."""
    journal = JournalEnMemoire()
    application = GovernedFastMCP(
        "gouvernance-http",
        matrix=_matrice(),
        audit=journal,
        verifier=LocalKeyTokenVerifier(secret=SECRET, issuer=ISSUER, audience=AUDIENCE),
    )

    @application.tool(name=TOOL)
    def qui_suis_je() -> str:
        """Rend le sujet que la gouvernance a reconnu pour *cet* appel."""
        identite = current_identity.get()
        return "<aucune identité>" if identite is None else identite.subject

    @application.tool(name=TOOL_EN_ECHEC)
    def hors_corpus() -> str:
        """Échoue toujours : le corpus ne contient pas la réponse (E1).

        Lève l'erreur domaine depuis la fonction du tool — donc *pendant* le
        dispatch, là où le SDK la réenveloppe — avec la corrélation que la
        barrière 1 a posée pour cet appel.
        """
        raise NotFoundInCorpusError(current_correlation_id.get())

    port = _port_libre()
    http = uvicorn.Server(
        uvicorn.Config(
            application.streamable_http_app(), host="127.0.0.1", port=port, log_level="critical"
        )
    )
    tache = asyncio.create_task(http.serve())
    async with asyncio.timeout(10):
        while not http.started:
            await asyncio.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}/mcp", journal
    finally:
        http.should_exit = True
        # Borné : un uvicorn qui ne rendrait pas la main bloquerait la suite du
        # run indéfiniment plutôt que de faire échouer seulement ce test.
        async with asyncio.timeout(10):
            await tache


async def _ouvre_session(client: httpx.AsyncClient, url: str, token: str) -> str:
    """Ouvre une session MCP avec ce token et rend son `Mcp-Session-Id`."""
    initialisation = await client.post(
        url,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": LATEST_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1.0"},
            },
        },
        headers=_entetes(token),
    )
    initialisation.raise_for_status()
    session_id = str(initialisation.headers["mcp-session-id"])
    pret = await client.post(
        url,
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers=_entetes(token, session_id=session_id),
    )
    pret.raise_for_status()
    return session_id


async def _appelle(
    client: httpx.AsyncClient,
    url: str,
    *,
    token: str | None,
    session_id: str,
    nom: str = TOOL,
    correlation: str | None = None,
) -> httpx.Response:
    """Appelle le tool en rejouant `session_id`, avec le token donné ou sans aucun."""
    entetes = _entetes(token, session_id=session_id)
    if correlation is not None:
        entetes["X-Correlation-Id"] = correlation
    reponse = await client.post(
        url,
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": nom, "arguments": {}},
        },
        headers=entetes,
    )
    reponse.raise_for_status()
    return reponse


async def test_une_session_rejouee_avec_un_autre_token_est_servie_sous_la_bonne_identite() -> None:
    """L'attaque de la tâche 1, rejouée contre la barrière 1 : elle doit échouer.

    Sans redérivation par appel, le tool rendrait `alice` alors que la requête
    porte le token de `mallory` — c'est exactement le fail open démontré en
    tâche 1, et c'est cette assertion qui interdit son retour.
    """
    async with serveur_gouverne() as (url, journal):
        # Arrange — alice ouvre une session et retient son identifiant
        async with httpx.AsyncClient(timeout=10) as client:
            session_id = await _ouvre_session(client, url, _token("alice", "sales"))
            depart = await _appelle(
                client, url, token=_token("alice", "sales"), session_id=session_id
            )

            # Act — mallory rejoue la session d'alice avec SON propre token
            emprunt = await _appelle(
                client, url, token=_token("mallory", "dev"), session_id=session_id
            )

    # Assert — alice reste alice sur son propre appel…
    assert _texte_du_resultat(depart.text) == "alice"
    # …et mallory est servie comme mallory, jamais comme alice.
    assert _texte_du_resultat(emprunt.text) == "mallory"

    # Assert — l'audit distingue les deux appelants (E5)
    appels = [entree for entree in journal.entrees if entree.tool == TOOL]
    assert [entree.subject for entree in appels] == ["alice", "mallory"]
    assert [entree.profile for entree in appels] == ["sales", "dev"]


async def test_une_session_rejouee_sans_token_est_refusee() -> None:
    """Rejouer une session ouverte par alice, sans en-tête, ne donne pas son identité.

    Le refus doit être `UNAUTHENTICATED` et non un service silencieux sous
    l'identité initiale ; il doit aussi être journalisé (spec §7.1).

    Arbitrage rendu sur le comportement suivant, constaté en écrivant ce test :
    le serveur bas niveau du SDK appelle `list_tools()` pour valider la sortie
    d'un `tools/call`, sur cache miss de `_tool_cache` (global au processus).
    Cet appel interne traverse la barrière 1 comme un autre et produit **sa
    propre** entrée d'audit — un `call_tool` laisse donc deux lignes au journal,
    pas une, mais seulement la première fois qu'un tool est appelé sur ce
    serveur. On garde les deux lignes (une barrière qui cesserait de journaliser
    certaines de ses décisions serait pire) mais on **marque** la ligne interne
    (`GovernedFastMCP._marquer_call_tool`) : sans ce marqueur, la même action
    cliente produirait une ou deux lignes indiscernables selon l'historique du
    serveur — le pire résultat possible pour une preuve d'audit E5.
    """
    async with serveur_gouverne() as (url, journal):
        # Arrange
        async with httpx.AsyncClient(timeout=10) as client:
            session_id = await _ouvre_session(client, url, _token("alice", "sales"))

            # Act — même session, plus aucun en-tête d'autorisation
            anonyme = await _appelle(client, url, token=None, session_id=session_id)

    # Assert — erreur typée, et surtout pas le sujet d'alice
    corps = _enveloppe(anonyme.text)
    assert "alice" not in anonyme.text
    assert _code_erreur(corps) == "UNAUTHENTICATED"

    # Assert — le refus est journalisé, sans identité (spec §7.1, E5), et la
    # ligne interne au SDK est reconnaissable de celle du client : si le
    # marquage disparaissait, `entree.tool` porterait deux fois `TOOL` (une
    # levée par `_get_cached_tool_definition`, une par l'appel client) au lieu
    # de `["list_tools:internal", TOOL]`.
    refus = [entree for entree in journal.entrees if entree.decision == "deny"]
    assert [entree.tool for entree in refus] == ["list_tools:internal", TOOL]
    assert all(entree.subject is None for entree in refus)
    assert all(entree.error_code == "UNAUTHENTICATED" for entree in refus)


async def test_une_erreur_levee_pendant_le_dispatch_arrive_structuree_sur_le_fil() -> None:
    """Les sept codes de la spec §7 atteignent le client sous la même forme.

    `UNAUTHENTICATED` et `UNAUTHORIZED_TOOL` sont levés par la barrière 1, avant
    tout dispatch, et remontent intacts au serveur bas niveau. Les cinq autres
    — dont `NOT_FOUND_IN_CORPUS`, éprouvé ici — naissent *dans* la fonction du
    tool et traversent `ToolManager.call_tool`, qui les réenveloppe dans la
    `ToolError` du SDK préfixée de `"Error executing tool <nom>: "`. Sans la
    reprise de `GovernedFastMCP.call_tool`, ce préfixe partirait sur le fil :
    `isError` resterait vrai, mais le contenu ne serait plus parsable en JSON —
    et le bot Slack recevrait, pour une question hors corpus, un texte anglais
    qu'un LLM peut paraphraser en réponse (E1). C'est ce que ce test interdit,
    au seul niveau où la réenveloppe est observable : le fil.
    """
    async with serveur_gouverne() as (url, journal):
        # Arrange — une session valide, ouverte par un profil autorisé sur les
        # deux tools : rien ici ne doit être refusé par la barrière 1.
        async with httpx.AsyncClient(timeout=10) as client:
            session_id = await _ouvre_session(client, url, _token("alice", "sales"))

            # Act — le tool autorisé échoue dans sa propre fonction
            reponse = await _appelle(
                client,
                url,
                token=_token("alice", "sales"),
                session_id=session_id,
                nom=TOOL_EN_ECHEC,
                correlation=CORRELATION_CLIENT,
            )

    # Assert — contenu strictement `{error_code, message, correlation_id}` et
    # `isError` (les deux sont vérifiés par `_code_erreur`), jamais le préfixe
    # narratif du SDK.
    corps = _enveloppe(reponse.text)
    assert "Error executing tool" not in reponse.text
    assert _code_erreur(corps) == "NOT_FOUND_IN_CORPUS"

    # Assert — la corrélation rendue est celle que *le client* a posée, reprise
    # par la barrière 1 puis propagée jusqu'à la fonction du tool.
    charge = json.loads(corps["result"]["content"][0]["text"])
    assert charge["correlation_id"] == CORRELATION_CLIENT

    # Assert — séquence d'audit réelle d'un `tools/call` : la ligne interne du
    # SDK (validation de sortie sur cache miss) précède celle de l'appel client,
    # qui reste `allow` — l'autorisation a bien été accordée — avec le vrai code
    # d'erreur (E5). C'est la séquence qu'un appel direct à `serveur.call_tool()`
    # ne produit pas (cf. spec §12, É10).
    assert [(entree.tool, entree.decision, entree.error_code) for entree in journal.entrees] == [
        ("list_tools:internal", "allow", None),
        (TOOL_EN_ECHEC, "allow", "NOT_FOUND_IN_CORPUS"),
    ]


def _entetes(token: str | None, *, session_id: str | None = None) -> dict[str, str]:
    """En-têtes d'un appel JSON-RPC brut ; `token=None` n'en pose aucun."""
    entetes = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": LATEST_PROTOCOL_VERSION,
    }
    if token is not None:
        entetes["Authorization"] = f"Bearer {token}"
    if session_id is not None:
        entetes["Mcp-Session-Id"] = session_id
    return entetes


def _enveloppe(charge: str) -> dict[str, Any]:
    """Enveloppe JSON-RPC d'une réponse, qu'elle soit rendue en JSON ou en SSE."""
    for ligne in charge.splitlines():
        if ligne.startswith("data:"):
            charge = ligne[len("data:") :].strip()
            break
    enveloppe: dict[str, Any] = json.loads(charge)
    return enveloppe


def _texte_du_resultat(charge: str) -> str:
    """Texte du premier bloc de contenu d'un appel réussi."""
    enveloppe = _enveloppe(charge)
    assert "error" not in enveloppe, enveloppe
    texte: str = enveloppe["result"]["content"][0]["text"]
    return texte


def _code_erreur(enveloppe: dict[str, Any]) -> str:
    """Code d'erreur domaine porté par le corps `{error_code, message, correlation_id}`.

    Quelle que soit la barrière qui l'a levée, l'erreur domaine atteint le
        serveur bas niveau du SDK intacte : la barrière 1 la lève avant tout
        dispatch, et `GovernedFastMCP.call_tool` la relève telle quelle quand elle
        naît pendant le dispatch (sans quoi le SDK la réenveloppe derrière un texte
        narratif). `str(exception)` — le JSON du domaine (`ToolError.__str__`, spec
        §7) — atterrit donc dans le premier bloc de contenu d'un `CallToolResult`
        marqué `isError`. On parse cette enveloppe et on vérifie sa structure,
        plutôt que de chercher une sous-chaîne dans le JSON brut (ce qui ne
        prouverait ni `isError`, ni la forme du corps).
    """
    resultat = enveloppe["result"]
    assert resultat["isError"] is True, enveloppe
    corps = json.loads(resultat["content"][0]["text"])
    assert set(corps) == {"error_code", "message", "correlation_id"}, corps
    return str(corps["error_code"])

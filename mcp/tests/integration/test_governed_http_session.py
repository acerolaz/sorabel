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
import pytest
import uvicorn
from app.api.context import current_identity
from app.api.governance import GovernedFastMCP
from app.domain.access_matrix import AccessMatrix, ProfileEntry
from app.domain.models import AuditEntry, Scope
from app.infrastructure.keycloak.local_key_verifier import LocalKeyTokenVerifier
from mcp.types import LATEST_PROTOCOL_VERSION

SECRET = token_urlsafe(32)
ISSUER = "https://idp.test/realms/sorabel"
AUDIENCE = "sorabel-mcp"
#: Tool réellement présent au catalogue — `decide` refuse tout nom hors catalogue.
TOOL = "search_documents"


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
    return AccessMatrix(
        version=1,
        profiles={
            "sales": ProfileEntry(tools=frozenset({TOOL}), scope=portee),
            "dev": ProfileEntry(tools=frozenset({TOOL}), scope=portee),
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
    client: httpx.AsyncClient, url: str, *, token: str | None, session_id: str
) -> httpx.Response:
    """Appelle le tool en rejouant `session_id`, avec le token donné ou sans aucun."""
    reponse = await client.post(
        url,
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": TOOL, "arguments": {}},
        },
        headers=_entetes(token, session_id=session_id),
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

    # Assert — la requête portait bien le token de mallory…
    assert emprunt.request.headers["authorization"].startswith("Bearer ")
    # …alice reste alice sur son propre appel…
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

    Note de comportement, constatée ici et non corrigée : le serveur bas niveau du
    SDK appelle `list_tools()` pour valider la sortie d'un `tools/call`. Cet appel
    interne traverse la barrière 1 comme un autre et produit **sa propre** entrée
    d'audit. Un `call_tool` laisse donc deux lignes au journal, pas une. Le test
    l'asserte tel quel plutôt que de le masquer — à arbitrer en revue.
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

    # Assert — le refus est journalisé, sans identité (spec §7.1, E5)
    refus = [entree for entree in journal.entrees if entree.decision == "deny"]
    assert [entree.tool for entree in refus] == ["list_tools", TOOL]
    assert all(entree.subject is None for entree in refus)
    assert all(entree.error_code == "UNAUTHENTICATED" for entree in refus)


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
    """Code d'erreur domaine, que le SDK rende une erreur JSON-RPC ou un `isError`.

    Le SDK réenveloppe l'exception du tool dans sa propre `ToolError` en préfixant
    le message : le corps JSON du domaine est donc extrait de ce message.
    """
    brut = json.dumps(enveloppe)
    debut = brut.find("UNAUTHENTICATED")
    if debut == -1:
        pytest.fail(f"aucun code d'erreur domaine dans la réponse : {brut}")
    return "UNAUTHENTICATED"

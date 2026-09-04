"""Comment un tool atteint-il l'en-tête `Authorization` de l'appel en cours ?

Question fondatrice pour la barrière 1 (tâche 10) : le serveur est monté sur le
transport HTTP streamable, où le message JSON-RPC est traité dans une tâche
appartenant au groupe de tâches de la *session*, pas à celui de la requête HTTP.

Ces tests sont joués contre un vrai serveur `uvicorn` sur une vraie socket, avec
un vrai client MCP du SDK — pas de monkeypatch, pas d'accès aux objets internes.
"""

import asyncio
import contextvars
import itertools
import json
import socket
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from typing import Any

import httpx
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server.fastmcp import FastMCP
from mcp.types import LATEST_PROTOCOL_VERSION, ContentBlock

AUTORISATION: contextvars.ContextVar[str] = contextvars.ContextVar(
    "autorisation", default="<absente>"
)


class ServeurTemoin(FastMCP):
    """Surcharge le point d'interception de la tâche 10 pour enregistrer ce qu'il voit."""

    vu_par_call_tool: tuple[str, str] = ("<jamais appelé>", "<jamais appelé>")

    async def call_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> Sequence[ContentBlock] | dict[str, Any]:
        """Enregistre (numéro de requête, en-tête Authorization) vus à l'interception."""
        requete = self.get_context().request_context.request
        if requete is None:
            self.vu_par_call_tool = ("<pas de requête HTTP>", "<pas de requête HTTP>")
        else:
            self.vu_par_call_tool = (
                str(requete.headers.get("x-seq")),
                str(requete.headers.get("authorization")),
            )
        return await super().call_tool(name, arguments)


def _port_libre() -> int:
    with socket.socket() as sonde:
        sonde.bind(("127.0.0.1", 0))
        return int(sonde.getsockname()[1])


@asynccontextmanager
async def serveur_mcp(*, stateless: bool = False) -> AsyncIterator[tuple[str, ServeurTemoin]]:
    """Un serveur MCP HTTP streamable derrière une middleware ASGI d'authentification.

    La middleware pose l'en-tête `Authorization` dans un `ContextVar` et numérote
    chaque requête HTTP entrante (`x-seq`), à partir de 1 et pour ce serveur seul :
    les tests peuvent donc dire *quelle* requête a fourni la valeur vue par le tool.
    """
    application = ServeurTemoin("smoke-http", stateless_http=stateless)

    @application.tool()
    def echo_contexte() -> str:
        return AUTORISATION.get()

    interne = application.streamable_http_app()
    sequence = itertools.count(1)

    async def middleware(scope: Any, receive: Any, send: Callable[..., Awaitable[None]]) -> None:
        if scope["type"] == "http":
            numero = next(sequence)
            scope = {**scope, "headers": [*scope["headers"], (b"x-seq", str(numero).encode())]}
            entetes = dict(scope["headers"])
            brut = entetes.get(b"authorization", b"").decode() or "<absente>"
            AUTORISATION.set(f"{brut}#req{numero}")
        await interne(scope, receive, send)

    port = _port_libre()
    http = uvicorn.Server(
        uvicorn.Config(middleware, host="127.0.0.1", port=port, log_level="critical")
    )
    tache = asyncio.create_task(http.serve())
    async with asyncio.timeout(10):
        while not http.started:
            await asyncio.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}/mcp", application
    finally:
        http.should_exit = True
        await tache


async def test_le_context_var_de_la_middleware_est_fige_sur_la_requete_d_initialisation() -> None:
    """Le ContextVar est bien visible du tool — mais il porte la *première* requête.

    Il est donc inutilisable pour autoriser un appel : dans une session longue, la
    valeur reste celle du token présenté à l'initialisation, même si l'appelant en
    présente un autre (ou aucun) ensuite.
    """
    async with serveur_mcp() as (url, application):
        # Arrange / Act — deux appels dans la même session MCP
        async with httpx.AsyncClient(headers={"Authorization": "Bearer alice"}) as client:
            async with streamable_http_client(url, http_client=client) as (lecture, ecriture, _):
                async with ClientSession(lecture, ecriture) as session:
                    await session.initialize()
                    premier = await session.call_tool("echo_contexte", {})
                    vu_au_premier_appel = application.vu_par_call_tool
                    second = await session.call_tool("echo_contexte", {})
                    vu_au_second_appel = application.vu_par_call_tool

    # Assert — le tool voit exactement la 1re requête HTTP du serveur, celle qui a
    # ouvert la session ; `initialize` est le premier POST reçu.
    texte_premier = premier.content[0].text  # type: ignore[union-attr]
    texte_second = second.content[0].text  # type: ignore[union-attr]
    assert texte_premier == "Bearer alice#req1"
    # …et cette valeur ne bouge pas, alors que chaque appel a bien été porté par une
    # requête HTTP distincte et postérieure.
    assert texte_second == "Bearer alice#req1"
    assert vu_au_premier_appel[0] != vu_au_second_appel[0]
    assert {vu_au_premier_appel[0], vu_au_second_appel[0]}.isdisjoint({"1"})


async def test_une_session_reutilisee_avec_un_autre_token_conserve_l_identite_initiale() -> None:
    """Le gel du ContextVar est exploitable : c'est un fail-**open**, pas un fail-closed.

    Un appelant qui rejoue le `Mcp-Session-Id` d'une session ouverte par quelqu'un
    d'autre, en présentant son propre token, obtient un tool qui voit l'identité du
    *premier*. C'est le fait de sécurité qui condamne « middleware ASGI + ContextVar »
    comme source de vérité pour l'autorisation.

    Tout est joué en JSON-RPC brut : le client du SDK ne permet pas de détourner le
    `Mcp-Session-Id` d'autrui, ce qui est précisément le geste à reproduire ici.
    """
    async with serveur_mcp() as (url, _):
        async with httpx.AsyncClient(timeout=10) as client:
            # Arrange — alice ouvre la session et en retient l'identifiant
            initialisation = await client.post(
                url,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": LATEST_PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {"name": "alice", "version": "1.0"},
                    },
                },
                headers=_entetes("Bearer alice"),
            )
            initialisation.raise_for_status()
            session_id = initialisation.headers["mcp-session-id"]
            pret = await client.post(
                url,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                headers=_entetes("Bearer alice", session_id=session_id),
            )
            pret.raise_for_status()

            # Act — mallory rejoue la session d'alice avec SON token
            appel = await client.post(
                url,
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "echo_contexte", "arguments": {}},
                },
                headers=_entetes("Bearer mallory", session_id=session_id),
            )
            appel.raise_for_status()

    # Assert — la requête portait bien le token de mallory, et le serveur l'a acceptée…
    assert appel.request.headers["authorization"] == "Bearer mallory"
    # …mais le tool a vu celui d'alice, capturé à l'ouverture de session.
    assert _texte_du_resultat(appel.text) == "Bearer alice#req1"


async def test_en_mode_stateless_le_context_var_suit_la_requete_de_l_appel() -> None:
    """`stateless_http=True` recrée une tâche par requête : le gel disparaît.

    Le constat des deux tests précédents vaut donc pour le mode **avec état**, qui est
    le défaut. Ce test borne la portée de ce constat plutôt que de le laisser croire
    universel — mais il ne rend pas le ContextVar recommandable pour autant : le
    mécanisme retenu (`request_context.request`) est correct dans les deux modes.
    """
    async with serveur_mcp(stateless=True) as (url, _):
        # Arrange / Act
        async with httpx.AsyncClient(headers={"Authorization": "Bearer alice"}) as client:
            async with streamable_http_client(url, http_client=client) as (lecture, ecriture, _):
                async with ClientSession(lecture, ecriture) as session:
                    await session.initialize()
                    premier = await session.call_tool("echo_contexte", {})
                    second = await session.call_tool("echo_contexte", {})

    # Assert — deux appels, deux numéros de requête distincts, aucun figé sur `#req1`
    texte_premier = premier.content[0].text  # type: ignore[union-attr]
    texte_second = second.content[0].text  # type: ignore[union-attr]
    assert texte_premier != texte_second
    assert texte_premier.startswith("Bearer alice#req")
    assert texte_second.startswith("Bearer alice#req")
    assert "Bearer alice#req1" not in {texte_premier, texte_second}


async def test_call_tool_atteint_la_requete_http_reelle_de_l_appel() -> None:
    """`self.get_context().request_context.request` porte, lui, la bonne requête.

    C'est le mécanisme utilisable par la barrière 1 : il donne les en-têtes de la
    requête HTTP qui transporte *cet* appel, et non ceux d'une requête antérieure.
    """
    async with serveur_mcp() as (url, application):
        # Arrange / Act
        async with httpx.AsyncClient(headers={"Authorization": "Bearer alice"}) as client:
            async with streamable_http_client(url, http_client=client) as (lecture, ecriture, _):
                async with ClientSession(lecture, ecriture) as session:
                    await session.initialize()
                    await session.call_tool("echo_contexte", {})
                    premier = application.vu_par_call_tool
                    await session.call_tool("echo_contexte", {})
                    second = application.vu_par_call_tool

    # Assert — l'en-tête Authorization est lisible à l'interception…
    assert premier[1] == "Bearer alice"
    assert second[1] == "Bearer alice"
    # …et il provient bien de deux requêtes HTTP distinctes et successives,
    # pas d'une valeur capturée une fois pour toutes à l'ouverture de session.
    assert premier[0].isdigit() and second[0].isdigit()
    assert int(second[0]) > int(premier[0])


def _entetes(token: str, *, session_id: str | None = None) -> dict[str, str]:
    """En-têtes d'un appel JSON-RPC brut sur le transport HTTP streamable."""
    entetes = {
        "Authorization": token,
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": LATEST_PROTOCOL_VERSION,
    }
    if session_id is not None:
        entetes["Mcp-Session-Id"] = session_id
    return entetes


def _texte_du_resultat(charge: str) -> str:
    """Extrait le texte du premier bloc de contenu, que la réponse soit JSON ou SSE."""
    for ligne in charge.splitlines():
        if ligne.startswith("data:"):
            charge = ligne[len("data:") :].strip()
            break
    enveloppe = json.loads(charge)
    assert "error" not in enveloppe, enveloppe
    texte: str = enveloppe["result"]["content"][0]["text"]
    return texte

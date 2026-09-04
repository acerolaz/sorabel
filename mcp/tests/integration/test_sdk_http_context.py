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
import socket
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from typing import Any

import httpx
import pytest_asyncio
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server.fastmcp import FastMCP
from mcp.types import ContentBlock

AUTORISATION: contextvars.ContextVar[str] = contextvars.ContextVar(
    "autorisation", default="<absente>"
)


class ServeurTemoin(FastMCP):
    """Surcharge le point d'interception de la tâche 10 pour enregistrer ce qu'il voit."""

    vu_par_call_tool: str = "<jamais appelé>"

    async def call_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> Sequence[ContentBlock] | dict[str, Any]:
        requete = self.get_context().request_context.request
        self.vu_par_call_tool = (
            "<pas de requête HTTP>" if requete is None else str(requete.headers.get("x-seq"))
        )
        return await super().call_tool(name, arguments)


def _port_libre() -> int:
    with socket.socket() as sonde:
        sonde.bind(("127.0.0.1", 0))
        return int(sonde.getsockname()[1])


@pytest_asyncio.fixture
async def serveur() -> AsyncIterator[tuple[str, ServeurTemoin]]:
    """Un serveur MCP HTTP streamable derrière une middleware ASGI d'authentification.

    La middleware pose l'en-tête `Authorization` dans un `ContextVar` et numérote
    chaque requête HTTP entrante (`x-seq`), afin que le test puisse dire *quelle*
    requête a fourni la valeur que voit le tool.
    """
    application = ServeurTemoin("smoke-http")

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
    while not http.started:
        await asyncio.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}/mcp", application
    finally:
        http.should_exit = True
        await tache


async def test_le_context_var_de_la_middleware_est_fige_a_l_ouverture_de_session(
    serveur: tuple[str, ServeurTemoin],
) -> None:
    """Le ContextVar est bien visible du tool — mais il porte la *première* requête.

    Il est donc inutilisable pour autoriser un appel : dans une session longue, la
    valeur reste celle du token présenté à l'initialisation, même si l'appelant en
    présente un autre (ou aucun) ensuite.
    """
    # Arrange
    url, application = serveur

    # Act — deux appels dans la même session MCP
    async with httpx.AsyncClient(headers={"Authorization": "Bearer alice"}) as client:
        async with streamable_http_client(url, http_client=client) as (lecture, ecriture, _):
            async with ClientSession(lecture, ecriture) as session:
                await session.initialize()
                premier = await session.call_tool("echo_contexte", {})
                vu_au_premier_appel = application.vu_par_call_tool
                second = await session.call_tool("echo_contexte", {})
                vu_au_second_appel = application.vu_par_call_tool

    # Assert — le tool voit une valeur (la propagation existe)…
    texte_premier = premier.content[0].text  # type: ignore[union-attr]
    texte_second = second.content[0].text  # type: ignore[union-attr]
    assert texte_premier.startswith("Bearer alice#req")
    # …mais c'est celle de la requête d'initialisation, identique aux deux appels,
    # alors que chaque appel a été porté par une requête HTTP distincte.
    assert texte_premier == texte_second
    assert vu_au_premier_appel != vu_au_second_appel
    assert texte_premier != f"Bearer alice#req{vu_au_premier_appel}"


async def test_call_tool_atteint_la_requete_http_reelle_de_l_appel(
    serveur: tuple[str, ServeurTemoin],
) -> None:
    """`self.get_context().request_context.request` porte, lui, la bonne requête.

    C'est le mécanisme utilisable par la barrière 1 : il donne les en-têtes de la
    requête HTTP qui transporte *cet* appel, et non ceux d'une requête antérieure.
    """
    # Arrange
    url, application = serveur

    # Act
    async with httpx.AsyncClient(headers={"Authorization": "Bearer alice"}) as client:
        async with streamable_http_client(url, http_client=client) as (lecture, ecriture, _):
            async with ClientSession(lecture, ecriture) as session:
                await session.initialize()
                await session.call_tool("echo_contexte", {})
                premier = application.vu_par_call_tool
                await session.call_tool("echo_contexte", {})
                second = application.vu_par_call_tool

    # Assert — deux requêtes HTTP distinctes, donc deux numéros distincts et croissants
    assert premier.isdigit() and second.isdigit()
    assert int(second) > int(premier)

"""Surface du SDK MCP sur laquelle repose la barrière 1 (tâche 10).

Ces tests ne vérifient pas du code du projet : ils verrouillent les hypothèses
faites sur le SDK. Si l'un d'eux casse lors d'une montée de version, la stratégie
d'interception doit être revue avant toute autre chose.
"""

import inspect
import json

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError


class ErreurDomaineFactice(Exception):
    """Tient le rôle d'une erreur métier typée de `app/domain/errors.py`."""


def test_fastmcp_expose_les_points_d_interception_du_design() -> None:
    # Arrange
    server = FastMCP("smoke")

    # Act / Assert — la barrière 1 surcharge ces deux méthodes (tâche 10)
    assert inspect.iscoroutinefunction(server.list_tools)
    assert inspect.iscoroutinefunction(server.call_tool)
    # Le transport HTTP streamable est le seul retenu (spec D2)
    assert callable(server.streamable_http_app)


async def test_call_tool_enveloppe_l_erreur_domaine_dans_un_tool_error() -> None:
    """Le SDK ne renvoie pas `isError` : il lève, et masque l'erreur d'origine.

    Conséquence pour la tâche 10 : `str(exception)` n'est pas le message métier
    et n'est pas du JSON parsable ; l'erreur domaine se récupère par `__cause__`.
    """
    # Arrange
    server = FastMCP("smoke")
    charge_utile = json.dumps({"error_code": "UNAUTHORIZED_TOOL"})

    @server.tool()
    def tool_qui_echoue() -> str:
        raise ErreurDomaineFactice(charge_utile)

    # Act
    with pytest.raises(ToolError) as capture:
        await server.call_tool("tool_qui_echoue", {})

    # Assert — le type qui sort est celui du SDK, pas celui du domaine
    assert not isinstance(capture.value, ErreurDomaineFactice)
    # le message d'origine est préservé, mais préfixé : il n'est plus parsable
    assert str(capture.value) == f"Error executing tool tool_qui_echoue: {charge_utile}"
    with pytest.raises(json.JSONDecodeError):
        json.loads(str(capture.value))
    # seul `__cause__` porte l'erreur domaine intacte
    assert isinstance(capture.value.__cause__, ErreurDomaineFactice)
    assert str(capture.value.__cause__) == charge_utile

"""Six scénarios de bout en bout, un par persona — la démonstration que la
gouvernance tient réellement (E1-E6), pas une redite des tests unitaires et
d'intégration existants.

Aucun accès réseau réel : les trois ports backend sont les doublures de
`app/infrastructure/stub/` (spec §9.2), branchées par la fixture `gateway`
de `conftest.py`. Le serveur, la matrice réelle et le journal d'audit sont,
eux, ceux de production.
"""

import json
from collections.abc import Callable
from contextlib import AbstractContextManager
from io import StringIO
from typing import Any

import pytest
from app.api.governance import GovernedFastMCP
from app.domain.errors import ToolError

Gateway = Callable[[str | None], AbstractContextManager[GovernedFastMCP]]


def lignes_journal(journal: StringIO) -> list[dict[str, Any]]:
    return [json.loads(ligne) for ligne in journal.getvalue().strip().splitlines() if ligne]


def corps_erreur(exc: BaseException) -> dict[str, Any]:
    """Corps JSON `{error_code, message, correlation_id}` porté par un refus.

    Barrière 1 (`UNAUTHENTICATED`, `UNAUTHORIZED_TOOL` — avant tout dispatch) :
    l'erreur domaine (`ToolError`) est levée telle quelle par `GovernedFastMCP`,
    `str(exc)` est déjà ce corps JSON. Un échec survenu *pendant* le dispatch
    (barrière 2, ou port qui tombe) est en revanche réenveloppé par le SDK
    dans **sa propre** `ToolError` (`mcp.server.fastmcp.exceptions.ToolError`,
    sans rapport d'héritage avec celle du domaine) : l'erreur domaine n'est
    alors atteignable que via `__cause__`, exactement le mécanisme documenté
    par `app/api/governance.py::_error_code`.
    """
    cause = exc.__cause__
    source: BaseException = cause if isinstance(cause, ToolError) else exc
    resultat: dict[str, Any] = json.loads(str(source))
    return resultat


async def test_bot_slack_support_ne_voit_que_ses_cinq_tools(
    gateway: Gateway, journal: StringIO
) -> None:
    # Arrange / Act
    with gateway("support") as serveur:
        catalogue = {tool.name for tool in await serveur.list_tools()}
        with pytest.raises(Exception) as refus:
            await serveur.call_tool("get_customer_order_history", {"customer_id": "C-1"})
        await serveur.call_tool("get_stock", {"product_ref": "REF-8842"})

    # Assert — E4 : le catalogue est la première défense ; E5 : tout est journalisé
    assert catalogue == {
        "search_documents",
        "lookup_by_reference",
        "ask_database",
        "get_stock",
        "get_order_status",
    }
    assert corps_erreur(refus.value)["error_code"] == "UNAUTHORIZED_TOOL"
    # Trois appels ont franchi la barrière 1 : le catalogue projeté (autorisé
    # — spec §7.1, `list_tools` est journalisé au même titre qu'un `call_tool`),
    # le tool refusé, puis le tool figé accordé.
    decisions = [ligne["decision"] for ligne in lignes_journal(journal)]
    assert decisions == ["allow", "deny", "allow"]


async def test_poste_de_vente_recoit_des_citations_sans_texte_redige(
    gateway: Gateway, journal: StringIO
) -> None:
    # Arrange / Act
    with gateway("sales") as serveur:
        resultat = await serveur.call_tool("answer_question", {"query": "tension de REF-8842 ?"})

    # Assert — E1 : des sources, jamais une réponse rédigée par le serveur
    rendu = json.dumps(resultat, default=str)
    assert "citations" in rendu
    assert "REF-8842" in rendu
    assert "La tension nominale est" not in rendu  # aucun texte rédigé ne transite


async def test_ide_dev_execute_du_sql_mais_ne_peut_pas_en_generer(
    gateway: Gateway, journal: StringIO
) -> None:
    # Arrange / Act
    with gateway("dev") as serveur:
        catalogue = {tool.name for tool in await serveur.list_tools()}
        await serveur.call_tool("run_sql_query", {"sql": "SELECT 1", "profile": "dev"})
        with pytest.raises(Exception) as refus:
            await serveur.call_tool("ask_database", {"question": "stock ?", "profile": "dev"})

    # Assert — l'invisibilité n'est pas la seule protection : l'appel forcé est refusé
    assert "run_sql_query" in catalogue
    assert "ask_database" not in catalogue
    assert corps_erreur(refus.value)["error_code"] == "UNAUTHORIZED_TOOL"


async def test_une_question_hors_corpus_est_une_erreur_typee(
    gateway: Gateway, journal: StringIO
) -> None:
    # Arrange / Act
    with gateway("sales") as serveur:
        with pytest.raises(Exception) as refus:
            await serveur.call_tool("answer_question", {"query": "information absente du corpus"})

    # Assert — E1 : jamais une réponse plausible de substitution
    assert corps_erreur(refus.value)["error_code"] == "NOT_FOUND_IN_CORPUS"


async def test_un_appel_sans_token_ne_voit_rien_et_ne_peut_rien(
    gateway: Gateway, journal: StringIO
) -> None:
    # Arrange / Act
    with gateway(None) as serveur:
        catalogue = await serveur.list_tools()
        with pytest.raises(Exception) as refus:
            await serveur.call_tool("get_stock", {"product_ref": "REF-8842"})

    # Assert
    assert catalogue == []
    assert corps_erreur(refus.value)["error_code"] == "UNAUTHENTICATED"
    assert lignes_journal(journal)[0]["decision"] == "deny"


async def test_un_backend_injoignable_donne_une_erreur_typee(
    gateway: Gateway, journal: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — le port RAG tombe en panne réseau
    from app.domain.errors import BackendUnavailableError

    async def tombe(*args: object, **kwargs: object) -> dict[str, Any]:
        raise BackendUnavailableError("corr-acceptance")

    monkeypatch.setattr("app.infrastructure.stub.rag_stub.RagStub.answer", tombe)

    # Act
    with gateway("sales") as serveur:
        with pytest.raises(Exception) as refus:
            await serveur.call_tool("answer_question", {"query": "tension ?"})

    # Assert — le client reçoit un code stable, pas une trace d'exception
    charge = corps_erreur(refus.value)
    assert charge["error_code"] == "BACKEND_UNAVAILABLE"
    assert "Traceback" not in charge["message"]

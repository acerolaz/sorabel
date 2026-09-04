"""Sept scénarios de bout en bout, un par persona — la démonstration que la
gouvernance de `mcp` tient réellement, pour les exigences qu'elle porte
elle-même : E1 (chaque réponse documentaire s'appuie sur des citations,
jamais une rédaction transitant par le serveur ; refus explicite
`NOT_FOUND_IN_CORPUS` hors corpus), E4 (un catalogue de tools projeté par
profil — barrière 1 — et un périmètre documentaire/SQL résolu depuis la
matrice, jamais depuis la demande du client — barrière 2) et E5 côté audit
(tout appel, autorisé ou refusé, est journalisé avec son identité, son
profil, le tool visé et la décision).

E6 (le gain mesuré du retrieval hybride + reranking) est évalué côté
`rag-hybride`, sur son propre corpus — rien à en démontrer ici. Le masquage
de colonnes (volet SQL de E5) est transmis par `mcp` au backend d'exécution
(`scope.masked_columns`) mais son application n'est démontrée par aucun
scénario de ce fichier : `mcp` ne fait que le relayer, `sorabelsql-api`
l'applique.

Aucun accès réseau réel : les trois ports backend sont les doublures de
`app/infrastructure/stub/` (spec §9.2), branchées par la fixture `gateway`
de `conftest.py`. Le serveur, la matrice réelle et le journal d'audit sont,
eux, ceux de production.
"""

import json
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from io import StringIO
from typing import Any

import pytest
from app.api.governance import GovernedFastMCP
from app.domain.errors import ToolError
from app.infrastructure.stub.rag_stub import CITATION, RagStub

from tests.acceptance.conftest import CORRELATION

Gateway = Callable[[str | None], AbstractContextManager[GovernedFastMCP]]

#: Rédaction que le backend `rag-hybride` peut renvoyer et que la projection
#: D6 de `answer_question` doit écarter (cf. `TEXTE_REDIGE` de
#: `tests/unit/test_answer_question_composite.py`, même convention).
TEXTE_REDIGE = "La tension nominale de la REF-8842 est de 230 volts."

#: Champs exacts d'une ligne de journal (spec §8, `AuditEntry`). Écrits ici en
#: toutes lettres, jamais dérivés de la dataclasse : c'est justement l'ajout
#: d'un champ — un résultat métier, interdit par `.claude/rules/security.md` —
#: que cette liste doit faire échouer, et une dérivation l'accepterait sans rien
#: dire. Le retrait d'un champ tombe ici tout autant.
CHAMPS_JOURNAL = {
    "timestamp",
    "correlation_id",
    "subject",
    "profile",
    "tool",
    "arguments",
    "decision",
    "rule",
    "backend",
    "row_count",
    "latency_ms",
    "error_code",
}


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
    # le tool refusé, puis le tool figé accordé. Sur les couples (tool, decision)
    # plutôt que la seule colonne `decision` : une montée de version du SDK qui
    # ajouterait des lignes internes, ou une régression qui déplacerait un refus
    # sur le mauvais tool, ferait tomber cette assertion pour la bonne raison.
    lignes = lignes_journal(journal)
    assert [(ligne["tool"], ligne["decision"]) for ligne in lignes] == [
        ("list_tools", "allow"),
        ("get_customer_order_history", "deny"),
        ("get_stock", "allow"),
    ]
    # E5 : chaque ligne porte l'identité et le profil de l'appelant…
    assert all(ligne["subject"] == "sujet-jeton-support" for ligne in lignes)
    assert all(ligne["profile"] == "support" for ligne in lignes)
    # …et rien d'autre que les champs de la spec §8 : y ajouter un résultat
    # métier (interdit par `.claude/rules/security.md`) fait tomber ceci.
    assert all(set(ligne) == CHAMPS_JOURNAL for ligne in lignes)

    # E5, spec §8 : `backend` et `row_count` sont renseignés sur un `call_tool`,
    # pas seulement déclarés. `backend` vient du catalogue — il est donc connu
    # même d'un appel refusé, et vaut `None` pour ce qui ne vise aucun service en
    # aval (`list_tools`). `row_count` est la *seule* chose retenue du résultat :
    # 1 ligne pour le stock rendu, et `None` — jamais un zéro fabriqué — pour un
    # appel qui n'a rendu aucune ligne.
    par_tool = {ligne["tool"]: ligne for ligne in lignes}
    assert par_tool["get_stock"]["backend"] == "sqlapi"
    assert par_tool["get_stock"]["row_count"] == 1
    assert par_tool["get_customer_order_history"]["backend"] == "sqlapi"
    assert par_tool["get_customer_order_history"]["row_count"] is None
    assert par_tool["list_tools"]["backend"] is None


async def test_poste_de_vente_recoit_des_citations_sans_texte_redige(
    gateway: Gateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — le backend RAG rédige une réponse ; la projection D6 de
    # `answer_question` doit l'écarter et ne relayer que les sources.
    reponse_originale = RagStub.answer

    async def redige_une_reponse(
        self: RagStub, query: str, collections: Sequence[str], correlation_id: str
    ) -> dict[str, Any]:
        reponse = await reponse_originale(self, query, collections, correlation_id)
        return {**reponse, "answer": TEXTE_REDIGE}

    monkeypatch.setattr(RagStub, "answer", redige_une_reponse)

    # Act
    with gateway("sales") as serveur:
        resultat = await serveur.call_tool("answer_question", {"query": "tension de REF-8842 ?"})

    # Assert — E1 : jamais la rédaction du backend, quand bien même il en
    # fournirait une (vérifié en premier : si la projection D6 disparaît, la
    # réponse rendue change aussi de forme, et une assertion structurelle sur
    # les citations échouerait alors pour une mauvaise raison — `KeyError`
    # plutôt que la fuite de rédaction réellement visée par ce scénario).
    rendu = json.dumps(resultat, default=str)
    assert TEXTE_REDIGE not in rendu
    # ...et des citations réelles transitent bel et bien.
    _, corps = resultat
    citations = corps["sources"]["citations"]
    assert citations, "aucune citation dans la réponse rendue"
    assert citations[0]["doc_id"] == CITATION["doc_id"]


async def test_support_ne_voit_que_son_perimetre_documentaire(gateway: Gateway) -> None:
    # Arrange / Act
    with gateway("support") as serveur:
        resultat = await serveur.call_tool("search_documents", {"query": "procédure de retour"})

    # Assert — barrière 2 : le périmètre transmis au backend est celui du
    # profil (`rag_collections: [procedure_sav, manuel]`), jamais l'intégralité
    # des collections de la matrice (`sales` y ajoute `datasheet`).
    _, corps = resultat
    assert set(corps["collections"]) == {"procedure_sav", "manuel"}
    assert "datasheet" not in corps["collections"]


async def test_ide_dev_execute_du_sql_mais_ne_peut_pas_en_generer(gateway: Gateway) -> None:
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
    # E5 : l'autorisation a été accordée (barrière 1 franchie), l'échec vient
    # du backend — la ligne de journal doit porter `allow` et le vrai code
    # d'erreur, jamais un `deny` ni un code générique. Supprimer le bloc
    # `except Exception` d'audit de `governance.py` laisserait cet appel
    # autorisé-puis-en-échec disparaître du journal sans qu'aucune autre
    # assertion de ce fichier ne le voie.
    lignes = lignes_journal(journal)
    assert [(ligne["tool"], ligne["decision"]) for ligne in lignes] == [
        ("answer_question", "allow")
    ]
    assert lignes[0]["error_code"] == "NOT_FOUND_IN_CORPUS"


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
    # E5 : le `list_tools` à vide ET le `call_tool` refusé sont chacun une
    # ligne de journal — `list_tools()[0]` seul laisserait passer la
    # disparition de la seconde ligne (le refus du `call_tool` lui-même).
    lignes = lignes_journal(journal)
    assert [(ligne["tool"], ligne["decision"]) for ligne in lignes] == [
        ("list_tools", "deny"),
        ("get_stock", "deny"),
    ]
    assert all(ligne["error_code"] == "UNAUTHENTICATED" for ligne in lignes)
    assert all(ligne["subject"] is None and ligne["profile"] is None for ligne in lignes)


async def test_un_backend_injoignable_donne_une_erreur_typee(
    gateway: Gateway, journal: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — le port RAG tombe en panne réseau
    from app.domain.errors import BackendUnavailableError

    async def tombe(*args: object, **kwargs: object) -> dict[str, Any]:
        raise BackendUnavailableError(CORRELATION)

    monkeypatch.setattr("app.infrastructure.stub.rag_stub.RagStub.answer", tombe)

    # Act
    with gateway("sales") as serveur:
        with pytest.raises(Exception) as refus:
            await serveur.call_tool("answer_question", {"query": "tension ?"})

    # Assert — le client reçoit le corps d'erreur uniforme complet, pas une trace
    charge = corps_erreur(refus.value)
    assert charge["error_code"] == "BACKEND_UNAVAILABLE"
    assert set(charge) == {"error_code", "message", "correlation_id"}
    assert charge["correlation_id"] == CORRELATION
    # E5 : même exigence que le scénario hors-corpus — appel autorisé, échec
    # de backend, la ligne doit porter `allow` et le code réel.
    lignes = lignes_journal(journal)
    assert [(ligne["tool"], ligne["decision"]) for ligne in lignes] == [
        ("answer_question", "allow")
    ]
    assert lignes[0]["error_code"] == "BACKEND_UNAVAILABLE"

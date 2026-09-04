"""Barrière 1 : un tool non autorisé n'est ni listé, ni dispatché (spec §4.2, §7.1, §8).

Ces tests pilotent `GovernedFastMCP` en posant le contexte de requête du SDK
(`request_ctx`) exactement comme le fait le serveur bas niveau : l'identité doit
donc être dérivée de l'en-tête `Authorization` de *cette* requête, à chaque appel.
Seuls des ports sont doublés (`AuditLogPort`, `TokenVerifierPort`) — par les
doubles de `tests/harness.py`, unique copie du harnais.
"""

import asyncio
import json
import threading
import uuid
from typing import Any

import pytest
from app.api.context import current_correlation_id, current_scope
from app.api.governance import GovernedFastMCP
from app.domain.access_matrix import AccessMatrix, ProfileEntry
from app.domain.errors import NotFoundInCorpusError, ToolError
from app.domain.models import Scope
from mcp.server.fastmcp.exceptions import ToolError as SdkToolError

from tests.harness import CORRELATION, FakeAuditLog, FakeTokenVerifier, appel_http
from tests.harness import entetes as _entetes

PORTEE_SUPPORT = Scope(("manuels",), ("stock",), ("marge",))
PORTEE_VENDEUR = Scope(("fiches",), ("commandes",), ())


class ServeurSousTest(GovernedFastMCP):
    """Serveur de test exposant quatre tools et comptant leurs dispatches réels."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.dispatches: list[str] = []
        self.contexte_vu: list[tuple[str, Scope | None]] = []

        @self.tool()
        def get_stock(product_ref: str) -> dict[str, object]:
            """Stock d'une référence."""
            self.dispatches.append(f"get_stock:{product_ref}")
            self.contexte_vu.append((current_correlation_id.get(), current_scope.get()))
            return {"product_ref": product_ref, "quantity": 7}

        @self.tool()
        def get_query_history(profile: str) -> dict[str, object]:
            """Historique des requêtes."""
            self.dispatches.append("get_query_history")
            return {"items": []}

        @self.tool()
        def get_order_status(order_id: str) -> dict[str, object]:
            """Statut d'une commande — échoue systématiquement, hors corpus."""
            self.dispatches.append("get_order_status")
            raise NotFoundInCorpusError("corr-du-tool")

        @self.tool()
        def get_schema_info() -> dict[str, object]:
            """Schéma accessible — simule une déconnexion client en cours de dispatch.

            `tools/base.py:116` du SDK n'attrape que `except Exception` : une
            `asyncio.CancelledError` levée ici (héritant de `BaseException`
            depuis Python 3.8) le traverse sans être réenveloppée, exactement
            comme une vraie annulation le ferait.
            """
            self.dispatches.append("get_schema_info")
            raise asyncio.CancelledError()


@pytest.fixture
def matrix() -> AccessMatrix:
    return AccessMatrix(
        version=1,
        profiles={
            "support": ProfileEntry(
                tools=frozenset({"get_stock", "get_order_status", "get_schema_info"}),
                scope=PORTEE_SUPPORT,
            ),
            "vendeur": ProfileEntry(tools=frozenset({"get_query_history"}), scope=PORTEE_VENDEUR),
        },
    )


@pytest.fixture
def audit() -> FakeAuditLog:
    return FakeAuditLog()


@pytest.fixture
def verifier() -> FakeTokenVerifier:
    return FakeTokenVerifier({"jeton-alice": "support", "jeton-mallory": "vendeur"})


@pytest.fixture
def serveur(
    matrix: AccessMatrix, audit: FakeAuditLog, verifier: FakeTokenVerifier
) -> ServeurSousTest:
    return ServeurSousTest(matrix=matrix, audit=audit, verifier=verifier, name="test")


async def test_list_tools_ne_renvoie_que_les_tools_du_profil(serveur: ServeurSousTest) -> None:
    # Arrange / Act
    with appel_http(_entetes("jeton-alice")):
        outils = await serveur.list_tools()

    # Assert — la projection est exactement le sous-ensemble du profil `support`
    assert [outil.name for outil in outils] == ["get_stock", "get_order_status", "get_schema_info"]


async def test_list_tools_projette_selon_le_token_de_la_requete_courante(
    serveur: ServeurSousTest,
) -> None:
    # Arrange / Act — deux requêtes successives, deux porteurs différents
    with appel_http(_entetes("jeton-alice")):
        vus_par_alice = [outil.name for outil in await serveur.list_tools()]
    with appel_http(_entetes("jeton-mallory")):
        vus_par_mallory = [outil.name for outil in await serveur.list_tools()]

    # Assert
    assert vus_par_alice == ["get_stock", "get_order_status", "get_schema_info"]
    assert vus_par_mallory == ["get_query_history"]


async def test_list_tools_est_vide_sans_authentification(
    serveur: ServeurSousTest, audit: FakeAuditLog
) -> None:
    # Arrange / Act — aucun en-tête Authorization
    with appel_http(_entetes(token=None)):
        outils = await serveur.list_tools()

    # Assert — catalogue vide (spec §7.1) et événement journalisé
    assert outils == []
    assert [(e.tool, e.decision, e.error_code, e.rule) for e in audit.entrees] == [
        ("list_tools", "deny", "UNAUTHENTICATED", "fail_closed:unauthenticated")
    ]


async def test_list_tools_autorise_est_journalise_avec_la_regle_et_le_row_count(
    serveur: ServeurSousTest, audit: FakeAuditLog
) -> None:
    # Arrange / Act
    with appel_http(_entetes("jeton-alice")):
        outils = await serveur.list_tools()

    # Assert — la projection est journalisée comme un appel autorisé (spec §7.1,
    # §8) : si `list_tools` cessait de journaliser son succès, ceci tomberait.
    (entree,) = audit.entrees
    assert entree.decision == "allow"
    assert entree.rule == "projection:support"
    assert entree.row_count == len(outils) == 3


async def test_list_tools_est_vide_hors_contexte_de_requete(
    serveur: ServeurSousTest, audit: FakeAuditLog
) -> None:
    # Arrange / Act — `request_context` lève hors requête : la garde doit tenir
    outils = await serveur.list_tools()

    # Assert
    assert outils == []
    assert [entree.error_code for entree in audit.entrees] == ["UNAUTHENTICATED"]


async def test_un_tool_autorise_est_bien_dispatche(serveur: ServeurSousTest) -> None:
    # Arrange / Act
    with appel_http(_entetes("jeton-alice")):
        await serveur.call_tool("get_stock", {"product_ref": "REF-8842"})

    # Assert
    assert serveur.dispatches == ["get_stock:REF-8842"]


async def test_un_tool_interdit_est_refuse_avant_tout_dispatch(serveur: ServeurSousTest) -> None:
    # Arrange / Act
    with appel_http(_entetes("jeton-alice")):
        with pytest.raises(ToolError) as capture:
            await serveur.call_tool("get_query_history", {"profile": "support"})

    # Assert — erreur typée, et la fonction du tool n'a jamais été atteinte
    assert json.loads(str(capture.value))["error_code"] == "UNAUTHORIZED_TOOL"
    assert serveur.dispatches == []


async def test_un_tool_inconnu_rend_le_meme_refus_qu_un_tool_interdit(
    serveur: ServeurSousTest,
) -> None:
    # Arrange / Act
    with appel_http(_entetes("jeton-alice")):
        with pytest.raises(ToolError) as capture:
            await serveur.call_tool("tool_inexistant", {})

    # Assert — un refus ne confirme jamais l'existence d'une ressource
    assert json.loads(str(capture.value))["error_code"] == "UNAUTHORIZED_TOOL"


async def test_un_appel_sans_token_est_refuse(
    serveur: ServeurSousTest, audit: FakeAuditLog
) -> None:
    # Arrange / Act
    with appel_http(_entetes(token=None)):
        with pytest.raises(ToolError) as capture:
            await serveur.call_tool("get_stock", {"product_ref": "REF-8842"})

    # Assert
    assert json.loads(str(capture.value))["error_code"] == "UNAUTHENTICATED"
    assert serveur.dispatches == []
    # …et la ligne d'audit porte la règle dédiée, pas une chaîne vide : si les
    # trois levées d'`UnauthenticatedError` de `_authenticate` perdaient leur
    # `matrix_rule`, `entree.rule` retomberait à `""`.
    (entree,) = audit.entrees
    assert entree.rule == "fail_closed:unauthenticated"


async def test_un_token_invalide_est_refuse(serveur: ServeurSousTest) -> None:
    # Arrange / Act
    with appel_http(_entetes("jeton-inconnu")):
        with pytest.raises(ToolError) as capture:
            await serveur.call_tool("get_stock", {"product_ref": "REF-8842"})

    # Assert
    assert json.loads(str(capture.value))["error_code"] == "UNAUTHENTICATED"
    assert serveur.dispatches == []


async def test_un_appel_hors_contexte_de_requete_est_refuse(serveur: ServeurSousTest) -> None:
    # Arrange / Act — aucun `request_ctx` posé : `request_context` lève
    with pytest.raises(ToolError) as capture:
        await serveur.call_tool("get_stock", {"product_ref": "REF-8842"})

    # Assert — refus typé, pas une `ValueError` du SDK qui remonterait telle quelle
    assert json.loads(str(capture.value))["error_code"] == "UNAUTHENTICATED"
    assert serveur.dispatches == []


async def test_l_identite_est_verifiee_a_chaque_appel(
    serveur: ServeurSousTest, verifier: FakeTokenVerifier
) -> None:
    # Arrange / Act — deux appels successifs, deux porteurs différents
    with appel_http(_entetes("jeton-alice")):
        await serveur.call_tool("get_stock", {"product_ref": "REF-1"})
    with appel_http(_entetes("jeton-mallory")):
        with pytest.raises(ToolError) as capture:
            await serveur.call_tool("get_stock", {"product_ref": "REF-2"})

    # Assert — le token du second appel a bien été vérifié et a décidé du refus
    assert verifier.jetons_vus == ["jeton-alice", "jeton-mallory"]
    assert json.loads(str(capture.value))["error_code"] == "UNAUTHORIZED_TOOL"
    assert serveur.dispatches == ["get_stock:REF-1"]


async def test_la_verification_du_token_ne_bloque_pas_la_boucle_d_evenements(
    serveur: ServeurSousTest, verifier: FakeTokenVerifier
) -> None:
    # Arrange
    fil_principal = threading.current_thread().name

    # Act
    with appel_http(_entetes("jeton-alice")):
        await serveur.call_tool("get_stock", {"product_ref": "REF-8842"})

    # Assert — `verify` est synchrone et fait de l'E/S : il est délégué à un thread
    assert verifier.fils_d_execution
    assert fil_principal not in verifier.fils_d_execution


async def test_la_correlation_et_la_portee_sont_disponibles_pendant_le_dispatch(
    serveur: ServeurSousTest,
) -> None:
    # Arrange / Act
    with appel_http(_entetes("jeton-alice", correlation="corr-42")):
        await serveur.call_tool("get_stock", {"product_ref": "REF-8842"})

    # Assert — la barrière 2 lira la portée résolue par la matrice, jamais l'appelant
    assert serveur.contexte_vu == [("corr-42", PORTEE_SUPPORT)]
    # …et le contexte ne survit pas à l'appel
    assert current_scope.get() is None


async def test_chaque_appel_est_journalise_autorise_comme_refuse(
    serveur: ServeurSousTest, audit: FakeAuditLog
) -> None:
    # Arrange / Act
    with appel_http(_entetes("jeton-alice")):
        await serveur.call_tool("get_stock", {"product_ref": "REF-8842"})
        with pytest.raises(ToolError):
            await serveur.call_tool("get_query_history", {"profile": "support"})

    # Assert
    autorise, refuse = audit.entrees
    assert (autorise.decision, autorise.error_code) == ("allow", None)
    assert (autorise.tool, autorise.arguments) == ("get_stock", {"product_ref": "REF-8842"})
    assert (autorise.subject, autorise.profile) == ("sujet-jeton-alice", "support")
    assert autorise.correlation_id == CORRELATION
    assert autorise.latency_ms is not None and autorise.latency_ms >= 0
    assert (refuse.decision, refuse.error_code) == ("deny", "UNAUTHORIZED_TOOL")
    assert refuse.correlation_id == CORRELATION


async def test_le_journal_porte_la_regle_de_matrice_et_non_le_code_d_erreur(
    serveur: ServeurSousTest, audit: FakeAuditLog
) -> None:
    # Arrange / Act
    with appel_http(_entetes("jeton-alice")):
        await serveur.call_tool("get_stock", {"product_ref": "REF-8842"})
        with pytest.raises(ToolError):
            await serveur.call_tool("get_query_history", {"profile": "support"})
        with pytest.raises(ToolError):
            await serveur.call_tool("tool_inexistant", {})

    # Assert — `rule` distingue les cas que le code d'erreur confond volontairement
    assert [entree.rule for entree in audit.entrees] == [
        "matrix:support:get_stock",
        "matrix:support:get_query_history:not_granted",
        "fail_closed:tool_unknown",
    ]
    assert all(entree.rule != entree.error_code for entree in audit.entrees)


async def test_la_regle_de_matrice_ne_fuit_jamais_vers_le_client(
    serveur: ServeurSousTest,
) -> None:
    # Arrange / Act
    with appel_http(_entetes("jeton-alice")):
        with pytest.raises(ToolError) as capture:
            await serveur.call_tool("get_query_history", {"profile": "support"})

    # Assert — corps strictement `{error_code, message, correlation_id}`
    corps = json.loads(str(capture.value))
    assert set(corps) == {"error_code", "message", "correlation_id"}
    assert "not_granted" not in str(capture.value)


async def test_un_appel_autorise_qui_echoue_est_journalise(
    serveur: ServeurSousTest, audit: FakeAuditLog
) -> None:
    # Arrange / Act — ce chemin passe par `super().call_tool()`, où le SDK
    # réenveloppe l'erreur du tool dans **sa propre** `ToolError`
    # (`mcp.server.fastmcp.exceptions`), préfixée d'un texte narratif.
    with appel_http(_entetes("jeton-alice")):
        with pytest.raises(ToolError) as capture:
            await serveur.call_tool("get_order_status", {"order_id": "CMD-1"})

    # Assert — c'est l'erreur *domaine* qui ressort, récupérée par `__cause__`
    # puis relevée telle quelle (spec §7) : `str()` est le corps du contrat, et
    # non `"Error executing tool get_order_status: {...}"`, que le client ne
    # saurait pas parser. Si la reprise de `call_tool` disparaissait, ce
    # `pytest.raises(ToolError)` — l'erreur **domaine** — ne capturerait plus
    # rien, la `SdkToolError` n'en héritant pas.
    assert not isinstance(capture.value, SdkToolError)
    corps = json.loads(str(capture.value))
    assert set(corps) == {"error_code", "message", "correlation_id"}
    assert corps["error_code"] == "NOT_FOUND_IN_CORPUS"

    # Assert — l'échec reste journalisé avec le vrai code d'erreur (E5)
    (entree,) = audit.entrees
    assert (entree.decision, entree.error_code) == ("allow", "NOT_FOUND_IN_CORPUS")
    assert entree.rule == "matrix:support:get_order_status"


async def test_un_appel_autorise_annule_est_journalise_sans_etre_avale(
    serveur: ServeurSousTest, audit: FakeAuditLog
) -> None:
    # Arrange / Act — `get_schema_info` lève `asyncio.CancelledError` directement,
    # non interceptée par le `except Exception` du SDK (`tools/base.py:116`) :
    # elle traverse jusqu'à `GovernedFastMCP.call_tool` telle quelle.
    with appel_http(_entetes("jeton-alice")):
        with pytest.raises(asyncio.CancelledError):
            await serveur.call_tool("get_schema_info", {})

    # Assert — l'annulation n'est pas avalée (elle vient de se re-lever ci-dessus)
    # et laisse quand même une trace : sans la clause `except asyncio.CancelledError`
    # dédiée, cet appel pourtant autorisé ne laisserait aucune ligne au journal.
    (entree,) = audit.entrees
    assert (entree.decision, entree.error_code) == ("allow", "CANCELLED")
    assert entree.rule == "matrix:support:get_schema_info"


async def test_un_correlation_id_est_genere_sans_en_tete(
    serveur: ServeurSousTest, audit: FakeAuditLog
) -> None:
    # Arrange / Act — deux appels successifs, tous deux sans en-tête de corrélation
    with appel_http(_entetes("jeton-alice", correlation=None)):
        await serveur.call_tool("get_stock", {"product_ref": "REF-1"})
    with appel_http(_entetes("jeton-alice", correlation=None)):
        await serveur.call_tool("get_stock", {"product_ref": "REF-2"})

    # Assert — un UUID valide (pas une constante en dur), différent à chaque appel :
    # une implémentation qui renverrait toujours la même chaîne non vide tomberait ici.
    premiere, seconde = (entree.correlation_id for entree in audit.entrees)
    uuid.UUID(premiere)
    uuid.UUID(seconde)
    assert premiere != seconde


async def test_le_serveur_n_expose_ni_ressource_ni_prompt(serveur: ServeurSousTest) -> None:
    """Garde-fou de non-régression : `GovernedFastMCP` ne gouverne pas ces primitives.

    Rien n'est enregistré aujourd'hui sur `ServeurSousTest`, donc ces listes sont
    vides sans qu'aucune barrière n'intervienne. Le jour où une ressource ou un
    prompt sera ajouté à ce serveur sans passer par la matrice d'accès, ce test
    échouera et rappellera de gouverner ces points d'entrée (cf. docstring de
    `GovernedFastMCP`).
    """
    # Arrange / Act
    ressources = await serveur.list_resources()
    modeles = await serveur.list_resource_templates()
    prompts = await serveur.list_prompts()

    # Assert
    assert ressources == []
    assert modeles == []
    assert prompts == []

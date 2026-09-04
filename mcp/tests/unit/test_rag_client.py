"""Adapter HTTP réel vers `rag-hybride` (spec §9.1, §11.1) : seule la méthode
`answer()` parle au vrai endpoint `POST /api/v1/query` ; le reste est délégué
au stub, la provenance restant visible dans chaque retour (spec §9.2).

Transport `httpx` simulé (`httpx.MockTransport`), explicitement autorisé par
la spec §11.1 pour ce niveau de test — aucun socket réel.
"""

import json
from collections.abc import Callable

import httpx
import pytest
from app.domain.errors import BackendUnavailableError, NotFoundInCorpusError, SchemaMismatchError
from app.infrastructure.http.rag_client import RagHttpClient

Handler = Callable[[httpx.Request], httpx.Response]


def client_avec(handler: Handler) -> RagHttpClient:
    transport = httpx.MockTransport(handler)
    return RagHttpClient("http://rag.test", timeout_s=5.0, transport=transport)


# --- answer() : endpoint réel --------------------------------------------


async def test_une_reponse_200_donne_les_citations_sans_le_texte_genere() -> None:
    # Arrange — rag-hybride génère un texte que le serveur MCP ne doit pas propager
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "answer": "La tension nominale est de 230V.",
                "citations": [{"title": "Fiche REF-8842", "product_ref": "REF-8842"}],
                "confidence": "high",
                "refused": False,
            },
        )

    # Act
    resultat = await client_avec(handler).answer("tension ?", ("manuel",), "corr")

    # Assert — citations et confidence conservées, la rédaction écartée
    assert resultat["citations"][0]["product_ref"] == "REF-8842"
    assert "answer" not in resultat
    assert "230V" not in str(resultat)


async def test_la_reponse_reelle_porte_source_live_jamais_stub() -> None:
    # Arrange — falsifiable : un adapter qui oublierait la provenance, ou qui
    # copierait "stub" par erreur, ferait échouer cette assertion (spec §9.2)
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"answer": "x", "citations": [], "confidence": "low", "refused": False}
        )

    # Act
    resultat = await client_avec(handler).answer("tension ?", ("manuel",), "corr")

    # Assert
    assert resultat["source"] == "live"


async def test_un_refus_de_corpus_devient_une_erreur_typee() -> None:
    # Arrange
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"answer": "", "citations": [], "refused": True})

    # Act / Assert
    with pytest.raises(NotFoundInCorpusError):
        await client_avec(handler).answer("question absente", ("manuel",), "corr")


# --- Mapping statut HTTP -> erreur typée (arbitrage A) --------------------


async def test_une_erreur_serveur_5xx_devient_backend_unavailable() -> None:
    # Arrange — 502, comme le renvoie réellement rag-hybride sur EMBEDDING_SERVICE_ERROR
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, json={"error_code": "EMBEDDING_SERVICE_ERROR"})

    # Act / Assert
    with pytest.raises(BackendUnavailableError):
        await client_avec(handler).answer("tension ?", ("manuel",), "corr")


async def test_un_404_devient_schema_mismatch() -> None:
    # Arrange — falsifiable : si l'adapter traitait tout 4xx comme
    # BackendUnavailableError (arbitrage A), cette levée n'aurait pas lieu
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error_code": "UNKNOWN_COLLECTION"})

    # Act / Assert
    with pytest.raises(SchemaMismatchError):
        await client_avec(handler).answer("tension ?", ("collection-inconnue",), "corr")


async def test_un_422_devient_backend_unavailable_pas_schema_mismatch() -> None:
    # Arrange — falsifiable : si l'adapter traitait tout 4xx comme
    # SchemaMismatchError, cette levée-ci échouerait
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": [{"msg": "field required"}]})

    # Act / Assert
    with pytest.raises(BackendUnavailableError):
        await client_avec(handler).answer("tension ?", ("manuel",), "corr")


async def test_une_indisponibilite_reseau_devient_backend_unavailable() -> None:
    # Arrange — arbitrage C : timeout/DNS/connexion refusée ne doivent jamais
    # laisser fuir une exception httpx nue
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connexion refusée", request=request)

    # Act / Assert
    with pytest.raises(BackendUnavailableError):
        await client_avec(handler).answer("tension ?", ("manuel",), "corr")


async def test_un_timeout_devient_backend_unavailable() -> None:
    # Arrange
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("délai dépassé", request=request)

    # Act / Assert
    with pytest.raises(BackendUnavailableError):
        await client_avec(handler).answer("tension ?", ("manuel",), "corr")


# --- correlation_id propagé au backend (spec §8) --------------------------


async def test_le_correlation_id_est_propage_au_backend() -> None:
    # Arrange
    recu: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        recu["id"] = request.headers.get("x-correlation-id", "")
        return httpx.Response(200, json={"citations": [], "confidence": "low", "refused": False})

    # Act
    await client_avec(handler).answer("tension ?", ("manuel",), "corr-42")

    # Assert
    assert recu["id"] == "corr-42"


# --- Délégation au stub (spec §9.1) ---------------------------------------


async def test_les_briques_sans_endpoint_sont_deleguees_au_stub() -> None:
    # Arrange — aucune requête HTTP ne doit partir pour ces méthodes
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("aucun appel réseau attendu")

    client = client_avec(handler)

    # Act
    resultat = await client.search("tension", 3, ("manuel",), "corr")

    # Assert — la provenance reste explicite. La *valeur* de DELEGATED_TO_STUB
    # n'est volontairement pas assertée ici : c'est un verrou de gouvernance,
    # il appartient au test d'exhaustivité de la tâche 17 et n'a pas à être
    # dupliqué mot pour mot dans deux fichiers.
    assert resultat["source"] == "stub"


@pytest.mark.parametrize("methode", ["search", "lookup", "document_metadata", "confidence"])
async def test_chaque_methode_deleguee_ne_declenche_aucun_appel_reseau(methode: str) -> None:
    # Arrange — falsifiable : si une méthode listée dans DELEGATED_TO_STUB
    # appelait quand même le transport HTTP, cette assertion échouerait
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"aucun appel réseau attendu pour {methode}")

    client = client_avec(handler)
    arguments: dict[str, tuple[object, ...]] = {
        "search": ("tension", 3, ("manuel",), "corr"),
        "lookup": ("REF-8842", ("manuel",), "corr"),
        "document_metadata": ("doc-1", ("manuel",), "corr"),
        "confidence": ("tension", ("manuel",), "corr"),
    }

    # Act
    resultat = await getattr(client, methode)(*arguments[methode])

    # Assert
    assert resultat["source"] == "stub"


async def test_document_types_est_delegue_au_stub() -> None:
    # Arrange
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("aucun appel réseau attendu")

    client = client_avec(handler)

    # Act
    resultat = await client.document_types(("manuel",), "corr")

    # Assert
    assert resultat["source"] == "stub"


# --- corrections de la ronde 1/5 ------------------------------------------


async def test_un_perimetre_vide_ne_declenche_aucun_appel_et_refuse() -> None:
    """Zéro collection autorisée ne se rabat jamais sur le corpus entier.

    Falsifiable : sans le garde, la requête partirait et le handler lèverait
    `AssertionError` au lieu de `NotFoundInCorpusError`.
    """

    # Arrange — tout appel réseau est une erreur pour ce scénario
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("aucun appel réseau attendu sur un périmètre vide")

    client = client_avec(handler)

    # Act / Assert
    with pytest.raises(NotFoundInCorpusError):
        await client.answer("tension nominale ?", (), "corr")


async def test_le_corps_emis_ne_porte_que_la_question() -> None:
    """Déclencheur : le jour où `collections` sera transmis, ce test tombera.

    `QueryRequest` de `rag-hybride` ne porte aucun champ de collections
    (spec §14). Verrouiller la forme exacte du corps oblige à rouvrir ce test
    — et donc à relire l'adapter — quand le contrat amont évoluera.
    """
    # Arrange
    vus: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        vus.append(json.loads(request.content))
        return httpx.Response(200, json={"citations": [], "confidence": 0.5})

    client = client_avec(handler)

    # Act
    await client.answer("tension nominale ?", ("manuel",), "corr")

    # Assert — égalité stricte, pas une appartenance
    assert vus == [{"query": "tension nominale ?"}]


async def test_une_url_de_base_malformee_devient_backend_unavailable() -> None:
    """`httpx.InvalidURL` n'hérite pas de `HTTPError`.

    Sans branche dédiée, l'exception sortirait nue jusqu'au client MCP.
    """

    # Arrange — port malformé, cas réaliste d'une variable d'environnement fautive
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("la construction du client doit échouer avant l'appel")

    client = RagHttpClient(
        "http://rag.test:8O00", timeout_s=5.0, transport=httpx.MockTransport(handler)
    )

    # Act / Assert
    with pytest.raises(BackendUnavailableError):
        await client.answer("tension ?", ("manuel",), "corr")


async def test_un_200_non_json_devient_backend_unavailable() -> None:
    """Une page HTML de proxy ne doit pas faire remonter une `JSONDecodeError` nue."""

    # Arrange
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>proxy</html>")

    client = client_avec(handler)

    # Act / Assert
    with pytest.raises(BackendUnavailableError):
        await client.answer("tension ?", ("manuel",), "corr")


async def test_un_200_json_non_objet_devient_backend_unavailable() -> None:
    """Un tableau JSON ferait lever `AttributeError` sur `corps.get`."""

    # Arrange
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=["pas", "un", "objet"])

    client = client_avec(handler)

    # Act / Assert
    with pytest.raises(BackendUnavailableError):
        await client.answer("tension ?", ("manuel",), "corr")


async def test_un_404_sans_error_code_est_une_indisponibilite_pas_un_schema() -> None:
    """Un statut nu ne signale rien (spec §7).

    Un 404 de route inconnue est une erreur de configuration, pas un refus de
    schéma : le classer en `SCHEMA_MISMATCH` enverrait l'exploitant sur une
    fausse piste.
    """

    # Arrange
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="Not Found")

    client = client_avec(handler)

    # Act / Assert
    with pytest.raises(BackendUnavailableError):
        await client.answer("tension ?", ("manuel",), "corr")

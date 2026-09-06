import pytest
from app.domain.errors import BackendUnavailableError, NotFoundInCorpusError
from app.infrastructure.http.rag_client import RagHttpClient

from .conftest import ServeurRag


async def test_appelle_reellement_le_serveur_et_renvoie_les_citations(
    serveur_rag: ServeurRag,
) -> None:
    # Arrange
    client = RagHttpClient(serveur_rag.url, timeout_s=5.0)

    # Act
    resultat = await client.answer("tension nominale ?", ("manuel",), "corr-1")

    # Assert
    assert resultat["citations"][0]["product_ref"] == "REF-8842"
    assert resultat["source"] == "live"
    assert "answer" not in resultat


async def test_un_refus_de_corpus_traverse_le_reseau_en_erreur_typee(
    serveur_rag: ServeurRag,
) -> None:
    client = RagHttpClient(serveur_rag.url, timeout_s=5.0)
    with pytest.raises(NotFoundInCorpusError):
        await client.answer("information absente", ("manuel",), "corr-2")


async def test_une_erreur_500_reelle_devient_backend_unavailable(serveur_rag: ServeurRag) -> None:
    client = RagHttpClient(serveur_rag.url, timeout_s=5.0)
    with pytest.raises(BackendUnavailableError):
        await client.answer("panne du service", ("manuel",), "corr-3")


async def test_un_timeout_reel_devient_backend_unavailable(serveur_rag: ServeurRag) -> None:
    # Arrange — le serveur met 0,6s (ronde de correction 1, constat 1), le
    # client attend 0,1s : l'abandon reste largement antérieur à la réponse.
    client = RagHttpClient(serveur_rag.url, timeout_s=0.1)

    # Act / Assert
    with pytest.raises(BackendUnavailableError):
        await client.answer("réponse lente", ("manuel",), "corr-4")


async def test_une_connexion_refusee_devient_backend_unavailable() -> None:
    client = RagHttpClient("http://127.0.0.1:1", timeout_s=1.0)
    with pytest.raises(BackendUnavailableError):
        await client.answer("tension ?", ("manuel",), "corr-5")


async def test_le_correlation_id_arrive_reellement_chez_le_backend(serveur_rag: ServeurRag) -> None:
    """Preuve bout-en-bout que `RagHttpClient` pose l'en-tête sur une vraie
    socket (ronde de correction 1, constat 2) : contrairement à la version
    précédente, ce test passe par le code sous test — s'il était supprimé du
    dépôt, ou si l'en-tête n'était pas posé, `serveur_rag.correlation_ids`
    resterait vide et l'assertion échouerait. Falsifiabilité vérifiée
    manuellement (voir le rapport de tâche) en neutralisant temporairement la
    pose de l'en-tête dans `rag_client.py`.
    """
    # Arrange
    client = RagHttpClient(serveur_rag.url, timeout_s=5.0)

    # Act
    await client.answer("tension nominale ?", ("manuel",), "corr-9")

    # Assert
    assert "corr-9" in serveur_rag.correlation_ids


@pytest.mark.live
async def test_contre_le_vrai_rag_hybride_s_il_ecoute() -> None:
    """Vérification cross-projet, opt-in : `pytest -m live` avec rag-hybride démarré."""
    client = RagHttpClient("http://localhost:8001", timeout_s=10.0)
    resultat = await client.answer("tension nominale", ("manuel",), "corr-live")
    assert "citations" in resultat

import socket
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# Borne de temps sur l'attente du démarrage du serveur (voir `serveur_rag`
# ci-dessous) : un `uvicorn.Server.started` qui ne passe jamais à `True`
# (port déjà occupé, exception d'import dans le thread serveur) ferait
# pendre `while not serveur.started: ...` indéfiniment, donc toute la
# suite. Quelques secondes suffisent très largement à un démarrage local
# (démarrage mesuré à ~0,08s en pratique).
_DELAI_DEMARRAGE_MAX_S = 5.0


@dataclass
class ServeurRag:
    """Doublure `rag-hybride` réellement servie, et ce qu'elle a observé.

    `correlation_ids` accumule, dans l'ordre de réception, le `X-Correlation-Id`
    de chaque requête reçue — seule preuve bout-en-bout que l'en-tête posé par
    `RagHttpClient` traverse une vraie socket (ronde de correction 1, constat 2).
    """

    url: str
    correlation_ids: list[str] = field(default_factory=list)


def _port_libre() -> int:
    with socket.socket() as prise:
        prise.bind(("127.0.0.1", 0))
        return int(prise.getsockname()[1])


def _application_double(correlation_ids: list[str]) -> FastAPI:
    """Doublure du contrat `rag-hybride`, servie par un vrai serveur.

    Les deux projets exposent chacun un paquet `app` : importer l'application
    réelle de `rag-hybride` ici entrerait en collision (cf. ../CLAUDE.md).
    """
    application = FastAPI()

    @application.post("/api/v1/query")
    async def query(request: Request) -> Any:
        correlation_ids.append(request.headers.get("x-correlation-id", ""))
        corps = await request.json()
        requete = corps.get("query", "")
        if "absente" in requete:
            return {"answer": "", "citations": [], "confidence": "refused", "refused": True}
        if "panne" in requete:
            return JSONResponse(status_code=500, content={"error_code": "EMBEDDING_SERVICE_ERROR"})
        if "lent" in requete:
            # Bloquant, volontairement : ce scénario n'existe que pour éprouver
            # le timeout du client contre une boucle d'événements serveur
            # réellement occupée (cf. brief de la tâche 15) — ne jamais
            # remplacer par `asyncio.sleep`, qui ne bloquerait rien. Réduit à
            # 0,6s (ronde de correction 1, constat 1) : le client abandonne
            # toujours largement avant (`timeout_s=0.1` dans le test de
            # timeout), et le résidu de blocage sur le fil serveur qui
            # contaminait les tests suivants (fixture de portée session) est
            # divisé par plus de trois.
            time.sleep(0.6)
        return {
            "answer": "La tension nominale est de 230V.",
            "citations": [
                {
                    "title": "Fiche REF-8842",
                    "product_ref": "REF-8842",
                    "published_date": "2026-01-15",
                    "document_type": "datasheet",
                }
            ],
            "confidence": "high",
            "refused": False,
        }

    return application


@pytest.fixture(scope="session")
def serveur_rag() -> Iterator[ServeurRag]:
    correlation_ids: list[str] = []
    port = _port_libre()
    config = uvicorn.Config(
        _application_double(correlation_ids), host="127.0.0.1", port=port, log_level="warning"
    )
    serveur = uvicorn.Server(config)
    fil = threading.Thread(target=serveur.run, daemon=True)
    fil.start()

    try:
        debut = time.monotonic()
        while not serveur.started:
            if time.monotonic() - debut > _DELAI_DEMARRAGE_MAX_S:
                raise RuntimeError(
                    "le serveur uvicorn de la doublure rag-hybride n'a pas démarré "
                    f"dans le délai imparti ({_DELAI_DEMARRAGE_MAX_S}s) — port déjà "
                    "occupé ou échec du thread serveur"
                )
            time.sleep(0.05)

        yield ServeurRag(f"http://127.0.0.1:{port}", correlation_ids)
    finally:
        # `finally`, pas seulement après le `yield` : si la borne ci-dessus a
        # levé avant que le serveur ne soit prêt, `should_exit` doit malgré
        # tout être posé — sinon un fil resterait en écoute pour le reste de
        # la session (ronde de correction 1, constat 3).
        serveur.should_exit = True
        fil.join(timeout=5)
        # `Thread.join()` ne renvoie jamais rien (toujours `None`) : l'arrêt
        # effectif se lit sur `is_alive()`, pas sur la valeur de retour.
        if fil.is_alive():
            raise RuntimeError(
                "le fil du serveur uvicorn de la doublure rag-hybride ne s'est "
                "pas arrêté dans le délai imparti (5s) après should_exit"
            )

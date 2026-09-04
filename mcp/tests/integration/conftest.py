import socket
import threading
import time
from collections.abc import Iterator
from typing import Any

import pytest
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# Borne de temps sur l'attente du démarrage du serveur (voir `serveur_rag`
# ci-dessous) : un `uvicorn.Server.started` qui ne passe jamais à `True`
# (port déjà occupé, exception d'import dans le thread serveur) ferait
# pendre `while not serveur.started: ...` indéfiniment, donc toute la
# suite. Quelques secondes suffisent très largement à un démarrage local.
_DELAI_DEMARRAGE_MAX_S = 5.0


def _port_libre() -> int:
    with socket.socket() as prise:
        prise.bind(("127.0.0.1", 0))
        return int(prise.getsockname()[1])


def _application_double() -> FastAPI:
    """Doublure du contrat `rag-hybride`, servie par un vrai serveur.

    Les deux projets exposent chacun un paquet `app` : importer l'application
    réelle de `rag-hybride` ici entrerait en collision (cf. ../CLAUDE.md).
    """
    application = FastAPI()

    @application.post("/api/v1/query")
    async def query(request: Request) -> Any:
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
            # remplacer par `asyncio.sleep`, qui ne bloquerait rien.
            time.sleep(2)
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
            "correlation_id_recu": request.headers.get("x-correlation-id", ""),
        }

    return application


@pytest.fixture(scope="session")
def serveur_rag() -> Iterator[str]:
    port = _port_libre()
    config = uvicorn.Config(_application_double(), host="127.0.0.1", port=port, log_level="warning")
    serveur = uvicorn.Server(config)
    fil = threading.Thread(target=serveur.run, daemon=True)
    fil.start()

    debut = time.monotonic()
    while not serveur.started:
        if time.monotonic() - debut > _DELAI_DEMARRAGE_MAX_S:
            raise RuntimeError(
                "le serveur uvicorn de la doublure rag-hybride n'a pas démarré "
                f"dans le délai imparti ({_DELAI_DEMARRAGE_MAX_S}s) — port déjà "
                "occupé ou échec du thread serveur"
            )
        time.sleep(0.05)

    yield f"http://127.0.0.1:{port}"
    serveur.should_exit = True
    fil.join(timeout=5)

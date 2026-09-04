"""Harnais commun aux tests unitaires qui pilotent `GovernedFastMCP`.

`call_tool` rederive l'identité à *chaque* appel depuis la requête HTTP courante
(cf. `app/api/governance.py`) : un test ne peut donc pas se contenter de poser
`current_identity`, il doit poser le contexte de requête du SDK comme le fait le
serveur bas niveau. Ce module rassemble ce qu'il faut pour cela, plutôt que de
le recopier dans chaque fichier de test.
"""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, cast

from app.domain.errors import InvalidTokenError
from app.domain.models import AuditEntry, Identity
from mcp.server.lowlevel.server import request_ctx
from mcp.shared.context import RequestContext
from starlette.requests import Request

JETON = "jeton-de-test"
CORRELATION = "corr-de-test"


class FakeAuditLog:
    """Double du port `AuditLogPort` — conserve les entrées en mémoire."""

    def __init__(self) -> None:
        self.entrees: list[AuditEntry] = []

    def record(self, entry: AuditEntry) -> None:
        self.entrees.append(entry)


class FakeTokenVerifier:
    """Double du port `TokenVerifierPort` — table jeton → profil."""

    def __init__(self, profils: Mapping[str, str]) -> None:
        self._profils = profils

    def verify(self, token: str) -> Identity:
        profil = self._profils.get(token)
        if profil is None:
            raise InvalidTokenError("jeton inconnu")
        return Identity(
            subject=f"sujet-{token}",
            profile=profil,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )


def requete(entetes: Mapping[str, str]) -> Request:
    """Une vraie requête Starlette, comme celle que porte `request_context.request`."""
    brutes = [(clef.lower().encode(), valeur.encode()) for clef, valeur in entetes.items()]
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "method": "POST",
            "scheme": "http",
            "path": "/mcp",
            "raw_path": b"/mcp",
            "query_string": b"",
            "root_path": "",
            "server": ("127.0.0.1", 8000),
            "client": ("127.0.0.1", 51234),
            "headers": brutes,
        }
    )


@contextmanager
def appel_http(token: str = JETON, correlation: str = CORRELATION) -> Iterator[None]:
    """Pose le contexte de requête du SDK, comme le serveur bas niveau le fait."""
    jeton = request_ctx.set(
        RequestContext(
            request_id=1,
            meta=None,
            session=cast(Any, None),
            lifespan_context=None,
            request=requete({"Authorization": f"Bearer {token}", "X-Correlation-Id": correlation}),
        )
    )
    try:
        yield
    finally:
        request_ctx.reset(jeton)

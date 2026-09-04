"""Adapter de vérification JWT par JWKS (Keycloak) — infrastructure.

Vérifie la signature RS256 d'un JWT contre les clés publiques exposées par
`sorabel-idp` (endpoint JWKS), avec les mêmes contrôles `iss`/`aud`/`exp` et
la même discipline d'erreur que `LocalKeyTokenVerifier` (spec §5). Adapter
de production, sélectionné par `MCP_TOKEN_VERIFIER=jwks`.
"""

from datetime import datetime, timezone

import jwt
from jwt import PyJWKClient

from app.config import Settings
from app.domain.errors import InvalidTokenError
from app.domain.models import Identity
from app.domain.ports import TokenVerifierPort
from app.infrastructure.keycloak.local_key_verifier import (
    PROFILE_CLAIM,
    UnsafeVerifierConfiguration,
    build_local_verifier,
)

_ALGORITHM = "RS256"


class JwksTokenVerifier:
    """Vérifie un JWT Keycloak via le JWKS publié, clés mises en cache.

    Traitement de la boucle d'événements (exigence B) : `verify()` reste
    synchrone — c'est le contrat de `TokenVerifierPort` — alors que le SDK
    MCP l'appellera depuis un `call_tool` asynchrone (tâche 10).
    `PyJWKClient` maintient un cache à deux niveaux (jeu de clés complet,
    TTL 5 min par défaut ; clés individuelles par `kid`) : l'immense
    majorité des appels à `verify()` ne touchent donc que ce cache mémoire,
    un coût négligeable dans la boucle d'événements.

    Trois cas seulement déclenchent un aller-retour réseau **synchrone** :
    le tout premier appel (cache froid), l'expiration du TTL du jeu de
    clés, et la rencontre d'un `kid` absent du cache (rotation de clé côté
    IdP — le client retente alors un fetch avant de conclure à une clé
    inconnue). Pour réduire la fréquence du premier cas, le constructeur
    tente un préchargement synchrone du JWKS au démarrage — avant que la
    boucle d'événements ne serve la moindre requête, donc sans risque de
    geler un appel concurrent. Cette tentative est **meilleur effort** :
    elle n'échoue jamais le démarrage du serveur — un IdP injoignable au
    boot ne doit pas empêcher `mcp` de démarrer, l'échec sera simplement
    reproduit (et journalisé côté audit, tâche 10) au premier `verify()`.

    Limite assumée, non résolue par cette classe : au-delà du
    préchargement, le TTL qui expire ou une rotation de clé restent une
    fenêtre où `verify()` bloque réellement le thread appelant le temps
    d'un aller-retour HTTP vers l'IdP. Cette classe ne peut pas s'en
    affranchir sans devenir asynchrone, ce que `TokenVerifierPort` interdit.
    Il revient donc à l'appelant asynchrone (tâche 10, `call_tool`) de ne
    jamais attendre `verify()` directement dans une coroutine, mais de
    l'exécuter hors boucle d'événements, par exemple via
    `await asyncio.to_thread(verifier.verify, token)` — faute de quoi cet
    aller-retour occasionnel gèlerait tous les appels concurrents.
    """

    def __init__(self, jwks_url: str, issuer: str, audience: str, timeout_s: float) -> None:
        self._issuer = issuer
        self._audience = audience
        self._client = PyJWKClient(
            jwks_url, cache_keys=True, timeout=timeout_s if timeout_s > 0 else 1.0
        )
        try:
            self._client.get_signing_keys()
        except Exception:
            # Préchargement meilleur effort (voir docstring de la classe) :
            # un IdP injoignable au démarrage ne doit pas empêcher `mcp` de
            # démarrer. L'échec, s'il persiste, sera reproduit au premier
            # `verify()` et rejeté normalement par le bloc ci-dessous.
            pass

    def verify(self, token: str) -> Identity:
        """Vérifie signature, `iss`, `aud`, `exp`, puis le claim de profil.

        Lève `InvalidTokenError` pour toute anomalie — signature invalide,
        clé inconnue ou JWKS injoignable, émetteur ou audience incorrects,
        expiration, claims `sub`/`sorabel_profile` absents ou mal typés. Le
        message ne distingue jamais ces cas entre eux (même discipline que
        `LocalKeyTokenVerifier`).
        """
        try:
            cle = self._client.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                cle.key,
                algorithms=[_ALGORITHM],
                issuer=self._issuer,
                audience=self._audience,
            )
        except Exception as exc:
            # `PyJWKClient` lève des erreurs réseau/JSON (`PyJWKClientError`,
            # `PyJWKClientConnectionError`) qui ne dérivent pas de
            # `PyJWTError` ; le comportement attendu est identique dans tous
            # les cas — refuser le token avec le même message générique.
            # Toute autre couche du projet reste soumise à la règle
            # « jamais d'`Exception` large ».
            raise InvalidTokenError("token invalide") from exc

        profile = claims.get(PROFILE_CLAIM)
        subject = claims.get("sub")
        if not isinstance(profile, str) or not isinstance(subject, str):
            raise InvalidTokenError("claims obligatoires manquants")

        expires_at_raw = claims.get("exp")
        if not isinstance(expires_at_raw, (int, float)):
            raise InvalidTokenError("claim `exp` manquant")

        return Identity(
            subject=subject,
            profile=profile,
            expires_at=datetime.fromtimestamp(float(expires_at_raw), tz=timezone.utc),
        )


def build_token_verifier(settings: Settings) -> TokenVerifierPort:
    """Sélectionne l'adapter de vérification selon `MCP_TOKEN_VERIFIER`.

    Porte d'entrée unique (spec §5) : les garde-fous communs aux deux
    adapters vivent ici, une seule fois — pas dupliqués dans
    `build_local_verifier`. Refuse de démarrer si :

    - `MCP_JWT_ISSUER` ou `MCP_JWT_AUDIENCE` est vide (les deux adapters
      valident `iss`/`aud`) ;
    - `MCP_TOKEN_VERIFIER=jwks` alors que `MCP_JWKS_URL` est vide ;
    - `MCP_TOKEN_VERIFIER` porte une valeur inconnue (fail closed — jamais
      de repli permissif sur un adapter).

    Le garde spécifique à l'adapter `local` (`MCP_ENV`, `MCP_DEV_JWT_SECRET`)
    reste dans `build_local_verifier`, seul appelant légitime de cet
    adapter.
    """
    if not settings.mcp_jwt_issuer or not settings.mcp_jwt_audience:
        raise UnsafeVerifierConfiguration("MCP_JWT_ISSUER ou MCP_JWT_AUDIENCE est vide")

    if settings.mcp_token_verifier == "local":
        return build_local_verifier(settings)

    if settings.mcp_token_verifier == "jwks":
        if not settings.mcp_jwks_url:
            raise UnsafeVerifierConfiguration("MCP_JWKS_URL est vide")
        return JwksTokenVerifier(
            jwks_url=settings.mcp_jwks_url,
            issuer=settings.mcp_jwt_issuer,
            audience=settings.mcp_jwt_audience,
            timeout_s=settings.mcp_http_timeout_s,
        )

    raise UnsafeVerifierConfiguration(
        f"MCP_TOKEN_VERIFIER inconnu : {settings.mcp_token_verifier!r}"
    )

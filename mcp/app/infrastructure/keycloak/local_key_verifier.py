from datetime import datetime, timezone

import jwt

from app.config import Settings
from app.domain.errors import InvalidTokenError
from app.domain.models import Identity

PROFILE_CLAIM = "sorabel_profile"


class UnsafeVerifierConfiguration(Exception):
    """Configuration d'authentification refusée au démarrage.

    Distincte d'`InvalidTokenError` : celle-ci sanctionne un token au moment
    de sa vérification, celle-ci sanctionne la configuration du serveur
    avant qu'il n'accepte la moindre requête (garde-fous spec §5).
    """


class LocalKeyTokenVerifier:
    """Vérificateur symétrique (HS256), réservé au développement.

    Permet de signer des tokens de test sans Keycloak. Interdit hors `dev`
    par `build_local_verifier` — voir ses deux garde-fous.
    """

    def __init__(self, secret: str, issuer: str, audience: str) -> None:
        self._secret = secret
        self._issuer = issuer
        self._audience = audience

    def verify(self, token: str) -> Identity:
        """Vérifie signature, `iss`, `aud`, `exp`, puis le claim de profil.

        Lève `InvalidTokenError` pour toute anomalie — signature invalide,
        émetteur ou audience incorrects, expiration, claims `sub`/
        `sorabel_profile` absents ou mal typés. Le message ne distingue
        jamais ces cas entre eux : le détail va au journal (via la tâche 10),
        jamais au client, pour ne pas aider un attaquant à discriminer les
        causes de rejet (point de vigilance sécurité).
        """
        try:
            claims = jwt.decode(
                token,
                self._secret,
                algorithms=["HS256"],
                issuer=self._issuer,
                audience=self._audience,
            )
        except jwt.PyJWTError as exc:
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


def build_local_verifier(settings: Settings) -> LocalKeyTokenVerifier:
    """Construit le vérificateur de dev, ou refuse de démarrer.

    Deux garde-fous (spec §5) : l'adapter local ne doit jamais survivre à un
    déploiement hors `dev`, et un secret vide ne doit jamais démarrer
    silencieusement avec une clé de signature triviale.
    """
    if settings.mcp_env != "dev":
        raise UnsafeVerifierConfiguration("MCP_TOKEN_VERIFIER=local est réservé à MCP_ENV=dev")
    if not settings.mcp_dev_jwt_secret:
        raise UnsafeVerifierConfiguration("MCP_DEV_JWT_SECRET est vide")
    if not settings.mcp_jwt_issuer or not settings.mcp_jwt_audience:
        # Non demandé explicitement par la spec §5 pour cet adapter, mais du
        # même ordre que les deux garde-fous ci-dessus : fail-fast contre un
        # `.env` tronqué qui démarrerait silencieusement avec un émetteur ou
        # une audience vide, plutôt qu'un mode dégradé découvert plus tard.
        # Ce n'est pas la fermeture d'une brèche de sécurité : une audience
        # vide fait déjà lever `MissingRequiredClaimError` à PyJWT sur tout
        # token (`_validate_aud`), et un émetteur vide exige toujours une
        # signature valide. Le même garde a vocation à être hissé dans
        # `build_token_verifier` (tâche 8), où il vaudra aussi pour l'adapter
        # JWKS — `mcp_jwks_url` n'est pas couvert ici.
        raise UnsafeVerifierConfiguration("MCP_JWT_ISSUER ou MCP_JWT_AUDIENCE est vide")
    return LocalKeyTokenVerifier(
        secret=settings.mcp_dev_jwt_secret,
        issuer=settings.mcp_jwt_issuer,
        audience=settings.mcp_jwt_audience,
    )

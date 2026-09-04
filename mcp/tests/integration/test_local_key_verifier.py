from datetime import datetime, timedelta, timezone

import jwt
import pytest
from app.config import Settings
from app.domain.errors import InvalidTokenError
from app.infrastructure.keycloak.local_key_verifier import (
    LocalKeyTokenVerifier,
    UnsafeVerifierConfiguration,
    build_local_verifier,
)

SECRET = "secret-de-test-uniquement-au-moins-32-octets"
ISSUER = "https://idp.test/realms/sorabel-data-gate"
AUDIENCE = "sorabel-mcp"


def forge(**overrides: object) -> str:
    """Fabrique un token de test réellement signé (HS256)."""
    payload: dict[str, object] = {
        "sub": "poste-vente-42",
        "sorabel_profile": "sales",
        "iss": ISSUER,
        "aud": AUDIENCE,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
    }
    payload.update(overrides)
    return jwt.encode(payload, SECRET, algorithm="HS256")


@pytest.fixture
def verifier() -> LocalKeyTokenVerifier:
    return LocalKeyTokenVerifier(secret=SECRET, issuer=ISSUER, audience=AUDIENCE)


def test_un_token_valide_donne_le_sujet_et_le_profil(verifier: LocalKeyTokenVerifier) -> None:
    # Act
    identity = verifier.verify(forge())

    # Assert
    assert identity.subject == "poste-vente-42"
    assert identity.profile == "sales"


def test_un_token_expire_est_refuse(verifier: LocalKeyTokenVerifier) -> None:
    # Arrange
    expire = forge(exp=datetime.now(timezone.utc) - timedelta(seconds=1))

    # Act / Assert
    with pytest.raises(InvalidTokenError):
        verifier.verify(expire)


def test_un_mauvais_emetteur_est_refuse(verifier: LocalKeyTokenVerifier) -> None:
    with pytest.raises(InvalidTokenError):
        verifier.verify(forge(iss="https://attaquant.test/realms/autre"))


def test_une_mauvaise_audience_est_refusee(verifier: LocalKeyTokenVerifier) -> None:
    with pytest.raises(InvalidTokenError):
        verifier.verify(forge(aud="autre-service"))


def test_une_signature_falsifiee_est_refusee(verifier: LocalKeyTokenVerifier) -> None:
    # Arrange — signé avec un secret différent de celui du vérificateur
    faux = jwt.encode(
        {"sub": "x", "iss": ISSUER, "aud": AUDIENCE},
        "mauvais-secret-lui-aussi-assez-long-pour-hs256",
        algorithm="HS256",
    )

    # Act / Assert
    with pytest.raises(InvalidTokenError):
        verifier.verify(faux)


def test_un_claim_de_profil_absent_est_refuse(verifier: LocalKeyTokenVerifier) -> None:
    # Arrange — token valide mais sans le claim `sorabel_profile`
    sans_profil = jwt.encode(
        {
            "sub": "x",
            "iss": ISSUER,
            "aud": AUDIENCE,
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        SECRET,
        algorithm="HS256",
    )

    # Act / Assert
    with pytest.raises(InvalidTokenError):
        verifier.verify(sans_profil)


def test_le_verificateur_local_est_interdit_hors_developpement() -> None:
    # Arrange
    settings = Settings(
        _env_file=None, mcp_env="prod", mcp_token_verifier="local", mcp_dev_jwt_secret=SECRET
    )

    # Act / Assert — un adapter de dev ne doit pas survivre à un déploiement
    with pytest.raises(UnsafeVerifierConfiguration):
        build_local_verifier(settings)


def test_un_secret_vide_empeche_le_demarrage() -> None:
    # Arrange
    settings = Settings(_env_file=None, mcp_env="dev", mcp_dev_jwt_secret="")

    # Act / Assert
    with pytest.raises(UnsafeVerifierConfiguration):
        build_local_verifier(settings)


def test_un_emetteur_ou_une_audience_vide_empeche_le_demarrage() -> None:
    # Arrange — secret présent, mais issuer/audience laissés à leur défaut
    # vide : un `.env` tronqué ne doit pas démarrer silencieusement.
    settings = Settings(
        _env_file=None,
        mcp_env="dev",
        mcp_dev_jwt_secret=SECRET,
        mcp_jwt_issuer="",
        mcp_jwt_audience="",
    )

    # Act / Assert
    with pytest.raises(UnsafeVerifierConfiguration):
        build_local_verifier(settings)

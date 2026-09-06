import secrets
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

# Générés en session, jamais en dur : un secret littéral resterait un secret,
# même de test (consigne de sécurité).
SECRET = secrets.token_urlsafe(32)
AUTRE_SECRET = secrets.token_urlsafe(32)
ISSUER = "https://idp.test/realms/sorabel-data-gate"
AUDIENCE = "sorabel-mcp"


def forge(secret: str = SECRET, **overrides: object) -> str:
    """Fabrique un token de test réellement signé (HS256).

    `secret` par défaut à `SECRET` (celui du vérificateur) : le paramétrer
    permet de forger un payload par ailleurs intégralement valide, mais signé
    avec une autre clé — c'est la seule façon de prouver qu'un test isole
    réellement la vérification de signature du reste des contrôles.
    """
    payload: dict[str, object] = {
        "sub": "poste-vente-42",
        "sorabel_profile": "sales",
        "iss": ISSUER,
        "aud": AUDIENCE,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
    }
    payload.update(overrides)
    return jwt.encode(payload, secret, algorithm="HS256")


@pytest.fixture
def verifier() -> LocalKeyTokenVerifier:
    return LocalKeyTokenVerifier(secret=SECRET, issuer=ISSUER, audience=AUDIENCE)


def test_un_token_valide_donne_le_sujet_et_le_profil(verifier: LocalKeyTokenVerifier) -> None:
    # Arrange
    expire_dans = datetime.now(timezone.utc) + timedelta(minutes=5)
    token = forge(exp=expire_dans)

    # Act
    identity = verifier.verify(token)

    # Assert — y compris `expires_at`, seul endroit qui exerce la conversion
    # `datetime.fromtimestamp(..., tz=timezone.utc)` : une erreur de fuseau
    # ou d'unité (secondes vs. millisecondes) doit être détectée ici, pas
    # découverte plus tard dans l'audit (tâche 10).
    assert identity.subject == "poste-vente-42"
    assert identity.profile == "sales"
    assert abs((identity.expires_at - expire_dans).total_seconds()) < 1


def test_un_token_expire_est_refuse(verifier: LocalKeyTokenVerifier) -> None:
    # Arrange
    expire = forge(exp=datetime.now(timezone.utc) - timedelta(seconds=1))

    # Act / Assert
    with pytest.raises(InvalidTokenError):
        verifier.verify(expire)


def test_un_mauvais_emetteur_est_refuse(verifier: LocalKeyTokenVerifier) -> None:
    # Arrange — payload par ailleurs valide, seul `iss` diffère
    mauvais_emetteur = forge(iss="https://attaquant.test/realms/autre")

    # Act / Assert
    with pytest.raises(InvalidTokenError):
        verifier.verify(mauvais_emetteur)


def test_une_mauvaise_audience_est_refusee(verifier: LocalKeyTokenVerifier) -> None:
    # Arrange — payload par ailleurs valide, seule `aud` diffère
    mauvaise_audience = forge(aud="autre-service")

    # Act / Assert
    with pytest.raises(InvalidTokenError):
        verifier.verify(mauvaise_audience)


def test_une_signature_falsifiee_est_refusee(verifier: LocalKeyTokenVerifier) -> None:
    # Arrange — payload complet et par ailleurs valide (claims, `exp`
    # compris), signé avec un secret différent de celui du vérificateur.
    # Signer un payload incomplet rendrait ce test vert même sans
    # vérification de signature (l'échec viendrait alors du claim manquant) :
    # c'est ce que ce payload complet élimine.
    faux = forge(secret=AUTRE_SECRET)

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


def test_un_claim_de_sujet_absent_est_refuse(verifier: LocalKeyTokenVerifier) -> None:
    # Arrange — token valide, `sorabel_profile` présent, mais sans `sub` :
    # branche symétrique de celle testée ci-dessus, non couverte par le
    # brief mais nécessaire pour exercer l'autre moitié du garde combiné.
    sans_sujet = jwt.encode(
        {
            "sorabel_profile": "sales",
            "iss": ISSUER,
            "aud": AUDIENCE,
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        SECRET,
        algorithm="HS256",
    )

    # Act / Assert
    with pytest.raises(InvalidTokenError):
        verifier.verify(sans_sujet)


def test_un_claim_exp_absent_est_refuse(verifier: LocalKeyTokenVerifier) -> None:
    # Arrange — token par ailleurs valide, mais sans `exp` : un token
    # éternel est un mode de défaillance réel, pas seulement défensif.
    sans_exp = jwt.encode(
        {"sub": "poste-vente-42", "sorabel_profile": "sales", "iss": ISSUER, "aud": AUDIENCE},
        SECRET,
        algorithm="HS256",
    )

    # Act / Assert
    with pytest.raises(InvalidTokenError):
        verifier.verify(sans_exp)


@pytest.mark.parametrize(
    "token_invalide",
    [
        pytest.param(lambda: forge(secret=AUTRE_SECRET), id="signature-falsifiee"),
        pytest.param(
            lambda: forge(iss="https://attaquant.test/realms/autre"), id="mauvais-emetteur"
        ),
        pytest.param(lambda: forge(aud="autre-service"), id="mauvaise-audience"),
        pytest.param(
            lambda: forge(exp=datetime.now(timezone.utc) - timedelta(seconds=1)), id="expire"
        ),
    ],
)
def test_les_messages_de_rejet_sont_indistinguables(
    verifier: LocalKeyTokenVerifier, token_invalide: object
) -> None:
    """Un attaquant ne doit pas pouvoir distinguer ces quatre causes de rejet
    entre elles à la lecture du message : elles doivent toutes produire
    exactement le même message générique.
    """
    # Arrange
    assert callable(token_invalide)
    token = token_invalide()

    # Act
    with pytest.raises(InvalidTokenError) as excinfo:
        verifier.verify(token)

    # Assert
    assert str(excinfo.value) == "token invalide"


def test_le_verificateur_local_est_interdit_hors_developpement() -> None:
    # Arrange — issuer/audience renseignés pour isoler ce garde des autres :
    # sans eux, le 3e garde-fou (issuer/audience vide) suffirait à lui seul
    # à faire lever `UnsafeVerifierConfiguration`, et ce test resterait vert
    # même si le garde `MCP_ENV` était supprimé.
    settings = Settings(
        _env_file=None,
        mcp_env="prod",
        mcp_token_verifier="local",
        mcp_dev_jwt_secret=SECRET,
        mcp_jwt_issuer=ISSUER,
        mcp_jwt_audience=AUDIENCE,
    )

    # Act / Assert — un adapter de dev ne doit pas survivre à un déploiement,
    # et c'est bien CE garde qui le prouve (message dédié).
    with pytest.raises(UnsafeVerifierConfiguration, match="MCP_TOKEN_VERIFIER=local"):
        build_local_verifier(settings)


def test_un_secret_vide_empeche_le_demarrage() -> None:
    # Arrange — issuer/audience renseignés pour la même raison que ci-dessus :
    # isoler ce garde du 3e garde-fou.
    settings = Settings(
        _env_file=None,
        mcp_env="dev",
        mcp_dev_jwt_secret="",
        mcp_jwt_issuer=ISSUER,
        mcp_jwt_audience=AUDIENCE,
    )

    # Act / Assert
    with pytest.raises(UnsafeVerifierConfiguration, match="MCP_DEV_JWT_SECRET"):
        build_local_verifier(settings)

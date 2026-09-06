import json
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, cast

import jwt
import pytest
from app.config import Settings
from app.domain.errors import InvalidTokenError
from app.infrastructure.keycloak.jwks_verifier import JwksTokenVerifier, build_token_verifier
from app.infrastructure.keycloak.local_key_verifier import (
    LocalKeyTokenVerifier,
    UnsafeVerifierConfiguration,
)
from cryptography.hazmat.primitives.asymmetric import rsa

ISSUER = "https://idp.test/realms/sorabel-data-gate"
AUDIENCE = "sorabel-mcp"


class JwksServer:
    """Sert un document JWKS réel sur un port éphémère, et compte ses appels.

    `set_jwks` permet de changer le document servi en cours de vie du
    serveur, pour simuler une rotation de clé côté IdP.
    """

    def __init__(self, jwks: dict[str, object]) -> None:
        self.appels = 0
        self._jwks = jwks
        serveur = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 — imposé par BaseHTTPRequestHandler
                serveur.appels += 1
                corps = json.dumps(serveur._jwks).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(corps)))
                self.end_headers()
                self.wfile.write(corps)

            def log_message(self, *args: object) -> None:
                return

        self._httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._httpd.server_port}/certs"
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    def set_jwks(self, jwks: dict[str, object]) -> None:
        self._jwks = jwks

    def __enter__(self) -> "JwksServer":
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()


def paire_de_cles(kid: str = "cle-test") -> tuple[rsa.RSAPrivateKey, dict[str, object]]:
    cle = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cle.public_key()))
    jwk.update({"kid": kid, "use": "sig", "alg": "RS256"})
    return cle, {"keys": [jwk]}


def forge(cle: rsa.RSAPrivateKey, kid: str = "cle-test", **overrides: object) -> str:
    """Fabrique un token de test réellement signé (RS256).

    Un payload par ailleurs intégralement valide, avec `overrides` pour ne
    faire varier qu'un seul claim à la fois — c'est ce qui permet à chaque
    test de rejet d'isoler la protection qu'il prétend couvrir.
    """
    payload: dict[str, object] = {
        "sub": "bot-slack-support",
        "sorabel_profile": "support",
        "iss": ISSUER,
        "aud": AUDIENCE,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
    }
    payload.update(overrides)
    return jwt.encode(payload, cle, algorithm="RS256", headers={"kid": kid})


def test_verifie_une_signature_contre_un_jwks_reellement_servi() -> None:
    # Arrange
    cle, jwks = paire_de_cles()
    with JwksServer(jwks) as serveur:
        verifier = JwksTokenVerifier(serveur.url, ISSUER, AUDIENCE, timeout_s=5.0)

        # Act
        identity = verifier.verify(forge(cle))

    # Assert
    assert identity.profile == "support"
    assert identity.subject == "bot-slack-support"


def test_les_cles_sont_mises_en_cache_entre_deux_verifications() -> None:
    # Arrange
    cle, jwks = paire_de_cles()
    with JwksServer(jwks) as serveur:
        verifier = JwksTokenVerifier(serveur.url, ISSUER, AUDIENCE, timeout_s=5.0)

        # Act
        verifier.verify(forge(cle))
        verifier.verify(forge(cle))

        # Assert — un seul aller-retour réseau (préchargement au démarrage
        # inclus) pour la construction et les deux vérifications : si le
        # cache était désactivé ou contourné, ce compteur monterait à 3.
        assert serveur.appels == 1


def test_une_rotation_de_cle_est_prise_en_compte_apres_le_cache() -> None:
    # Arrange — l'IdP publie d'abord la clé A seule
    cle_a, jwks_a = paire_de_cles(kid="cle-a")
    cle_b, jwks_b = paire_de_cles(kid="cle-b")
    with JwksServer(jwks_a) as serveur:
        verifier = JwksTokenVerifier(serveur.url, ISSUER, AUDIENCE, timeout_s=5.0)
        verifier.verify(forge(cle_a, kid="cle-a"))
        appels_avant_rotation = serveur.appels

        # Act — rotation : l'IdP ne publie désormais plus que la clé B
        serveur.set_jwks(jwks_b)
        identity = verifier.verify(forge(cle_b, kid="cle-b"))

    # Assert — la nouvelle clé est acceptée (si le cache ignorait
    # définitivement les `kid` inconnus, ce `verify` lèverait
    # `InvalidTokenError` au lieu de renvoyer une identité), et sa
    # découverte a bien coûté un nouvel appel réseau (si l'implémentation ne
    # rafraîchissait jamais son cache, ce compteur n'aurait pas bougé).
    assert identity.subject == "bot-slack-support"
    assert serveur.appels > appels_avant_rotation


def test_apres_expiration_du_cache_une_cle_revoquee_est_refusee() -> None:
    """Direction dangereuse de la rotation : une clé retirée du JWKS (ex.
    compromission) doit cesser d'être acceptée une fois le cache expiré —
    pas seulement une nouvelle clé sous un nouveau `kid` acceptée (déjà
    couvert par le test de rotation ci-dessus, direction inoffensive).
    """
    # Arrange — la clé A est publiée et acceptée une première fois
    cle_a, jwks_a = paire_de_cles(kid="cle-a")
    _, jwks_b = paire_de_cles(kid="cle-b")
    with JwksServer(jwks_a) as serveur:
        verifier = JwksTokenVerifier(serveur.url, ISSUER, AUDIENCE, timeout_s=5.0)
        token_ancien = forge(cle_a, kid="cle-a")
        verifier.verify(token_ancien)  # accepté tant que la clé A est publiée

        # Act — la clé A est retirée du JWKS (révocation), et on force
        # l'expiration du cache tier-1 (sans attendre les 5 minutes de TTL
        # par défaut) pour simuler l'écoulement du temps après la révocation.
        # Une durée de vie de 0 ne suffit pas toujours : `is_expired()`
        # exige une comparaison strictement supérieure au timestamp de mise
        # en cache, et le prochain appel peut retomber sur le même instant
        # `monotonic()` ; une valeur négative (mais > -1, sentinelle
        # « jamais expirer ») garantit un TTL déjà dépassé.
        serveur.set_jwks(jwks_b)
        verifier._client.jwk_set_cache.lifespan = -0.5  # type: ignore[union-attr]

        # Assert — le même token, signé par une clé désormais révoquée,
        # n'est plus accepté. Si le cache par `kid` (tier-2, sans expiration
        # temporelle) était réactivé, `verifier` répondrait toujours depuis
        # ce cache sans jamais retourner interroger le JWKS, et cette
        # assertion échouerait.
        with pytest.raises(InvalidTokenError):
            verifier.verify(token_ancien)


def test_une_signature_falsifiee_sous_un_kid_valide_est_refusee() -> None:
    """Isole la vérification cryptographique elle-même, pas la résolution du
    `kid`. Le token est signé par une clé privée qui n'est pas celle du
    JWKS, mais revendique le `kid` réellement publié : la résolution du
    `kid` réussit (elle trouve la vraie clé publique), donc seule la
    comparaison de signature dans `jwt.decode` peut faire échouer ce test.
    Si `jwt.decode` était appelé avec `options={"verify_signature": False}`,
    ce test échouerait — les claims sont par ailleurs entièrement valides.
    """
    # Arrange — le JWKS publie la clé légitime sous "cle-legitime" ; le
    # token est forgé avec une tout autre clé privée, sous ce même kid.
    _, jwks = paire_de_cles(kid="cle-legitime")
    cle_attaquant, _ = paire_de_cles(kid="cle-legitime")
    with JwksServer(jwks) as serveur:
        verifier = JwksTokenVerifier(serveur.url, ISSUER, AUDIENCE, timeout_s=5.0)
        faux = forge(cle_attaquant, kid="cle-legitime")

        # Act / Assert
        with pytest.raises(InvalidTokenError):
            verifier.verify(faux)


def test_une_cle_inconnue_est_refusee() -> None:
    # Arrange — le token est signé par une clé absente du JWKS servi, avec
    # un payload par ailleurs entièrement valide : le rejet ne peut donc
    # venir que de l'absence de la clé, pas d'un autre garde.
    _, jwks = paire_de_cles()
    autre_cle, _ = paire_de_cles()
    with JwksServer(jwks) as serveur:
        verifier = JwksTokenVerifier(serveur.url, ISSUER, AUDIENCE, timeout_s=5.0)

        # Act / Assert
        with pytest.raises(InvalidTokenError):
            verifier.verify(forge(autre_cle, kid="cle-inconnue"))


def test_un_jwks_injoignable_refuse_le_token() -> None:
    # Arrange — port fermé, y compris pour le préchargement au démarrage
    verifier = JwksTokenVerifier("http://127.0.0.1:1/certs", ISSUER, AUDIENCE, timeout_s=1.0)
    cle, _ = paire_de_cles()

    # Act / Assert — jamais d'acceptation par défaut quand l'IdP est muet
    with pytest.raises(InvalidTokenError):
        verifier.verify(forge(cle))


def test_un_mauvais_emetteur_est_refuse() -> None:
    # Arrange — payload par ailleurs valide, seul `iss` diffère.
    cle, jwks = paire_de_cles()
    with JwksServer(jwks) as serveur:
        verifier = JwksTokenVerifier(serveur.url, ISSUER, AUDIENCE, timeout_s=5.0)
        mauvais_emetteur = forge(cle, iss="https://attaquant.test/realms/autre")

        # Act / Assert
        with pytest.raises(InvalidTokenError):
            verifier.verify(mauvais_emetteur)


def test_une_mauvaise_audience_est_refusee() -> None:
    # Arrange — payload par ailleurs valide, seule `aud` diffère.
    cle, jwks = paire_de_cles()
    with JwksServer(jwks) as serveur:
        verifier = JwksTokenVerifier(serveur.url, ISSUER, AUDIENCE, timeout_s=5.0)
        mauvaise_audience = forge(cle, aud="autre-service")

        # Act / Assert
        with pytest.raises(InvalidTokenError):
            verifier.verify(mauvaise_audience)


def test_un_token_expire_est_refuse() -> None:
    # Arrange — payload par ailleurs valide, seule `exp` est passée.
    cle, jwks = paire_de_cles()
    with JwksServer(jwks) as serveur:
        verifier = JwksTokenVerifier(serveur.url, ISSUER, AUDIENCE, timeout_s=5.0)
        expire = forge(cle, exp=datetime.now(timezone.utc) - timedelta(seconds=1))

        # Act / Assert
        with pytest.raises(InvalidTokenError):
            verifier.verify(expire)


def test_un_claim_de_profil_absent_est_refuse() -> None:
    # Arrange — token par ailleurs valide (signature, iss, aud, exp), mais
    # sans le claim `sorabel_profile`.
    cle, jwks = paire_de_cles()
    with JwksServer(jwks) as serveur:
        verifier = JwksTokenVerifier(serveur.url, ISSUER, AUDIENCE, timeout_s=5.0)
        sans_profil = jwt.encode(
            {
                "sub": "bot-slack-support",
                "iss": ISSUER,
                "aud": AUDIENCE,
                "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
            },
            cle,
            algorithm="RS256",
            headers={"kid": "cle-test"},
        )

        # Act / Assert
        with pytest.raises(InvalidTokenError):
            verifier.verify(sans_profil)


def test_un_claim_de_sujet_absent_est_refuse() -> None:
    # Arrange — token par ailleurs valide, `sorabel_profile` présent, mais
    # sans `sub` : branche symétrique du garde combiné ci-dessus.
    cle, jwks = paire_de_cles()
    with JwksServer(jwks) as serveur:
        verifier = JwksTokenVerifier(serveur.url, ISSUER, AUDIENCE, timeout_s=5.0)
        sans_sujet = jwt.encode(
            {
                "sorabel_profile": "support",
                "iss": ISSUER,
                "aud": AUDIENCE,
                "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
            },
            cle,
            algorithm="RS256",
            headers={"kid": "cle-test"},
        )

        # Act / Assert
        with pytest.raises(InvalidTokenError):
            verifier.verify(sans_sujet)


def test_les_messages_de_rejet_sont_indistinguables() -> None:
    """Les causes de rejet cryptographiques/de claims ne doivent jamais être
    distinguables à la lecture du message — même discipline que la tâche 7.
    """
    # Arrange
    cle, jwks = paire_de_cles(kid="cle-legitime")
    cle_attaquant, _ = paire_de_cles(kid="cle-legitime")
    with JwksServer(jwks) as serveur:
        verifier = JwksTokenVerifier(serveur.url, ISSUER, AUDIENCE, timeout_s=5.0)
        tokens_invalides = [
            forge(cle_attaquant, kid="cle-legitime"),  # signature falsifiée
            forge(cle, iss="https://attaquant.test/realms/autre"),  # mauvais émetteur
            forge(cle, aud="autre-service"),  # mauvaise audience
            forge(cle, exp=datetime.now(timezone.utc) - timedelta(seconds=1)),  # expiré
        ]

        # Act / Assert
        for token in tokens_invalides:
            with pytest.raises(InvalidTokenError) as excinfo:
                verifier.verify(token)
            assert str(excinfo.value) == "token invalide"


def test_build_token_verifier_refuse_emetteur_ou_audience_vide() -> None:
    # Arrange — adapter `local` par ailleurs valide (secret présent), pour
    # isoler ce garde de celui, spécifique à `local`, sur `MCP_ENV`/le
    # secret : ce garde doit être hissé dans `build_token_verifier` (donc
    # valoir aussi pour `local`), pas seulement `build_local_verifier`.
    settings = Settings(
        _env_file=None,
        mcp_env="dev",
        mcp_token_verifier="local",
        mcp_dev_jwt_secret="un-secret-de-dev",
        mcp_jwt_issuer="",
        mcp_jwt_audience="",
    )

    # Act / Assert
    with pytest.raises(UnsafeVerifierConfiguration, match="MCP_JWT_ISSUER"):
        build_token_verifier(settings)


def test_build_token_verifier_refuse_jwks_url_vide() -> None:
    # Arrange — issuer/audience renseignés pour isoler ce garde du premier.
    settings = Settings(
        _env_file=None,
        mcp_env="prod",
        mcp_token_verifier="jwks",
        mcp_jwks_url="",
        mcp_jwt_issuer=ISSUER,
        mcp_jwt_audience=AUDIENCE,
    )

    # Act / Assert
    with pytest.raises(UnsafeVerifierConfiguration, match="MCP_JWKS_URL"):
        build_token_verifier(settings)


def test_build_token_verifier_refuse_un_adaptateur_inconnu() -> None:
    # Arrange — `MCP_TOKEN_VERIFIER` est un `Literal["local", "jwks"]` :
    # `Settings(...)` normal ne peut donc pas construire une valeur
    # inconnue. `model_construct` contourne cette validation pour exercer
    # le garde fail-closed de `build_token_verifier` lui-même, seconde ligne
    # de défense si le typage était un jour affaibli.
    settings = Settings.model_construct(
        mcp_token_verifier=cast(Any, "carrier-pigeon"),
        mcp_jwt_issuer=ISSUER,
        mcp_jwt_audience=AUDIENCE,
    )

    # Act / Assert
    with pytest.raises(UnsafeVerifierConfiguration, match="MCP_TOKEN_VERIFIER"):
        build_token_verifier(settings)


def test_build_token_verifier_selectionne_local() -> None:
    # Arrange
    settings = Settings(
        _env_file=None,
        mcp_env="dev",
        mcp_token_verifier="local",
        mcp_dev_jwt_secret="un-secret-de-dev",
        mcp_jwt_issuer=ISSUER,
        mcp_jwt_audience=AUDIENCE,
    )

    # Act
    verifier = build_token_verifier(settings)

    # Assert
    assert isinstance(verifier, LocalKeyTokenVerifier)


def test_build_token_verifier_selectionne_jwks() -> None:
    # Arrange — port fermé : la construction ne doit pas en dépendre
    # (préchargement meilleur effort), seul le choix d'adapter est vérifié.
    settings = Settings(
        _env_file=None,
        mcp_env="prod",
        mcp_token_verifier="jwks",
        mcp_jwks_url="http://127.0.0.1:1/certs",
        mcp_jwt_issuer=ISSUER,
        mcp_jwt_audience=AUDIENCE,
        mcp_http_timeout_s=1.0,
    )

    # Act
    verifier = build_token_verifier(settings)

    # Assert
    assert isinstance(verifier, JwksTokenVerifier)

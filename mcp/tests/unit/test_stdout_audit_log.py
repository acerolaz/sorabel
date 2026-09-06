import io
import json
from datetime import datetime, timezone

import pytest
from app.domain.models import AuditEntry
from app.infrastructure.audit.stdout_audit_log import StdoutAuditLog


def entree(**overrides: object) -> AuditEntry:
    valeurs: dict[str, object] = {
        "timestamp": datetime(2026, 9, 4, 10, 0, tzinfo=timezone.utc),
        "correlation_id": "corr-1",
        "subject": "poste-vente-42",
        "profile": "sales",
        "tool": "get_stock",
        "arguments": {"product_ref": "REF-8842"},
        "decision": "allow",
        "rule": "sales.tools",
        "backend": "stub",
        "row_count": 3,
        "latency_ms": 12,
    }
    valeurs.update(overrides)
    return AuditEntry(**valeurs)  # type: ignore[arg-type]


def test_ecrit_une_ligne_json_par_appel() -> None:
    # Arrange
    flux = io.StringIO()
    journal = StdoutAuditLog(stream=flux)

    # Act
    journal.record(entree())
    journal.record(entree(decision="deny", error_code="UNAUTHORIZED_TOOL"))

    # Assert
    lignes = flux.getvalue().strip().splitlines()
    assert len(lignes) == 2
    assert json.loads(lignes[0])["decision"] == "allow"
    assert json.loads(lignes[1])["error_code"] == "UNAUTHORIZED_TOOL"


def test_journalise_tous_les_champs_exiges_par_e5() -> None:
    # Arrange
    flux = io.StringIO()

    # Act
    StdoutAuditLog(stream=flux).record(entree())

    # Assert
    ligne = json.loads(flux.getvalue())
    assert set(ligne) >= {
        "timestamp",
        "correlation_id",
        "subject",
        "profile",
        "tool",
        "arguments",
        "decision",
        "rule",
        "backend",
        "row_count",
        "latency_ms",
    }


def test_la_ligne_json_ne_porte_aucune_cle_hors_de_auditentry() -> None:
    # Arrange — remplace l'assertion tautologique du brief ("rows" not in ligne,
    # vraie par construction puisque AuditEntry n'a pas de champ "rows") par une
    # vérification de la liste EXHAUSTIVE des clés produites, en dur : c'est ce
    # qui verrouille réellement la frontière de journalisation de la spec §8
    # (la requête est journalisée, jamais le résultat, seul son row_count l'est).
    flux = io.StringIO()

    # Act
    StdoutAuditLog(stream=flux).record(entree(row_count=42))

    # Assert
    ligne = json.loads(flux.getvalue())
    assert set(ligne) == {
        "timestamp",
        "correlation_id",
        "subject",
        "profile",
        "tool",
        "arguments",
        "decision",
        "rule",
        "backend",
        "row_count",
        "latency_ms",
        "error_code",
    }
    assert ligne["row_count"] == 42
    assert "rows" not in ligne
    assert "result" not in ligne


def test_record_ne_leve_jamais_meme_avec_un_argument_non_serialisable() -> None:
    # Arrange — un dict circulaire fait déjà échouer `dataclasses.asdict`, en
    # amont de `json.dumps` : la conversion récursive de `arguments` boucle et
    # lève `RecursionError` avant même la sérialisation. C'est le cas
    # réellement pathologique, pas un cas théorique.
    flux = io.StringIO()
    journal = StdoutAuditLog(stream=flux)
    argument_circulaire: dict[str, object] = {}
    argument_circulaire["self"] = argument_circulaire

    # Act — ne doit lever aucune exception
    journal.record(entree(arguments=argument_circulaire))

    # Assert — l'échec de sérialisation n'écrit rien sur le canal d'audit
    assert flux.getvalue() == ""


def test_record_ne_leve_jamais_avec_un_type_non_serialisable_convertible() -> None:
    # Arrange — un objet non JSON-natif mais convertible par `str()` : la ligne
    # est bien écrite, avec la représentation texte de l'objet.
    class Reference:
        def __str__(self) -> str:
            return "REF-8842"

    flux = io.StringIO()
    journal = StdoutAuditLog(stream=flux)

    # Act
    journal.record(entree(arguments={"product_ref": Reference()}))

    # Assert
    ligne = json.loads(flux.getvalue())
    assert ligne["arguments"] == {"product_ref": "REF-8842"}


def test_echec_de_serialisation_est_signale_sur_stderr_jamais_sur_le_flux(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Arrange
    flux = io.StringIO()
    journal = StdoutAuditLog(stream=flux)
    argument_circulaire: dict[str, object] = {}
    argument_circulaire["self"] = argument_circulaire

    # Act
    journal.record(entree(arguments=argument_circulaire))

    # Assert — l'avertissement, s'il existe, ne va jamais sur le flux d'audit
    capture = capsys.readouterr()
    assert flux.getvalue() == ""
    assert capture.out == ""


def test_stream_par_defaut_est_sys_stdout(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Arrange
    journal = StdoutAuditLog()

    # Act
    journal.record(entree())

    # Assert
    capture = capsys.readouterr()
    ligne = json.loads(capture.out.strip())
    assert ligne["tool"] == "get_stock"

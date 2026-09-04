import json
import sys
from dataclasses import asdict
from typing import TextIO

from app.domain.models import AuditEntry


class StdoutAuditLog:
    """Journal append-only : une ligne JSON par appel, sur un flux texte.

    Aucun contenu métier n'est écrit — l'entrée elle-même ne porte que des
    métadonnées de résultat (`row_count`, `latency_ms`), par construction
    (spec §8, `.claude/rules/security.md`).

    Contrat de `record` (`AuditLogPort`, ruling t6) : ne lève **jamais**. Un
    échec de sérialisation ou d'écriture est absorbé ici et, s'il est
    signalé, l'est sur `stderr` — jamais sur `stream`, qui est le canal
    d'audit lui-même (réservé à `stdout` par défaut).
    """

    def __init__(self, stream: TextIO | None = None) -> None:
        self._stream = stream if stream is not None else sys.stdout

    def record(self, entry: AuditEntry) -> None:
        try:
            ligne = asdict(entry)
            ligne["timestamp"] = entry.timestamp.isoformat()
            texte = json.dumps(ligne, ensure_ascii=False, default=str)
        except Exception as exc:
            print(
                f"[mcp] avertissement : entrée d'audit non sérialisable, ligne perdue ({exc}).",
                file=sys.stderr,
            )
            return

        try:
            self._stream.write(texte + "\n")
            self._stream.flush()
        except Exception as exc:
            print(
                f"[mcp] avertissement : écriture du journal d'audit échouée ({exc}).",
                file=sys.stderr,
            )

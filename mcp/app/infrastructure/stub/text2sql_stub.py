"""Doublure de l'agent Text-to-SQL (`text2sql-ai`, spec §9.2) : génère du SQL
de lecture seule plausible, n'exécute jamais.

Une séquence `tables` vide signifie un périmètre autorisé de zéro table pour
le profil appelant — jamais l'absence de filtre (spec §4.2, ports.py) : aucune
génération n'est alors possible sur une table par défaut ou devinée.
"""

from collections.abc import Sequence
from typing import Any

from app.domain.errors import SchemaMismatchError


class Text2SqlStub:
    """Doublure de l'agent Text-to-SQL : génère, n'exécute jamais."""

    async def generate_sql(
        self, question: str, profile: str, tables: Sequence[str], correlation_id: str
    ) -> dict[str, Any]:
        if not tables:
            raise SchemaMismatchError(correlation_id)
        return {
            "source": "stub",
            "sql": f"SELECT * FROM {tables[0]} LIMIT 100",
            "tables": list(tables),
            "question": question,
        }

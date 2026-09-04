"""Loads the static commented schema (one YAML file per table, per
Text2SQL_Sorabel.md §4) once, at construction time, and serves filtered subsets of
it. Implements SchemaRepositoryPort. Also loads the two sibling ingredient files
(business_rules.yaml, few_shot.yaml) used by domain/prompt.py."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import yaml  # type: ignore[import-untyped]

from app.domain.errors import SchemaLoadError
from app.domain.models import SchemaColumn, SchemaTable

SCHEMA_DIR = Path(__file__).parent

_RESERVED_FILES = {"business_rules.yaml", "few_shot.yaml"}


def _load_table(path: Path) -> SchemaTable:
    """Parse one table YAML file. A missing or malformed key raises SchemaLoadError
    naming the file, so the failure is diagnosable at boot (see app/main.py's
    lifespan) instead of surfacing as a bare KeyError on every request."""
    try:
        data = cast(dict[str, Any], yaml.safe_load(path.read_text()))
        columns = [
            SchemaColumn(
                name=col["name"],
                type=col["type"],
                comment=col["comment"],
                is_primary_key=col.get("is_primary_key", False),
                is_foreign_key=col.get("is_foreign_key", False),
                enum_values=col.get("enum_values", []),
            )
            for col in data["columns"]
        ]
        return SchemaTable(name=data["name"], comment=data["comment"], columns=columns)
    except (KeyError, TypeError) as exc:
        raise SchemaLoadError(f"schéma de table invalide dans {path.name} : {exc}") from exc
    except yaml.YAMLError as exc:
        raise SchemaLoadError(f"YAML illisible dans {path.name} : {exc}") from exc


def load_business_rules(schema_dir: Path) -> dict[str, str]:
    path = schema_dir / "business_rules.yaml"
    if not path.exists():
        return {}
    return cast(dict[str, str], yaml.safe_load(path.read_text())) or {}


def load_few_shot_examples(schema_dir: Path) -> list[dict[str, str]]:
    path = schema_dir / "few_shot.yaml"
    if not path.exists():
        return []
    return cast(list[dict[str, str]], yaml.safe_load(path.read_text())) or []


class YamlSchemaRepository:
    """Implements SchemaRepositoryPort by loading every *.yaml file (excluding the
    reserved ingredient files) in a directory once, at construction time."""

    def __init__(self, schema_dir: Path = SCHEMA_DIR) -> None:
        self._tables: dict[str, SchemaTable] = {}
        for path in sorted(schema_dir.glob("*.yaml")):
            if path.name in _RESERVED_FILES:
                continue
            table = _load_table(path)
            self._tables[table.name] = table

    def get_tables(self, allowed_tables: list[str]) -> list[SchemaTable]:
        return [self._tables[name] for name in allowed_tables if name in self._tables]

    def all_table_names(self) -> list[str]:
        return list(self._tables.keys())

    def all_column_names(self) -> set[str]:
        return {c.name for t in self._tables.values() for c in t.columns}

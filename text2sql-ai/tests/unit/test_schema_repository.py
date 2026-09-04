from pathlib import Path

import pytest
from app.domain.errors import SchemaLoadError
from app.infrastructure.schema.repository import (
    YamlSchemaRepository,
    load_business_rules,
    load_few_shot_examples,
)


def _write_table(dir_path: Path, name: str) -> None:
    (dir_path / f"{name}.yaml").write_text(
        f"name: {name}\n"
        f"comment: table {name}\n"
        "columns:\n"
        "  - name: id\n"
        "    type: integer\n"
        "    comment: identifiant\n"
        "    is_primary_key: true\n"
    )


def test_get_tables_filters_by_allowed_list(tmp_path):
    _write_table(tmp_path, "stock")
    _write_table(tmp_path, "products")
    repo = YamlSchemaRepository(schema_dir=tmp_path)

    result = repo.get_tables(["stock"])

    assert [t.name for t in result] == ["stock"]


def test_get_tables_silently_drops_unknown_table(tmp_path):
    _write_table(tmp_path, "stock")
    repo = YamlSchemaRepository(schema_dir=tmp_path)

    result = repo.get_tables(["stock", "does_not_exist"])

    assert [t.name for t in result] == ["stock"]


def test_get_tables_loads_column_flags(tmp_path):
    _write_table(tmp_path, "stock")
    repo = YamlSchemaRepository(schema_dir=tmp_path)

    table = repo.get_tables(["stock"])[0]

    assert table.columns[0].is_primary_key is True


def test_all_table_names_lists_everything_unfiltered(tmp_path):
    _write_table(tmp_path, "stock")
    _write_table(tmp_path, "products")
    repo = YamlSchemaRepository(schema_dir=tmp_path)

    assert set(repo.all_table_names()) == {"stock", "products"}


def test_reserved_files_are_not_loaded_as_tables(tmp_path):
    _write_table(tmp_path, "stock")
    (tmp_path / "business_rules.yaml").write_text('"CA du mois": "definition"\n')
    (tmp_path / "few_shot.yaml").write_text("- question: q\n  sql: s\n")

    repo = YamlSchemaRepository(schema_dir=tmp_path)

    assert set(repo.all_table_names()) == {"stock"}


def test_load_business_rules_reads_yaml_dict(tmp_path):
    (tmp_path / "business_rules.yaml").write_text('"CA du mois": "definition"\n')

    rules = load_business_rules(tmp_path)

    assert rules == {"CA du mois": "definition"}


def test_load_few_shot_examples_reads_yaml_list(tmp_path):
    (tmp_path / "few_shot.yaml").write_text("- question: q\n  sql: s\n")

    examples = load_few_shot_examples(tmp_path)

    assert examples == [{"question": "q", "sql": "s"}]


def test_malformed_table_file_raises_a_contextual_schema_load_error(tmp_path):
    (tmp_path / "stock.yaml").write_text("name: stock\ncomment: stock\n")

    with pytest.raises(SchemaLoadError) as excinfo:
        YamlSchemaRepository(schema_dir=tmp_path)

    assert "stock.yaml" in str(excinfo.value)


def test_table_file_with_incomplete_column_raises_schema_load_error(tmp_path):
    (tmp_path / "stock.yaml").write_text("name: stock\ncomment: stock\ncolumns:\n  - name: id\n")

    with pytest.raises(SchemaLoadError):
        YamlSchemaRepository(schema_dir=tmp_path)

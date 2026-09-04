from app.domain.models import SchemaColumn, SchemaTable
from app.domain.prompt import build_system_prompt

STOCK_TABLE = SchemaTable(
    name="stock",
    comment="Niveaux de stock",
    columns=[
        SchemaColumn(
            name="status",
            type="varchar",
            comment="statut",
            enum_values=["pending", "shipped"],
        ),
    ],
)

PRODUCTS_TABLE = SchemaTable(name="products", comment="Catalogue", columns=[])


def test_prompt_includes_only_filtered_schema():
    prompt = build_system_prompt([STOCK_TABLE], {}, [])

    assert "stock" in prompt
    assert "products" not in prompt


def test_prompt_spells_out_enum_values():
    prompt = build_system_prompt([STOCK_TABLE], {}, [])

    assert "'pending'" in prompt
    assert "'shipped'" in prompt


def test_prompt_includes_critical_instruction():
    prompt = build_system_prompt([STOCK_TABLE], {}, [])

    assert "CRITICAL" in prompt


def test_prompt_includes_readonly_instruction():
    prompt = build_system_prompt([STOCK_TABLE], {}, [])

    assert "lecture seule" in prompt


def test_prompt_includes_business_rules():
    prompt = build_system_prompt(
        [STOCK_TABLE], {"CA du mois": "SUM(amount) WHERE status != 'cancelled'"}, []
    )

    assert "CA du mois" in prompt


def test_prompt_includes_few_shot_examples():
    prompt = build_system_prompt([STOCK_TABLE], {}, [{"question": "stock ?", "sql": "SELECT 1"}])

    assert "stock ?" in prompt
    assert "SELECT 1" in prompt

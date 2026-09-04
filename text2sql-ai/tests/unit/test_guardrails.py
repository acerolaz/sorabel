from app.domain.guardrails import check_ast, check_blocklist, validate
from app.domain.models import SchemaColumn, SchemaTable

STOCK_TABLE = SchemaTable(
    name="stock",
    comment="stock",
    columns=[
        SchemaColumn(name="product_ref", type="varchar", comment="ref"),
        SchemaColumn(name="quantity", type="integer", comment="qty"),
    ],
)


def test_blocklist_catches_delete():
    violation = check_blocklist("DELETE FROM stock WHERE product_ref = 'REF-1'")

    assert violation is not None
    assert violation.rule == "blocklist"


def test_blocklist_catches_delete_inside_cte():
    sql = "WITH x AS (DELETE FROM stock RETURNING *) SELECT * FROM x"

    assert check_blocklist(sql) is not None


def test_blocklist_allows_plain_select():
    assert check_blocklist("SELECT quantity FROM stock") is None


def test_ast_rejects_multiple_statements():
    sql = "SELECT quantity FROM stock; SELECT quantity FROM stock;"

    violation = check_ast(sql, [STOCK_TABLE])

    assert violation is not None
    assert violation.rule == "ast"


def test_ast_rejects_unauthorized_table():
    sql = "SELECT product_ref FROM products"

    assert check_ast(sql, [STOCK_TABLE]) is not None


def test_ast_rejects_unauthorized_column():
    sql = "SELECT unknown_column FROM stock"

    assert check_ast(sql, [STOCK_TABLE]) is not None


def test_ast_accepts_valid_select():
    sql = "SELECT quantity FROM stock WHERE product_ref = 'REF-8842'"

    assert check_ast(sql, [STOCK_TABLE]) is None


def test_ast_rejects_non_select_statement():
    violation = check_ast("EXPLAIN SELECT quantity FROM stock", [STOCK_TABLE])

    assert violation is not None
    assert violation.rule == "ast"


def test_validate_runs_blocklist_before_ast():
    violation = validate("DROP TABLE stock", [STOCK_TABLE])

    assert violation is not None
    assert violation.rule == "blocklist"


def test_validate_returns_none_for_valid_sql():
    assert validate("SELECT quantity FROM stock", [STOCK_TABLE]) is None


def test_ast_accepts_benign_cte():
    sql = "WITH x AS (SELECT quantity FROM stock) SELECT * FROM x"

    assert check_ast(sql, [STOCK_TABLE]) is None


def test_ast_rejects_cte_reading_unauthorized_table():
    sql = "WITH x AS (SELECT * FROM products) SELECT * FROM x"

    assert check_ast(sql, [STOCK_TABLE]) is not None

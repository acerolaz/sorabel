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

ORDERS_TABLE = SchemaTable(
    name="orders",
    comment="commandes",
    columns=[
        SchemaColumn(name="id", type="integer", comment="id"),
        SchemaColumn(name="status", type="varchar", comment="statut"),
        SchemaColumn(name="customer_id", type="integer", comment="client"),
    ],
)

CUSTOMERS_TABLE = SchemaTable(
    name="customers",
    comment="clients",
    columns=[
        SchemaColumn(name="id", type="integer", comment="id"),
        SchemaColumn(name="name", type="varchar", comment="nom"),
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


def test_ast_accepts_table_alias_without_as():
    sql = "SELECT s.quantity FROM stock s"

    assert check_ast(sql, [STOCK_TABLE]) is None


def test_ast_accepts_table_alias_with_as():
    sql = "SELECT s.quantity FROM stock AS s"

    assert check_ast(sql, [STOCK_TABLE]) is None


def test_ast_accepts_aliased_join_across_two_tables():
    sql = "SELECT o.status, c.name FROM orders o JOIN customers c ON c.id = o.customer_id"

    assert check_ast(sql, [ORDERS_TABLE, CUSTOMERS_TABLE]) is None


def test_ast_rejects_unauthorized_column_behind_an_alias():
    sql = "SELECT s.unknown_column FROM stock s"

    violation = check_ast(sql, [STOCK_TABLE])

    assert violation is not None
    assert violation.rule == "ast"


def test_ast_rejects_column_qualified_by_the_wrong_alias():
    sql = "SELECT o.quantity FROM orders o"

    assert check_ast(sql, [ORDERS_TABLE, STOCK_TABLE]) is not None


def test_ast_accepts_aliased_cte():
    sql = "WITH x AS (SELECT quantity FROM stock) SELECT y.quantity FROM x AS y"

    assert check_ast(sql, [STOCK_TABLE]) is None


def test_ast_rejects_schema_qualified_table():
    sql = "SELECT quantity FROM other_schema.stock"

    violation = check_ast(sql, [STOCK_TABLE])

    assert violation is not None
    assert violation.rule == "ast"


def test_ast_rejects_catalog_qualified_table():
    sql = "SELECT quantity FROM other_db.public.stock"

    assert check_ast(sql, [STOCK_TABLE]) is not None

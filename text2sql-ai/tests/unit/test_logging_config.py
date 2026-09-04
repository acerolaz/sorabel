import json
import logging

from app.logging_config import JsonLogFormatter


def _record(**extra):
    record = logging.LogRecord(
        name="app.application.use_cases.generate_sql",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="text2sql_generation",
        args=(),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_formatter_promotes_the_audit_fields_to_json_keys():
    record = _record(
        profile="support",
        allowed_tables=["stock"],
        question="stock de la REF-8842 ?",
        sql="SELECT quantity FROM stock",
        outcome="generated",
        attempts=1,
    )

    payload = json.loads(JsonLogFormatter().format(record))

    assert payload["message"] == "text2sql_generation"
    assert payload["outcome"] == "generated"
    assert payload["profile"] == "support"
    assert payload["allowed_tables"] == ["stock"]
    assert payload["attempts"] == 1


def test_formatter_omits_audit_fields_that_are_absent():
    payload = json.loads(JsonLogFormatter().format(_record()))

    assert "outcome" not in payload
    assert payload["level"] == "INFO"


def test_formatter_keeps_accents_readable():
    payload = JsonLogFormatter().format(_record(question="quelle référence ?"))

    assert "référence" in payload

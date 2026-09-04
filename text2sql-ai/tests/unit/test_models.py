from app.domain.models import (
    GenerationOutcome,
    GenerationOutcomeType,
    GenerationRequest,
    GuardrailViolation,
    JudgeVerdict,
    JudgeVerdictLabel,
    SchemaColumn,
    SchemaTable,
    SqlCandidate,
)


def test_schema_table_holds_columns():
    column = SchemaColumn(name="quantity", type="integer", comment="qty")
    table = SchemaTable(name="stock", comment="stock levels", columns=[column])

    assert table.name == "stock"
    assert table.columns == [column]


def test_schema_column_defaults():
    column = SchemaColumn(name="id", type="integer", comment="id")

    assert column.is_primary_key is False
    assert column.is_foreign_key is False
    assert column.enum_values == []


def test_generation_request_holds_allowed_tables():
    request = GenerationRequest(question="q", profile="support", allowed_tables=["stock"])

    assert request.allowed_tables == ["stock"]


def test_sql_candidate_defaults_to_not_ambiguous():
    candidate = SqlCandidate(sql="SELECT 1", intent_reformulation="one")

    assert candidate.is_ambiguous is False
    assert candidate.clarification_needed is None
    assert candidate.is_out_of_schema is False


def test_judge_verdict_label_values_match_api_contract():
    assert JudgeVerdictLabel.ALIGNED.value == "ALIGNED"
    assert JudgeVerdictLabel.DRIFT.value == "DRIFT"
    assert JudgeVerdictLabel.UNCERTAIN.value == "UNCERTAIN"


def test_generation_outcome_type_values_match_api_contract():
    assert GenerationOutcomeType.GENERATED.value == "generated"
    assert GenerationOutcomeType.NEEDS_CLARIFICATION.value == "needs_clarification"
    assert GenerationOutcomeType.REFUSED_OUT_OF_SCHEMA.value == "refused_out_of_schema"
    assert GenerationOutcomeType.REJECTED_GUARDRAIL.value == "rejected_guardrail"
    assert GenerationOutcomeType.REJECTED_JUDGE.value == "rejected_judge"


def test_generation_outcome_defaults():
    outcome = GenerationOutcome(outcome=GenerationOutcomeType.REFUSED_OUT_OF_SCHEMA)

    assert outcome.sql is None
    assert outcome.attempts == 0


def test_guardrail_violation_holds_rule_and_reason():
    violation = GuardrailViolation(rule="blocklist", reason="mot interdit")

    assert violation.rule == "blocklist"


def test_judge_verdict_holds_verdict_and_reason():
    verdict = JudgeVerdict(verdict=JudgeVerdictLabel.ALIGNED, reason="ok")

    assert verdict.verdict == JudgeVerdictLabel.ALIGNED

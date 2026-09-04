import logging

from app.application.use_cases.generate_sql import GenerateSqlUseCase
from app.domain.models import (
    GenerationOutcomeType,
    GenerationRequest,
    JudgeVerdict,
    JudgeVerdictLabel,
    SchemaColumn,
    SchemaTable,
    SqlCandidate,
)

STOCK_TABLE = SchemaTable(
    name="stock",
    comment="stock",
    columns=[
        SchemaColumn(name="product_ref", type="varchar", comment="ref"),
        SchemaColumn(name="quantity", type="integer", comment="qty"),
    ],
)


class FakeSchemaRepository:
    def __init__(self, tables):
        self._tables = {t.name: t for t in tables}

    def get_tables(self, allowed_tables):
        return [self._tables[name] for name in allowed_tables if name in self._tables]

    def all_table_names(self):
        return list(self._tables.keys())

    def all_column_names(self):
        return {c.name for t in self._tables.values() for c in t.columns}


class FakeLlm:
    def __init__(self, candidates):
        self._candidates = list(candidates)
        self.calls: list[str | None] = []

    async def generate(self, system_prompt, question, previous_attempt_feedback=None):
        self.calls.append(previous_attempt_feedback)
        return self._candidates.pop(0)


class FakeJudge:
    def __init__(self, verdicts):
        self._verdicts = list(verdicts)

    async def evaluate(self, question, intent_reformulation, sql):
        return self._verdicts.pop(0)


def make_use_case(tables, llm, judge):
    return GenerateSqlUseCase(
        schema_repository=FakeSchemaRepository(tables),
        llm=llm,
        judge=judge,
        business_rules={},
        few_shot_examples=[],
    )


async def test_happy_path_returns_generated():
    llm = FakeLlm([SqlCandidate(sql="SELECT quantity FROM stock", intent_reformulation="stock")])
    judge = FakeJudge([JudgeVerdict(verdict=JudgeVerdictLabel.ALIGNED, reason="ok")])
    use_case = make_use_case([STOCK_TABLE], llm, judge)

    outcome = await use_case.execute(
        GenerationRequest(
            question="stock de la REF-8842", profile="support", allowed_tables=["stock"]
        )
    )

    assert outcome.outcome == GenerationOutcomeType.GENERATED
    assert outcome.sql == "SELECT quantity FROM stock"
    assert outcome.attempts == 1


async def test_empty_allowed_tables_refuses_out_of_schema():
    use_case = make_use_case([STOCK_TABLE], FakeLlm([]), FakeJudge([]))

    outcome = await use_case.execute(
        GenerationRequest(question="stock ?", profile="support", allowed_tables=[])
    )

    assert outcome.outcome == GenerationOutcomeType.REFUSED_OUT_OF_SCHEMA


async def test_model_flagging_out_of_schema_refuses_out_of_schema():
    llm = FakeLlm([SqlCandidate(sql="", intent_reformulation="", is_out_of_schema=True)])
    use_case = make_use_case([STOCK_TABLE], llm, FakeJudge([]))

    outcome = await use_case.execute(
        GenerationRequest(
            question="quel est le NPS de nos clients ?",
            profile="support",
            allowed_tables=["stock"],
        )
    )

    assert outcome.outcome == GenerationOutcomeType.REFUSED_OUT_OF_SCHEMA
    assert outcome.attempts == 1
    assert outcome.message is not None
    assert len(llm.calls) == 1


async def test_french_question_without_english_identifier_reaches_the_llm():
    """Regression: the lexical pre-check short-circuited any French question that
    did not literally contain an English schema identifier."""
    llm = FakeLlm([SqlCandidate(sql="SELECT quantity FROM stock", intent_reformulation="stock")])
    judge = FakeJudge([JudgeVerdict(verdict=JudgeVerdictLabel.ALIGNED, reason="ok")])
    use_case = make_use_case([STOCK_TABLE], llm, judge)

    outcome = await use_case.execute(
        GenerationRequest(
            question="Quel est le statut de la commande 12345 ?",
            profile="support",
            allowed_tables=["stock"],
        )
    )

    assert len(llm.calls) == 1
    assert outcome.outcome == GenerationOutcomeType.GENERATED


async def test_ambiguous_candidate_needs_clarification():
    llm = FakeLlm(
        [
            SqlCandidate(
                sql="",
                intent_reformulation="",
                is_ambiguous=True,
                clarification_needed="CA en montant ou en volume ?",
            )
        ]
    )
    use_case = make_use_case([STOCK_TABLE], llm, FakeJudge([]))

    outcome = await use_case.execute(
        GenerationRequest(
            question="quel est le meilleur produit en stock",
            profile="support",
            allowed_tables=["stock"],
        )
    )

    assert outcome.outcome == GenerationOutcomeType.NEEDS_CLARIFICATION
    assert outcome.message == "CA en montant ou en volume ?"


async def test_guardrail_violation_retries_then_rejects():
    candidate = SqlCandidate(sql="DROP TABLE stock", intent_reformulation="x")
    llm = FakeLlm([candidate, candidate, candidate])
    use_case = make_use_case([STOCK_TABLE], llm, FakeJudge([]))

    outcome = await use_case.execute(
        GenerationRequest(question="stock ?", profile="support", allowed_tables=["stock"])
    )

    assert outcome.outcome == GenerationOutcomeType.REJECTED_GUARDRAIL
    assert outcome.attempts == 3
    assert llm.calls[0] is None
    assert llm.calls[1] is not None
    assert "DROP TABLE stock" in llm.calls[1]


async def test_judge_drift_feedback_replays_the_rejected_sql():
    candidate = SqlCandidate(sql="SELECT quantity FROM stock", intent_reformulation="x")
    llm = FakeLlm([candidate, candidate, candidate])
    drift = JudgeVerdict(verdict=JudgeVerdictLabel.DRIFT, reason="mauvaise période")
    judge = FakeJudge([drift, drift, drift])
    use_case = make_use_case([STOCK_TABLE], llm, judge)

    await use_case.execute(
        GenerationRequest(question="stock ?", profile="support", allowed_tables=["stock"])
    )

    assert llm.calls[1] is not None
    assert "SELECT quantity FROM stock" in llm.calls[1]


async def test_judge_drift_retries_then_rejects():
    candidate = SqlCandidate(sql="SELECT quantity FROM stock", intent_reformulation="x")
    llm = FakeLlm([candidate, candidate, candidate])
    drift = JudgeVerdict(verdict=JudgeVerdictLabel.DRIFT, reason="mauvaise période")
    judge = FakeJudge([drift, drift, drift])
    use_case = make_use_case([STOCK_TABLE], llm, judge)

    outcome = await use_case.execute(
        GenerationRequest(question="stock ?", profile="support", allowed_tables=["stock"])
    )

    assert outcome.outcome == GenerationOutcomeType.REJECTED_JUDGE
    assert outcome.attempts == 3


async def test_judge_uncertain_needs_clarification():
    llm = FakeLlm([SqlCandidate(sql="SELECT quantity FROM stock", intent_reformulation="x")])
    judge = FakeJudge([JudgeVerdict(verdict=JudgeVerdictLabel.UNCERTAIN, reason="ambigu")])
    use_case = make_use_case([STOCK_TABLE], llm, judge)

    outcome = await use_case.execute(
        GenerationRequest(question="stock ?", profile="support", allowed_tables=["stock"])
    )

    assert outcome.outcome == GenerationOutcomeType.NEEDS_CLARIFICATION
    assert outcome.judge_verdict == JudgeVerdictLabel.UNCERTAIN


async def test_execute_logs_outcome(caplog):
    llm = FakeLlm([SqlCandidate(sql="SELECT quantity FROM stock", intent_reformulation="stock")])
    judge = FakeJudge([JudgeVerdict(verdict=JudgeVerdictLabel.ALIGNED, reason="ok")])
    use_case = make_use_case([STOCK_TABLE], llm, judge)

    with caplog.at_level(logging.INFO):
        await use_case.execute(
            GenerationRequest(question="stock ?", profile="support", allowed_tables=["stock"])
        )

    audit = [r for r in caplog.records if r.message == "text2sql_generation"]
    assert len(audit) == 1
    assert audit[0].outcome == "generated"
    assert audit[0].profile == "support"
    assert audit[0].attempts == 1

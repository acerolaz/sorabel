from app.domain.models import Answer, Citation
from tests.eval.run_eval import evaluate_pipeline, load_questions


class FakeUseCase:
    def __init__(self, answers_by_question: dict[str, Answer]):
        self._answers = answers_by_question

    async def execute(self, query, product_ref=None, top_k=20):
        return self._answers[query]


def test_load_questions_reads_all_categories():
    # Arrange / Act
    questions = load_questions("tests/eval/questions_rag.jsonl")

    # Assert
    categories = {q["category"] for q in questions}
    assert categories == {"reference_exacte", "couverte", "hors_corpus"}


async def test_evaluate_pipeline_computes_refusal_accuracy_for_hors_corpus():
    # Arrange
    questions = [{"category": "hors_corpus", "question": "q1", "expected_refused": True}]
    use_case = FakeUseCase(
        {
            "q1": Answer(
                text="Je ne trouve pas cette information dans le corpus.",
                citations=[],
                confidence="refused",
            )
        }
    )

    # Act
    metrics = await evaluate_pipeline(use_case, questions)

    # Assert
    assert metrics["refusal_accuracy"] == 1.0


async def test_evaluate_pipeline_computes_hit_rate_at_1_for_reference_exacte():
    # Arrange
    questions = [
        {"category": "reference_exacte", "question": "q1", "expected_product_ref": "REF-1"}
    ]
    from datetime import date

    citation = Citation(title="t", product_ref="REF-1", published_date=date(2026, 1, 1), document_type="datasheet")
    use_case = FakeUseCase({"q1": Answer(text="ok", citations=[citation], confidence="high")})

    # Act
    metrics = await evaluate_pipeline(use_case, questions)

    # Assert
    assert metrics["hit_rate_at_1"] == 1.0

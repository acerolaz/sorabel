import json
from dataclasses import dataclass

from app.application.use_cases.answer_query import AnswerQueryUseCase


def load_questions(path: str) -> list[dict]:
    questions = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                questions.append(json.loads(line))
    return questions


async def evaluate_pipeline(
    use_case: AnswerQueryUseCase, questions: list[dict]
) -> dict[str, float]:
    by_category: dict[str, list[dict]] = {}
    for question in questions:
        by_category.setdefault(question["category"], []).append(question)

    metrics: dict[str, float] = {}

    reference_exacte = by_category.get("reference_exacte", [])
    if reference_exacte:
        hits = 0
        for q in reference_exacte:
            answer = await use_case.execute(q["question"])
            if answer.citations and answer.citations[0].product_ref == q["expected_product_ref"]:
                hits += 1
        metrics["hit_rate_at_1"] = hits / len(reference_exacte)

    couverte = by_category.get("couverte", [])
    if couverte:
        recall_hits = 0
        reciprocal_ranks = 0.0
        for q in couverte:
            answer = await use_case.execute(q["question"])
            document_types = [c.document_type for c in answer.citations[:5]]
            expected_type = q["expected_document_type"]
            if expected_type in document_types:
                recall_hits += 1
                reciprocal_ranks += 1.0 / (document_types.index(expected_type) + 1)
        metrics["recall_at_5"] = recall_hits / len(couverte)
        metrics["mrr"] = reciprocal_ranks / len(couverte)

    hors_corpus = by_category.get("hors_corpus", [])
    if hors_corpus:
        correct_refusals = 0
        for q in hors_corpus:
            answer = await use_case.execute(q["question"])
            if (answer.confidence == "refused") == q["expected_refused"]:
                correct_refusals += 1
        metrics["refusal_accuracy"] = correct_refusals / len(hors_corpus)

    return metrics


@dataclass
class ComparisonRow:
    category: str
    metric: str
    pipeline_a: float
    pipeline_b: float


async def run_comparison(
    dense_only_use_case: AnswerQueryUseCase,
    hybrid_use_case: AnswerQueryUseCase,
    questions: list[dict],
) -> None:
    metrics_a = await evaluate_pipeline(dense_only_use_case, questions)
    metrics_b = await evaluate_pipeline(hybrid_use_case, questions)

    print(f"{'Metric':<20}{'Pipeline A (dense only)':<28}{'Pipeline B (hybrid)':<20}")
    for metric_name in sorted(set(metrics_a) | set(metrics_b)):
        value_a = metrics_a.get(metric_name, float("nan"))
        value_b = metrics_b.get(metric_name, float("nan"))
        print(f"{metric_name:<20}{value_a:<28.2f}{value_b:<20.2f}")


if __name__ == "__main__":
    import asyncio

    print(
        "run_eval.py is a manual benchmarking script — wire real Pipeline A / "
        "Pipeline B use cases before running."
    )
    asyncio.run(run_comparison(None, None, load_questions("tests/eval/questions_rag.jsonl")))  # type: ignore[arg-type]

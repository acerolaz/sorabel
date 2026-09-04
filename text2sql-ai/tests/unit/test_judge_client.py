import json
from unittest.mock import AsyncMock, MagicMock

from app.domain.models import JudgeVerdictLabel
from app.infrastructure.azure_openai.judge_client import AzureOpenAiJudgeClient


def _make_response(payload: dict) -> MagicMock:
    message = MagicMock()
    message.content = json.dumps(payload)
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


async def test_evaluate_returns_aligned_verdict():
    fake_client = MagicMock()
    fake_client.chat.completions.create = AsyncMock(
        return_value=_make_response({"verdict": "ALIGNED", "reason": "correspond à la question"})
    )
    judge = AzureOpenAiJudgeClient(fake_client, "judge-deployment")

    verdict = await judge.evaluate(
        "stock de REF-8842", "stock actuel de REF-8842", "SELECT quantity FROM stock"
    )

    assert verdict.verdict == JudgeVerdictLabel.ALIGNED
    assert verdict.reason == "correspond à la question"


async def test_evaluate_returns_drift_verdict():
    fake_client = MagicMock()
    fake_client.chat.completions.create = AsyncMock(
        return_value=_make_response({"verdict": "DRIFT", "reason": "mauvaise période"})
    )
    judge = AzureOpenAiJudgeClient(fake_client, "judge-deployment")

    verdict = await judge.evaluate("q", "reformulation", "SELECT 1")

    assert verdict.verdict == JudgeVerdictLabel.DRIFT


async def test_evaluate_sends_question_reformulation_and_sql():
    fake_client = MagicMock()
    fake_client.chat.completions.create = AsyncMock(
        return_value=_make_response({"verdict": "ALIGNED", "reason": "ok"})
    )
    judge = AzureOpenAiJudgeClient(fake_client, "judge-deployment")

    await judge.evaluate("ma question", "ma reformulation", "SELECT 1")

    _, kwargs = fake_client.chat.completions.create.call_args
    user_message = kwargs["messages"][-1]["content"]
    assert "ma question" in user_message
    assert "ma reformulation" in user_message
    assert "SELECT 1" in user_message

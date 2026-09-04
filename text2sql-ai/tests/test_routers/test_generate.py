from app.dependencies import get_generate_sql_use_case, get_schema_repository
from app.domain.errors import JudgeServiceError, LlmServiceError
from app.domain.models import GenerationOutcome, GenerationOutcomeType, JudgeVerdictLabel
from app.main import app
from fastapi.testclient import TestClient


class StubUseCase:
    def __init__(self, outcome: GenerationOutcome) -> None:
        self._outcome = outcome

    async def execute(self, request):
        return self._outcome


class RaisingUseCase:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def execute(self, request):
        raise self._exc


def _override(outcome: GenerationOutcome) -> None:
    app.dependency_overrides[get_generate_sql_use_case] = lambda: StubUseCase(outcome)


async def test_generate_happy_path(client):
    outcome = GenerationOutcome(
        outcome=GenerationOutcomeType.GENERATED,
        sql="SELECT quantity FROM stock WHERE product_ref = 'REF-8842'",
        intent_reformulation="stock de REF-8842",
        judge_verdict=JudgeVerdictLabel.ALIGNED,
        attempts=1,
    )
    _override(outcome)

    response = await client.post(
        "/api/v1/generate",
        json={
            "question": "stock de la REF-8842 ?",
            "profile": "support",
            "allowed_tables": ["stock"],
        },
    )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    data = response.json()
    assert data["outcome"] == "generated"
    assert data["sql"] == "SELECT quantity FROM stock WHERE product_ref = 'REF-8842'"
    assert data["judge_verdict"] == "ALIGNED"


async def test_generate_out_of_schema_refusal(client):
    outcome = GenerationOutcome(
        outcome=GenerationOutcomeType.REFUSED_OUT_OF_SCHEMA,
        message="La question ne correspond à aucune donnée disponible pour ce profil.",
    )
    _override(outcome)

    response = await client.post(
        "/api/v1/generate",
        json={"question": "quel est le NPS ?", "profile": "support", "allowed_tables": ["stock"]},
    )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    data = response.json()
    assert data["outcome"] == "refused_out_of_schema"
    assert data["sql"] is None


async def test_generate_rejects_empty_allowed_tables_with_422(client):
    response = await client.post(
        "/api/v1/generate",
        json={"question": "stock ?", "profile": "support", "allowed_tables": []},
    )

    assert response.status_code == 422


async def test_health_endpoint_returns_ok(client):
    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_generate_returns_502_when_llm_unavailable(client):
    app.dependency_overrides[get_generate_sql_use_case] = lambda: RaisingUseCase(
        LlmServiceError("appel de génération échoué")
    )

    response = await client.post(
        "/api/v1/generate",
        json={"question": "stock ?", "profile": "support", "allowed_tables": ["stock"]},
    )

    app.dependency_overrides.clear()
    assert response.status_code == 502
    data = response.json()
    assert data["error_code"] == "LLM_UNAVAILABLE"
    assert "correlation_id" in data


async def test_generate_returns_502_when_judge_unavailable(client):
    app.dependency_overrides[get_generate_sql_use_case] = lambda: RaisingUseCase(
        JudgeServiceError("verdict du juge illisible")
    )

    response = await client.post(
        "/api/v1/generate",
        json={"question": "stock ?", "profile": "support", "allowed_tables": ["stock"]},
    )

    app.dependency_overrides.clear()
    assert response.status_code == 502
    assert response.json()["error_code"] == "JUDGE_UNAVAILABLE"


async def test_unexpected_error_still_honours_the_uniform_error_format(tolerant_client):
    app.dependency_overrides[get_generate_sql_use_case] = lambda: RaisingUseCase(
        KeyError("columns")
    )

    response = await tolerant_client.post(
        "/api/v1/generate",
        json={"question": "stock ?", "profile": "support", "allowed_tables": ["stock"]},
    )

    app.dependency_overrides.clear()
    assert response.status_code == 500
    data = response.json()
    assert data["error_code"] == "INTERNAL_ERROR"
    assert "correlation_id" in data
    assert "columns" not in data["message"]


async def test_openapi_publishes_the_outcome_enumeration(client):
    response = await client.get("/openapi.json")

    schemas = response.json()["components"]["schemas"]
    assert set(schemas["GenerationOutcomeType"]["enum"]) == {
        "generated",
        "needs_clarification",
        "refused_out_of_schema",
        "rejected_guardrail",
        "rejected_judge",
    }
    assert set(schemas["JudgeVerdictLabel"]["enum"]) == {"ALIGNED", "DRIFT", "UNCERTAIN"}


def test_lifespan_loads_the_schema_at_boot():
    """The spec requires a malformed YAML schema to fail fast at boot, not per
    request: the lifespan must warm the schema caches before serving traffic."""
    get_schema_repository.cache_clear()
    assert get_schema_repository.cache_info().currsize == 0

    with TestClient(app):
        assert get_schema_repository.cache_info().currsize == 1

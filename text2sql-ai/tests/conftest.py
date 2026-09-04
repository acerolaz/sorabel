import pytest
import pytest_asyncio
from app.dependencies import get_azure_client, get_settings
from app.main import app
from httpx import ASGITransport, AsyncClient


@pytest.fixture(autouse=True)
def _stub_azure_settings(monkeypatch):
    """Make the suite self-contained: FastAPI resolves the full dependency tree
    (including get_settings()) even for requests that fail body validation before
    reaching the route body, so Settings() must be constructible without a real
    .env file. Also clears the get_settings/get_azure_client lru_caches so no
    stale instance leaks between tests."""
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://dummy.openai.azure.com/")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "dummy")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT_GENERATOR", "dummy")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT_JUDGE", "dummy")
    get_settings.cache_clear()
    get_azure_client.cache_clear()
    yield
    get_settings.cache_clear()
    get_azure_client.cache_clear()


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

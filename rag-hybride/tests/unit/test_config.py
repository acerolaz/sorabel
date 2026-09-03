from pathlib import Path

from app.config import Settings
from pydantic import ValidationError


def test_env_file_est_resolu_depuis_la_racine_de_la_solution():
    # Arrange — test_config.py -> unit/ -> tests/ -> rag-hybride/ -> src/
    solution_root = Path(__file__).resolve().parents[3]

    # Act
    env_file = Settings.model_config["env_file"]

    # Assert
    assert Path(env_file) == solution_root / ".env"


def test_un_env_du_repertoire_courant_est_ignore(tmp_path, monkeypatch):
    # Arrange — un leurre complet dans le répertoire courant
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "DATABASE_URL=leurre\n"
        "AZURE_OPENAI_API_KEY=leurre\n"
        "AZURE_OPENAI_ENDPOINT=leurre\n"
        "AZURE_OPENAI_EMBEDDING_DEPLOYMENT=leurre\n"
        "AZURE_OPENAI_CHAT_DEPLOYMENT=leurre\n"
    )
    for var in (
        "DATABASE_URL",
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_EMBEDDING_DEPLOYMENT",
        "AZURE_OPENAI_CHAT_DEPLOYMENT",
    ):
        monkeypatch.delenv(var, raising=False)

    # Act / Assert — le leurre ne doit jamais être lu
    try:
        settings = Settings()  # type: ignore[call-arg]
    except ValidationError:
        return  # pas de .env racine sur cette machine : le leurre a bien été ignoré
    assert settings.database_url != "leurre"

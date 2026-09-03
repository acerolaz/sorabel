from pathlib import Path

from app.config import Settings


def test_env_file_est_resolu_depuis_la_racine_de_la_solution():
    # Arrange — test_config.py -> unit/ -> tests/ -> rag-hybride/ -> src/
    solution_root = Path(__file__).resolve().parents[3]

    # Act
    candidates = Settings.model_config["env_file"]

    # Assert
    assert Path(candidates[0]) == solution_root / ".env"


def test_env_file_est_independant_du_repertoire_courant():
    # Act
    candidates = Settings.model_config["env_file"]

    # Assert — premier candidat absolu : insensible au cwd
    assert Path(candidates[0]).is_absolute()
    # Repli relatif : rag-hybride extrait dans son propre dépôt
    assert Path(candidates[1]) == Path(".env")

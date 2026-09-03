from app.domain.versioning import resolve_ingest_action


def test_no_existing_document_is_created():
    assert resolve_ingest_action(existing_hash=None, new_hash="abc") == "created"


def test_same_hash_is_unchanged():
    assert resolve_ingest_action(existing_hash="abc", new_hash="abc") == "unchanged"


def test_different_hash_is_updated():
    assert resolve_ingest_action(existing_hash="abc", new_hash="def") == "updated"

DOCUMENT_ID_SEPARATOR = "::"


def make_document_id(product_ref: str, document_type: str, version: str) -> str:
    """Identity of one *version* of a document.

    The version belongs in the identity: with a version-less id, re-ingesting a
    product's datasheet overwrote the previous document row and deleted its
    chunks, so no superseded version survived to be audited. Keying per version
    lets the old row stay behind, marked `deprecated`.

    Re-ingesting corrected content under an unchanged version string
    deliberately maps to the same id, updating that version in place rather
    than accumulating a second row for it.
    """
    return DOCUMENT_ID_SEPARATOR.join((product_ref, document_type, version))


def resolve_ingest_action(existing_hash: str | None, new_hash: str) -> str:
    if existing_hash is None:
        return "created"
    if existing_hash == new_hash:
        return "unchanged"
    return "updated"

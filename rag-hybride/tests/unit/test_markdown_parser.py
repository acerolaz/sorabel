import pytest

from app.domain.errors import UnparsableDocumentError
from app.infrastructure.parsers.markdown_parser import MarkdownParser

# Test data with markdown content may exceed line length limits
# ruff: noqa: E501
VALID_MARKDOWN = b"""---
title: Fiche REF-8842
product_ref: REF-8842
version: "2"
published_date: 2026-01-15
---

# Caracteristiques

Tension nominale : 230V. Cet appareil est conforme aux normes en vigueur pour ce type de produit electrique domestique standard.

## Dimensions

| Largeur | Hauteur |
|---|---|
| 10cm | 5cm |
"""


def test_parses_frontmatter_into_document_metadata():
    # Arrange
    parser = MarkdownParser()

    # Act
    document, sections = parser.parse(VALID_MARKDOWN, "datasheet", "REF-8842.md")

    # Assert
    assert document.product_ref == "REF-8842"
    assert document.title == "Fiche REF-8842"
    assert document.version == "2"


def test_splits_into_sections_by_header_and_detects_tables():
    # Arrange
    parser = MarkdownParser()

    # Act
    _document, sections = parser.parse(VALID_MARKDOWN, "datasheet", "REF-8842.md")

    # Assert
    content_types = [s.content_type for s in sections]
    assert "table" in content_types


def test_missing_frontmatter_raises_unparsable_error():
    # Arrange
    parser = MarkdownParser()

    # Act / Assert
    with pytest.raises(UnparsableDocumentError):
        parser.parse(b"# Just a header, no frontmatter", "datasheet", "bad.md")


def test_missing_required_frontmatter_key_raises_unparsable_error_not_key_error():
    # Arrange
    parser = MarkdownParser()
    missing_product_ref = b"""---
title: Fiche sans reference
version: "1"
published_date: 2026-01-15
---

# Section

Contenu.
"""

    # Act / Assert
    with pytest.raises(UnparsableDocumentError):
        parser.parse(missing_product_ref, "datasheet", "bad.md")

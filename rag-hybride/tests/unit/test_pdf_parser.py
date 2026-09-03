import io

import pytest
from reportlab.pdfgen import canvas

from app.domain.errors import UnparsableDocumentError
from app.infrastructure.parsers.pdf_parser import PdfParser


def _build_pdf_with_heading_and_body() -> bytes:
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(50, 750, "CARACTERISTIQUES TECHNIQUES")
    c.setFont("Helvetica", 10)
    c.drawString(50, 720, "Tension nominale 230V, courant maximal 10A pour ce modele standard.")
    c.setFont("Helvetica-Bold", 18)
    c.drawString(50, 690, "PROCEDURE DE MONTAGE")
    c.setFont("Helvetica", 10)
    c.drawString(50, 660, "Suivre les etapes decrites dans le manuel fourni avec l'appareil.")
    c.save()
    return buffer.getvalue()


def test_parses_pdf_into_a_document_and_sections():
    # Arrange
    parser = PdfParser()
    raw_bytes = _build_pdf_with_heading_and_body()

    # Act
    document, sections = parser.parse(raw_bytes, "manuel", "notice.pdf")

    # Assert
    assert document.source_path == "notice.pdf"
    assert len(sections) >= 1


def test_font_size_change_creates_a_new_section_boundary():
    # Arrange
    parser = PdfParser()
    raw_bytes = _build_pdf_with_heading_and_body()

    # Act
    _document, sections = parser.parse(raw_bytes, "manuel", "notice.pdf")

    # Assert
    text_sections = [s for s in sections if s.content_type == "text"]
    assert len(text_sections) >= 2
    assert "CARACTERISTIQUES" in text_sections[0].content


def test_empty_pdf_raises_unparsable_error():
    # Arrange
    parser = PdfParser()
    buffer = io.BytesIO()
    canvas.Canvas(buffer).save()

    # Act / Assert
    with pytest.raises(UnparsableDocumentError):
        parser.parse(buffer.getvalue(), "manuel", "empty.pdf")

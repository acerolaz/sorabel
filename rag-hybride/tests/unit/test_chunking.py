from app.domain.chunking import (
    MAX_CHUNK_TOKENS,
    MIN_CHUNK_TOKENS,
    OVERLAP_RATIO,
    RawSection,
    chunk_sections,
)


def test_tiny_document_becomes_a_single_chunk():
    # Arrange
    text = "Courte notice de dix mots pour un petit accessoire technique ici"
    sections = [RawSection(content=text, content_type="text")]

    # Act
    chunks = chunk_sections(sections)

    # Assert
    assert len(chunks) == 1
    assert chunks[0].content_type == "text"


def test_table_section_is_never_split_even_if_large():
    # Arrange
    table_content = "\n".join(f"row {i}\tvalue {i}" for i in range(400))
    sections = [
        RawSection(content="intro " * 200, content_type="text"),
        RawSection(content=table_content, content_type="table"),
    ]

    # Act
    chunks = chunk_sections(sections)

    # Assert
    table_chunks = [c for c in chunks if c.content_type == "table"]
    assert len(table_chunks) == 1
    assert table_chunks[0].content == table_content


def test_large_text_section_is_split_with_overlap():
    # Arrange
    words = [f"word{i}" for i in range(600)]
    sections = [RawSection(content=" ".join(words), content_type="text")]

    # Act
    chunks = chunk_sections(sections)

    # Assert
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk.content.split()) <= 250
    # overlap: the last `overlap` words of one chunk equal the first `overlap` words of the next
    overlap = int(MAX_CHUNK_TOKENS * OVERLAP_RATIO)
    first_chunk_words = chunks[0].content.split()
    second_chunk_words = chunks[1].content.split()
    assert first_chunk_words[-overlap:] == second_chunk_words[:overlap]


def test_small_text_sections_are_merged_until_min_tokens():
    # Arrange
    text2 = "phrase courte numero deux avec quelques mots supplementaires"
    sections = [
        RawSection(
            content="phrase courte numero un avec quelques mots",
            content_type="text",
        ),
        RawSection(content=text2, content_type="text"),
        RawSection(
            content=" ".join(f"filler{i}" for i in range(300)),
            content_type="text",
        ),
    ]

    # Act
    chunks = chunk_sections(sections)

    # Assert
    assert len(chunks[0].content.split()) >= 50
    # Verify the invariant: all text chunks are within [MIN_CHUNK_TOKENS, MAX_CHUNK_TOKENS]
    for chunk in chunks:
        if chunk.content_type == "text":
            chunk_size = len(chunk.content.split())
            assert MIN_CHUNK_TOKENS <= chunk_size <= MAX_CHUNK_TOKENS, (
                f"Text chunk size {chunk_size} outside [{MIN_CHUNK_TOKENS}, {MAX_CHUNK_TOKENS}]"
            )

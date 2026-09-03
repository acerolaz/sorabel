from dataclasses import dataclass

MIN_CHUNK_TOKENS = 50
MAX_CHUNK_TOKENS = 250
TINY_DOCUMENT_TOKENS = 150
OVERLAP_RATIO = 0.125


@dataclass(frozen=True)
class RawSection:
    content: str
    content_type: str  # "text" | "table"


@dataclass(frozen=True)
class ChunkCandidate:
    content: str
    content_type: str  # "text" | "table"


def estimate_tokens(text: str) -> int:
    """Word-count approximation of token count — adequate for the chunk-sizing heuristic."""
    return len(text.split())


def chunk_sections(sections: list[RawSection]) -> list[ChunkCandidate]:
    total_tokens = sum(estimate_tokens(s.content) for s in sections)
    if total_tokens < TINY_DOCUMENT_TOKENS:
        combined = "\n\n".join(s.content for s in sections)
        is_single_table = len(sections) == 1 and sections[0].content_type == "table"
        content_type = "table" if is_single_table else "text"
        return [ChunkCandidate(content=combined, content_type=content_type)]

    chunks: list[ChunkCandidate] = []
    buffer: list[str] = []
    buffer_tokens = 0

    def flush_buffer() -> None:
        nonlocal buffer, buffer_tokens
        if buffer:
            chunks.append(ChunkCandidate(content="\n\n".join(buffer), content_type="text"))
            buffer = []
            buffer_tokens = 0

    for section in sections:
        if section.content_type == "table":
            flush_buffer()
            chunks.append(ChunkCandidate(content=section.content, content_type="table"))
            continue

        section_tokens = estimate_tokens(section.content)
        if section_tokens > MAX_CHUNK_TOKENS:
            # If buffer has content but is below MIN_CHUNK_TOKENS, pad from
            # the large section to reach minimum
            if buffer and buffer_tokens < MIN_CHUNK_TOKENS:
                needed = MIN_CHUNK_TOKENS - buffer_tokens
                words = section.content.split()
                # needed is at most MIN_CHUNK_TOKENS (~50); section_tokens > 250;
                # so needed < len(words) is always true for large sections
                buffer.append(" ".join(words[:needed]))
                buffer_tokens += needed
                flush_buffer()
                remaining = " ".join(words[needed:])
                chunks.extend(_split_large_text(remaining))
            else:
                flush_buffer()
                chunks.extend(_split_large_text(section.content))
            continue

        buffer.append(section.content)
        buffer_tokens += section_tokens
        if buffer_tokens >= MIN_CHUNK_TOKENS:
            flush_buffer()

    # Avoid emitting a trailing undersized text chunk (< MIN_CHUNK_TOKENS) when possible.
    if buffer and buffer_tokens < MIN_CHUNK_TOKENS:
        for i in range(len(chunks) - 1, -1, -1):
            if (
                chunks[i].content_type == "text"
                and estimate_tokens(chunks[i].content) + buffer_tokens <= MAX_CHUNK_TOKENS
            ):
                merged = chunks[i].content + "\n\n" + "\n\n".join(buffer)
                chunks[i] = ChunkCandidate(content=merged, content_type="text")
                buffer = []
                buffer_tokens = 0
                break

    flush_buffer()
    return chunks


def _split_large_text(text: str) -> list[ChunkCandidate]:
    words = text.split()
    step = MAX_CHUNK_TOKENS
    overlap = int(step * OVERLAP_RATIO)
    chunks: list[ChunkCandidate] = []
    start = 0
    while start < len(words):
        end = min(start + step, len(words))
        remaining_after_chunk = len(words) - end

        # If there are remaining words, ensure the tail chunk won't be too small.
        # Tail would start at (end - overlap) and end at len(words), giving size:
        # len(words) - (end - overlap) = remaining_after_chunk + overlap
        if remaining_after_chunk > 0:
            tail_size = remaining_after_chunk + overlap
            if tail_size < MIN_CHUNK_TOKENS:
                # Reduce end to make the tail chunk at least MIN_CHUNK_TOKENS
                # We want: remaining_after_chunk + overlap >= MIN_CHUNK_TOKENS
                # So: len(words) - end + overlap >= MIN_CHUNK_TOKENS
                # So: end <= len(words) - (MIN_CHUNK_TOKENS - overlap)
                end = len(words) - (MIN_CHUNK_TOKENS - overlap)
                # Ensure current chunk is also >= MIN_CHUNK_TOKENS
                end = max(end, start + MIN_CHUNK_TOKENS)
                # Ensure current chunk is <= MAX_CHUNK_TOKENS
                end = min(end, start + MAX_CHUNK_TOKENS)
                # Don't exceed word list
                end = min(end, len(words))

        chunks.append(ChunkCandidate(content=" ".join(words[start:end]), content_type="text"))
        if end == len(words):
            break
        start = end - overlap
    return chunks

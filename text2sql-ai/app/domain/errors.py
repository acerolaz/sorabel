"""Domain-level error types. Adapters wrap their SDK / parsing failures into these so
the outer layers (api/) map domain errors to HTTP without ever importing an SDK —
see ../../../.claude/rules/python-hexagonal.md."""

from __future__ import annotations


class LlmServiceError(Exception):
    """Raised when the generator LLM call fails or returns an unusable payload."""


class JudgeServiceError(Exception):
    """Raised when the intent judge LLM call fails or returns an unusable payload."""


class SchemaLoadError(Exception):
    """Raised when a schema YAML file cannot be loaded into the domain model."""

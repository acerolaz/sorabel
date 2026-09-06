from collections.abc import Callable, Sequence
from typing import TypeVar

from app.domain.access_matrix import AccessMatrix
from app.domain.models import Identity

T = TypeVar("T")


def list_available_tools(
    matrix: AccessMatrix,
    identity: Identity | None,
    tools: Sequence[T],
    name_of: Callable[[T], str],
) -> list[T]:
    """Projection du catalogue : ne conserve que les tools du profil.

    Sans identité, la projection est vide — un appelant non authentifié
    n'apprend pas quels tools existent (spec §7.1).

    Générique sur le type de tool pour que `domain`/`application` ignorent le
    type `Tool` du SDK MCP.
    """
    if identity is None:
        return []
    autorises = set(matrix.tools_for(identity.profile))
    return [tool for tool in tools if name_of(tool) in autorises]

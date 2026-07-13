from __future__ import annotations

import unicodedata


_UNSAFE_CATEGORIES = {'Cc', 'Cf', 'Cs'}


def is_unsafe_character(character: str) -> bool:
    """Return whether a character is unsafe in identifiers or operator-facing text."""
    return unicodedata.category(character) in _UNSAFE_CATEGORIES

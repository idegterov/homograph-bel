"""Stable orthography contract shared with the dictionary parser."""

from enum import StrEnum


class Orthography(StrEnum):
    """Orthography used by a dictionary source record."""

    OFFICIAL_2008 = "official_2008"
    CLASSICAL = "classical"
    MIXED_OR_UNKNOWN = "mixed_or_unknown"

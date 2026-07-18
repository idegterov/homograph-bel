"""Stable consumer contracts for Belarusian homograph inference."""

from homograph_bel.inference.dictionary import (
    LEAN_PROMPT_VERSION,
    LEAN_SYSTEM_PROMPT,
    PROMPT_VERSION,
    AdjudicationPrompt,
    HomographOccurrence,
    HomographScanner,
    LeanAdjudicationPrompt,
    LeanAdjudicationResult,
    LeanResponseStatus,
    PromptContractError,
    build_adjudication_prompt,
    build_lean_adjudication_prompt,
    parse_lean_adjudication_response,
)

__all__ = [
    "LEAN_PROMPT_VERSION",
    "LEAN_SYSTEM_PROMPT",
    "PROMPT_VERSION",
    "AdjudicationPrompt",
    "HomographOccurrence",
    "HomographScanner",
    "LeanAdjudicationPrompt",
    "LeanAdjudicationResult",
    "LeanResponseStatus",
    "PromptContractError",
    "build_adjudication_prompt",
    "build_lean_adjudication_prompt",
    "parse_lean_adjudication_response",
]

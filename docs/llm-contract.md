# Lean LLM contract

The lean contract is designed for small instruction models. It minimizes tokens
without discarding the context that usually separates homographs.

## Input

Send exactly two messages:

1. `system_prompt`: a short Belarusian instruction and output grammar.
2. `user_prompt`: the original sentence with one `<t>...</t>` target, followed
   by numbered candidates.

Each candidate line has this shape:

```text
N stressed-form | lemma; POS; Feature=Value; Meaning=optional source meaning
```

Repeated grammatical forms are folded under `Forms=`. Duplicate analyses are
removed. Unknown GrammarDB tag structures are not guessed; the raw analysis is
retained host-side.

Do not send stable IDs, offsets, hashes, provenance records, JSON schema, or raw
source tags to the model. They do not improve a numbered choice enough to justify
their token cost. The returned `LeanAdjudicationPrompt` keeps all of them needed
for deterministic host-side mapping.

## Output

Accept only:

- an exact decimal integer from `1` through the number of candidates; or
- the exact token `?` for insufficient context.

Leading and trailing whitespace is ignored. Explanations, JSON, punctuation,
out-of-range numbers, leading zeroes, and injected text are invalid. Never parse
the answer with a permissive regular expression in application code; use
`parse_lean_adjudication_response`.

## Result

The parser returns:

- `selected`: a valid choice mapped to its stable candidate ID and all possible
  decoded analyses;
- `abstained`: the model returned `?`; or
- `invalid`: the response violated the grammar.

Morphology is candidate evidence, not a contextual prediction. Multiple
`possible_analyses` may remain after stress selection. If the application needs
one exact grammatical analysis, run a separate morphology stage or use the full
prompt contract.

## Small-model settings

Start with deterministic decoding: temperature 0, no sampling, and a very small
output budget (typically 2–4 tokens). Stop after the first line when the runtime
supports stop sequences. These are provider settings, not part of the stable
prompt hash.

The contract versions are `homograph-lean-choice-v1` and
`grammardb-unimorph-c328ce92`. Store both plus `prompt_hash`, dictionary version,
raw response, and parse status when reproducibility matters.

# Python API

## Load

`bundled_dictionary_path(cache_root=None)` verifies and materializes the package
resource. `bundled_dictionary_index(cache_root=None)` additionally validates all
table hashes, links, logical hash, and release metadata, then returns an immutable
`DictionaryIndex`.

Use `DictionaryIndex.from_bundle(path)` for a custom unpacked Dictionary v2.

## Browse

- `index.get_homograph(surface)` performs case-, stress-, Unicode-, and
  apostrophe-normalized lookup.
- `index.list_homographs(status=None, limit=None)` returns deterministic surface
  order.
- `len(index)` returns the number of surfaces.

## Detect

`HomographScanner(index).scan(text)` returns every whole-token occurrence in
source order. Each `HomographOccurrence` preserves original text, exact Python
character offsets, source surface, normalized target, stable dictionary IDs,
release, status, and closed candidates.

Create one scanner per loaded index and reuse it. `scan_many(iterable)` streams
results without materializing the input corpus.

## Prompt

- `build_lean_adjudication_prompt(occurrence)` produces minimal system/user
  messages plus a host-side candidate map.
- `parse_lean_adjudication_response(prompt, response)` validates the closed
  output grammar.
- `build_adjudication_prompt(...)` produces the verbose JSON-answer contract and
  can include caller-supplied morphology and examples.

All prompt builders are deterministic for the same occurrence and contract
version. The SHA-256 `prompt_hash` is suitable for logs and caches.

## Morphology

`decode_grammar_db_analysis(analysis)` returns `DecodedGrammarDBAnalysis`:

- `lemma`: source lemma;
- `pos`: coarse POS such as `NOUN`, `VERB`, `ADJ`, `PROPN`, or `PRON`;
- `features`: ordered `(name, value)` pairs;
- `meaning`: optional source meaning;
- `decoded`: whether structured features were safely decoded; and
- `raw_tag`: lossless source tag concatenation for auditing.

The decoder prefers explicit source morphology. Otherwise it applies the pinned
GrammarDB tag grammar and refuses unknown structures.

# homograph-bel

Offline Belarusian homograph detection, dictionary lookup, morphology evidence,
and compact prompts for constrained LLM stress selection.

The package ships a verified Dictionary v2 derived from Belarus GrammarDB
`RELEASE-202601`: 19,992 homograph surfaces, 40,167 stressed candidates, and
73,047 source analyses. Runtime dependencies: none. Runtime network calls: none.

## Install

Python 3.12 or 3.13 is required. Until a PyPI release exists, install the pinned
GitHub release:

```bash
uv tool install "homograph-bel @ git+https://github.com/idegterov/homograph-bel@v0.1.0"
```

For library use:

```bash
uv add "homograph-bel @ git+https://github.com/idegterov/homograph-bel@v0.1.0"
```

The first command extracts the bundled 5 MB dictionary archive into a user
cache. Later calls reuse it after checking the release marker. Set
`HOMOGRAPH_BEL_CACHE` or pass `--cache-root` to control that location.

## Run the dictionary

No dictionary path is required:

```bash
homograph-bel dictionary list --limit 3
homograph-bel dictionary show яна
homograph-bel dictionary detect --text "Яна чытае кнігу."
homograph-bel dictionary path
```

`detect` emits one compact JSON object per occurrence, with exact source offsets,
stable IDs, dictionary version, and closed stress candidates. A custom unpacked
Dictionary v2 can be supplied to any command with `--bundle PATH`.

## Minimal LLM contract

Use the `lean` profile for Gemma, Qwen, and other small instruction models:

```bash
homograph-bel dictionary prompt \
  --text "Яна чытае кнігу." \
  --profile lean
```

The model receives only two messages. The complete first example is:

```text
system: Выберы правільны націск для <t>...</t>. Адкажы толькі нумарам варыянта або ?.

user: <t>Яна</t> чытае кнігу.
1 яна́ | ён; PRON; Case=Nom; Number=Sing; Gender=Fem; Person=3
2 я́на | ян; PROPN; Forms=Case=Gen,Number=Sing,Gender=Masc,Animacy=Anim | Case=Acc,Number=Sing,Gender=Masc,Animacy=Anim
```

Expected model output:

```text
1
```

A second context uses the same candidate order:

```text
system: Выберы правільны націск для <t>...</t>. Адкажы толькі нумарам варыянта або ?.

user: Бачу <t>Яна</t>.
1 яна́ | ён; PRON; Case=Nom; Number=Sing; Gender=Fem; Person=3
2 я́на | ян; PROPN; Forms=Case=Gen,Number=Sing,Gender=Masc,Animacy=Anim | Case=Acc,Number=Sing,Gender=Masc,Animacy=Anim
```

Expected model output:

```text
2
```

The only valid responses are an exact 1-based candidate number or `?` to
abstain. Stable candidate IDs and detailed morphology stay host-side. This is
deliberate: the LLM sees the minimum evidence needed to decide, while the host
validates its untrusted response and returns the production metadata.

```bash
homograph-bel dictionary prompt \
  --text "Бачу Яна." \
  --profile lean \
  --response 2
```

Selected output, abbreviated:

```json
{
  "response_status": "selected",
  "selected_candidate_id": "v_7152bbd36dee6d2b91cd",
  "possible_analyses": [
    {
      "lemma": "ян",
      "pos": "PROPN",
      "features": [["Case", "Gen"], ["Number", "Sing"], ["Gender", "Masc"], ["Animacy", "Anim"]],
      "meaning": null,
      "decoded": true,
      "raw_tag": "NPAPNM1GS"
    }
  ]
}
```

`possible_analyses` can contain more than one item because a stressed surface may
still have multiple grammatical analyses. The decoder reports noun/verb/etc.,
case, number, gender, person, tense, aspect, voice, mood, and other features only
when GrammarDB supplies them or its pinned tag grammar can decode them. It does
not guess unknown tags. See [the full LLM contract](docs/llm-contract.md).

## Python API

```python
from homograph_bel.inference import (
    HomographScanner,
    build_lean_adjudication_prompt,
    parse_lean_adjudication_response,
)
from homograph_bel.resources import bundled_dictionary_index

index = bundled_dictionary_index()
scanner = HomographScanner(index)
occurrence = scanner.scan("Бачу Яна.")[0]
prompt = build_lean_adjudication_prompt(occurrence)

# Send prompt.system_prompt and prompt.user_prompt to the model.
result = parse_lean_adjudication_response(prompt, "2")
assert result.selected_candidate_id == prompt.candidate_ids[1]
assert result.possible_analyses[0].pos == "PROPN"
```

The main contracts are documented in [Python API](docs/python-api.md). The
longer `full` prompt profile remains available when an application needs stable
IDs, provenance, supplied morphology, examples, and a structured JSON answer.

## Reliability boundaries

- Dictionary detection is deterministic; contextual resolution is not.
- Treat all LLM text as untrusted and pass it through the response parser.
- `candidate_only` is evidence, not a production pronunciation guarantee.
- Morphology describes possible source-backed analyses of the candidate. It is
  not a separate contextual morphological parser.
- The data retains upstream limitations and may contain ambiguity or conflict.
  Use `?` when context is insufficient.

## Development

```bash
make setup
make format
make check
make build
```

The lock file is committed. CI tests Python 3.12 and 3.13, enforces formatting,
lint, strict types, and 100% statement coverage, then smoke-tests release wheels.
See [CONTRIBUTING.md](CONTRIBUTING.md) and [the release runbook](docs/releasing.md).

## Licenses and attribution

Source code is GPL-3.0-or-later; see [LICENSE](LICENSE). The bundled derived
dictionary is CC BY-SA 4.0; see [DATA_LICENSE.md](DATA_LICENSE.md), the full
[CC BY-SA 4.0 text](LICENSES/CC-BY-SA-4.0.txt), and [NOTICE.md](NOTICE.md).

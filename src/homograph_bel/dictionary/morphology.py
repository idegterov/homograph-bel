"""Readable, source-backed morphology derived from GrammarDB analyses."""

from __future__ import annotations

from dataclasses import dataclass

from homograph_bel.dictionary.v2 import GrammarDBAnalysis

MORPHOLOGY_DECODER_VERSION = "grammardb-unimorph-c328ce92"

_COARSE_POS = {
    "A": "ADJ",
    "C": "CONJ",
    "E": "PART",
    "F": "WORD_PART",
    "I": "ADP",
    "M": "NUM",
    "N": "NOUN",
    "P": "PARTICIPLE",
    "R": "ADV",
    "S": "PRON",
    "V": "VERB",
    "W": "PREDICATIVE",
    "Y": "INTJ",
    "Z": "PARENTHETICAL",
}
_CASE = {
    "N": "Nom",
    "G": "Gen",
    "D": "Dat",
    "A": "Acc",
    "I": "Ins",
    "L": "Loc",
    "V": "Voc",
}
_NUMBER = {"S": "Sing", "P": "Plur"}
_GENDER = {"M": "Masc", "F": "Fem", "N": "Neut"}
_ANIMACY = {"A": "Anim", "I": "Inan"}
_TENSE = {"R": "Present", "P": "Past", "F": "Future", "Q": "Pluperfect"}
_ASPECT = {"P": "Perfective", "M": "Imperfective"}
_VOICE = {"A": "Active", "P": "Passive"}
_DEGREE = {"C": "Comparative", "S": "Superlative"}
_FEATURE_ORDER = {
    name: index
    for index, name in enumerate(
        (
            "Case",
            "Number",
            "Gender",
            "Animacy",
            "Person",
            "Tense",
            "Aspect",
            "Voice",
            "Mood",
            "VerbForm",
            "Degree",
        )
    )
}


@dataclass(frozen=True, slots=True)
class DecodedGrammarDBAnalysis:
    """One analysis rendered for compact downstream model evidence."""

    lemma: str
    pos: str
    features: tuple[tuple[str, str], ...]
    meaning: str | None
    decoded: bool
    raw_tag: str


def decode_grammar_db_analysis(analysis: GrammarDBAnalysis) -> DecodedGrammarDBAnalysis:
    """Decode one GrammarDB analysis without guessing unknown tag structures."""

    raw_tag = analysis.paradigm_tag + analysis.variant_tag + analysis.form_tag
    supplied = _source_features(analysis.morphology)
    decoded = supplied if supplied is not None else _tag_features(analysis)
    pos = _decoded_pos(analysis)
    return DecodedGrammarDBAnalysis(
        lemma=analysis.lemma,
        pos=pos,
        features=() if decoded is None else _ordered(decoded),
        meaning=analysis.meaning,
        decoded=decoded is not None,
        raw_tag=raw_tag,
    )


def _decoded_pos(analysis: GrammarDBAnalysis) -> str:
    tag = analysis.paradigm_tag + analysis.variant_tag
    if tag.startswith("NP"):
        return "PROPN"
    if tag.startswith("AP") or (tag.startswith("S") and len(tag) > 2 and tag[2] == "S"):
        return "DET"
    if tag.startswith("M") and len(tag) > 2 and tag[2] == "O":
        return "ADJ"
    if tag.startswith("V") and analysis.form_tag in {"RG", "PG"}:
        return "CONVERB"
    source_pos = tag[:1] if tag[:1] in _COARSE_POS else analysis.pos
    return _COARSE_POS.get(source_pos, source_pos or "UNKNOWN")


def _source_features(values: tuple[str, ...]) -> dict[str, str] | None:
    if not values:
        return None
    features: dict[str, str] = {}
    for value in values:
        for item in value.split("|"):
            key, separator, feature = item.partition("=")
            if not separator or not key or not feature:
                return None
            features[key] = feature
    return features


def _tag_features(analysis: GrammarDBAnalysis) -> dict[str, str] | None:
    tag = analysis.paradigm_tag + analysis.variant_tag
    pos = tag[:1] or analysis.pos
    if pos == "N":
        return _noun_features(tag, analysis.form_tag)
    if pos == "V":
        return _verb_features(tag, analysis.form_tag)
    if pos == "A":
        return _adjective_features(tag, analysis.form_tag)
    if pos == "M":
        return _numeral_features(tag, analysis.form_tag)
    if pos == "S":
        return _pronoun_features(tag, analysis.form_tag)
    if pos == "P":
        return _participle_features(tag, analysis.form_tag)
    if pos == "R":
        return _adverb_features(tag, analysis.form_tag)
    if pos in "CEFIWYZ" and tag and not analysis.form_tag:
        return {}
    return None


def _noun_features(tag: str, form: str) -> dict[str, str] | None:
    if (
        len(tag) != 7
        or tag[0] != "N"
        or tag[1] not in "CPX"
        or tag[2] not in "AIX"
        or tag[5] not in "MFNCXPSU"
    ):
        return None
    if tag[5] in "SU":
        result = _gender_case_number(form)
        if tag[6] != "5" or result is None:
            return None
    else:
        result = _case_number(form)
        if result is None:
            return None
        if tag[5] in _GENDER:
            result["Gender"] = _GENDER[tag[5]]
    if tag[2] in _ANIMACY:
        result["Animacy"] = _ANIMACY[tag[2]]
    return result


def _verb_features(tag: str, form: str) -> dict[str, str] | None:
    if len(tag) != 5 or tag[0] != "V" or tag[2] not in "PMX":
        return None
    result: dict[str, str] = {}
    if form == "0":
        result["VerbForm"] = "Infinitive"
    elif form in {"RG", "PG"}:
        result["Tense"] = _TENSE[form[0]]
    elif len(form) == 3 and form[0] in "RFQ" and form[1] in "1230" and form[2] in _NUMBER:
        if form[0] in _TENSE:
            result["Tense"] = _TENSE[form[0]]
        result["Person"] = form[1]
        result["Number"] = _NUMBER[form[2]]
    elif len(form) == 3 and form[0] == "P" and form[1] in "MFNX" and form[2] in _NUMBER:
        result["Tense"] = "Past"
        if form[1] in _GENDER:
            result["Gender"] = _GENDER[form[1]]
        result["Number"] = _NUMBER[form[2]]
    elif len(form) == 3 and form[0] == "I" and form[1] in "1230" and form[2] in _NUMBER:
        result["Person"] = form[1]
        result["Number"] = _NUMBER[form[2]]
        result["Mood"] = "Imperative"
    else:
        return None
    if tag[2] in _ASPECT:
        result["Aspect"] = _ASPECT[tag[2]]
    return result


def _adjective_features(tag: str, form: str) -> dict[str, str] | None:
    if tag == "A0" and not form:
        return {}
    if len(tag) != 3 or tag[0] != "A" or tag[1] not in "QRPX" or tag[2] not in "PCS":
        return None
    if form == "R":
        result: dict[str, str] = {}
    else:
        parsed = _gender_case_number(form)
        if parsed is None:
            return None
        result = parsed
    if tag[2] in _DEGREE:
        result["Degree"] = _DEGREE[tag[2]]
    return result


def _numeral_features(tag: str, form: str) -> dict[str, str] | None:
    if len(tag) != 4 or tag[0] != "M" or tag[1] not in "NAX0":
        return None
    if tag[1] == "0":
        return {} if form == "0" else None
    return _gender_case_number(form)


def _pronoun_features(tag: str, form: str) -> dict[str, str] | None:
    if len(tag) != 4 or tag[0] != "S" or tag[3] not in "1230X":
        return None
    if form == "1":
        result: dict[str, str] = {}
    else:
        parsed = _gender_case_number(form)
        if parsed is None:
            return None
        result = parsed
    if tag[3] in "123":
        result["Person"] = tag[3]
    return result


def _participle_features(tag: str, form: str) -> dict[str, str] | None:
    if (
        len(tag) != 4
        or tag[0] != "P"
        or tag[1] not in _VOICE
        or tag[2] not in "RP"
        or tag[3] not in "PMX"
    ):
        return None
    if form == "R":
        result: dict[str, str] = {}
    else:
        parsed = _gender_case_number(form)
        if parsed is None:
            return None
        result = parsed
    result["Voice"] = _VOICE[tag[1]]
    result["Tense"] = _TENSE[tag[2]]
    if tag[3] in _ASPECT:
        result["Aspect"] = _ASPECT[tag[3]]
    return result


def _adverb_features(tag: str, form: str) -> dict[str, str] | None:
    if len(tag) != 2 or tag[0] != "R" or not form or form not in "PCS":
        return None
    return {"Degree": _DEGREE[form]} if form in _DEGREE else {}


def _case_number(form: str) -> dict[str, str] | None:
    if len(form) != 2 or form[0] not in _CASE or form[1] not in _NUMBER:
        return None
    return {"Case": _CASE[form[0]], "Number": _NUMBER[form[1]]}


def _gender_case_number(form: str) -> dict[str, str] | None:
    if len(form) != 3 or form[0] not in "MFNPX0" or form[1] not in _CASE:
        return None
    result = _case_number(form[1:])
    if result is None:
        return None
    if form[0] in _GENDER:
        result["Gender"] = _GENDER[form[0]]
    return result


def _ordered(features: dict[str, str]) -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted(features.items(), key=lambda item: (_FEATURE_ORDER.get(item[0], 99), item[0]))
    )

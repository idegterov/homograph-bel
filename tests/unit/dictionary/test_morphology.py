from __future__ import annotations

from homograph_bel.dictionary import (
    MORPHOLOGY_DECODER_VERSION,
    DecodedGrammarDBAnalysis,
    decode_grammar_db_analysis,
)
from homograph_bel.dictionary.v2 import GrammarDBAnalysis


def _analysis(
    *,
    lemma: str,
    pos: str,
    paradigm_tag: str,
    form_tag: str,
    meaning: str | None = None,
    morphology: tuple[str, ...] = (),
) -> GrammarDBAnalysis:
    return GrammarDBAnalysis(
        release="RELEASE-202601",
        source_paradigm_id="1",
        source_variant_id="a",
        source_form_id="1",
        lemma=lemma,
        stressed_lemma=lemma,
        pos=pos,
        paradigm_tag=paradigm_tag,
        variant_tag="",
        form_tag=form_tag,
        meaning=meaning,
        theme=None,
        regulation=None,
        variant_type=None,
        form_type=None,
        form_options=None,
        source_dictionaries=("sbm2012",),
        orthographies=("A2008",),
        morphology=morphology,
        phonetic_forms=(),
        notes=(),
    )


def test_decodes_released_grammar_db_noun_form() -> None:
    decoded = decode_grammar_db_analysis(
        _analysis(lemma="плач", pos="N", paradigm_tag="NCIINM1", form_tag="GS")
    )

    assert MORPHOLOGY_DECODER_VERSION.endswith("c328ce92")
    assert decoded.pos == "NOUN"
    assert decoded.features == (
        ("Case", "Gen"),
        ("Number", "Sing"),
        ("Gender", "Masc"),
        ("Animacy", "Inan"),
    )
    assert decoded.decoded is True
    assert decoded.raw_tag == "NCIINM1GS"
    assert isinstance(decoded, DecodedGrammarDBAnalysis)


def test_decodes_released_grammar_db_verb_form() -> None:
    decoded = decode_grammar_db_analysis(
        _analysis(lemma="плаціць", pos="V", paradigm_tag="VDMN2", form_tag="R1S")
    )

    assert decoded.pos == "VERB"
    assert decoded.features == (
        ("Number", "Sing"),
        ("Person", "1"),
        ("Tense", "Present"),
        ("Aspect", "Imperfective"),
    )
    assert decoded.decoded is True


def test_preserves_source_morphology_and_meaning() -> None:
    decoded = decode_grammar_db_analysis(
        _analysis(
            lemma="вада",
            pos="N",
            paradigm_tag="N",
            form_tag="UNKNOWN",
            meaning="рэчыва",
            morphology=("Case=Nom|Number=Sing",),
        )
    )

    assert decoded.pos == "NOUN"
    assert decoded.features == (("Case", "Nom"), ("Number", "Sing"))
    assert decoded.meaning == "рэчыва"
    assert decoded.decoded is True


def test_unknown_tag_keeps_safe_coarse_pos_without_guessing_features() -> None:
    decoded = decode_grammar_db_analysis(
        _analysis(lemma="слова", pos="V", paradigm_tag="BROKEN", form_tag="TAG")
    )

    assert decoded.pos == "VERB"
    assert decoded.features == ()
    assert decoded.decoded is False
    assert decoded.raw_tag == "BROKENTAG"


def test_decodes_adjective_pronoun_and_participle_forms() -> None:
    adjective = decode_grammar_db_analysis(
        _analysis(lemma="абкапаны", pos="A", paradigm_tag="ARP", form_tag="MGS")
    )
    determiner = decode_grammar_db_analysis(
        _analysis(lemma="ваш", pos="S", paradigm_tag="SAS1", form_tag="MGS")
    )
    participle = decode_grammar_db_analysis(
        _analysis(lemma="зроблены", pos="P", paradigm_tag="PPPP", form_tag="MGS")
    )

    assert adjective.pos == "ADJ"
    assert adjective.features == (
        ("Case", "Gen"),
        ("Number", "Sing"),
        ("Gender", "Masc"),
    )
    assert determiner.pos == "DET"
    assert determiner.features == (
        ("Case", "Gen"),
        ("Number", "Sing"),
        ("Gender", "Masc"),
        ("Person", "1"),
    )
    assert participle.pos == "PARTICIPLE"
    assert participle.features == (
        ("Case", "Gen"),
        ("Number", "Sing"),
        ("Gender", "Masc"),
        ("Tense", "Past"),
        ("Aspect", "Perfective"),
        ("Voice", "Passive"),
    )


def test_decodes_special_verb_and_invariant_forms() -> None:
    imperative = decode_grammar_db_analysis(
        _analysis(lemma="аб'явіць", pos="V", paradigm_tag="VTPN2", form_tag="I2P")
    )
    infinitive = decode_grammar_db_analysis(
        _analysis(lemma="аб'явіць", pos="V", paradigm_tag="VTPN2", form_tag="0")
    )
    adverb = decode_grammar_db_analysis(
        _analysis(lemma="вышэй", pos="R", paradigm_tag="RX", form_tag="C")
    )
    particle = decode_grammar_db_analysis(
        _analysis(lemma="але", pos="E", paradigm_tag="E", form_tag="")
    )

    assert imperative.features == (
        ("Number", "Plur"),
        ("Person", "2"),
        ("Aspect", "Perfective"),
        ("Mood", "Imperative"),
    )
    assert infinitive.features == (
        ("Aspect", "Perfective"),
        ("VerbForm", "Infinitive"),
    )
    assert adverb.pos == "ADV"
    assert adverb.features == (("Degree", "Comparative"),)
    assert particle.pos == "PART"
    assert particle.features == ()
    assert particle.decoded is True


def test_decodes_plural_only_and_substantivized_nouns() -> None:
    plural_only = decode_grammar_db_analysis(
        _analysis(lemma="абрубы", pos="N", paradigm_tag="NPIINP7", form_tag="DP")
    )
    substantivized = decode_grammar_db_analysis(
        _analysis(lemma="дзяжурны", pos="N", paradigm_tag="NCIINS5", form_tag="MGS")
    )

    assert plural_only.pos == "PROPN"
    assert plural_only.features == (
        ("Case", "Dat"),
        ("Number", "Plur"),
        ("Animacy", "Inan"),
    )
    assert substantivized.features == (
        ("Case", "Gen"),
        ("Number", "Sing"),
        ("Gender", "Masc"),
        ("Animacy", "Inan"),
    )


def test_decodes_forms_with_explicit_absent_gender() -> None:
    pronoun = decode_grammar_db_analysis(
        _analysis(lemma="любы", pos="S", paradigm_tag="SAE0", form_tag="0DP")
    )
    verb = decode_grammar_db_analysis(
        _analysis(lemma="абабіцца", pos="V", paradigm_tag="VIPR1", form_tag="PXP")
    )

    assert pronoun.features == (("Case", "Dat"), ("Number", "Plur"))
    assert verb.features == (
        ("Number", "Plur"),
        ("Tense", "Past"),
        ("Aspect", "Perfective"),
    )


def test_decodes_remaining_supported_form_shapes() -> None:
    converb = decode_grammar_db_analysis(
        _analysis(lemma="зрабіўшы", pos="V", paradigm_tag="VIPN1", form_tag="PG")
    )
    past = decode_grammar_db_analysis(
        _analysis(lemma="зрабіць", pos="V", paradigm_tag="VIPN1", form_tag="PFS")
    )
    indeclinable_adjective = decode_grammar_db_analysis(
        _analysis(lemma="хакі", pos="A", paradigm_tag="A0", form_tag="")
    )
    adverbial_adjective = decode_grammar_db_analysis(
        _analysis(lemma="вышэй", pos="A", paradigm_tag="ARC", form_tag="R")
    )
    numeral = decode_grammar_db_analysis(
        _analysis(lemma="два", pos="M", paradigm_tag="MNCS", form_tag="MGS")
    )
    ordinal = decode_grammar_db_analysis(
        _analysis(lemma="другі", pos="M", paradigm_tag="MAOS", form_tag="MGS")
    )
    indeclinable_numeral = decode_grammar_db_analysis(
        _analysis(lemma="шмат", pos="M", paradigm_tag="M0CS", form_tag="0")
    )
    fixed_pronoun = decode_grammar_db_analysis(
        _analysis(lemma="нешта", pos="S", paradigm_tag="SNF0", form_tag="1")
    )
    short_participle = decode_grammar_db_analysis(
        _analysis(lemma="зроблена", pos="P", paradigm_tag="PPPP", form_tag="R")
    )

    assert converb.pos == "CONVERB"
    assert converb.features == (("Tense", "Past"), ("Aspect", "Perfective"))
    assert past.features == (
        ("Number", "Sing"),
        ("Gender", "Fem"),
        ("Tense", "Past"),
        ("Aspect", "Perfective"),
    )
    assert indeclinable_adjective.features == ()
    assert adverbial_adjective.features == (("Degree", "Comparative"),)
    assert numeral.features == (
        ("Case", "Gen"),
        ("Number", "Sing"),
        ("Gender", "Masc"),
    )
    assert ordinal.pos == "ADJ"
    assert indeclinable_numeral.features == ()
    assert fixed_pronoun.features == ()
    assert short_participle.features == (
        ("Tense", "Past"),
        ("Aspect", "Perfective"),
        ("Voice", "Passive"),
    )


def test_malformed_source_and_tag_shapes_remain_undecoded() -> None:
    values = (
        _analysis(
            lemma="плач",
            pos="N",
            paradigm_tag="NCIINM1",
            form_tag="GS",
            morphology=("not-a-feature",),
        ),
        _analysis(lemma="x", pos="N", paradigm_tag="N", form_tag="GS"),
        _analysis(lemma="x", pos="N", paradigm_tag="NCIINS4", form_tag="MGS"),
        _analysis(lemma="x", pos="N", paradigm_tag="NCIINM1", form_tag="ZZ"),
        _analysis(lemma="x", pos="V", paradigm_tag="V", form_tag="0"),
        _analysis(lemma="x", pos="V", paradigm_tag="VDMN2", form_tag="ZZ"),
        _analysis(lemma="x", pos="A", paradigm_tag="A", form_tag=""),
        _analysis(lemma="x", pos="A", paradigm_tag="ARP", form_tag="ZGS"),
        _analysis(lemma="x", pos="A", paradigm_tag="ARP", form_tag="MGZ"),
        _analysis(lemma="x", pos="M", paradigm_tag="M", form_tag=""),
        _analysis(lemma="x", pos="M", paradigm_tag="M0CS", form_tag="X"),
        _analysis(lemma="x", pos="S", paradigm_tag="S", form_tag=""),
        _analysis(lemma="x", pos="S", paradigm_tag="SAS1", form_tag="ZZZ"),
        _analysis(lemma="x", pos="P", paradigm_tag="P", form_tag=""),
        _analysis(lemma="x", pos="P", paradigm_tag="PPPP", form_tag="ZZZ"),
        _analysis(lemma="x", pos="R", paradigm_tag="RX", form_tag=""),
    )

    decoded = tuple(decode_grammar_db_analysis(value) for value in values)

    assert decoded[0].decoded is True
    assert decoded[0].features[0] == ("Case", "Gen")
    assert all(item.decoded is False for item in decoded[1:])

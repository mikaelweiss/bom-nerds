"""Reads Macula's grammar codes: OSHB morphology for Hebrew and Aramaic, Robinson's for Greek.

Each code becomes its features by name, as db/seed.sql spells them. A code that does not parse completely raises ValueError.
"""

import re

PARTS_OF_SPEECH = {
    "A": "Adjective", "C": "Conjunction", "D": "Adverb", "N": "Noun", "P": "Pronoun", "R": "Preposition", "S": "Suffix", "T": "Particle", "V": "Verb",
}

HEBREW_TYPES = {
    "A": {"a": "Adjective", "c": "Cardinal number", "g": "Gentilic", "o": "Ordinal number"},
    "N": {"c": "Common", "g": "Gentilic"},
    "P": {"d": "Demonstrative", "f": "Indefinite", "i": "Interrogative", "p": "Personal", "r": "Relative"},
    "R": {"d": "Definite article"},
    "S": {"d": "Directional he", "h": "Paragogic he", "n": "Paragogic nun", "p": "Pronominal"},
    "T": {"a": "Affirmation", "e": "Exhortation", "i": "Interrogative", "m": "Demonstrative", "n": "Negative", "o": "Direct object marker", "r": "Relative"},
}

# Some type letters name a part of speech of their own, the one Greek and English words of that kind take.
HEBREW_TYPED_PARTS = {("N", "p"): "Proper noun", ("T", "d"): "Article", ("T", "j"): "Interjection"}

HEBREW_STEMS = {
    "q": "Qal", "N": "Niphal", "p": "Piel", "P": "Pual", "h": "Hiphil", "H": "Hophal", "t": "Hithpael", "o": "Polel", "O": "Polal",
    "r": "Hithpolel", "m": "Poel", "M": "Poal", "k": "Palel", "K": "Pulal", "Q": "Qal passive", "l": "Pilpel", "L": "Polpal",
    "f": "Hithpalpel", "D": "Nithpael", "j": "Pealal", "i": "Pilel", "u": "Hothpaal", "c": "Tiphil", "v": "Hishtaphel",
    "w": "Nithpalel", "y": "Nithpoel", "z": "Hithpoel",
}

# Aramaic gives many of the same letters to other stems.
ARAMAIC_STEMS = {
    "q": "Peal", "Q": "Peil", "u": "Hithpeel", "p": "Pael", "P": "Ithpaal", "M": "Hithpaal", "a": "Aphel", "h": "Haphel", "s": "Saphel",
    "e": "Shaphel", "H": "Hophal", "i": "Ithpeel", "t": "Hishtaphel", "v": "Ishtaphel", "w": "Hithaphel", "o": "Polel", "z": "Ithpoel",
    "r": "Hithpolel", "f": "Hithpalpel", "b": "Hephal", "c": "Tiphel", "m": "Poel", "l": "Palpel", "L": "Ithpalpel", "O": "Ithpolel",
    "G": "Ittaphal",
}

FINITE = {"p": "Perfect", "q": "Sequential perfect", "i": "Imperfect", "w": "Sequential imperfect", "h": "Cohortative", "j": "Jussive", "v": "Imperative"}
PARTICIPLES = {"r": "Active participle", "s": "Passive participle"}
INFINITIVES = {"a": "Infinitive absolute", "c": "Infinitive construct"}
VERB_FORMS = FINITE | PARTICIPLES | INFINITIVES

PERSONS = {"1": 1, "2": 2, "3": 3}
HEBREW_GENDERS = {"m": "Masculine", "f": "Feminine", "c": "Common", "b": "Both"}
HEBREW_NUMBERS = {"s": "Singular", "p": "Plural", "d": "Dual"}
STATES = {"a": "Absolute", "c": "Construct", "d": "Determined"}

HEBREW_SLOTS = {
    "A": ("word_type", "gender", "grammatical_number", "state"),
    "C": (),
    "D": (),
    "N": ("word_type", "gender", "grammatical_number", "state"),
    "P": ("word_type", "person", "gender", "grammatical_number"),
    "R": ("word_type",),
    "S": ("word_type", "person", "gender", "grammatical_number"),
    "T": ("word_type",),
}

GREEK_PRONOUNS = {
    "P": "Personal", "R": "Relative", "C": "Reciprocal", "D": "Demonstrative", "K": "Correlative", "I": "Interrogative",
    "X": "Indefinite", "Q": "Correlative or interrogative", "F": "Reflexive", "S": "Possessive",
}
GREEK_WORDS = {"ADV": "Adverb", "CONJ": "Conjunction", "COND": "Conjunction", "PRT": "Particle", "PREP": "Preposition", "INJ": "Interjection"}
TRANSLITERATED = {"ARAM": "arc", "HEB": "hbo"}
TENSES = {"P": "Present", "I": "Imperfect", "F": "Future", "A": "Aorist", "R": "Perfect", "L": "Pluperfect"}
VOICES = {
    "A": "Active", "M": "Middle", "P": "Passive", "D": "Middle deponent", "O": "Passive deponent",
    "N": "Middle or passive deponent", "E": "Middle or passive",
}
MOODS = {"I": "Indicative", "S": "Subjunctive", "O": "Optative", "M": "Imperative", "N": "Infinitive", "P": "Participle"}
CASES = {"N": "Nominative", "G": "Genitive", "D": "Dative", "A": "Accusative", "V": "Vocative"}
GREEK_GENDERS = {"M": "Masculine", "F": "Feminine", "N": "Neuter"}
GREEK_NUMBERS = {"S": "Singular", "P": "Plural"}
DEGREES = {"C": "Comparative", "S": "Superlative"}
SUFFIX_TYPES = {"N": "Negative", "I": "Interrogative"}

# Robinson writes case, number, and gender in that order, after a person where one applies: "N-NSM", "P-1NS", "F-3ASM", "S-1SNSM".
NOMINAL = re.compile(r"(?P<person>[123])?(?P<possessor>[SP](?=[NGDAV][SP]))?(?P<case>[NGDAV])(?P<number>[SP])(?P<gender>[MFN])?")
VERB = re.compile(r"(?P<second>2)?(?P<tense>[PIFARL])(?P<voice>[AMPDONE])(?P<mood>[ISOMNP])(?:-(?:(?P<person>[123])(?P<number>[SP])|(?P<case>[NGDAV])(?P<pnumber>[SP])(?P<gender>[MFN])))?")


def hebrew(code: str, aramaic: bool) -> dict:
    """The features of an OSHB code such as "Vqp3ms": qal, perfect, third person, masculine, singular.

    An "x" stands for a feature the code leaves unknown or unneeded, which is left out.
    """
    letter, rest = code[:1], code[1:]
    if letter not in PARTS_OF_SPEECH:
        raise ValueError(f"unknown part of speech in Hebrew code {code!r}")
    features = {"part_of_speech": PARTS_OF_SPEECH[letter]}
    if letter == "V":
        stems = ARAMAIC_STEMS if aramaic else HEBREW_STEMS
        if len(rest) < 2 or rest[0] not in stems or rest[1] not in VERB_FORMS:
            raise ValueError(f"unknown stem or verb form in Hebrew code {code!r}")
        features |= {"stem": stems[rest[0]], "verb_form": VERB_FORMS[rest[1]]}
        form, rest = rest[1], rest[2:]
        slots = ("person", "gender", "grammatical_number") if form in FINITE else ("gender", "grammatical_number", "state") if form in PARTICIPLES else ()
    elif (letter, rest[:1]) in HEBREW_TYPED_PARTS:
        features["part_of_speech"] = HEBREW_TYPED_PARTS[(letter, rest[:1])]
        rest, slots = rest[1:], HEBREW_SLOTS[letter][1:]
    else:
        slots = HEBREW_SLOTS[letter]
    if len(rest) > len(slots):
        raise ValueError(f"Hebrew code {code!r} is longer than its part of speech allows")
    values = {
        "word_type": HEBREW_TYPES.get(letter, {}), "person": PERSONS, "gender": HEBREW_GENDERS,
        "grammatical_number": HEBREW_NUMBERS, "state": STATES,
    }
    for slot, char in zip(slots, rest):
        if char == "x":
            continue
        if char not in values[slot]:
            raise ValueError(f"unknown {slot} {char!r} in Hebrew code {code!r}")
        features[slot] = values[slot][char]
    return features


def greek(code: str) -> dict:
    """The features of a Robinson code such as "V-2AAI-3S": second aorist, active, indicative, third person, singular."""
    head, _, rest = code.partition("-")
    features = {"second_form": False, "indeclinable": False, "crasis": False, "attic_form": False}
    if head in TRANSLITERATED and not rest:
        return features | {"indeclinable": True, "transliterated_from": TRANSLITERATED[head]}
    suffixes = []
    if head == "V":
        match = VERB.match(rest)
        if not match:
            raise ValueError(f"unparsed verb in Greek code {code!r}")
        found = match.groupdict()
        features |= {
            "part_of_speech": "Verb", "second_form": bool(found["second"]), "tense": TENSES[found["tense"]],
            "voice": VOICES[found["voice"]], "mood": MOODS[found["mood"]],
        }
        mood = features["mood"]
        if bool(found["person"]) != (mood not in ("Infinitive", "Participle")) or bool(found["case"]) != (mood == "Participle"):
            raise ValueError(f"Greek code {code!r} does not fit its mood")
        if found["person"]:
            features |= {"person": int(found["person"]), "grammatical_number": GREEK_NUMBERS[found["number"]]}
        if found["case"]:
            features |= {"grammatical_case": CASES[found["case"]], "grammatical_number": GREEK_NUMBERS[found["pnumber"]], "gender": GREEK_GENDERS[found["gender"]]}
        remainder = rest[match.end():]
        if remainder and not remainder.startswith("-"):
            raise ValueError(f"unparsed {remainder!r} in Greek code {code!r}")
        suffixes = remainder.split("-")[1:]
    elif head in GREEK_WORDS:
        features["part_of_speech"] = GREEK_WORDS[head]
        if head == "COND":
            features["word_type"] = "Conditional"
        suffixes = rest.split("-") if rest else []
    elif head in ("N", "A", "T") or head in GREEK_PRONOUNS:
        features["part_of_speech"] = {"N": "Noun", "A": "Adjective", "T": "Article"}.get(head, "Pronoun")
        if head in GREEK_PRONOUNS:
            features["word_type"] = GREEK_PRONOUNS[head]
        body, *suffixes = rest.split("-")
        if body in ("PRI", "LI", "OI") and head == "N" or body == "NUI" and head == "A":
            features["indeclinable"] = True
            features |= {"PRI": {"part_of_speech": "Proper noun"}, "LI": {"word_type": "Letter"}, "OI": {}, "NUI": {"word_type": "Numeral"}}[body]
        else:
            match = NOMINAL.fullmatch(body)
            if not match:
                raise ValueError(f"unparsed case, number, and gender in Greek code {code!r}")
            found = match.groupdict()
            if found["person"] and head not in ("P", "F", "S") or found["possessor"] and head != "S":
                raise ValueError(f"Greek code {code!r} gives a person or possessor to a word that takes none")
            features |= {"grammatical_case": CASES[found["case"]], "grammatical_number": GREEK_NUMBERS[found["number"]]}
            if found["person"]:
                features["person"] = int(found["person"])
            if found["possessor"]:
                features["possessor_number"] = GREEK_NUMBERS[found["possessor"]]
            if found["gender"]:
                features["gender"] = GREEK_GENDERS[found["gender"]]
        # A trailing "-" marks a gender the code leaves unknown: "P-AP-".
        if suffixes == [""]:
            suffixes = []
    else:
        raise ValueError(f"unknown part of speech in Greek code {code!r}")
    for suffix in suffixes:
        if suffix in DEGREES:
            features["degree"] = DEGREES[suffix]
        elif suffix in SUFFIX_TYPES and "word_type" not in features:
            features["word_type"] = SUFFIX_TYPES[suffix]
        elif suffix == "K":
            features["crasis"] = True
        elif suffix == "ATT":
            features["attic_form"] = True
        else:
            raise ValueError(f"unknown suffix {suffix!r} in Greek code {code!r}")
    return features

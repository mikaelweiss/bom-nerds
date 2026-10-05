"""English headwords and parts of speech: a lookup table first, then spaCy and Stanza as the two runs, with MorphAdorner breaking ties.

Words all three leave unsettled get no headword.
"""

import json
import re
import sqlite3

from .rows import row_id
from .taggers import CACHE, TAGGERS
from .text import WORDS, english_editions, marks

PRONOUNS = {
    "I": "i me my mine myself", "thou": "thou thee thy thine thyself", "you": "ye you your yours yourself yourselves",
    "he": "he him his himself", "she": "she her hers herself", "it": "it its itself",
    "we": "we us our ours ourselves", "they": "they them their theirs themselves",
}
ARCHAIC_VERBS = {
    "have": "hath hast hadst", "do": "doth dost didst", "say": "saith sayest saidst", "speak": "spake spakest", "be": "art wast wert",
    "shall": "shall shalt", "will": "wilt", "can": "canst cannot", "could": "could couldest couldst", "would": "would wouldest wouldst",
    "should": "should shouldest shouldst", "may": "mayest mayst", "might": "mightest", "must": "must",
}
# Word: (headword, part of speech). None keeps the taggers' answer for that half.
TABLE = {
    **{form: (headword, "Pronoun") for headword, forms in PRONOUNS.items() for form in forms.split()},
    **{form: (headword, "Verb") for headword, forms in ARCHAIC_VERBS.items() for form in forms.split()},
    "these": ("this", None), "those": ("that", None), "an": ("a", "Article"), "o": ("O", "Interjection"), "yea": ("yea", "Interjection"),
}
# Old past tenses the taggers read as other words. Each counts only where the word is a verb: "she bare a son", but "made bare".
PAST_TENSES = {"bare": "bear", "brake": "break", "sware": "swear", "clave": "cleave", "gat": "get", "drave": "drive", "durst": "dare", "holpen": "help", "wrought": "work"}
TITLES = {"lord", "father", "son", "god", "christ", "messiah", "savior", "saviour", "redeemer", "creator", "spirit", "ghost", "lamb"}

UNIVERSAL = {
    "NOUN": "Noun", "PROPN": "Proper noun", "PRON": "Pronoun", "VERB": "Verb", "AUX": "Verb", "ADJ": "Adjective", "ADV": "Adverb",
    "ADP": "Preposition", "CCONJ": "Conjunction", "SCONJ": "Conjunction", "NUM": "Numeral", "PART": "Particle", "INTJ": "Interjection",
}
ARTICLES = {"the", "a", "an"}


def clear(db: sqlite3.Connection):
    english = english_editions(db)
    db.execute(
        f"update word set headword_id = null, meaning_id = null, part_of_speech_id = null where id in (select w.id from {WORDS} where c.edition_id in ({marks(english)}))",
        english,
    )
    language = row_id(db, "language", "en", "iso_code")
    db.execute("delete from meaning where headword_id in (select id from headword where language_id = ?)", (language,))
    db.execute("delete from headword where language_id = ?", (language,))


def run(db: sqlite3.Connection):
    answers = {name: load(name) for name in TAGGERS}
    verbs = {lemma.lower() for name in TAGGERS for lemma, pos in answers[name].values() if pos == "Verb"}
    rows, unsettled = [], 0
    english = english_editions(db)
    words = list(db.execute(f"select w.id, w.text from {WORDS} where c.edition_id in ({marks(english)}) order by w.sequence", english))
    for index, (id, text) in enumerate(words):
        spacy, stanza, morph = (answers[name].get(id) for name in TAGGERS)
        table_headword, table_pos = TABLE.get(text.lower(), (None, None))
        previous = words[index - 1][1].lower() if index else ""
        archaic = archaic_verb(text.lower(), previous, {t.lower() for _, t in words[max(0, index - 3):index + 4]}, verbs, morph)
        if archaic:
            table_headword, table_pos = archaic, "Verb"
        if text.lower() in TITLES:
            table_pos = "Noun"
        pos = table_pos or vote(*(a and a[1] for a in (spacy, stanza, morph)))
        if pos == "Verb" and text.lower() in PAST_TENSES:
            table_headword = PAST_TENSES[text.lower()]
        headword = table_headword or vote(*(a and a[0].lower() for a in (spacy, stanza, morph)))
        if headword and pos:
            rows.append((id, spelled(headword, pos, text), pos))
        else:
            unsettled += 1

    headwords = sorted({h for _, h, _ in rows})
    language = row_id(db, "language", "en", "iso_code")
    db.executemany("insert into headword (language_id, text) values (?, ?)", [(language, h) for h in headwords])
    ids = dict(db.execute("select text, id from headword where language_id = ?", (language,)))
    parts_of_speech = {name: row_id(db, "part_of_speech", name) for name in {p for _, _, p in rows}}
    db.executemany("update word set headword_id = ?, part_of_speech_id = ? where id = ?", [(ids[h], parts_of_speech[p], w) for w, h, p in rows])
    print(f"headwords: {len(rows)} English words settled into {len(headwords)} headwords, {unsettled} left unsettled")


def load(name: str) -> dict[int, tuple[str, str | None]]:
    found = {}
    with open(CACHE / f"{name}.jsonl", encoding="utf-8") as lines:
        for line in lines:
            for id, lemma, tag, _, _ in json.loads(line):
                found[id] = (lemma, nupos(tag, lemma) if name == "morphadorner" else universal(tag, lemma))
    return found


def vote(spacy, stanza, morph):
    if spacy and spacy == stanza:
        return spacy
    if morph and morph in (spacy, stanza):
        return morph
    return None


def spelled(headword: str, pos: str, text: str) -> str:
    """Headwords are lowercase, except proper nouns, "I", and "O"."""
    if headword.lower() in ("i", "o"):
        return headword.upper()
    if pos == "Proper noun":
        # Small capitals print some names in full capitals, "BABYLON", and they share the name's headword.
        return text if text.lower() == headword.lower() and not text.isupper() else headword[:1].upper() + headword[1:].lower()
    return headword.lower()


def archaic_verb(word: str, previous: str, neighbors: set[str], verbs: set[str], morph) -> str | None:
    """Every "-eth" and "-est" verb form: "giveth" is "give", "lovest" is "love".

    An "-est" verb has "thou" nearby, which tells it from a superlative like "the greatest".
    """
    if word.endswith("est"):
        if "thou" not in neighbors or previous in ("the", "most"):
            return None
    elif not word.endswith("eth"):
        return None
    stem = word[:-3]
    # A one-letter stem is a name or a superlative, not a verb: "Seth", "best".
    if len(stem) < 2:
        return None
    # "seeth" is "see", not "se", but "goeth" is "go".
    candidates = [stem + "e", stem] if stem[-1] in "aeiou" else [stem, stem + "e"]
    if len(stem) > 2 and stem[-1] == stem[-2]:
        candidates.append(stem[:-1])
    if stem.endswith("i"):
        candidates.append(stem[:-1] + "y")
    for candidate in candidates:
        if candidate in verbs:
            return candidate
    if morph and morph[1] == "Verb":
        return morph[0].lower()
    return None


def universal(tag: str, lemma: str) -> str | None:
    if tag == "DET":
        return "Article" if lemma.lower() in ARTICLES else "Adjective"
    return UNIVERSAL.get(tag)


def nupos(tag: str, lemma: str) -> str | None:
    """Map MorphAdorner's NUPOS tags onto our parts of speech."""
    rules = [
        (r"np", "Proper noun"), (r"n", "Noun"), (r"pc-", "Particle"), (r"pp|p-", "Preposition"), (r"p[nosxi]|r|q-", "Pronoun"),
        (r"v", "Verb"), (r"j|ord", "Adjective"), (r"av", "Adverb"), (r"xx", "Particle"), (r"crd", "Numeral"), (r"c", "Conjunction"),
        (r"uh", "Interjection"),
    ]
    if tag.startswith("d"):
        return "Article" if lemma.lower() in ARTICLES else "Adjective"
    return next((pos for pattern, pos in rules if re.match(pattern, tag)), None)

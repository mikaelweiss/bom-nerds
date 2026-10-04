"""English headwords and parts of speech: a lookup table first, then spaCy and Stanza as the two runs, with MorphAdorner breaking ties.

Words all three leave unsettled get no headword here, and are listed in cache/headwords-unsettled.jsonl for the AI.
"""

import json
import re
import sqlite3

from .sentences import ENGLISH
from .taggers import CACHE, TAGGERS

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
    **{form: (headword, "pronoun") for headword, forms in PRONOUNS.items() for form in forms.split()},
    **{form: (headword, "verb") for headword, forms in ARCHAIC_VERBS.items() for form in forms.split()},
    "these": ("this", None), "those": ("that", None), "an": ("a", "article"), "o": ("O", "interjection"), "yea": ("yea", "interjection"),
}
# Old past tenses the taggers read as other words. Each counts only where the word is a verb: "she bare a son", but "made bare".
PAST_TENSES = {"bare": "bear", "brake": "break", "sware": "swear", "clave": "cleave", "gat": "get", "drave": "drive", "durst": "dare", "holpen": "help", "wrought": "work"}
TITLES = {"lord", "father", "son", "god", "christ", "messiah", "savior", "saviour", "redeemer", "creator", "spirit", "ghost", "lamb"}

UNIVERSAL = {
    "NOUN": "noun", "PROPN": "proper_noun", "PRON": "pronoun", "VERB": "verb", "AUX": "verb", "ADJ": "adjective", "ADV": "adverb",
    "ADP": "preposition", "CCONJ": "conjunction", "SCONJ": "conjunction", "NUM": "numeral", "PART": "particle", "INTJ": "interjection",
}
ARTICLES = {"the", "a", "an"}


def clear(db: sqlite3.Connection):
    db.execute("delete from word_meaning where meaning_id in (select m.id from meaning m join headword h on h.id = m.headword_id where h.language = 'en')")
    db.execute("delete from meaning where headword_id in (select id from headword where language = 'en')")
    db.execute(f"delete from word_headword where word_id in (select id from word where edition_id in ({','.join('?' * len(ENGLISH))}))", ENGLISH)
    db.execute("delete from headword where language = 'en'")


def run(db: sqlite3.Connection):
    answers = {name: load(name) for name in TAGGERS}
    verbs = {lemma.lower() for name in TAGGERS for lemma, pos in answers[name].values() if pos == "verb"}
    rows, unsettled = [], []
    words = list(db.execute(f"select id, text from word where edition_id in ({','.join('?' * len(ENGLISH))}) order by id", ENGLISH))
    for index, (id, text) in enumerate(words):
        spacy, stanza, morph = (answers[name].get(id) for name in TAGGERS)
        table_headword, table_pos = TABLE.get(text.lower(), (None, None))
        previous = words[index - 1][1].lower() if index else ""
        archaic = archaic_verb(text.lower(), previous, {t.lower() for _, t in words[max(0, index - 3):index + 4]}, verbs, morph)
        if archaic:
            table_headword, table_pos = archaic, "verb"
        if text.lower() in TITLES:
            table_pos = "noun"
        pos = table_pos or vote(*(a and a[1] for a in (spacy, stanza, morph)))
        if pos == "verb" and text.lower() in PAST_TENSES:
            table_headword = PAST_TENSES[text.lower()]
        headword = table_headword or vote(*(a and a[0].lower() for a in (spacy, stanza, morph)))
        if headword and pos:
            rows.append((id, spelled(headword, pos, text), pos))
        else:
            unsettled.append({"word": id, "text": text, "spacy": spacy, "stanza": stanza, "morphadorner": morph})

    headwords = sorted({h for _, h, _ in rows})
    db.executemany("insert into headword (language, text) values ('en', ?)", [(h,) for h in headwords])
    ids = dict(db.execute("select text, id from headword where language = 'en'"))
    db.executemany("insert into word_headword (word_id, headword_id, part_of_speech) values (?, ?, ?)", [(w, ids[h], p) for w, h, p in rows])
    with open(CACHE / "headwords-unsettled.jsonl", "w", encoding="utf-8") as out:
        for item in unsettled:
            out.write(json.dumps(item, ensure_ascii=False) + "\n")
    print(f"headwords: {len(rows)} English words settled into {len(headwords)} headwords, {len(unsettled)} left for the AI")


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
    if pos == "proper_noun":
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
    if morph and morph[1] == "verb":
        return morph[0].lower()
    return None


def universal(tag: str, lemma: str) -> str | None:
    if tag == "DET":
        return "article" if lemma.lower() in ARTICLES else "adjective"
    return UNIVERSAL.get(tag)


def nupos(tag: str, lemma: str) -> str | None:
    """Map MorphAdorner's NUPOS tags onto our parts of speech."""
    rules = [
        (r"np", "proper_noun"), (r"n", "noun"), (r"pc-", "particle"), (r"pp|p-", "preposition"), (r"p[nosxi]|r|q-", "pronoun"),
        (r"v", "verb"), (r"j|ord", "adjective"), (r"av", "adverb"), (r"xx", "particle"), (r"crd", "numeral"), (r"c", "conjunction"),
        (r"uh", "interjection"),
    ]
    if tag.startswith("d"):
        return "article" if lemma.lower() in ARTICLES else "adjective"
    return next((pos for pattern, pos in rules if re.match(pattern, tag)), None)

"""Give English headwords the senses of Webster's 1828 dictionary, and tag words whose headword has one sense.

    python fill_english_meanings.py scripture.db WEBSTER_SQL

WEBSTER_SQL is dictionary_webster1828.sql from github.com/DataWar/1828-dictionary.
A headword takes the senses filed under the parts of speech its words use. Proper nouns are left out.
"""

import html
import re
import sqlite3
import sys
from collections import Counter, defaultdict

ROW = re.compile(
    r"\((\d+), '((?:[^'\\]|\\.)*)', \d+, '((?:[^'\\]|\\.)*)', '(?:[^'\\]|\\.)*', '(?:[^'\\]|\\.)*', '((?:[^'\\]|\\.)*)'\)"
)
ENTRY = re.compile(r"<p><b>[^<]*</b>[^<]{0,12}<i>([^<]*)</i>")
NUMBERED = re.compile(r"^<b>\d+\.</b>\s*")
PART_OF_SPEECH = {
    "noun": "Noun", "verb": "Verb", "participle": "Verb", "adjective": "Adjective", "adverb": "Adverb",
    "preposition": "Preposition", "conjunction": "Conjunction", "pronoun": "Pronoun", "interjection": "Interjection",
    "exclamation": "Interjection", "article": "Article",
}
ABBREVIATION = {
    "n": "Noun", "v": "Verb", "pp": "Verb", "ppr": "Verb", "a": "Adjective", "adv": "Adverb", "prep": "Preposition",
    "conj": "Conjunction", "pron": "Pronoun", "interj": "Interjection", "exclam": "Interjection",
}
OLD_ENTRY = re.compile(r"<p><b>[^<]*</b>,?\s*((?:[a-z]+\.\s*)+)")
GLOSS_LENGTH = 60


def unescape_sql(text):
    return re.sub(r"\\(.)", lambda m: {"n": "\n", "r": "", "t": " "}.get(m.group(1), m.group(1)), text)


def plain(fragment):
    text = re.sub(r"<[^>]+>", "", fragment)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def senses(content):
    """(part of speech, definition) for each numbered sense, or the lone definition of an unnumbered entry."""
    found = []
    pieces = ENTRY.split(content)
    if len(pieces) == 1:
        paragraphs = [p for p in re.split(r"</?p>", content) if plain(p)][1:]
        numbered = [plain(NUMBERED.sub("", p)) for p in paragraphs if NUMBERED.match(p.strip())]
        lone = next((plain(p) for p in paragraphs if len(plain(p).split()) >= 3), None)
        return [(None, d) for d in numbered if d] or ([(None, lone)] if lone else [])
    for label, body in zip(pieces[1::2], pieces[2::2]):
        kind = next((v for k, v in PART_OF_SPEECH.items() if re.search(rf"\b{k}\b", label.lower())), None)
        paragraphs = [p for p in re.split(r"</?p>", body) if p.strip()]
        numbered = [plain(NUMBERED.sub("", p)) for p in paragraphs if NUMBERED.match(p.strip())]
        if numbered:
            found.extend((kind, d) for d in numbered if d)
        else:
            # The heading paragraph may hold only pronunciation and etymology, with the definition after it.
            texts = [plain(re.sub(r"\[[^\]]*\]", "", paragraphs[0]))] + [plain(p) for p in paragraphs[1:]] if paragraphs else []
            lone = next((t for t in texts if len(t.split()) >= 3), None)
            if lone:
                found.append((kind, lone))
    return found


def old_senses(string):
    """Senses from the older plain markup some rows keep in place of the formatted entry."""
    found = []
    pieces = OLD_ENTRY.split(string)
    for label, body in zip(pieces[1::2], pieces[2::2]):
        kind = ABBREVIATION.get(label.split(".")[0].strip())
        numbered = [plain(d) for d in re.findall(r"<DD>\s*\d+\.\s*(.*?)(?=<p>|$)", body, flags=re.S)]
        if numbered:
            found.extend((kind, d) for d in numbered if d)
        else:
            lone = plain(re.sub(r"\[[^\]]*\]", "", body.split("<p>")[0]))
            if len(lone.split()) >= 3:
                found.append((kind, lone))
    return found


def defines(segment):
    words = segment.split()
    if not words or re.match(r"(?i)(preterit|participle|pret|pp)\b", segment):
        return False
    return len(words) >= 2 or ("'" not in segment and segment[0].isupper())


def gloss(definition):
    """The first clause that defines, skipping pronunciation and inflection notes."""
    segments = [re.sub(r"^(?:\S*'\S*\s+)+(?=[A-Z])", "", x.strip()) for x in re.split(r"[;:.]", definition)]
    first = next(
        (x for x in segments if defines(x)),
        next((x for x in segments if x), definition),
    )
    if len(first) <= GLOSS_LENGTH:
        return first
    return first[:GLOSS_LENGTH].rsplit(" ", 1)[0]


def main(path, webster):
    dictionary = defaultdict(list)
    for _, word, string, content in ROW.findall(open(webster, encoding="utf-8", errors="replace").read()):
        dictionary[unescape_sql(word).lower()].extend(senses(unescape_sql(content)) or old_senses(unescape_sql(string)))

    db = sqlite3.connect(path)
    db.execute("pragma foreign_keys = on")
    english = db.execute("select id from language where iso_code = 'en'").fetchone()[0]
    uses = defaultdict(Counter)
    for headword, pos in db.execute(
        "select w.headword_id, p.name from word w join headword h on h.id = w.headword_id "
        "join part_of_speech p on p.id = w.part_of_speech_id where h.language_id = ?", (english,)
    ):
        uses[headword][pos] += 1

    given = sense_count = 0
    for headword, text in db.execute(
        "select id, text from headword where language_id = ? and id not in (select headword_id from meaning)", (english,)
    ).fetchall():
        kinds = uses.get(headword)
        if not kinds or kinds.most_common(1)[0][0] == "Proper noun":
            continue
        entry = dictionary.get(text.lower())
        if not entry:
            continue
        chosen = [d for kind, d in entry if kind in kinds] or [d for _, d in entry]
        for number, definition in enumerate(dict.fromkeys(chosen), 1):
            db.execute(
                "insert into meaning (headword_id, number, gloss, definition) values (?, ?, ?, ?)",
                (headword, number, gloss(definition), definition),
            )
            sense_count += 1
        given += 1

    tagged = db.execute(
        "update word set meaning_id = (select min(m.id) from meaning m where m.headword_id = word.headword_id) "
        "where meaning_id is null and headword_id in (select h.id from headword h join meaning m on m.headword_id = h.id "
        "where h.language_id = ? group by h.id having count(*) = 1)", (english,)
    ).rowcount
    db.commit()
    print(f"{given} English headwords given {sense_count} meanings, {tagged} words tagged with their headword's only meaning")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])

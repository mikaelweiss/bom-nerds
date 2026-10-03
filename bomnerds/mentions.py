"""Mentions of names that a script can settle: Bible names by Strong's number and TIPNR's verse lists, and the names of Jehovah."""

import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass

from . import tipnr
from .entities import EPONYMS, GENTILIC, JESUS, JESUS_CHRIST, bible_entities, build_ids, is_name, peoples, usable
from .refs import OLD_TESTAMENT, USFM, codes
from .strongs import base, translation_units
from .text import bible, slug
from .versification import mapping

# Latter-day Saint doctrine: the LORD, JAH, and GOD of the Old Testament render the name Jehovah, who is Jesus Christ.
JEHOVAH_STRONGS = {"H3068", "H3050", "H3069"}

# The two words before an eponym's name settle whether it means his people or their land: "tribe of Judah", "land of Judah".
PEOPLE_CUES = {("tribe", "of"), ("tribes", "of"), ("children", "of"), ("house", "of")}
LAND_CUES = {("land", "of"), ("cities", "of"), ("coast", "of"), ("coasts", "of"), ("border", "of"), ("borders", "of")}
KINGDOM_CUES = {("king", "of"), ("kings", "of"), ("kingdom", "of")}


@dataclass(frozen=True)
class Name:
    """One of a TIPNR record's name forms."""

    entity: str
    # The people the record's gentilic words name, and the words that name it and not the record: "Egyptians" and not "Egypt".
    people: str | None = None
    gentilics: frozenset[str] = frozenset()
    # The record, when it is an eponym whose name also names his people and their land.
    eponym: str | None = None
    group: bool = False


def clear(db: sqlite3.Connection):
    db.execute("delete from mention where kind_id = 'names'")


def run(db: sqlite3.Connection):
    books = codes(db, USFM)
    old_testament = set(books[c] for c in USFM[:OLD_TESTAMENT])
    renumbered = mapping(db)
    records = usable(tipnr.records())
    people = peoples(records)
    entities = bible_entities(records)
    candidates = defaultdict(set)
    for entity_id, record in build_ids(records):
        if record.unique == JESUS:
            entity_id = JESUS_CHRIST[0]
        group = people.get(record.unique)
        gentilics = frozenset(entities[group.id].names - entities[entity_id].names) if group else frozenset()
        eponym = record.unique if record.unique in EPONYMS else None
        for form in record.forms:
            if not is_name(form.kjv):
                continue
            name = Name(entity_id, group.id if group else None, gentilics, eponym, form.kind == "Group")
            for code, chapter, verse in form.refs:
                if code in books:
                    candidates[(books[code], chapter, verse, base(form.strongs))].add(name)

    kjv = {}
    texts = {}
    for id, b, c, v, p, text in db.execute("select id, book_id, chapter, verse, position, text from word where edition_id = 'kjv'"):
        kjv[(b, c, v, p)] = id
        texts[id] = text
    found = set()
    ambiguous = unsettled = 0
    for book in bible():
        book_id = slug(book.name)
        for (chapter, verse), words in book.verses.items():
            refs = [(book_id, chapter, verse), *renumbered.get((book_id, chapter, verse), [])]
            units = translation_units([(kjv[(book_id, chapter, verse, n)], w.strongs) for n, w in enumerate(words, 1)])
            for number, spans in units.items():
                if number in JEHOVAH_STRONGS and book_id in old_testament:
                    names = {Name(JESUS_CHRIST[0])}
                else:
                    names = set().union(*(candidates.get((*ref, number), set()) for ref in refs))
                owners = {(n.entity, n.eponym) for n in names}
                if len(owners) > 1:
                    ambiguous += len(spans)
                if len(owners) != 1:
                    continue
                name = merged(names)
                for span in spans:
                    words_named = name_words(span, texts)
                    if not words_named:
                        continue
                    entity = meaning(name, words_named[0], texts, book_id, chapter)
                    if entity:
                        found.add((entity, *words_named))
                    else:
                        unsettled += 1

    for id, in db.execute("select id from word where lower(text) = 'jehovah' and edition_id not in ('wlc', 'sblgnt')"):
        found.add((JESUS_CHRIST[0], id, id))
    db.executemany("insert into mention (entity_id, kind_id, first_word_id, last_word_id) values (?, 'names', ?, ?)", sorted(found))
    print(
        f"mentions: {len(found)} name mentions, {ambiguous} words left where several entities carry the name, "
        f"{unsettled} where a name may mean a man, his people, or their land"
    )


def merged(names: set[Name]) -> Name:
    """The forms of one record that share a Strong's number in a verse, as one name that is a people's only if every form is."""
    first = next(iter(names))
    return Name(first.entity, first.people, first.gentilics, first.eponym, all(n.group for n in names))


def meaning(name: Name, first: int, texts: dict[int, str], book: str, chapter: int) -> str | None:
    """The entity a name means where it stands, or None where only the AI can tell."""
    word = re.sub(r"’s?$", "", texts[first])
    if name.people and (name.group or word in name.gentilics or GENTILIC.search(word)):
        return name.people
    eponym = EPONYMS.get(name.eponym)
    if not eponym:
        return name.entity
    if word in eponym.people_names:
        return eponym.people.id
    # Genesis tells of the men themselves, so "the house of Joseph" is his household. Only Jacob's blessing in chapter 49
    # speaks of the tribes, and "Israel" names the whole family throughout.
    if book == "genesis" and chapter != 49 and word != "Israel":
        return name.entity
    before = (texts.get(first - 2, "").lower(), texts.get(first - 1, "").lower())
    if before in PEOPLE_CUES:
        return eponym.people.id
    if before in LAND_CUES and eponym.lands:
        return eponym.lands[0].id
    if before in KINGDOM_CUES and eponym.kingdom:
        return eponym.kingdom
    return None


def name_words(span: list[int], texts: dict[int, str]) -> tuple[int, int] | None:
    """Trim a tagged phrase such as "the prophet Elijah" to its capitalized words."""
    capitalized = [id for id in span if re.match(r"[A-Z]", texts[id])]
    return (capitalized[0], capitalized[-1]) if capitalized else None

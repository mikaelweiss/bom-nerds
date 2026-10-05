import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass

from . import tipnr
from .entities import EPONYMS, GENTILIC, JESUS, JESUS_CHRIST, bible_entities, build_keys, is_name, peoples, stored_ids, usable
from .refs import OLD_TESTAMENT, USFM, codes
from .rows import row_id
from .strongs import base, translation_units
from .text import KJV, WORDS, bible, english_editions, marks
from .versification import mapping

REFERS_TO = "Refers to"

JEHOVAH_STRONGS = {"H3068", "H3050", "H3069"}

PEOPLE_CUES = {("tribe", "of"), ("tribes", "of"), ("children", "of"), ("house", "of")}
LAND_CUES = {("land", "of"), ("cities", "of"), ("coast", "of"), ("coasts", "of"), ("border", "of"), ("borders", "of")}
KINGDOM_CUES = {("king", "of"), ("kings", "of"), ("kingdom", "of")}


@dataclass(frozen=True)
class Name:

    entity: str
    people: str | None = None
    gentilics: frozenset[str] = frozenset()
    eponym: str | None = None
    group: bool = False


def clear(db: sqlite3.Connection):
    db.execute("delete from mention where mention_kind_id = ?", (row_id(db, "mention_kind", REFERS_TO),))


def run(db: sqlite3.Connection):
    books = codes(db, USFM)
    old_testament = set(books[c] for c in USFM[:OLD_TESTAMENT])
    renumbered = mapping(db)
    records = usable(tipnr.records())
    people = peoples(records)
    entities = bible_entities(records)
    candidates = defaultdict(set)
    for key, record in build_keys(records):
        if record.unique == JESUS:
            key = JESUS_CHRIST[0]
        group = people.get(record.unique)
        gentilics = frozenset(entities[group.key].names - entities[key].names) if group else frozenset()
        eponym = record.unique if record.unique in EPONYMS else None
        for form in record.forms:
            if not is_name(form.kjv):
                continue
            name = Name(key, group.key if group else None, gentilics, eponym, form.kind == "Group")
            for code, chapter, verse in form.refs:
                if code in books:
                    candidates[(books[code], chapter, verse, base(form.strongs))].add(name)

    kjv = {}
    texts = {}
    ids = {}
    for id, sequence, b, c, v, p, text in db.execute(
        f"select w.id, w.sequence, c.book_id, c.number, v.number, w.position, w.text from {WORDS} where c.edition_id = ?", (row_id(db, "edition", KJV),)
    ):
        kjv[(b, c, v, p)] = sequence
        texts[sequence] = text
        ids[sequence] = id
    book_ids = dict(db.execute("select name, id from book where work_id = ?", (row_id(db, "work", "Bible"),)))
    found = set()
    ambiguous = unsettled = 0
    for book in bible():
        book_id = book_ids[book.name]
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
                    entity = meaning(name, words_named[0], texts, book.name, chapter)
                    if entity:
                        found.add((entity, ids[words_named[0]], ids[words_named[1]]))
                    else:
                        unsettled += 1

    english = english_editions(db)
    for id, in db.execute(f"select w.id from {WORDS} where lower(w.text) = 'jehovah' and c.edition_id in ({marks(english)})", english):
        found.add((JESUS_CHRIST[0], id, id))
    entity_ids = stored_ids(db, entities)
    kind = row_id(db, "mention_kind", REFERS_TO)
    db.executemany(
        "insert into mention (entity_id, mention_kind_id, first_word_id, last_word_id) values (?, ?, ?, ?)",
        sorted((entity_ids[entity], kind, first, last) for entity, first, last in found),
    )
    print(
        f"mentions: {len(found)} name mentions, {ambiguous} words left where several entities carry the name, "
        f"{unsettled} where a name may mean a man, his people, or their land"
    )


def merged(names: set[Name]) -> Name:
    first = next(iter(names))
    return Name(first.entity, first.people, first.gentilics, first.eponym, all(n.group for n in names))


def meaning(name: Name, first: int, texts: dict[int, str], book: str, chapter: int) -> str | None:
    word = re.sub(r"’s?$", "", texts[first])
    if name.people and (name.group or word in name.gentilics or GENTILIC.search(word)):
        return name.people
    eponym = EPONYMS.get(name.eponym)
    if not eponym:
        return name.entity
    if word in eponym.people_names:
        return eponym.people.key
    if book == "Genesis" and chapter != 49 and word != "Israel":
        return name.entity
    before = (texts.get(first - 2, "").lower(), texts.get(first - 1, "").lower())
    if before in PEOPLE_CUES:
        return eponym.people.key
    if before in LAND_CUES and eponym.lands:
        return eponym.lands[0].key
    if before in KINGDOM_CUES and eponym.kingdom:
        return eponym.kingdom
    return None


def name_words(span: list[int], texts: dict[int, str]) -> tuple[int, int] | None:
    capitalized = [id for id in span if re.match(r"[A-Z]", texts[id])]
    return (capitalized[0], capitalized[-1]) if capitalized else None

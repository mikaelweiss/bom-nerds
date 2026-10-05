"""Bible parents, children, siblings, and spouses from STEPBible's TIPNR."""

import sqlite3
from collections import defaultdict

from . import tipnr
from .entities import JESUS, JESUS_CHRIST, bible_entities, build_keys, stored_ids, usable
from .rows import row_id
from .text import KJV, WORDS, marks

PARENTS, SIBLINGS, PARTNERS, OFFSPRING = 2, 3, 4, 5
CHILD_OF, SIBLING_OF, SPOUSE_OF = "child of", "sibling of", "spouse of"
FAMILY = (CHILD_OF, SIBLING_OF, SPOUSE_OF)

# A verse is evidence when it names both people with one of these words: "Seth begat Enos", "Aaron the brother of Moses".
# Siblings are usually named together as one parent's children, with the word before both names: "the sons of Leah; Reuben and Simeon".
CHILDREN = {"son", "sons", "daughter", "daughters", "child", "children", "firstborn"}
KINSHIP = {
    CHILD_OF: {"begat", "begot", "beget", "bare", "born", "father", "mother"} | CHILDREN,
    SIBLING_OF: {"brother", "brethren", "sister", "sisters"} | CHILDREN,
    SPOUSE_OF: {"wife", "wives", "husband", "married", "took"},
}
# Two names farther apart than this are usually items in a list, not a stated relationship.
NEARBY = 30


def kinds(db: sqlite3.Connection) -> dict[str, int]:
    return {name: row_id(db, "relationship_kind", name) for name in FAMILY}


def clear(db: sqlite3.Connection):
    db.execute(f"delete from relationship where relationship_kind_id in ({marks(FAMILY)})", list(kinds(db).values()))


def run(db: sqlite3.Connection):
    records = usable(tipnr.records())
    entity_ids = stored_ids(db, bible_entities(records))
    kind_ids = kinds(db)
    db.executemany(
        "insert or ignore into relationship (subject_id, relationship_kind_id, object_id) values (?, ?, ?)",
        sorted((entity_ids[subject], kind_ids[kind], entity_ids[object]) for subject, kind, object in facts(records)),
    )
    cited = cite(db, kind_ids)
    total = db.execute(f"select count(*) from relationship where relationship_kind_id in ({marks(FAMILY)})", list(kind_ids.values())).fetchone()[0]
    print(f"family: {total} relationships, {cited} with a verse as evidence")


def facts(records: list[tipnr.Record]) -> set[tuple[str, str, str]]:
    """(subject, kind, object) for every family link between two people TIPNR records, each person named by entity key."""
    # TIPNR's table of nations calls peoples like the Jebusites sons of Canaan. Family links here join two people only.
    keys = {}
    people = []
    for key, record in build_keys(records):
        if record.section == "PERSON(s)" and record.type in ("Male", "Female"):
            keys[record.unique] = JESUS_CHRIST[0] if record.unique == JESUS else key
            people.append(record)
    found = set()
    for record in people:
        person = keys[record.unique]
        for kind, column, reverse in ((CHILD_OF, PARENTS, False), (SIBLING_OF, SIBLINGS, False), (SPOUSE_OF, PARTNERS, False), (CHILD_OF, OFFSPRING, True)):
            for linked in record.links(column):
                other = keys.get(linked)
                if other and other != person:
                    subject, object = (other, person) if reverse else (person, other)
                    if kind != CHILD_OF:
                        subject, object = sorted((subject, object))
                    found.add((subject, kind, object))
    return found


def cite(db: sqlite3.Connection, kind_ids: dict[str, int]) -> int:
    """Cite the first verse that names both people beside a kinship word. Words are counted by sequence."""
    mentions = defaultdict(lambda: defaultdict(list))
    reading = {}
    for entity, first, last, verse in db.execute(
        f"select m.entity_id, w.sequence, l.sequence, w.verse_id from mention m join word l on l.id = m.last_word_id, {WORDS} "
        "where w.id = m.first_word_id and c.edition_id = ?",
        (row_id(db, "edition", KJV),),
    ):
        mentions[entity][verse].append((first, last))
        reading[verse] = first
    names = {id: name for name, id in kind_ids.items()}
    texts = {}
    ids = {}
    evidence = []
    for id, subject, kind, object in db.execute(
        f"select id, subject_id, relationship_kind_id, object_id from relationship where relationship_kind_id in ({marks(FAMILY)}) order by id",
        list(kind_ids.values()),
    ):
        kind = names[kind]
        for verse in sorted(mentions[subject].keys() & mentions[object].keys(), key=reading.get):
            spans = mentions[subject][verse] + mentions[object][verse]
            first, last = min(f for f, _ in spans), max(l for _, l in spans)
            if last - first > NEARBY:
                continue
            if verse not in texts:
                rows = list(db.execute("select sequence, id, lower(text) from word where verse_id = ?", (verse,)))
                texts[verse] = {sequence: text for sequence, _, text in rows}
                ids.update((sequence, id) for sequence, id, _ in rows)
            cues = [w for w, t in texts[verse].items() if t in KINSHIP[kind] and first - NEARBY <= w <= last + NEARBY and not (kind == SIBLING_OF and t in CHILDREN and w > first)]
            if cues:
                nearest = min(cues, key=lambda w: 0 if first <= w <= last else min(abs(w - first), abs(w - last)))
                evidence.append((id, ids[min(first, nearest)], ids[max(last, nearest)]))
                break
    db.executemany("insert into relationship_evidence (relationship_id, first_word_id, last_word_id) values (?, ?, ?)", evidence)
    return len(evidence)

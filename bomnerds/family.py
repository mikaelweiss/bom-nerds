"""Bible parents, children, siblings, and spouses from STEPBible's TIPNR."""

import sqlite3
from collections import defaultdict

from . import tipnr
from .entities import JESUS, JESUS_CHRIST, build_ids, usable

PARENTS, SIBLINGS, PARTNERS, OFFSPRING = 2, 3, 4, 5
FAMILY = ("child_of", "sibling_of", "spouse_of")

# A verse is evidence when it names both people with one of these words: "Seth begat Enos", "Aaron the brother of Moses".
# Siblings are usually named together as one parent's children, with the word before both names: "the sons of Leah; Reuben and Simeon".
CHILDREN = {"son", "sons", "daughter", "daughters", "child", "children", "firstborn"}
KINSHIP = {
    "child_of": {"begat", "begot", "beget", "bare", "born", "father", "mother"} | CHILDREN,
    "sibling_of": {"brother", "brethren", "sister", "sisters"} | CHILDREN,
    "spouse_of": {"wife", "wives", "husband", "married", "took"},
}
# Two names farther apart than this are usually items in a list, not a stated relationship.
NEARBY = 30


def clear(db: sqlite3.Connection):
    db.execute(f"delete from relationship where kind_id in ({','.join('?' * len(FAMILY))})", FAMILY)


def run(db: sqlite3.Connection):
    # TIPNR's table of nations calls peoples like the Jebusites sons of Canaan. Family links here join two people only.
    ids = {}
    people = []
    for entity_id, record in build_ids(usable(tipnr.records())):
        if record.section == "PERSON(s)" and record.type in ("Male", "Female"):
            ids[record.unique] = JESUS_CHRIST[0] if record.unique == JESUS else entity_id
            people.append(record)
    facts = set()
    for record in people:
        person = ids[record.unique]
        for kind, column, reverse in (("child_of", PARENTS, False), ("sibling_of", SIBLINGS, False), ("spouse_of", PARTNERS, False), ("child_of", OFFSPRING, True)):
            for linked in record.links(column):
                other = ids.get(linked)
                if other and other != person:
                    subject, object = (other, person) if reverse else (person, other)
                    if kind != "child_of":
                        subject, object = sorted((subject, object))
                    facts.add((subject, kind, object))
    db.executemany("insert or ignore into relationship (subject_id, kind_id, object_id) values (?, ?, ?)", sorted(facts))
    cited = cite(db)
    total = db.execute(f"select count(*) from relationship where kind_id in ({','.join('?' * len(FAMILY))})", FAMILY).fetchone()[0]
    print(f"family: {total} relationships, {cited} with a verse as evidence")


def cite(db: sqlite3.Connection) -> int:
    """Cite the first verse that names both people beside a kinship word."""
    mentions = defaultdict(lambda: defaultdict(list))
    for entity, first, last, book, chapter, verse in db.execute(
        "select m.entity_id, m.first_word_id, m.last_word_id, w.book_id, w.chapter, w.verse from mention m join word w on w.id = m.first_word_id where w.edition_id = 'kjv'"
    ):
        mentions[entity][(book, chapter, verse)].append((first, last))
    texts = {}
    evidence = []
    for id, subject, kind, object in db.execute(
        f"select id, subject_id, kind_id, object_id from relationship where kind_id in ({','.join('?' * len(FAMILY))}) order by id", FAMILY
    ):
        for verse in sorted(mentions[subject].keys() & mentions[object].keys()):
            spans = mentions[subject][verse] + mentions[object][verse]
            first, last = min(f for f, _ in spans), max(l for _, l in spans)
            if last - first > NEARBY:
                continue
            if verse not in texts:
                texts[verse] = dict(db.execute("select id, lower(text) from word where edition_id = 'kjv' and book_id = ? and chapter = ? and verse = ?", verse))
            cues = [w for w, t in texts[verse].items() if t in KINSHIP[kind] and first - NEARBY <= w <= last + NEARBY and not (kind == "sibling_of" and t in CHILDREN and w > first)]
            if cues:
                nearest = min(cues, key=lambda w: 0 if first <= w <= last else min(abs(w - first), abs(w - last)))
                evidence.append((id, min(first, nearest), max(last, nearest)))
                break
    db.executemany("insert into relationship_evidence (relationship_id, first_word_id, last_word_id) values (?, ?, ?)", evidence)
    return len(evidence)

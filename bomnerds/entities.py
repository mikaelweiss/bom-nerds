"""Bible people, groups, places, and other named things from STEPBible's TIPNR, with place kinds from OpenBible."""

import json
import re
import sqlite3
from collections import defaultdict

from . import tipnr
from .refs import USFM, codes
from .sources import fetch
from .text import slug

# TIPNR files Jesus under his mortal name. Every other Bible entity takes its id from TIPNR's name.
JESUS = "Jesus@Isa.7.14-Rev"
JESUS_CHRIST = ("jesus-christ", "Jesus Christ", "The Son of God, who is Jehovah of the Old Testament.")

# TIPNR's LORD record merges every name of God, but Latter-day Saint doctrine gives them to different beings.
SKIPPED = {"LORD@Gen.1.1-Rev"}

OTHER_TYPES = {"Supernatural": "person", "Group": "group", "Title": "office", "Star": "object", "Other": "object"}

PLACE_TYPES = {
    "settlement": "city", "district in settlement": "city", "region": "land", "valley": "land", "field": "land", "plain": "land",
    "natural area": "land", "island": "land", "mountain": "mountain", "hill": "mountain", "mountain range": "mountain",
    "mountain ridge": "mountain", "cliff": "mountain", "river": "water", "body of water": "water", "spring": "water",
    "pool": "water", "well": "water", "wadi": "water", "ford": "water",
}


def clear(db: sqlite3.Connection):
    owned = "select id from entity where id in (select value from json_each(?))"
    ids = json.dumps([entity_id for entity_id, _ in build_ids(usable(tipnr.records()))] + [JESUS_CHRIST[0]])
    db.execute(f"delete from entity_book where entity_id in ({owned})", (ids,))
    db.execute(f"delete from entity_name where entity_id in ({owned})", (ids,))
    db.execute(f"delete from entity where id in ({owned})", (ids,))


def run(db: sqlite3.Connection):
    books = codes(db, USFM)
    records = usable(tipnr.records())
    places = place_types()
    for entity_id, record in build_ids(records):
        if record.unique == JESUS:
            entity_id, name, description = JESUS_CHRIST
        else:
            name, description = record.name, describe(record)
        db.execute("insert into entity (id, type_id, name, description) values (?, ?, ?, ?)", (entity_id, entity_type(record, places), name, description))
        names = {name, *record.names, *(form.kjv for form in record.forms if is_name(form.kjv))}
        is_title = int(record.type == "Title")
        db.executemany("insert into entity_name (entity_id, name, is_title) values (?, ?, ?)", [(entity_id, n, is_title) for n in sorted(names)])
        appears = {books[code] for form in record.forms for code, _, _ in form.refs if code in books}
        db.executemany("insert into entity_book (entity_id, book_id) values (?, ?)", [(entity_id, b) for b in sorted(appears)])
    print(f"entities: {len(records)} Bible entities")


def usable(records: list[tipnr.Record]) -> list[tipnr.Record]:
    return [r for r in records if r.unique not in SKIPPED and (r.section != "OTHER" or r.type.strip() in OTHER_TYPES)]


def is_name(text: str | None) -> bool:
    return bool(text) and text[0].isupper()


def entity_type(record: tipnr.Record, places: dict[str, list[str]]) -> str:
    if record.section.startswith("PLACE"):
        if "wilderness" in record.name.lower():
            return "wilderness"
        kinds = [PLACE_TYPES[t] for t in places.get(without_last_book(record.unique), []) if t in PLACE_TYPES]
        return kinds[0] if kinds else "place"
    if record.section == "OTHER":
        return OTHER_TYPES[record.type.strip()]
    return "group" if record.type == "Group" else "person"


def describe(record: tipnr.Record) -> str:
    summary = re.sub(r"<[^>]+>", "", record.fields[7] if len(record.fields) > 7 else "").lstrip("#").split(" first mentioned")[0].strip()
    return record.brief or record.briefest or summary or record.name


def without_last_book(unique: str) -> str:
    """OpenBible links TIPNR places as "Lehi@Jdg.15.9", without the "-2Sa" naming the last book."""
    return re.sub(r"-\w*$", "", unique)


def place_types() -> dict[str, list[str]]:
    types = {}
    for line in fetch("openbible-ancient.jsonl").read_text(encoding="utf-8").splitlines():
        place = json.loads(line)
        kinds = place.get("types") or []
        for link in (place.get("linked_data") or {}).values():
            if "@" in str(link.get("id", "")):
                types[link["id"]] = kinds
    return types


def build_ids(records: list[tipnr.Record]) -> list[tuple[str, tipnr.Record]]:
    """An id is the entity's name, plus what sets it apart when other entities share that name."""
    by_unique = {r.unique: r for r in records}
    groups = defaultdict(list)
    for record in records:
        groups[slug(record.name)].append(record)
    ids = []
    for base, group in groups.items():
        if len(group) == 1:
            ids.append((base, group[0]))
            continue
        qualified = [(f"{base}-{qualifier(r, by_unique)}" if qualifier(r, by_unique) else base, r) for r in group]
        counts = defaultdict(int)
        for entity_id, _ in qualified:
            counts[entity_id] += 1
        for entity_id, record in qualified:
            if counts[entity_id] > 1:
                entity_id = f"{entity_id}-{slug(record.unique.split('@')[1].split('-')[0])}"
            ids.append((entity_id, record))
    return ids


def qualifier(record: tipnr.Record, by_unique: dict[str, tipnr.Record]) -> str:
    def name_of(unique):
        linked = by_unique.get(unique)
        return slug(linked.name if linked else unique.split("@")[0])

    if record.section.startswith("PLACE"):
        near = re.search(r"near (\S+?)(?:_\d+)?(?:\s|$|\()", record.fields[1]) if len(record.fields) > 1 else None
        return f"near-{slug(near.group(1))}" if near else ""
    child = "daughter" if record.type == "Female" else "son"
    if record.type in ("Male", "Female"):
        parents = record.links(2)
        if parents:
            return f"{child}-of-{name_of(parents[0])}"
        partners = record.links(4)
        if partners:
            return f"{'wife' if record.type == 'Female' else 'husband'}-of-{name_of(partners[0])}"
        offspring = record.links(5)
        if offspring:
            return f"{'mother' if record.type == 'Female' else 'father'}-of-{name_of(offspring[0])}"
    return slug(record.briefest) if record.briefest else ""

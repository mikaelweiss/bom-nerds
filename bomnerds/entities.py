"""Bible people, groups, places, and other named things from STEPBible's TIPNR, with place kinds from OpenBible."""

import json
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, replace

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

# Words such as "Levite", "Egyptian", and "Jew" name a people, not the person or place TIPNR files them under.
# TIPNR marks most of them as group forms. This catches the rest, without catching names like "Midian".
GENTILIC = re.compile(r"(ites?|itess|eans?)$|^Jew")


@dataclass(frozen=True)
class Entity:
    id: str
    type: str
    name: str
    description: str
    names: tuple[str, ...] = ()


@dataclass(frozen=True)
class Eponym:
    """A man whose name also names the people descended from him, and the land they held."""

    person: str
    people: Entity
    lands: tuple[Entity, ...] = ()
    # The people that words like "Jew" name, where it differs from the people that bear his name.
    gentilic: Entity | None = None
    # The land that a "king of" this name rules, where the name alone settles which.
    kingdom: str | None = None
    # Names that always mean the people: "Jeshurun" is only ever Israel the nation.
    people_names: tuple[str, ...] = ()


def tribe(name: str, parents: str, land: bool = True) -> Eponym:
    people = Entity(f"tribe-of-{slug(name)}", "group", f"Tribe of {name}", f"The tribe of Israel descended from {name}.", (name, f"children of {name}"))
    lands = (Entity(f"land-of-{slug(name)}", "land", f"Land of {name}", f"The land given to the tribe of {name}.", (name,)),) if land else ()
    return Eponym(f"Son of {parents}, father of the tribe of {name}.", people, lands)


# TIPNR files each of these men, his tribe or nation, and its land as one record with one verse list, so no source says which a verse means.
EPONYMS = {
    "Israel@Gen.25.26-Rev": Eponym(
        "Patriarch, son of Isaac, also named Jacob. Father of the twelve tribes.",
        Entity("house-of-israel", "group", "House of Israel", "The people descended from Israel, the covenant people of the Lord.",
               ("Israel", "Israelites", "children of Israel", "Jacob", "house of Jacob", "Jeshurun")),
        (Entity("land-of-israel", "land", "Land of Israel", "The land of the twelve tribes of Israel.", ("Israel",)),
         Entity("kingdom-of-israel", "land", "Kingdom of Israel", "The northern kingdom of the ten tribes, after the kingdom divided.", ("Israel", "Ephraim"))),
        people_names=("Jeshurun",),
    ),
    "Reuben@Gen.29.32-Rev": tribe("Reuben", "Jacob and Leah"),
    "Simeon@Gen.29.33-Rev": tribe("Simeon", "Jacob and Leah"),
    "Levi@Gen.29.34-Rev": tribe("Levi", "Jacob and Leah", land=False),
    "Judah@Gen.29.35-Rev": replace(
        tribe("Judah", "Jacob and Leah"),
        lands=(Entity("land-of-judah", "land", "Land of Judah", "The land of the tribe of Judah, which became the southern kingdom of Judah.", ("Judah", "kingdom of Judah")),),
        gentilic=Entity("jews", "group", "Jews", "The people of the kingdom of Judah and their descendants.", ("Jew", "Jews")),
        kingdom="land-of-judah",
    ),
    "Dan@Gen.30.6-1Ch": tribe("Dan", "Jacob and Bilhah"),
    "Naphtali@Gen.30.8-Rev": tribe("Naphtali", "Jacob and Bilhah"),
    "Gad@Gen.30.11-Rev": tribe("Gad", "Jacob and Zilpah"),
    "Asher@Gen.30.13-Rev": tribe("Asher", "Jacob and Zilpah"),
    "Issachar@Gen.30.18-Rev": tribe("Issachar", "Jacob and Leah"),
    "Zebulun@Gen.30.20-Rev": tribe("Zebulun", "Jacob and Leah"),
    "Joseph@Gen.30.24-Rev": Eponym(
        "Son of Jacob and Rachel, ruler in Egypt, father of the tribes of Ephraim and Manasseh.",
        Entity("tribe-of-joseph", "group", "Tribe of Joseph", "The descendants of Joseph: the tribes of Ephraim and Manasseh.",
               ("Joseph", "house of Joseph", "children of Joseph")),
    ),
    "Benjamin@Gen.35.18-Rev": tribe("Benjamin", "Jacob and Rachel"),
    "Ephraim@Gen.41.52-Zec": tribe("Ephraim", "Joseph"),
    "Manasseh@Gen.41.51-Rev": tribe("Manasseh", "Joseph"),
}

PEOPLE_DESCRIPTIONS = {JESUS: "Followers of Jesus Christ."}


@dataclass
class BibleEntity:
    entity: Entity
    # The record its type and title come from.
    record: tipnr.Record
    names: set[str]
    # The name forms whose verses give the books it appears in.
    forms: list[tipnr.NameForm]


def clear(db: sqlite3.Connection):
    owned = "select id from entity where id in (select value from json_each(?))"
    ids = json.dumps(list(bible_entities(usable(tipnr.records()))))
    db.execute(f"delete from entity_book where entity_id in ({owned})", (ids,))
    db.execute(f"delete from entity_name where entity_id in ({owned})", (ids,))
    db.execute(f"delete from entity where id in ({owned})", (ids,))


def run(db: sqlite3.Connection):
    books = codes(db, USFM)
    places = place_types()
    found = bible_entities(usable(tipnr.records()))
    for found_entity in found.values():
        entity, record = found_entity.entity, found_entity.record
        db.execute("insert into entity (id, type_id, name, description) values (?, ?, ?, ?)", (entity.id, entity.type or kind(record, places), entity.name, entity.description))
        is_title = int(record.type == "Title")
        db.executemany("insert into entity_name (entity_id, name, is_title) values (?, ?, ?)", [(entity.id, n, is_title) for n in sorted(found_entity.names)])
        appears = {books[code] for form in found_entity.forms for code, _, _ in form.refs if code in books}
        db.executemany("insert into entity_book (entity_id, book_id) values (?, ?)", [(entity.id, b) for b in sorted(appears)])
    print(f"entities: {len(found)} Bible entities")


def bible_entities(records: list[tipnr.Record]) -> dict[str, BibleEntity]:
    """Every Bible entity by id: each record's own entity, the people its gentilic words name, and an eponym's people and lands."""
    people = peoples(records)
    found = {}

    def add(entity: Entity, record: tipnr.Record, names: list[str], forms: list[tipnr.NameForm]):
        if entity.id not in found:
            found[entity.id] = BibleEntity(entity, record, {entity.name, *entity.names}, [])
        found[entity.id].names.update(n for n in names if is_name(n))
        found[entity.id].forms.extend(forms)

    shared = []
    for entity_id, record in build_ids(records):
        eponym = EPONYMS.get(record.unique)
        if record.unique == JESUS:
            entity = Entity(JESUS_CHRIST[0], "", *JESUS_CHRIST[1:])
        else:
            entity = Entity(entity_id, "", record.name, eponym.person if eponym else describe(record))
        names = [n for name in record.names for n in split_names(name)] + [n for f in record.forms if f.kind != "Group" for n in split_names(f.kjv)]
        forms = record.forms
        if record.unique in people:
            groups = [f for f in record.forms if f.kind == "Group"]
            # A group form's own name can be the record's other name, as in "Christ|Jesus", rather than the people's.
            own_names = {f.name for f in groups if f.name} - {record.name, *names}
            renderings = {n for f in groups for n in split_names(f.kjv)} - {record.name}
            gentilic = {n for n in names if GENTILIC.search(n) or n in renderings} | renderings | own_names
            shared.append((people[record.unique], record, gentilic, groups))
            names = [n for n in names if n not in gentilic]
            forms = [f for f in record.forms if f not in groups]
        if eponym:
            names = [n for n in names if n not in eponym.people_names]
        add(entity, record, names, forms)
        if eponym:
            shared.extend((shares_the_name, record, [], forms) for shares_the_name in (eponym.people, *eponym.lands))
    for entity, record, names, forms in shared:
        add(entity, record, names, forms)
    return found


def peoples(records: list[tipnr.Record]) -> dict[str, Entity]:
    """The people that each record's gentilic words name, keyed by the record.

    TIPNR already lists some peoples, such as the Jebusites, as records of their own, and their gentilic words name that record.
    """
    ids = {record.unique: entity_id for entity_id, record in build_ids(records)}
    taken = set(ids.values())
    found = {}
    for record in records:
        eponym = EPONYMS.get(record.unique)
        if eponym:
            found[record.unique] = eponym.gentilic or eponym.people
        elif record.type != "Group" and (name := people_name(record)):
            description = PEOPLE_DESCRIPTIONS.get(record.unique) or (f"People of {record.name}." if record.section.startswith("PLACE") else f"Descendants of {record.name}.")
            found[record.unique] = Entity(slug(name), "" if slug(name) in taken else "group", name, description)
    counts = defaultdict(int)
    for entity in found.values():
        counts[entity.id] += 1
    return {
        unique: replace(entity, id=f"{entity.id}-of-{ids[unique]}") if entity.type and unique not in EPONYMS and counts[entity.id] > 1 else entity
        for unique, entity in found.items()
    }


def people_name(record: tipnr.Record) -> str | None:
    """The plural of the word a record's gentilic forms use: "Levites" from "Levite", "Jesuites" from "Jesui"."""
    words = [w for f in record.forms if f.kind == "Group" for w in (f.name, *split_names(f.kjv))]
    words = [w for w in words if is_name(w) and " " not in w and "-" not in w and w != record.name and not w.endswith("ess")]
    words.sort(key=lambda w: not re.search(r"(ites?|ians?|eans?|im)$", w))
    if not words:
        return None
    word = words[0]
    if word.endswith(("s", "im")):
        return word
    return word + "tes" if word.endswith("i") else word + "s"


def split_names(text: str | None) -> list[str]:
    """TIPNR lists one form's spellings together, "Ammonite,Ammon,Ammonitess", and marks word breaks with a slash, "City of/ the Lord"."""
    names = (" ".join(n.replace("/", " ").split()) for n in (text or "").split(","))
    return [n for n in names if n]


def usable(records: list[tipnr.Record]) -> list[tipnr.Record]:
    return [r for r in records if r.unique not in SKIPPED and (r.section != "OTHER" or r.type.strip() in OTHER_TYPES)]


def is_name(text: str | None) -> bool:
    return bool(text) and text[0].isupper()


def kind(record: tipnr.Record, places: dict[str, list[str]]) -> str:
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

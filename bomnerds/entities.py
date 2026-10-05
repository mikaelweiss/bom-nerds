import json
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, replace

from . import tipnr
from .rows import row_id
from .sources import fetch
from .text import marks

JESUS = "Jesus@Isa.7.14-Rev"
JESUS_CHRIST = ("jesus-christ", "Jesus Christ", "The Son of God, who is Jehovah of the Old Testament.")

SKIPPED = {"LORD@Gen.1.1-Rev"}

OTHER_TYPES = {"Supernatural": "Person", "Group": "Group", "Title": "Office", "Star": "Object", "Other": "Object"}

PLACE_TYPES = {
    "settlement": "City", "district in settlement": "City", "region": "Land", "valley": "Land", "field": "Land", "plain": "Land",
    "natural area": "Land", "island": "Land", "mountain": "Mountain", "hill": "Mountain", "mountain range": "Mountain",
    "mountain ridge": "Mountain", "cliff": "Mountain", "river": "Water", "body of water": "Water", "spring": "Water",
    "pool": "Water", "well": "Water", "wadi": "Water", "ford": "Water",
}

GENTILIC = re.compile(r"(ites?|itess|eans?)$|^Jew")


@dataclass(frozen=True)
class Entity:

    key: str
    type: str
    name: str
    description: str
    names: tuple[str, ...] = ()


@dataclass(frozen=True)
class Eponym:

    person: str
    people: Entity
    lands: tuple[Entity, ...] = ()
    gentilic: Entity | None = None
    kingdom: str | None = None
    people_names: tuple[str, ...] = ()


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def tribe(name: str, parents: str, land: bool = True) -> Eponym:
    people = Entity(f"tribe-of-{slug(name)}", "Group", f"Tribe of {name}", f"The tribe of Israel descended from {name}.", (name, f"children of {name}"))
    lands = (Entity(f"land-of-{slug(name)}", "Land", f"Land of {name}", f"The land given to the tribe of {name}.", (name,)),) if land else ()
    return Eponym(f"Son of {parents}, father of the tribe of {name}.", people, lands)


EPONYMS = {
    "Israel@Gen.25.26-Rev": Eponym(
        "Patriarch, son of Isaac, also named Jacob. Father of the twelve tribes.",
        Entity("house-of-israel", "Group", "House of Israel", "The people descended from Israel, the covenant people of the Lord.",
               ("Israel", "Israelites", "children of Israel", "Jacob", "house of Jacob", "Jeshurun")),
        (Entity("land-of-israel", "Land", "Land of Israel", "The land of the twelve tribes of Israel.", ("Israel",)),
         Entity("kingdom-of-israel", "Land", "Kingdom of Israel", "The northern kingdom of the ten tribes, after the kingdom divided.", ("Israel", "Ephraim"))),
        people_names=("Jeshurun",),
    ),
    "Reuben@Gen.29.32-Rev": tribe("Reuben", "Jacob and Leah"),
    "Simeon@Gen.29.33-Rev": tribe("Simeon", "Jacob and Leah"),
    "Levi@Gen.29.34-Rev": tribe("Levi", "Jacob and Leah", land=False),
    "Judah@Gen.29.35-Rev": replace(
        tribe("Judah", "Jacob and Leah"),
        lands=(Entity("land-of-judah", "Land", "Land of Judah", "The land of the tribe of Judah, which became the southern kingdom of Judah.", ("Judah", "kingdom of Judah")),),
        gentilic=Entity("jews", "Group", "Jews", "The people of the kingdom of Judah and their descendants.", ("Jew", "Jews")),
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
        Entity("tribe-of-joseph", "Group", "Tribe of Joseph", "The descendants of Joseph: the tribes of Ephraim and Manasseh.",
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
    record: tipnr.Record
    names: set[str]
    tipnr: str | None


def clear(db: sqlite3.Connection):
    owned = list(stored_ids(db, bible_entities(usable(tipnr.records()))).values())
    db.execute(f"delete from entity_name where entity_id in ({marks(owned)})", owned)
    db.execute(f"delete from entity where id in ({marks(owned)})", owned)


def run(db: sqlite3.Connection):
    places = place_types()
    found = bible_entities(usable(tipnr.records()))
    types = {}
    for found_entity in found.values():
        entity, record = found_entity.entity, found_entity.record
        type_name = entity.type or kind(record, places)
        if type_name not in types:
            types[type_name] = row_id(db, "entity_type", type_name)
        entity_id = db.execute(
            "insert into entity (entity_type_id, name, description, tipnr) values (?, ?, ?, ?)",
            (types[type_name], entity.name, entity.description, found_entity.tipnr),
        ).lastrowid
        is_title = int(record.type == "Title")
        db.executemany(
            "insert into entity_name (entity_id, name, is_title) values (?, ?, ?)", [(entity_id, n, is_title) for n in sorted(found_entity.names - {entity.name})]
        )
    print(f"entities: {len(found)} Bible entities")


def stored_ids(db: sqlite3.Connection, found: dict[str, BibleEntity]) -> dict[str, int]:
    listed = dict(db.execute("select tipnr, id from entity where tipnr is not null"))
    unlisted = defaultdict(list)
    for id, name, description in db.execute("select id, name, description from entity where tipnr is null order by id"):
        unlisted[(name, description)].append(id)
    ids = {}
    for key, found_entity in found.items():
        if found_entity.tipnr:
            id = listed.get(found_entity.tipnr)
        else:
            same = unlisted.get((found_entity.entity.name, found_entity.entity.description))
            id = same.pop(0) if same else None
        if id is not None:
            ids[key] = id
    return ids


def bible_entities(records: list[tipnr.Record]) -> dict[str, BibleEntity]:
    people = peoples(records)
    found = {}

    def add(entity: Entity, record: tipnr.Record, names: list[str], identifier: str | None):
        if entity.key not in found:
            found[entity.key] = BibleEntity(entity, record, {entity.name, *entity.names}, identifier)
        found[entity.key].names.update(n for n in names if is_name(n))

    shared = []
    for key, record in build_keys(records):
        eponym = EPONYMS.get(record.unique)
        if record.unique == JESUS:
            entity = Entity(JESUS_CHRIST[0], "", *JESUS_CHRIST[1:])
        else:
            entity = Entity(key, "", record.name, eponym.person if eponym else describe(record))
        names = [n for name in record.names for n in split_names(name)] + [n for f in record.forms if f.kind != "Group" for n in split_names(f.kjv)]
        if record.unique in people:
            groups = [f for f in record.forms if f.kind == "Group"]
            own_names = {f.name for f in groups if f.name} - {record.name, *names}
            renderings = {n for f in groups for n in split_names(f.kjv)} - {record.name}
            gentilic = {n for n in names if GENTILIC.search(n) or n in renderings} | renderings | own_names
            shared.append((people[record.unique], record, gentilic))
            names = [n for n in names if n not in gentilic]
        if eponym:
            names = [n for n in names if n not in eponym.people_names]
        add(entity, record, names, record.ustrong)
        if eponym:
            shared.extend((shares_the_name, record, []) for shares_the_name in (eponym.people, *eponym.lands))
    for entity, record, names in shared:
        add(entity, record, names, None)
    return found


def peoples(records: list[tipnr.Record]) -> dict[str, Entity]:
    keys = {record.unique: key for key, record in build_keys(records)}
    taken = set(keys.values())
    found = {}
    for record in records:
        eponym = EPONYMS.get(record.unique)
        if eponym:
            found[record.unique] = eponym.gentilic or eponym.people
        elif record.type != "Group" and (name := people_name(record)):
            description = PEOPLE_DESCRIPTIONS.get(record.unique) or (f"People of {record.name}." if record.section.startswith("PLACE") else f"Descendants of {record.name}.")
            found[record.unique] = Entity(slug(name), "" if slug(name) in taken else "Group", name, description)
    counts = defaultdict(int)
    for entity in found.values():
        counts[entity.key] += 1
    return {
        unique: replace(entity, key=f"{entity.key}-of-{keys[unique]}") if entity.type and unique not in EPONYMS and counts[entity.key] > 1 else entity
        for unique, entity in found.items()
    }


def people_name(record: tipnr.Record) -> str | None:
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
    names = (" ".join(n.replace("/", " ").split()) for n in (text or "").split(","))
    return [n for n in names if n]


def usable(records: list[tipnr.Record]) -> list[tipnr.Record]:
    return [r for r in records if r.unique not in SKIPPED and (r.section != "OTHER" or r.type.strip() in OTHER_TYPES)]


def is_name(text: str | None) -> bool:
    return bool(text) and text[0].isupper()


def kind(record: tipnr.Record, places: dict[str, list[str]]) -> str:
    if record.section.startswith("PLACE"):
        if "wilderness" in record.name.lower():
            return "Wilderness"
        kinds = [PLACE_TYPES[t] for t in places.get(without_last_book(record.unique), []) if t in PLACE_TYPES]
        return kinds[0] if kinds else "Place"
    if record.section == "OTHER":
        return OTHER_TYPES[record.type.strip()]
    return "Group" if record.type == "Group" else "Person"


def describe(record: tipnr.Record) -> str:
    summary = re.sub(r"<[^>]+>", "", record.fields[7] if len(record.fields) > 7 else "").lstrip("#").split(" first mentioned")[0].strip()
    return record.brief or record.briefest or summary or record.name


def without_last_book(unique: str) -> str:
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


def build_keys(records: list[tipnr.Record]) -> list[tuple[str, tipnr.Record]]:
    by_unique = {r.unique: r for r in records}
    groups = defaultdict(list)
    for record in records:
        groups[slug(record.name)].append(record)
    keys = []
    for base, group in groups.items():
        if len(group) == 1:
            keys.append((base, group[0]))
            continue
        qualified = [(f"{base}-{qualifier(r, by_unique)}" if qualifier(r, by_unique) else base, r) for r in group]
        counts = defaultdict(int)
        for key, _ in qualified:
            counts[key] += 1
        for key, record in qualified:
            if counts[key] > 1:
                key = f"{key}-{slug(record.unique.split('@')[1].split('-')[0])}"
            keys.append((key, record))
    return keys


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


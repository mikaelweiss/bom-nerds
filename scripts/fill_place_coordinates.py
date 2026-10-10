"""Give places without coordinates the OpenBible.info location when its identification is confident.

    python fill_place_coordinates.py scripture.db SOURCE_DIR

SOURCE_DIR holds OpenBible's ancient.jsonl and STEPBible's TIPNR.txt. A place matches an OpenBible entry
through its TIPNR id, or else by name and a shared verse. TIPNR's own coordinates are not used: many are
placeholders shared by every uncertain site in a region. An OpenBible point shared with another place
stands for an enclosing site, such as Jerusalem for its gates, so it is skipped too.
"""

import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict

CONFIDENT = 500


def openbible(source):
    entries = []
    for line in open(os.path.join(source, "ancient.jsonl"), encoding="utf-8"):
        place = json.loads(line)
        linked = place.get("linked_data", {}).get("s3b25cf", {})
        tipnr_keys = linked.get("ids") or ([linked["id"]] if "id" in linked else [])
        best = None
        for identification in place.get("identifications", []):
            resolution = (identification.get("resolutions") or [{}])[0]
            score = identification.get("score", {}).get("time_total", 0)
            if "lonlat" in resolution and (best is None or score > best[0]):
                longitude, latitude = map(float, resolution["lonlat"].split(","))
                best = (score, latitude, longitude)
        names = {place["friendly_id"].lower(), *(n.lower() for n in place.get("translation_name_counts") or {})}
        verses = {v["sort"] for v in place.get("verses", [])}
        entries.append((tipnr_keys, names, verses, best))
    return entries


def point(location):
    return round(location[1], 4), round(location[2], 4)


def tipnr_keys(source):
    keys = {}
    for line in open(os.path.join(source, "TIPNR.txt"), encoding="utf-8"):
        match = re.match(r"^([^\t@]+@[^\t=]+)=([HG]\d{4}[A-Za-z]?)\t", line)
        if match:
            keys[match.group(2)] = match.group(1)
    return keys


def main(path, source):
    db = sqlite3.connect(path)
    entries = openbible(source)
    by_tipnr = {key: entry for entry in entries for key in entry[0]}
    by_name = defaultdict(list)
    for entry in entries:
        for name in entry[1]:
            by_name[name].append(entry)
    keys = tipnr_keys(source)
    shared = Counter(point(e[3]) for e in entries if e[3])
    shared.update(point((0, lat, lon)) for lat, lon in db.execute("select latitude, longitude from entity where latitude is not null"))

    places = db.execute(
        "select e.id, e.name, e.tipnr from entity e join entity_type t on t.id = e.entity_type_id "
        "left join entity_type p on p.id = t.parent_id where 'Place' in (t.name, p.name) and e.latitude is null"
    ).fetchall()
    names = defaultdict(set)
    for entity, name in db.execute("select entity_id, name from entity_name"):
        names[entity].add(name.lower())
    verses = defaultdict(set)
    for entity, position, chapter, verse in db.execute(
        "select m.entity_id, eb.position, c.number, v.number from mention m join word w on w.id = m.first_word_id "
        "join verse v on v.id = w.verse_id join chapter c on c.id = v.chapter_id "
        "join edition_book eb on eb.edition_id = c.edition_id and eb.book_id = c.book_id where c.edition_id = 1"
    ):
        verses[entity].add(f"{position:02d}{chapter:03d}{verse or 0:03d}")

    filled = {"tipnr": 0, "name and verse": 0}
    for entity, name, tipnr in places:
        match, how = by_tipnr.get(keys.get(tipnr)), "tipnr"
        if match is None:
            candidates = {
                id(e): e for n in {name.lower()} | names[entity] for e in by_name.get(n, ()) if e[2] & verses[entity]
            }
            match, how = (next(iter(candidates.values())), "name and verse") if len(candidates) == 1 else (None, None)
        if match is None or match[3] is None or match[3][0] < CONFIDENT or shared[point(match[3])] > 1:
            continue
        _, latitude, longitude = match[3]
        db.execute("update entity set latitude = ?, longitude = ? where id = ?", (latitude, longitude, entity))
        filled[how] += 1
    db.commit()
    print(filled)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])

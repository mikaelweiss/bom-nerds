"""Add the places the settings pass found missing, from decisions/settings/places.jsonl.

    python scripts/add_restoration_places.py scripture.db [decisions/settings/places.jsonl]

Each line is {"name", "type", "description", "latitude", "longitude", "source"}, where type is a place type such as City or Water.
A place is matched by name among entities of a place type. A missing one is added, and an existing one is updated to match its line,
so a run can be repeated safely. A name shared by two places is rejected.
"""

import json
import os
import sqlite3
import sys
from collections import Counter

DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "decisions", "settings", "places.jsonl")


def main(path, source):
    db = sqlite3.connect(path, isolation_level=None)
    db.execute("pragma busy_timeout = 60000")
    db.execute("pragma foreign_keys = on")
    types = dict(
        db.execute(
            "select t.name, t.id from entity_type t left join entity_type p on p.id = t.parent_id where 'Place' in (t.name, p.name)"
        )
    )
    report = Counter()
    db.execute("begin immediate")
    for number, line in enumerate(open(source, encoding="utf-8"), 1):
        if not line.strip():
            continue
        place = json.loads(line)
        where = f"{os.path.basename(source)}:{number}"
        if place["type"] not in types:
            print(f"{where}: {place['type']} is not a place type")
            report["rejected"] += 1
            continue
        row = (types[place["type"]], place["description"], place["latitude"], place["longitude"])
        found = db.execute(
            "select x.id, x.entity_type_id, x.description, x.latitude, x.longitude from entity x "
            f"where x.name = ? and x.entity_type_id in ({','.join('?' * len(types))})",
            (place["name"], *types.values()),
        ).fetchall()
        if len(found) > 1:
            print(f"{where}: {place['name']} names {len(found)} places")
            report["rejected"] += 1
        elif not found:
            db.execute(
                "insert into entity (entity_type_id, name, description, latitude, longitude) values (?, ?, ?, ?, ?)",
                (row[0], place["name"], *row[1:]),
            )
            report["added"] += 1
        elif found[0][1:] != row:
            db.execute(
                "update entity set entity_type_id = ?, description = ?, latitude = ?, longitude = ? where id = ?",
                (*row, found[0][0]),
            )
            report["updated"] += 1
        else:
            report["unchanged"] += 1
    db.execute("commit")
    for key, n in sorted(report.items()):
        print(f"{key}: {n}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else DEFAULT)

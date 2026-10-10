"""Apply place coordinate decisions to the database.

    python apply_coordinates.py scripture.db [DECISIONS_DIR]

Reads every *.jsonl in DECISIONS_DIR (default decisions/coordinates in the repo). A line is
{"entity_id", "name", "latitude", "longitude", "source"} to set coordinates or {"entity_id", "name", "skip"}
to record a place left without them. A line is rejected when the entity is missing, is not a place, has a
different name, already has other coordinates, or conflicts with another line. Running it twice changes nothing.
"""

import glob
import json
import os
import sqlite3
import sys
from collections import Counter

SAME = 1e-6


def load(directory):
    decisions, problems = {}, []
    for path in sorted(glob.glob(os.path.join(directory, "*.jsonl"))):
        source = os.path.basename(path)
        for number, line in enumerate(open(path, encoding="utf-8"), 1):
            if not line.strip():
                continue
            where = f"{source}:{number}"
            try:
                decision = json.loads(line)
                entity = decision["entity_id"]
                if "skip" not in decision:
                    latitude, longitude = float(decision["latitude"]), float(decision["longitude"])
                    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                        raise ValueError("coordinates out of range")
                    if not decision.get("source"):
                        raise ValueError("missing source")
            except (KeyError, ValueError, TypeError) as error:
                problems.append(f"{where}: bad line ({error})")
                continue
            previous = decisions.get(entity)
            if previous and not same_decision(previous[0], decision):
                problems.append(f"{where}: conflicts with {previous[1]} for entity {entity}")
                continue
            decisions[entity] = (decision, where)
    return decisions, problems


def same_decision(a, b):
    if ("skip" in a) != ("skip" in b):
        return False
    if "skip" in a:
        return True
    return abs(a["latitude"] - b["latitude"]) < SAME and abs(a["longitude"] - b["longitude"]) < SAME


def main(path, directory):
    decisions, problems = load(directory)
    db = sqlite3.connect(path, timeout=60)
    db.execute("pragma busy_timeout = 60000")
    places = {
        row[0]: row[1:]
        for row in db.execute(
            "select e.id, e.name, e.latitude, e.longitude from entity e join entity_type t on t.id = e.entity_type_id "
            "left join entity_type p on p.id = t.parent_id where 'Place' in (t.name, p.name)"
        )
    }
    names = dict(db.execute("select id, name from entity"))

    counts, updates = Counter(), []
    for entity, (decision, where) in sorted(decisions.items()):
        if entity not in names:
            problems.append(f"{where}: no entity {entity}")
        elif entity not in places:
            problems.append(f"{where}: {names[entity]} ({entity}) is not a place")
        elif decision["name"] != places[entity][0]:
            problems.append(f"{where}: name {decision['name']!r} is {places[entity][0]!r} in the database")
        elif "skip" in decision:
            counts["skipped"] += 1
        else:
            _, latitude, longitude = places[entity]
            if latitude is None:
                updates.append((decision["latitude"], decision["longitude"], entity))
                counts["applied"] += 1
            elif abs(latitude - decision["latitude"]) < SAME and abs(longitude - decision["longitude"]) < SAME:
                counts["already applied"] += 1
            else:
                problems.append(f"{where}: {decision['name']} ({entity}) already has {latitude}, {longitude}")

    if updates:
        db.execute("begin immediate")
        db.executemany("update entity set latitude = ?, longitude = ? where id = ? and latitude is null", updates)
        db.commit()
    counts["rejected"] = len(problems)
    print(dict(counts))
    for problem in problems:
        print("rejected:", problem)
    return 1 if problems else 0


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    default = os.path.join(here, "..", "decisions", "coordinates")
    sys.exit(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else default))

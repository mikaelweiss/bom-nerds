"""Checks across finished layers for answers that cannot be true. It flags them and changes nothing."""

import sqlite3
from collections import defaultdict

from .rows import row_id
from .text import marks

# Kinds that cannot loop back on themselves: nobody is their own ancestor, and no place is north of itself.
ORDERED = [("child of", "descendant of"), ("north of",), ("east of",), ("higher than",)]
PEOPLE = ("Person", "Group")
FAMILY = ("child of", "descendant of", "spouse of", "sibling of")


def clear(db: sqlite3.Connection):
    pass


def run(db: sqlite3.Connection):
    names = dict(db.execute("select id, name from entity"))
    flags = []
    for kinds in ORDERED:
        ids = [row_id(db, "relationship_kind", kind) for kind in kinds]
        edges = defaultdict(set)
        for subject, object in db.execute(f"select subject_id, object_id from relationship where relationship_kind_id in ({marks(ids)})", ids):
            edges[subject].add(object)
        flags.extend(f"{' / '.join(kinds)} loops: {' -> '.join(f'{names[n]} ({n})' for n in cycle)}" for cycle in cycles(edges))
    family = [row_id(db, "relationship_kind", kind) for kind in FAMILY]
    for kind, subject, object in db.execute(
        f"select k.name, r.subject_id, r.object_id from relationship r join relationship_kind k on k.id = r.relationship_kind_id "
        f"join entity s on s.id = r.subject_id join entity o on o.id = r.object_id "
        f"where r.relationship_kind_id in ({marks(family)}) and (s.entity_type_id <> ? or o.entity_type_id <> ?)",
        (*family, row_id(db, "entity_type", "Person"), row_id(db, "entity_type", "Person")),
    ):
        flags.append(f"{kind} joins something other than two people: {names[subject]} ({subject}), {names[object]} ({object})")
    people = [row_id(db, "entity_type", name) for name in PEOPLE]
    for speech, speaker, type_name in db.execute(
        f"select s.id, s.speaker_id, t.name from speech s join entity e on e.id = s.speaker_id join entity_type t on t.id = e.entity_type_id "
        f"where e.entity_type_id not in ({marks(people)})",
        people,
    ):
        flags.append(f"speech {speech} has a speaker that is a {type_name.lower()}: {names[speaker]} ({speaker})")
    for flag in flags:
        print(f"checks: {flag}")
    print(f"checks: {len(flags)} flagged")


def cycles(edges: dict[int, set[int]]) -> list[list[int]]:
    found, state = [], {}

    def visit(node, path):
        state[node] = "open"
        for next_node in sorted(edges.get(node, ())):
            if state.get(next_node) == "open":
                found.append(path[path.index(next_node):] + [next_node])
            elif next_node not in state:
                visit(next_node, path + [next_node])
        state[node] = "done"

    for node in sorted(edges):
        if node not in state:
            visit(node, [node])
    return found

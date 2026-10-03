"""Checks across finished layers for answers that cannot be true. It flags them and changes nothing."""

import sqlite3
from collections import defaultdict

# Kinds that cannot loop back on themselves: nobody is their own ancestor, and no place is north of itself.
ORDERED = [("child_of", "descendant_of"), ("north_of",), ("east_of",), ("higher_than",)]
PEOPLE = ("person", "group")
FAMILY = ("child_of", "descendant_of", "spouse_of", "sibling_of")


def clear(db: sqlite3.Connection):
    pass


def run(db: sqlite3.Connection):
    flags = []
    for kinds in ORDERED:
        edges = defaultdict(set)
        for subject, object in db.execute(f"select subject_id, object_id from relationship where kind_id in ({','.join('?' * len(kinds))})", kinds):
            edges[subject].add(object)
        flags.extend(f"{' / '.join(kinds)} loops: {' -> '.join(cycle)}" for cycle in cycles(edges))
    for kind, subject, object in db.execute(
        f"select r.kind_id, r.subject_id, r.object_id from relationship r join entity s on s.id = r.subject_id join entity o on o.id = r.object_id "
        f"where r.kind_id in ({','.join('?' * len(FAMILY))}) and (s.type_id <> 'person' or o.type_id <> 'person')",
        FAMILY,
    ):
        flags.append(f"{kind} joins something other than two people: {subject}, {object}")
    for speech, speaker, type_id in db.execute(
        f"select s.id, s.speaker_id, e.type_id from speech s join entity e on e.id = s.speaker_id where e.type_id not in ({','.join('?' * len(PEOPLE))})", PEOPLE
    ):
        flags.append(f"speech {speech} has a speaker that is a {type_id}: {speaker}")
    for flag in flags:
        print(f"checks: {flag}")
    print(f"checks: {len(flags)} flagged")


def cycles(edges: dict[str, set[str]]) -> list[list[str]]:
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

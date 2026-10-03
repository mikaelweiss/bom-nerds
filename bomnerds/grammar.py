"""English clauses, subjects, and verbs that spaCy's and Stanza's parses agree on. The AI completes every sentence around them."""

import json
import sqlite3
from collections import defaultdict

from .sentences import ENGLISH
from .taggers import CACHE

# spaCy labels in the ClearNLP style, Stanza in Universal Dependencies. Each set names the same relations in both.
CLAUSES = {"ROOT", "root", "ccomp", "xcomp", "advcl", "relcl", "acl", "acl:relcl", "csubj", "csubjpass", "csubj:pass", "parataxis", "conj"}
SUBJECTS = {"nsubj", "nsubjpass", "nsubj:pass", "csubj", "csubjpass", "csubj:pass", "expl"}
AUXILIARIES = {"aux", "auxpass", "aux:pass", "cop"}
JOINERS = {"cc"}
VERBAL = {"VERB", "AUX"}
NEGATIONS = {"not", "never"}


def clear(db: sqlite3.Connection):
    english = f"select id from word where edition_id in ({','.join('?' * len(ENGLISH))})"
    db.execute(f"delete from clause where sentence_id in (select id from sentence where first_word_id in ({english}))", ENGLISH)


def run(db: sqlite3.Connection):
    texts = dict(db.execute(f"select id, lower(text) from word where edition_id in ({','.join('?' * len(ENGLISH))})", ENGLISH))
    sentences = dict(db.execute("select first_word_id, id from sentence"))
    clauses = parts = 0
    with open(CACHE / "spacy.jsonl", encoding="utf-8") as spacy, open(CACHE / "stanza.jsonl", encoding="utf-8") as stanza:
        for a, b in zip(spacy, stanza):
            a, b = json.loads(a), json.loads(b)
            if not a or a[0][0] != b[0][0]:
                continue
            first = analyse(a, texts)
            second = analyse(b, texts)
            agreed = sorted(first.keys() & second.keys(), key=lambda span: (span[0], -span[1]))
            ids = {}
            for span in agreed:
                parent = min((s for s in ids if s != span and s[0] <= span[0] and span[1] <= s[1]), key=lambda s: s[1] - s[0], default=None)
                ids[span] = db.execute(
                    "insert into clause (sentence_id, parent_id, first_word_id, last_word_id) values (?, ?, ?, ?)",
                    (sentences[a[0][0]], ids.get(parent), *span),
                ).lastrowid
                clauses += 1
                for role, part in sorted(first[span] & second[span]):
                    db.execute("insert into clause_part (clause_id, role_id, first_word_id, last_word_id) values (?, ?, ?, ?)", (ids[span], role, *part))
                    parts += 1
    print(f"grammar: {clauses} English clauses and {parts} subjects and verbs both parsers agree on")


def analyse(words: list[list], texts: dict[int, str]) -> dict[tuple[int, int], set[tuple[str, tuple[int, int]]]]:
    """Each clause span in one parse, with the subject and verb spans inside it."""
    children = defaultdict(list)
    tags = {}
    for id, _, pos, head, dep in words:
        tags[id] = (pos, dep)
        if head is not None:
            children[head].append(id)

    def subtree(id, skip_coordinated=False):
        found = [id]
        for child in children[id]:
            if skip_coordinated and tags[child][1] == "conj" and is_clause(child):
                continue
            found.extend(subtree(child))
        return found

    def is_clause(id):
        pos, dep = tags[id]
        if dep not in CLAUSES:
            return False
        kinds = {tags[c][1] for c in children[id]}
        return pos in VERBAL or bool(kinds & (SUBJECTS | AUXILIARIES))

    result = {}
    for id in tags:
        if not is_clause(id):
            continue
        members = trim(sorted(subtree(id, skip_coordinated=True)), tags)
        if not members:
            continue
        span = (members[0], members[-1])
        found = set()
        for child in children[id]:
            if tags[child][1] in SUBJECTS:
                subject = sorted(subtree(child))
                found.add(("subject", (subject[0], subject[-1])))
        verb = verb_span(id, children, tags, texts)
        if verb:
            found.add(("verb", verb))
        result[span] = found
    return result


def trim(members: list[int], tags) -> list[int]:
    while members and tags[members[0]][1] in JOINERS:
        members = members[1:]
    while members and tags[members[-1]][1] in JOINERS:
        members = members[:-1]
    return members


def verb_span(id, children, tags, texts) -> tuple[int, int] | None:
    """The verb and its auxiliaries, when they stand together: "hath commanded", "shalt not kill"."""
    copula = [c for c in children[id] if tags[c][1] == "cop"]
    main = copula[0] if copula else id
    if not copula and tags[id][0] not in VERBAL:
        return None
    members = [main] + [c for c in children[id] if tags[c][1] in AUXILIARIES and c != main]
    first, last = min(members), max(members)
    if all(m in members or texts.get(m) in NEGATIONS for m in range(first, last + 1)):
        return first, last
    return None

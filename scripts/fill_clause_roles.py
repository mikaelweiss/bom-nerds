"""Give English clauses their Object, Indirect object, Complement, and Adverbial parts, and a Subject and Verb where missing.

    python scripts/fill_clause_roles.py scripture.db PARSES [--book NAME] [--packets DIR] [--decisions PATH] [--dry-run]

Every English sentence is parsed with spaCy (en_core_web_trf) and Stanza (default_accurate), cached as PARSES/spacy.jsonl
and PARSES/stanza.jsonl; sentences missing from the cache are parsed first, which needs both libraries installed.
Each clause is found in both parses by its span, and the direct dependents of its head become parts:
objects and quoted or "that" complements are O, datives and "to"/"unto" phrases after give/say verbs IO,
predicate phrases C, and adverbs, prepositional phrases, and adverbial clauses A.
A part is added where both parsers give the same role and words. Where one parser splits a phrase the other gives
whole under the same role, Adverbials take the split and other roles the whole. In the KJV the roles of the matched Hebrew or Greek
words decide a part only one parser gives. Parts never overlap the parts already there or cut through a child clause.
A clause with an O, IO, C, or A part neither parser gives was annotated by hand and is left alone. Parts already there
are not added twice, so a run can be repeated and finds the same disagreements. Hebrew and Greek clauses
and clause spans are never changed.

--book limits the pass to one book, for example "1 Nephi". --packets writes the clauses the parsers disagree on as
review packets, one per chapter, with index.tsv and slices.tsv. --decisions applies reviewed lines from a .jsonl file
or a directory of them, after the parser parts:

    {"clause_id": 228040, "parts": [["O", 794526, 794537], ["A", 794538, 794540]], "note": "optional"}

Roles are S, V, O, IO, C, A. Parts must lie inside the clause, not overlap each other or parts already there, and not
cut through a child clause. A line that fails is skipped whole and printed; parts already there count as repeats.
--dry-run reports and writes packets without changing the database.
"""

import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from export_clause_packets import CODES, glosses_for, slug  # noqa: E402

ENGLISH = (1, 4, 5, 6)
KJV, HEBREW, GREEK = 1, 2, 3
PARSERS = ("spacy", "stanza")
BATCH = 500
POSSESSIVE = re.compile(r"(.+?)(['’]s)$")

S, V, O, IO, C, A = "S", "V", "O", "IO", "C", "A"
ROLE_NAMES = {"Subject": S, "Verb": V, "Object": O, "Indirect object": IO, "Complement": C, "Adverbial": A}
FILLED = {O, IO, C, A}

CLAUSES = {"ROOT", "root", "ccomp", "xcomp", "advcl", "relcl", "acl", "acl:relcl", "csubj", "csubjpass", "csubj:pass", "parataxis", "conj"}
SUBJECTS = {"nsubj", "nsubjpass", "nsubj:pass", "csubj", "csubjpass", "csubj:pass", "expl"}
AUXILIARIES = {"aux", "auxpass", "aux:pass", "cop"}
VERBAL = {"VERB", "AUX"}
NEGATIONS = {"not", "never"}
DEPENDENT_ROLES = {
    "dobj": O, "obj": O, "ccomp": O,
    "dative": IO, "iobj": IO,
    "attr": C, "acomp": C, "oprd": C, "xcomp": C,
    "advmod": A, "npadvmod": A, "advcl": A, "neg": A, "agent": A, "prep": A,
    "obl": A, "obl:tmod": A, "obl:npmod": A, "obl:agent": A, "obl:unmarked": A, "nmod:tmod": A, "nmod:npmod": A,
}
PHRASE = {
    "det", "det:predet", "amod", "nmod", "nmod:poss", "case", "compound", "flat", "fixed", "nummod", "appos",
    "acl", "acl:relcl", "conj", "cc", "cc:preconj", "advmod", "dep", "list", "goeswith", "nmod:unmarked",
}
GIVING = {
    "give", "gave", "given", "giveth", "givest", "say", "said", "saith", "sayest", "speak", "spake", "spoke", "spoken",
    "speaketh", "spakest", "tell", "told", "telleth", "show", "shew", "shewed", "shewn", "showed", "shewest", "sheweth",
    "send", "sent", "sendeth", "command", "commanded", "commandeth", "do", "did", "done", "doeth", "declare", "declared",
    "cry", "cried", "crieth", "write", "wrote", "written", "bring", "brought", "offer", "offered", "deliver",
    "delivered", "sell", "sold", "lend", "pay", "paid", "grant", "granted", "sing", "sang", "swear", "sware", "sworn",
    "answer", "answered", "minister", "ministered", "preach", "preached", "reveal", "revealed", "testify", "testified",
    "teach", "taught", "explain", "explained", "pray", "prayed", "call", "called", "write", "reply", "replied",
    "proclaim", "proclaimed", "manifest", "manifested", "impart", "imparted", "return", "restore", "restored",
    "forgive", "forgiven", "forgave", "bestow", "bestowed", "confer", "conferred", "promise", "promised", "lend", "lent",
}
SAYING = {"say", "said", "saith", "speak", "spake", "tell", "answer", "cry", "write", "declare", "command", "know", "see", "hear", "think", "believe", "testify", "swear", "sware", "proclaim", "preach", "pray", "teach"}
TO = {"to", "unto"}
NO_PART = {
    "and", "but", "or", "nor", "neither", "for", "yet", "yea", "nay", "behold", "lo", "o", "oh", "amen", "selah",
    "even", "also", "that", "because", "moreover", "nevertheless", "notwithstanding", "howbeit", "verily",
    "therefore", "wherefore", "alleluia", "hallelujah",
}
SUBORDINATORS = {"when", "where", "whither", "whence", "while", "whilst", "until", "till", "as", "if", "though", "although", "lest", "whether", "since", "after", "before"}
PARTICLES = {"up", "down", "forth", "out", "away", "off", "aside", "in", "over"}
PUNCTUATION = ".,;:!?'\"()[]"


def english_sentences(db, book=None):
    """{sentence id: [(word id, text), ...]} for English sentences, optionally of one book."""
    where, args = "", []
    if book:
        where, args = " and b.name = ?", [book]
    rows = db.execute(
        "select s.id, f.sequence, l.sequence from sentence s join word f on f.id = s.first_word_id "
        "join word l on l.id = s.last_word_id join verse v on v.id = f.verse_id join chapter c on c.id = v.chapter_id "
        f"join book b on b.id = c.book_id where c.edition_id in ({','.join('?' * len(ENGLISH))}){where}",
        [*ENGLISH, *args],
    ).fetchall()
    return {
        sentence: db.execute("select id, text from word where sequence between ? and ? order by sequence", (first, last)).fetchall()
        for sentence, first, last in rows
    }


def tokens(words):
    found, owners = [], []
    for index, (_, text) in enumerate(words):
        possessive = POSSESSIVE.match(text)
        parts = [possessive.group(1), possessive.group(2)] if possessive else [text]
        found.extend(parts)
        owners.extend([index] * len(parts))
    return found, owners


def to_words(words, owners, analyses):
    result, seen = [], set()
    for index, (lemma, pos, head, dep) in enumerate(analyses):
        owner = owners[index]
        if owner in seen:
            continue
        seen.add(owner)
        head_id = words[owners[head]][0] if head is not None and owners[head] != owner else None
        result.append([words[owner][0], lemma, pos, head_id, dep])
    return result


def run_spacy(batch):
    import spacy
    from spacy.tokens import Doc

    nlp = spacy.load("en_core_web_trf")
    docs = []
    for _, words in batch:
        found, _ = tokens(words)
        docs.append(Doc(nlp.vocab, words=found, sent_starts=[True] + [False] * (len(found) - 1)))
    for (sentence, words), doc in zip(batch, nlp.pipe(docs, batch_size=32)):
        _, owners = tokens(words)
        yield sentence, to_words(words, owners, [(t.lemma_, t.pos_, None if t.head.i == t.i else t.head.i, t.dep_) for t in doc])


def run_stanza(batch):
    import stanza
    import torch

    device = "mps" if torch.backends.mps.is_available() else None
    nlp = stanza.Pipeline(
        "en", processors="tokenize,pos,lemma,depparse", package="default_accurate",
        tokenize_pretokenized=True, verbose=False, device=device,
    )
    for start in range(0, len(batch), 200):
        chunk = batch[start:start + 200]
        doc = nlp([tokens(words)[0] for _, words in chunk])
        for (sentence, words), parsed in zip(chunk, doc.sentences):
            _, owners = tokens(words)
            yield sentence, to_words(words, owners, [(w.lemma, w.upos, w.head - 1 if w.head else None, w.deprel) for w in parsed.words])
        del doc
        if device == "mps":
            torch.mps.empty_cache()


def load_parses(folder, name):
    path = os.path.join(folder, f"{name}.jsonl")
    parses = {}
    if not os.path.exists(path):
        return parses
    data = open(path, "rb").read()
    whole = data[:data.rfind(b"\n") + 1]
    if len(whole) != len(data):
        open(path, "wb").write(whole)
    for line in whole.decode("utf-8").splitlines():
        record = json.loads(line)
        parses[record["sentence"]] = record["words"]
    return parses


def parse(folder, name, sentences):
    """The parses of one parser for these sentences, parsing and caching the ones missing or out of date."""
    os.makedirs(folder, exist_ok=True)
    parses = load_parses(folder, name)
    batch = [
        (s, words) for s, words in sorted(sentences.items())
        if [w[0] for w in parses.get(s, [])] != [w for w, _ in words]
    ]
    if batch:
        with open(os.path.join(folder, f"{name}.jsonl"), "a", encoding="utf-8") as out:
            for count, (sentence, words) in enumerate({"spacy": run_spacy, "stanza": run_stanza}[name](batch), 1):
                out.write(json.dumps({"sentence": sentence, "words": words}, ensure_ascii=False) + "\n")
                parses[sentence] = words
                if count % 1000 == 0:
                    out.flush()
                    print(f"{name}: {count} of {len(batch)} sentences parsed", flush=True)
    return {s: parses[s] for s in sentences}


class Parse:
    """One parser's dependency tree of a sentence, on word sequence numbers."""

    def __init__(self, words, seq, text):
        self.text = text
        self.tags, self.head, self.lemma = {}, {}, {}
        self.children = defaultdict(list)
        for word, lemma, pos, head, dep in words:
            n = seq[word]
            self.tags[n] = (pos, dep)
            self.lemma[n] = (lemma or "").lower()
            self.head[n] = None if head is None else seq[head]
            if head is not None:
                self.children[seq[head]].append(n)
        self.clauses = self.analyse()

    def dep(self, n):
        return self.tags[n][1]

    def subtree(self, n, skip_coordinated=False):
        found = [n]
        for child in self.children[n]:
            if skip_coordinated and self.dep(child) == "conj" and self.is_clause(child):
                continue
            found.extend(self.subtree(child))
        return found

    def is_clause(self, n):
        pos, dep = self.tags[n]
        if dep not in CLAUSES:
            return False
        kinds = {self.dep(c) for c in self.children[n]}
        return pos in VERBAL or bool(kinds & (SUBJECTS | AUXILIARIES))

    def analyse(self):
        found = {}
        for n in self.tags:
            if not self.is_clause(n):
                continue
            members = sorted(self.subtree(n, skip_coordinated=True))
            while members and self.dep(members[0]) == "cc":
                members = members[1:]
            while members and self.dep(members[-1]) == "cc":
                members = members[:-1]
            if members:
                found[(members[0], members[-1])] = n
        return found

    def head_of(self, span):
        """The token heading a clause span: the clause the parser finds there, or else its one clausal root."""
        if span in self.clauses:
            return self.clauses[span]
        a, b = span
        roots = [n for n in range(a, b + 1) if n in self.tags and (self.head[n] is None or not a <= self.head[n] <= b)]
        clausal = [n for n in roots if self.tags[n][0] in VERBAL or {self.dep(c) for c in self.children[n]} & (SUBJECTS | AUXILIARIES)]
        if len(clausal) == 1:
            return clausal[0]
        if len(roots) == 1:
            return roots[0]
        return None

    def run(self, members, keep, a, b):
        """The unbroken stretch of members around word keep, inside a..b."""
        members = set(members)
        first = last = keep
        while first - 1 >= a and first - 1 in members:
            first -= 1
        while last + 1 <= b and last + 1 in members:
            last += 1
        return first, last

    def word(self, n):
        return self.text[n].strip(PUNCTUATION).lower()

    def verb(self, h):
        copula = [c for c in self.children[h] if self.dep(c) == "cop"]
        main = copula[0] if copula else h
        if not copula and self.tags[h][0] not in VERBAL:
            return None
        members = [main] + [c for c in self.children[h] if self.dep(c) in AUXILIARIES and c != main and self.word(c) != "to"]
        runs, start = [], None
        for m in range(min(members), max(members) + 1):
            inside = m in members or self.word(m) in NEGATIONS and start is not None
            if inside and start is None:
                start = m
            if not inside and start is not None:
                runs.append((start, m - 1))
                start = None
        runs.append((start, max(members)))
        trimmed = []
        for x, y in runs:
            while y > x and y not in members:
                y -= 1
            if x in members:
                trimmed.append((x, y))
        return trimmed

    def giving(self, h):
        return self.lemma[h] in GIVING or self.word(h) in GIVING

    def parts(self, h, a, b):
        """Candidate (role, first, last) parts for the clause a..b headed by h."""
        found = set()
        for verb in self.verb(h) or ():
            found.add((V, *verb))
        copular = any(self.dep(c) == "cop" for c in self.children[h]) or self.tags[h][0] not in VERBAL
        passing = [c for c in self.children[h] if self.word(c) == "pass"] if self.lemma[h] == "come" else []
        be_predicate = self.lemma[h] == "be" and not any(self.dep(c) in ("attr", "acomp", "dobj", "oprd") for c in self.children[h])
        speech = None
        dependents = self.children[h] + [c for p in passing for c in self.children[p] if DEPENDENT_ROLES.get(self.dep(c)) == A]
        for c in sorted(dependents):
            if not a <= c <= b:
                continue
            dep = self.dep(c)
            if dep in SUBJECTS:
                found.add((S, *self.run(self.subtree(c), c, a, b)))
                continue
            role = DEPENDENT_ROLES.get(dep)
            if role is None or copular and self.in_predicate(h, c):
                continue
            members = self.subtree(c)
            first, last = self.run(members, c, a, b)
            if self.word(c) == "saying" or (passing and (c in passing or self.word(first) == "that")):
                continue
            if first == last and (
                self.word(first) in NO_PART or role == A and (self.word(first) in PARTICLES or first == a and self.word(first) in SUBORDINATORS)
            ):
                continue
            if role == A and dep in ("prep", "obl", "dative") or role == IO:
                lead = self.word(first)
                if self.giving(h) and lead in TO:
                    role = IO
                elif role == IO and lead not in TO and dep != "iobj" and dep != "dative":
                    role = A
            if dep == "ccomp" and self.lemma[h] == "let":
                subject = [g for g in self.children[c] if self.dep(g) in SUBJECTS and g < c]
                if subject:
                    x, y = self.run(self.subtree(subject[0]), subject[0], a, b)
                    found.add((O, x, y))
                    if y + 1 <= last:
                        found.add((C, y + 1, last))
                    continue
            if dep in ("ccomp", "xcomp") and (self.lemma[h] in SAYING or self.word(h) in SAYING):
                role = O
                if c > h:
                    speech = (O, first, last)
            if dep == "prep" and be_predicate and c > h:
                role, be_predicate = C, False
            found.add((role, first, last))
        if speech:
            found.discard(speech)
            before = max([h] + [p[2] for p in found if p[2] < speech[1]])
            after = b if not any(p[1] > speech[2] for p in found) else speech[2]
            found.add((O, before + 1, after))
        if copular:
            members = [h]
            for c in self.children[h]:
                if self.in_predicate(h, c):
                    members.extend(self.subtree(c))
            found.add((C, *self.run(members, h, a, b)))
        return found

    def in_predicate(self, h, c):
        """Whether a dependent of a nominal or adjectival predicate belongs to the predicate phrase itself."""
        dep = self.dep(c)
        if dep == "advmod":
            return abs(c - h) == 1 and self.tags[h][0] not in VERBAL
        if dep == "obl":
            return c > h and any(self.word(g) == "of" and self.dep(g) == "case" for g in self.children[c])
        return dep in PHRASE and not (dep == "conj" and self.is_clause(c))


def overlaps(x, y):
    return x[1] <= y[2] and y[1] <= x[2]


class Store:
    """English clauses, their parts, and the KJV-to-original matches, read once."""

    def __init__(self, db, sentence_ids):
        self.db = db
        self.roles = {}
        for role, name in db.execute("select id, name from clause_role"):
            self.roles[ROLE_NAMES[name]] = role
        self.code = {v: k for k, v in self.roles.items()}
        self.seq, self.at, self.text, self.after, self.edition, self.verse = {}, {}, {}, {}, {}, {}
        for word, seq, text, after, edition, verse in db.execute(
            "select w.id, w.sequence, w.text, w.after, c.edition_id, w.verse_id from word w join verse v on v.id = w.verse_id "
            "join chapter c on c.id = v.chapter_id"
        ):
            self.seq[word], self.at[seq], self.text[seq], self.edition[seq], self.verse[seq] = seq, word, text, edition, verse
            self.after[seq] = after.strip()
        self.sentences = set(sentence_ids)
        self.clauses = defaultdict(list)
        self.span = {}
        self.sentence_of = {}
        for clause, sentence, a, b in db.execute("select id, sentence_id, first_word_id, last_word_id from clause"):
            if self.edition[self.seq[a]] in ENGLISH and sentence not in self.sentences:
                continue
            self.span[clause] = (self.seq[a], self.seq[b])
            self.sentence_of[clause] = sentence
            self.clauses[sentence].append(clause)
        self.parts = defaultdict(set)
        for clause, role, a, b in db.execute("select clause_id, clause_role_id, first_word_id, last_word_id from clause_part"):
            if clause in self.span:
                self.parts[clause].add((self.code[role], self.seq[a], self.seq[b]))
        self.matches = defaultdict(list)
        for a, b in db.execute("select word_id, other_word_id from word_match"):
            a, b = self.seq[a], self.seq[b]
            if self.edition[a] == KJV and self.edition[b] in (HEBREW, GREEK):
                self.matches[a].append(b)
        self.verb_clause = {}
        for clause, (a, b) in self.span.items():
            if self.edition[a] not in (HEBREW, GREEK):
                continue
            for role, x, y in self.parts[clause]:
                if role == V:
                    for n in range(x, y + 1):
                        old = self.verb_clause.get(n)
                        if old is None or b - a < self.span[old][1] - self.span[old][0]:
                            self.verb_clause[n] = clause

    def inner(self, clause):
        a, b = self.span[clause]
        return [
            d for d in self.clauses[self.sentence_of[clause]]
            if d != clause and a <= self.span[d][0] and self.span[d][1] <= b and self.span[d] != (a, b)
        ]

    def fits(self, clause, part, others):
        """Whether a part lies in its clause, keeps clear of the other parts, and holds child clauses whole."""
        a, b = self.span[clause]
        if not a <= part[1] <= part[2] <= b:
            return False
        if any(overlaps(part, p) for p in others):
            return False
        for d in self.inner(clause):
            x, y = self.span[d]
            if part[1] <= y and x <= part[2] and not (part[1] <= x and y <= part[2]):
                return False
        return True

    def original_clause(self, verb_seqs):
        votes = Counter(self.verb_clause[o] for n in verb_seqs for o in self.matches.get(n, ()) if o in self.verb_clause)
        return votes.most_common(1)[0][0] if votes else None

    def vote(self, original, part):
        """The role the original clause gives the words matched to an English part, or None."""
        a, b = self.span[original]
        roles = Counter()
        for n in range(part[1], part[2] + 1):
            for o in self.matches.get(n, ()):
                if a <= o <= b:
                    roles[next((r for r, x, y in self.parts[original] if x <= o <= y), None)] += 1
        if not roles:
            return None
        role, n = roles.most_common(1)[0]
        if role is None or n * 2 < sum(roles.values()):
            return None
        if role == A and part[0] == IO and self.edition[a] == HEBREW:
            return IO
        return role


class Decider:
    def __init__(self, store, parses):
        self.store = store
        self.parses = parses

    def clause(self, clause):
        """(parts to add with their source, the disagreement or None) for one English clause."""
        store = self.store
        a, b = store.span[clause]
        sentence = store.sentence_of[clause]
        raw = []
        for name in PARSERS:
            tree = self.parses[name].get(sentence)
            h = tree.head_of((a, b)) if tree else None
            raw.append(tree.parts(h, a, b) if h is not None else set())
        if any(p[0] in FILLED and p not in raw[0] | raw[1] for p in store.parts[clause]):
            return [], None
        base = {p for p in store.parts[clause] if p[0] not in FILLED}
        have = {p[0] for p in base}
        proposals = [{p for p in found if not (p[0] in (S, V) and p[0] in have) and store.fits(clause, p, base)} for found in raw]
        agreed = proposals[0] & proposals[1]
        accepted = {p: "agreed" for p in agreed if not any(overlaps(p, q) for q in agreed if q != p)}
        for x, y in ((proposals[0], proposals[1]), (proposals[1], proposals[0])):
            for whole in y - set(accepted):
                pieces = sorted((p for p in x - set(accepted) if p[0] == whole[0] and whole[1] <= p[1] and p[2] <= whole[2]), key=lambda p: p[1])
                if len(pieces) < 2 or pieces[0][1] != whole[1] or pieces[-1][2] != whole[2]:
                    continue
                if any(q[1] != p[2] + 1 for p, q in zip(pieces, pieces[1:])):
                    continue
                for p in pieces if whole[0] == A else [whole]:
                    if not any(overlaps(p, q) for q in accepted):
                        accepted[p] = "split"
        rest = (proposals[0] | proposals[1]) - set(accepted)
        original = None
        if store.edition[a] == KJV and rest:
            verbs = [n for r, x, y in store.parts[clause] | set(accepted) if r == V for n in range(x, y + 1)]
            verbs = verbs or [n for r, x, y in rest if r == V for n in range(x, y + 1)]
            original = store.original_clause(verbs)
        if original is not None:
            supported = [p for p in rest if store.vote(original, p) == p[0]]
            for p in supported:
                if any(overlaps(p, q) for q in supported if q != p) or any(overlaps(p, q) for q in accepted):
                    continue
                accepted[p] = "original"
        existing = [p for p in store.parts[clause] if p[0] in FILLED]
        accepted = {p: source for p, source in accepted.items() if p in existing or not any(overlaps(p, q) for q in existing)}
        settled = list(accepted) + existing
        open_parts = [p for p in rest if p not in settled and not any(overlaps(p, q) for q in settled)]
        dispute = None
        if open_parts:
            dispute = {
                "clause": clause,
                "accepted": sorted(accepted, key=lambda p: p[1]),
                "spacy": sorted((p for p in proposals[0] if p not in accepted and p in open_parts), key=lambda p: p[1]),
                "stanza": sorted((p for p in proposals[1] if p not in accepted and p in open_parts), key=lambda p: p[1]),
                "original": original,
            }
        return sorted(accepted.items(), key=lambda item: item[0][1]), dispute


def write_parts(db, store, clause, parts, report, edition):
    for role, x, y in parts:
        db.execute(
            "insert into clause_part (clause_id, clause_role_id, first_word_id, last_word_id) values (?, ?, ?, ?)",
            (clause, store.roles[role], store.at[x], store.at[y]),
        )
        store.parts[clause].add((role, x, y))
        report[edition, role] += 1


class Rejected(Exception):
    pass


def decision_lines(target):
    paths = [target] if os.path.isfile(target) else sorted(
        os.path.join(target, n) for n in os.listdir(target) if n.endswith(".jsonl")
    )
    for path in paths:
        for number, line in enumerate(open(path, encoding="utf-8"), 1):
            if line.strip():
                yield f"{os.path.basename(path)}:{number}", line


def decided_parts(db, store, line):
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        raise Rejected("unreadable JSON")
    if not isinstance(record, dict) or not isinstance(record.get("clause_id"), int) or not isinstance(record.get("parts"), list):
        raise Rejected("a line needs clause_id and parts")
    if set(record) - {"clause_id", "parts", "note"}:
        raise Rejected(f"unknown keys {sorted(set(record) - {'clause_id', 'parts', 'note'})}")
    clause = record["clause_id"]
    if clause not in store.span:
        raise Rejected(f"clause {clause} is unknown or outside this run")
    if store.edition[store.span[clause][0]] not in ENGLISH:
        raise Rejected(f"clause {clause} is not English")
    wanted, repeats = [], 0
    for part in record["parts"]:
        if not (isinstance(part, list) and len(part) == 3 and part[0] in (S, V, O, IO, C, A)
                and all(isinstance(w, int) and w in store.seq for w in part[1:])):
            raise Rejected(f"part {part} must be [role, first_word_id, last_word_id]")
        entry = (part[0], store.seq[part[1]], store.seq[part[2]])
        if entry in store.parts[clause] or entry in wanted:
            repeats += 1
            continue
        if entry[1] > entry[2]:
            raise Rejected(f"part {part} runs backward")
        if not store.fits(clause, entry, store.parts[clause] | set(wanted)):
            raise Rejected(f"part {part} leaves its clause, overlaps another part, or cuts through a child clause")
        wanted.append(entry)
    return clause, wanted, repeats


def place(db, word):
    return db.execute(
        "select c.edition_id, eb.position, b.name, c.number, v.number from word w join verse v on v.id = w.verse_id "
        "join chapter c on c.id = v.chapter_id join book b on b.id = c.book_id "
        "join edition_book eb on eb.edition_id = c.edition_id and eb.book_id = c.book_id where w.id = ?",
        (word,),
    ).fetchone()


def quote(store, x, y, limit=8):
    words = [store.text[n] for n in range(x, y + 1)]
    if len(words) > limit:
        words = words[: limit // 2] + ["..."] + words[-(limit // 2):]
    return " ".join(words)


def shown(store, parts):
    return " ".join(
        f"{r}:{store.at[x]}" + (f"-{store.at[y]}" if y != x else "") + f' "{quote(store, x, y, 6)}"' for r, x, y in parts
    ) or "none"


def write_packets(db, store, disputes, out):
    by_sentence = defaultdict(list)
    for dispute in disputes:
        by_sentence[store.sentence_of[dispute["clause"]]].append(dispute)
    chapters = defaultdict(list)
    for sentence, items in by_sentence.items():
        first = min(store.span[c][0] for c in store.clauses[sentence])
        edition, position, book, chapter, _ = place(db, store.at[first])
        chapters[(edition, position, book, chapter)].append((first, sentence, items))
    os.makedirs(out, exist_ok=True)
    for stale in os.listdir(out):
        if stale.endswith(".txt") or stale.endswith(".tsv"):
            os.remove(os.path.join(out, stale))
    index = []
    for (edition, position, book, chapter), sentences in sorted(chapters.items()):
        name = f"{CODES[edition]}-{position:02d}-{slug(book)}-{chapter:03d}.txt"
        body = [f"# {CODES[edition]} {book} {chapter}\n"]
        count = 0
        for _, sentence, items in sorted(sentences):
            body.append(packet_entry(db, store, sentence, items))
            count += len(items)
        content = "\n".join(body)
        with open(os.path.join(out, name), "w", encoding="utf-8") as f:
            f.write(content)
        index.append((name, CODES[edition], book, chapter, len(sentences), count, len(content.encode("utf-8"))))
    with open(os.path.join(out, "index.tsv"), "w", encoding="utf-8") as f:
        f.write("packet\tedition\tbook\tchapter\tsentences\tclauses\tbytes\n")
        for row in index:
            f.write("\t".join(map(str, row)) + "\n")
    slices, current, size = [], [], 0
    for row in index:
        if current and (size + row[6] > 90000 or current[-1][1:3] != row[1:3]):
            slices.append(current)
            current, size = [], 0
        current.append(row)
        size += row[6]
    if current:
        slices.append(current)
    numbers = Counter()
    with open(os.path.join(out, "slices.tsv"), "w", encoding="utf-8") as f:
        f.write("slice\tbook\tpackets\tclauses\tbytes\tpacket_names\n")
        for rows in slices:
            numbers[rows[0][1]] += 1
            f.write(
                f"{rows[0][1]}-{numbers[rows[0][1]]:03d}\t{rows[0][2]}\t{len(rows)}\t{sum(r[5] for r in rows)}\t"
                f"{sum(r[6] for r in rows)}\t{','.join(r[0] for r in rows)}\n"
            )
    return len(index), len(slices)


def packet_entry(db, store, sentence, items):
    clauses = sorted(store.clauses[sentence], key=lambda c: (store.span[c][0], -store.span[c][1]))
    first = min(store.span[c][0] for c in clauses)
    last = max(store.span[c][1] for c in clauses)
    row = db.execute("select s.first_word_id, s.last_word_id from sentence s where s.id = ?", (sentence,)).fetchone()
    first, last = min(first, store.seq[row[0]]), max(last, store.seq[row[1]])
    _, _, book, chapter, verse = place(db, store.at[first])
    lines = [f"## s{sentence} {book} {chapter}:{verse}"]
    out, current = [], None
    for n in range(first, last + 1):
        if store.verse[n] != current:
            current = store.verse[n]
            number = db.execute("select number from verse where id = ?", (current,)).fetchone()[0]
            out.append(f"|v{number}|")
        out.append(f"{store.at[n]}:{store.text[n]}{store.after[n]}")
    lines.append(" ".join(out))
    lines.append("clauses:")
    depth = {}
    parent = dict(db.execute("select id, parent_id from clause where sentence_id = ?", (sentence,)))
    for clause in clauses:
        depth[clause] = depth.get(parent.get(clause), -1) + 1
        a, b = store.span[clause]
        lines.append(f"  {'  ' * depth[clause]}c{clause} {store.at[a]}-{store.at[b]} \"{quote(store, a, b)}\" {shown(store, sorted(store.parts[clause], key=lambda p: p[1]))}")
    for item in items:
        clause = item["clause"]
        a, b = store.span[clause]
        lines.append(f"review c{clause} \"{quote(store, a, b, 12)}\"")
        lines.append(f"  agreed: {shown(store, [p for p in item['accepted'] if p[0] in FILLED])}")
        lines.append(f"  parser 1: {shown(store, item['spacy'])}")
        lines.append(f"  parser 2: {shown(store, item['stanza'])}")
        if item["original"] is not None:
            lines.append(f"  original: {original_hint(db, store, item['original'])}")
    return "\n".join(lines) + "\n"


def original_hint(db, store, clause):
    a, b = store.span[clause]
    glosses = glosses_for(db, [store.at[n] for n in range(a, b + 1)])
    parts = sorted(store.parts[clause], key=lambda p: p[1])

    def gloss(x, y):
        return " ".join((glosses.get(store.at[n]) or "?") for n in range(x, y + 1))

    return " ".join(f'{r}:"{gloss(x, y)}"' for r, x, y in parts) or "no parts"


def main(path, parses_folder, book=None, packets=None, decisions=None, dry_run=False):
    db = sqlite3.connect(path, isolation_level=None, timeout=60)
    db.execute("pragma busy_timeout = 60000")
    db.execute("pragma foreign_keys = on")
    sentences = english_sentences(db, book)
    parses = {}
    store = Store(db, sentences)
    for name in PARSERS:
        parses[name] = {s: Parse(words, store.seq, store.text) for s, words in parse(parses_folder, name, sentences).items()}
    decider = Decider(store, parses)
    report, sources, disputes = Counter(), Counter(), []
    clauses = sorted(c for s in sentences for c in store.clauses[s])
    for start in range(0, len(clauses), BATCH):
        db.execute("begin immediate")
        for clause in clauses[start:start + BATCH]:
            edition = CODES[store.edition[store.span[clause][0]]]
            report[edition, "clauses"] += 1
            if not store.parts[clause]:
                report[edition, "clauses with no parts"] += 1
            accepted, dispute = decider.clause(clause)
            accepted = [(p, source) for p, source in accepted if p not in store.parts[clause]]
            for part, source in accepted:
                sources[edition, source] += 1
            write_parts(db, store, clause, [p for p, _ in accepted], report, edition)
            if dispute:
                disputes.append(dispute)
                report[edition, "clauses for review"] += 1
        db.execute("rollback" if dry_run else "commit")
    rejects = []
    if decisions:
        db.execute("begin immediate")
        for where, line in decision_lines(decisions):
            report["decision lines"] += 1
            try:
                clause, wanted, repeats = decided_parts(db, store, line)
            except Rejected as problem:
                rejects.append(f"{where}: {problem}")
                report["decision lines rejected"] += 1
                continue
            report["decision parts already there"] += repeats
            write_parts(db, store, clause, wanted, report, "decided")
        db.execute("rollback" if dry_run else "commit")
    for problem in rejects:
        print(f"rejected {problem}")
    if packets:
        files, slices = write_packets(db, store, disputes, packets)
        print(f"packets: {files} files, {slices} slices, {len(disputes)} clauses for review")
    for key, n in sorted(report.items(), key=str):
        print(f"{' '.join(key) if isinstance(key, tuple) else key}: {n}")
    for (edition, source), n in sorted(sources.items()):
        print(f"{edition} parts from {source}: {n}")
    if dry_run:
        print("dry run, nothing written")


if __name__ == "__main__":
    flags = {}
    args = []
    argv = sys.argv[1:]
    while argv:
        arg = argv.pop(0)
        if arg == "--dry-run":
            flags["dry_run"] = True
        elif arg in ("--book", "--packets", "--decisions"):
            flags[arg[2:]] = argv.pop(0)
        else:
            args.append(arg)
    main(*args, **flags)

"""Carry the King James Version's mentions onto the Hebrew and Greek editions.

    python3 tagging/originals.py [PASSAGE ...]

PASSAGE is a Bible book and chapter or chapter range, as in "Genesis 1" or
"Malachi 3-4". With none, every chapter is carried. The Hebrew and Greek
mentions of the chosen chapters are rebuilt from the King James mentions
through word_match, so rerun this after retagging a chapter.
"""

import argparse
import re
import sqlite3
from bisect import bisect_left
from collections import Counter, defaultdict
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "scripture.db"
KJV, HEBREW, GREEK = 1, 2, 3
REFERS_TO = 1
PRONOUN_FORMS = ("Pronoun", "Suffix", "Article")
NOUNS = ("Noun", "Proper noun")

SUBJECT, OBJECT, POSSESSIVE = "subject", "object", "possessive"
ENGLISH_PRONOUNS = {
    "i": (1, None, "Singular", {SUBJECT}),
    "me": (1, None, "Singular", {OBJECT}),
    "myself": (1, None, "Singular", {OBJECT}),
    "my": (1, None, "Singular", {POSSESSIVE}),
    "mine": (1, None, "Singular", {POSSESSIVE, OBJECT}),
    "we": (1, None, "Plural", {SUBJECT}),
    "us": (1, None, "Plural", {OBJECT}),
    "ourselves": (1, None, "Plural", {OBJECT}),
    "our": (1, None, "Plural", {POSSESSIVE}),
    "ours": (1, None, "Plural", {POSSESSIVE, OBJECT}),
    "thou": (2, None, "Singular", {SUBJECT}),
    "thee": (2, None, "Singular", {OBJECT}),
    "thyself": (2, None, "Singular", {OBJECT}),
    "thy": (2, None, "Singular", {POSSESSIVE}),
    "thine": (2, None, "Singular", {POSSESSIVE, OBJECT}),
    "ye": (2, None, "Plural", {SUBJECT}),
    "you": (2, None, "Plural", {OBJECT}),
    "yourselves": (2, None, "Plural", {OBJECT}),
    "your": (2, None, "Plural", {POSSESSIVE}),
    "yours": (2, None, "Plural", {POSSESSIVE, OBJECT}),
    "he": (3, "Masculine", "Singular", {SUBJECT}),
    "him": (3, "Masculine", "Singular", {OBJECT}),
    "himself": (3, "Masculine", "Singular", {OBJECT}),
    "his": (3, "Masculine", "Singular", {POSSESSIVE}),
    "she": (3, "Feminine", "Singular", {SUBJECT}),
    "her": (3, "Feminine", "Singular", {OBJECT, POSSESSIVE}),
    "herself": (3, "Feminine", "Singular", {OBJECT}),
    "hers": (3, "Feminine", "Singular", {POSSESSIVE, OBJECT}),
    "it": (3, None, "Singular", {SUBJECT, OBJECT}),
    "itself": (3, None, "Singular", {OBJECT}),
    "its": (3, None, "Singular", {POSSESSIVE}),
    "they": (3, None, "Plural", {SUBJECT}),
    "them": (3, None, "Plural", {OBJECT}),
    "themselves": (3, None, "Plural", {OBJECT}),
    "their": (3, None, "Plural", {POSSESSIVE}),
    "theirs": (3, None, "Plural", {POSSESSIVE, OBJECT}),
}
FINITE = ("Perfect", "Sequential perfect", "Imperfect", "Sequential imperfect", "Cohortative", "Jussive", "Imperative",
          "Indicative", "Subjunctive", "Optative")
CASE_ROLES = {"Nominative": {SUBJECT}, "Genitive": {POSSESSIVE, OBJECT}, "Dative": {OBJECT}, "Accusative": {OBJECT}}
EITHER_GENDER = (None, "Common", "Both")


class Text:
    def __init__(self, db: sqlite3.Connection):
        self.sequence = {}
        self.verse = {}
        self.chapter = {}
        self.edition = {}
        self.at = {}
        self.part = {}
        for wid, sequence, verse, chapter, edition, part in db.execute(
            "select w.id, w.sequence, w.verse_id, v.chapter_id, c.edition_id, p.name from word w join verse v on v.id = w.verse_id"
            " join chapter c on c.id = v.chapter_id left join part_of_speech p on p.id = w.part_of_speech_id where c.edition_id in (?, ?, ?)",
            (KJV, HEBREW, GREEK),
        ):
            self.part[wid] = part
            self.sequence[wid] = sequence
            self.verse[wid] = verse
            self.chapter[wid] = chapter
            self.edition[wid] = edition
            self.at[sequence] = wid
        self.verse_words = defaultdict(list)
        for wid in sorted(self.sequence, key=self.sequence.get):
            self.verse_words[self.verse[wid]].append(wid)
        self.book = dict(db.execute("select v.id, c.book_id from verse v join chapter c on c.id = v.chapter_id where c.edition_id = ?", (KJV,)))

    def span(self, first: int, last: int) -> list[int]:
        return [self.at[s] for s in range(self.sequence[first], self.sequence[last] + 1)]

    def verse_start(self, verse: int) -> int:
        return self.sequence[self.verse_words[verse][0]]


def alignment(db: sqlite3.Connection, text: Text) -> tuple[dict[int, set[int]], dict[int, set[int]]]:
    """Each King James word's Hebrew or Greek words, without stray matches,
    and the words that carry each pronoun.

    word_match often pairs an English pronoun with the verb, noun, or
    preposition that carries it, while the pronoun itself is a separate
    suffix or a verb ending, so a pronoun keeps only its matches to pronoun
    forms. Its other matches are the words that carry it.

    A King James verse almost always matches one original verse. Where it
    matches several, an original verse counts only when it lies between the
    verses its neighbours mostly match and takes more than one word, so
    stray matches into distant verses are dropped.
    """
    raw = defaultdict(set)
    carriers = defaultdict(set)
    for kjv, other in db.execute("select word_id, other_word_id from word_match"):
        if text.edition.get(kjv) != KJV or text.edition.get(other) not in (HEBREW, GREEK):
            continue
        if text.part[kjv] == "Pronoun" and text.part[other] not in PRONOUN_FORMS:
            carriers[kjv].add(other)
            continue
        raw[kjv].add(other)

    counts = defaultdict(Counter)
    for kjv, others in raw.items():
        for other in others:
            counts[text.verse[kjv]][text.verse[other]] += 1
    order = sorted(counts, key=text.verse_start)
    anchor = {v: text.verse_start(max(c, key=lambda t: (c[t], -text.verse_start(t)))) for v, c in counts.items()}

    allowed = {}
    for i, verse in enumerate(order):
        book = text.book[verse]
        low = anchor[order[i - 1]] if i > 0 and text.book[order[i - 1]] == book else float("-inf")
        high = anchor[order[i + 1]] if i + 1 < len(order) and text.book[order[i + 1]] == book else float("inf")
        targets = counts[verse]
        allowed[verse] = {
            t for t, n in targets.items() if low <= text.verse_start(t) <= high and (n > 1 or len(targets) == 1)
        }

    def kept(matches: dict[int, set[int]]) -> dict[int, set[int]]:
        found = {}
        for kjv, others in matches.items():
            inside = {o for o in others if text.verse[o] in allowed.get(text.verse[kjv], ())}
            if inside:
                found[kjv] = inside
        return found

    return kept(raw), kept(carriers)


class Pronouns:
    """The Hebrew or Greek word that expresses each King James pronoun word_match leaves unmatched.

    Hebrew writes most pronouns as a suffix on the word before it, both
    languages give a verb's subject as its ending, and Greek often gives it
    as a participle. The word must agree with the English pronoun in person,
    number, and any gender the English marks, and must be able to fill its
    role: a verb or nominative only for a subject, a genitive only for a
    possessive. A suffix stands for a subject only after a particle such as
    הִנֵּה or an infinitive, as in "here am I" or "when he came".

    The word is first sought on what the pronoun attaches to: the words
    word_match pairs it with, the verb after a subject, the verb or
    preposition before an object, or the noun after a possessive. It must be
    the only one there that agrees, with a finite verb ahead of a participle
    beside it, and no other pronoun may claim it.
    Failing that, an unmatched pronoun form, or an unmatched first or second
    person verb, counts when it is the only one that agrees between the
    original words matched to the English words either side, and no other
    open English pronoun could take it. Third person verbs are left out
    there, since a noun is usually their subject. Words the King James
    translators supplied are never carried.
    """

    def __init__(self, db: sqlite3.Connection, text: Text, links: dict[int, set[int]], carriers: dict[int, set[int]]):
        self.text = text
        self.links = links
        self.carriers = carriers
        self.after = {}
        self.form = {}
        self.verbs = set()
        self.matched = {o for others in links.values() for o in others}
        self.english = {}
        for wid, word, supplied in db.execute(
            "select w.id, lower(w.text), w.supplied from word w join verse v on v.id = w.verse_id join chapter c on c.id = v.chapter_id"
            " where c.edition_id = ? and w.part_of_speech_id = (select id from part_of_speech where name = 'Pronoun')",
            (KJV,),
        ):
            if word in ENGLISH_PRONOUNS:
                self.english[wid] = (ENGLISH_PRONOUNS[word], supplied)
        self.read_hebrew(db)
        self.read_greek(db)

    def read_hebrew(self, db: sqlite3.Connection):
        rows = db.execute(
            "select w.id, w.after, t.name, h.person, g.name, n.name, f.name from word w join hebrew_word h on h.word_id = w.id"
            " left join word_type t on t.id = h.word_type_id left join gender g on g.id = h.gender_id"
            " left join grammatical_number n on n.id = h.grammatical_number_id left join verb_form f on f.id = h.verb_form_id"
        ).fetchall()
        verb_form = {wid: form for wid, _, _, _, _, _, form in rows}
        for wid, after, kind, person, gender, number, form in rows:
            self.after[wid] = after
            part = self.text.part.get(wid)
            if part == "Suffix" and kind == "Pronominal":
                host = self.text.at[self.text.sequence[wid] - 1]
                roles = {OBJECT, POSSESSIVE}
                if self.text.part[host] in ("Particle", "Adverb", "Interjection") or verb_form.get(host) == "Infinitive construct":
                    roles.add(SUBJECT)
            elif part == "Pronoun" and kind == "Personal" and self.text.part.get(self.text.at.get(self.text.sequence[wid] - 1)) != "Article":
                roles = {SUBJECT, OBJECT, POSSESSIVE}
            elif part == "Verb" and form in FINITE and person:
                roles = {SUBJECT}
                self.verbs.add(wid)
            else:
                continue
            self.form[wid] = (person, gender, number, roles)

    def read_greek(self, db: sqlite3.Connection):
        for wid, kind, person, gender, number, case, mood in db.execute(
            "select w.id, t.name, g.person, ge.name, n.name, c.name, m.name from word w join greek_word g on g.word_id = w.id"
            " left join word_type t on t.id = g.word_type_id left join gender ge on ge.id = g.gender_id"
            " left join grammatical_number n on n.id = g.grammatical_number_id left join grammatical_case c on c.id = g.grammatical_case_id"
            " left join mood m on m.id = g.mood_id"
        ):
            part = self.text.part.get(wid)
            if part == "Pronoun" and kind in ("Personal", "Reflexive") and case in CASE_ROLES:
                self.form[wid] = (person or 3, gender, number, CASE_ROLES[case])
            elif part == "Verb" and (mood in FINITE and person or mood == "Participle" and case == "Nominative"):
                self.form[wid] = (person, gender, number, {SUBJECT})
                self.verbs.add(wid)

    def agrees(self, pronoun: int, word: int, role: str) -> bool:
        person, gender, number, roles = self.english[pronoun][0]
        o_person, o_gender, o_number, o_roles = self.form[word]
        return (
            role in roles
            and role in o_roles
            and person == (o_person or person)
            and number == o_number
            and (gender is None or o_gender in EITHER_GENDER or o_gender == gender)
            and (word in self.verbs or word not in self.matched)
        )

    def heads(self, pronoun: int, role: str) -> list[int]:
        """The English words a pronoun in this role attaches to."""
        part = self.text.part
        words = self.text.verse_words[self.text.verse[pronoun]]
        i = words.index(pronoun)
        before, after = words[i - 1 :: -1] if i else [], words[i + 1 :]

        def run(seq, parts, limit, through=()):
            found = []
            for w in seq[:limit]:
                if part[w] not in parts:
                    break
                found.append(w)
                if part[w] in through:
                    break
            return found

        if role == SUBJECT:
            verbs = [w for w in run(after, ("Verb", "Adverb"), 4) if part[w] == "Verb"]
            if verbs or OBJECT in self.english[pronoun][0][3]:
                return verbs
            return run(before, ("Verb",), 2)
        if role == OBJECT:
            return run(before, ("Verb", "Preposition", "Adverb", "Particle"), 3)
        return run(after, ("Adjective", "Numeral", "Verb", *NOUNS), 4, through=NOUNS)

    def attached(self, host: int, role: str) -> set[int]:
        """The words on a host that can express a pronoun: the host verb itself, or a suffix or pronoun beside it."""
        text = self.text
        found = {host} if role == SUBJECT and host in self.verbs else set()
        steps = (1,) if text.edition[host] == HEBREW else (1, -1)
        for step in steps:
            beside = text.at.get(text.sequence[host] + step)
            if beside is None or text.verse[beside] != text.verse[host] or beside in self.verbs or beside not in self.form:
                continue
            if text.edition[host] == HEBREW and (self.after[host] or text.part[beside] != "Suffix"):
                continue
            found.add(beside)
        return found

    def window(self, pronoun: int, targets: set[int]) -> range:
        """The original words between those matched to the nearest matched English words around a pronoun."""
        text = self.text
        words = text.verse_words[text.verse[pronoun]]
        i = words.index(pronoun)
        left = next((self.links[w] for w in words[i - 1 :: -1] if w in self.links), set()) if i else set()
        right = next((self.links[w] for w in words[i + 1 :] if w in self.links), set())
        firsts = [text.verse_start(v) for v in targets]
        lasts = [text.sequence[text.verse_words[v][-1]] for v in targets]
        low = min(text.sequence[w] for w in left) if left else min(firsts)
        high = max(text.sequence[w] for w in right) if right else max(lasts)
        if low > high:
            ends = [text.sequence[w] for w in left | right]
            low, high = min(ends), max(ends)
        beside = text.at.get(high + 1)
        if beside in self.form and text.part[beside] == "Suffix":
            high += 1
        return range(low, high + 1)

    def resolve(self) -> dict[int, int]:
        text = self.text
        targets = defaultdict(set)
        for kjv, others in self.links.items():
            targets[text.verse[kjv]] |= {text.verse[o] for o in others}
        loose = defaultdict(list)
        for word, (person, _, _, _) in self.form.items():
            if word not in self.matched and (word not in self.verbs or person in (1, 2)):
                loose[text.verse[word]].append(word)

        open_pronouns = self.english.keys() - self.links.keys()
        claims = defaultdict(set)
        undecided = set()
        for pronoun in open_pronouns:
            found = set()
            for role in self.english[pronoun][0][3]:
                hosts = set(self.carriers.get(pronoun, ()))
                for head in self.heads(pronoun, role):
                    hosts |= self.links.get(head, set())
                found |= {w for h in hosts for w in self.attached(h, role) if self.agrees(pronoun, w, role)}
            finite = {w for w in found if w in self.verbs and self.form[w][0]}
            if finite:
                found = finite | (found - self.verbs)
            if len(found) == 1:
                claims[found.pop()].add(pronoun)
            elif not found:
                undecided.add(pronoun)
        chosen = {next(iter(ps)): w for w, ps in claims.items() if len(ps) == 1}

        wanted = defaultdict(set)
        options = {}
        for pronoun in open_pronouns:
            verses = targets[text.verse[pronoun]]
            if not verses:
                continue
            near = self.window(pronoun, verses)
            options[pronoun] = {
                w
                for verse in verses
                for w in loose[verse]
                if text.sequence[w] in near and any(self.agrees(pronoun, w, role) for role in self.english[pronoun][0][3])
            }
            for w in options[pronoun]:
                wanted[w].add(pronoun)
        for pronoun in undecided & options.keys():
            found = {w for w in options[pronoun] if w not in claims}
            if len(found) == 1 and wanted[next(iter(found))] == {pronoun}:
                chosen[pronoun] = found.pop()
        return {p: w for p, w in chosen.items() if not self.english[p][1]}


class Projector:
    def __init__(self, text: Text, links: dict[int, set[int]], subjects: dict[int, int], mentions: list[tuple]):
        self.text = text
        self.links = links
        self.subjects = subjects
        self.names = defaultdict(list)
        for entity, kind, first, last in mentions:
            if kind == REFERS_TO:
                self.names[text.verse[first]].append((text.sequence[first], text.sequence[last], entity))
        self.matched_by = defaultdict(set)
        for kjv, others in links.items():
            for other in others:
                self.matched_by[other].add(kjv)
        self.sequences = {e: sorted(self.text.sequence[w] for w in self.matched_by if text.edition[w] == e) for e in (HEBREW, GREEK)}

    def foreign(self, a: int, b: int, inside: set[int]) -> int:
        """How many words between a and b match King James words outside the mention."""
        sequences = self.sequences[self.text.edition[a]]
        low, high = self.text.sequence[a], self.text.sequence[b]
        between = sequences[bisect_left(sequences, low + 1) : bisect_left(sequences, high)]
        return sum(1 for s in between if self.matched_by[self.text.at[s]] - inside)

    def nested(self, entity: int, first: int, last: int) -> set[int]:
        """Words of the mention that belong to a shorter mention of another entity inside it."""
        low, high = self.text.sequence[first], self.text.sequence[last]
        return {
            self.text.at[s]
            for a, b, other in self.names[self.text.verse[first]]
            if other != entity and low <= a and b <= high and (a, b) != (low, high)
            for s in range(a, b + 1)
        }

    def project(self, entity: int, kind: int, first: int, last: int) -> tuple[int, int] | str:
        """The original span of a King James mention, or why it has none.

        A single word matching text outside the mention, such as a
        postpositive δέ or a copula, does not break the span. More than one
        splits it, and the piece covering most of the mention's words wins,
        so a stray match drops out. A tie leaves no clear span. A pronoun
        matched to nothing takes the verb whose ending gives it.
        """
        text = self.text
        words = text.span(first, last)
        inside = set(words)
        matched = sorted({o for w in words for o in self.links.get(w, ())}, key=text.sequence.get)
        if not matched:
            verbs = {self.subjects[w] for w in words if w in self.subjects}
            if kind == REFERS_TO and len(verbs) == 1:
                verb = verbs.pop()
                return verb, verb
            return "unaligned"
        if kind == REFERS_TO:
            own = inside - self.nested(entity, first, last)
            if not any(w in self.links for w in own):
                return "nested"
            nouns = [w for w in own if text.part[w] in NOUNS]
            if nouns and not any(w in self.links for w in nouns):
                return "unmatched noun"

        clusters = [[matched[0]]]
        for a, b in zip(matched, matched[1:]):
            same_verse = text.verse[a] == text.verse[b]
            if (kind == REFERS_TO and not same_verse) or self.foreign(a, b, inside) > 1:
                clusters.append([b])
            else:
                clusters[-1].append(b)

        def covered(cluster: list[int]) -> int:
            return len({k for o in cluster for k in self.matched_by[o] & inside})

        ranked = sorted(clusters, key=covered, reverse=True)
        if len(ranked) > 1 and covered(ranked[0]) == covered(ranked[1]):
            return "scattered"
        start, end = ranked[0][0], ranked[0][-1]

        if kind != REFERS_TO:
            if first not in self.links:
                start = self.widen(start, -1)
            if last not in self.links:
                end = self.widen(end, 1)
        return start, end

    def widen(self, word: int, step: int) -> int:
        """Grow a passage's end over neighbouring words in its verse that match no King James word."""
        text = self.text
        while True:
            neighbour = text.at.get(text.sequence[word] + step)
            if neighbour is None or text.verse[neighbour] != text.verse[word] or neighbour in self.matched_by:
                return word
            word = neighbour


def chapters(db: sqlite3.Connection, passages: list[str]) -> set[int]:
    found = set()
    for label in passages:
        match = re.fullmatch(r"(.+?) (\d+)(?:-(\d+))?", label.strip())
        if not match:
            raise SystemExit(f"cannot read passage {label!r}: use Book C or Book C-C")
        book, low, high = match.groups()
        rows = db.execute(
            "select c.id from chapter c join book b on b.id = c.book_id where c.edition_id = ? and b.name = ? and c.number between ? and ?",
            (KJV, book, int(low), int(high or low)),
        ).fetchall()
        if not rows:
            raise SystemExit(f"no King James chapters in {label}")
        found |= {r for r, in rows}
    return found


def closure(text: Text, links: dict[int, set[int]], mentions: list[tuple], kjv: set[int]) -> tuple[set[int], set[int]]:
    """The King James and original chapters whose mentions rebuild together.

    Versification differs, as where the King James Malachi 4 is the Hebrew
    Malachi 3, so a chapter is rebuilt with every chapter that shares words
    with it, and with every chapter a mention starting in it runs into.
    """
    edges = defaultdict(set)

    def join(a, b):
        edges[a].add(b)
        edges[b].add(a)

    for k, others in links.items():
        for o in others:
            join(("kjv", text.chapter[k]), ("original", text.chapter[o]))
    for _, _, first, last in mentions:
        if text.chapter[first] != text.chapter[last]:
            for chapter in {text.chapter[w] for w in text.span(first, last)}:
                join(("kjv", text.chapter[first]), ("kjv", chapter))
    seen = {("kjv", c) for c in kjv}
    todo = list(seen)
    while todo:
        for node in edges[todo.pop()] - seen:
            seen.add(node)
            todo.append(node)
    return {c for side, c in seen if side == "kjv"}, {c for side, c in seen if side == "original"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("passage", nargs="*", help="a King James book and chapter or chapter range, such as \"Malachi 3-4\"")
    args = parser.parse_args()
    db = sqlite3.connect(DB)
    db.execute("pragma foreign_keys = on")
    text = Text(db)
    links, carriers = alignment(db, text)
    pronouns = Pronouns(db, text, links, carriers)
    subjects = {}
    for pronoun, word in pronouns.resolve().items():
        if word in pronouns.verbs:
            subjects[pronoun] = word
        else:
            links[pronoun] = {word}

    mentions = [m for m in db.execute("select entity_id, mention_kind_id, first_word_id, last_word_id from mention") if text.edition.get(m[2]) == KJV]
    projector = Projector(text, links, subjects, mentions)
    if args.passage:
        kjv, original = closure(text, links, mentions, chapters(db, args.passage))
        mentions = [m for m in mentions if text.chapter[m[2]] in kjv]
    else:
        kjv = {c for c, in db.execute("select id from chapter where edition_id = ?", (KJV,))}
        original = {c for c, in db.execute("select id from chapter where edition_id in (?, ?)", (HEBREW, GREEK))}

    rows = set()
    skipped = Counter()
    for entity, kind, first, last in mentions:
        span = projector.project(entity, kind, first, last)
        if isinstance(span, str):
            skipped[span] += 1
            continue
        rows.add((entity, kind, *span))

    with db:
        stale = [m for m, w in db.execute("select id, first_word_id from mention") if text.chapter.get(w) in original]
        db.executemany("delete from mention where id = ?", [(m,) for m in stale])
        db.executemany("insert into mention (entity_id, mention_kind_id, first_word_id, last_word_id) values (?, ?, ?, ?)", sorted(rows))
        problems = db.execute("pragma foreign_key_check").fetchall()
        if problems:
            raise SystemExit(f"foreign key problems: {problems[:5]}")

    made = Counter(text.edition[r[2]] for r in rows)
    print(f"{len(mentions)} King James mentions in {len(kjv)} chapters")
    print(f"removed {len(stale)}, added {made[HEBREW]} Hebrew and {made[GREEK]} Greek mentions")
    print(
        f"skipped {skipped['unaligned']} with no matched words, {skipped['nested']} matched only through a mention inside them,"
        f" {skipped['unmatched noun']} whose nouns have no match, and {skipped['scattered']} matched to scattered words"
    )


if __name__ == "__main__":
    main()

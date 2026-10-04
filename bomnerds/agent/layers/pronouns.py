"""Mentions of pronouns, and of passages that are about an entity without naming it."""

import sqlite3

from ..layer import Layer, Problems, Reading, numbered, passage_of, scope_span, split_chapter, verse_number, where

PRONOUN_GROUPS = {
    "first person": ("I", "me", "my", "mine", "myself", "we", "us", "our", "ours", "ourselves"),
    "second person": ("thou", "thee", "thy", "thine", "thyself", "ye", "you", "your", "yours", "yourself", "yourselves"),
    "third person": ("he", "him", "his", "himself", "she", "her", "hers", "herself", "it", "its", "itself", "they", "them", "their", "theirs", "themselves"),
    "relative": ("who", "whom", "whose"),
}
TAGGED = {word.casefold() for group in PRONOUN_GROUPS.values() for word in group}
POINT_TO_SPEAKER = {"i", "me", "my", "mine"}
POINT_TO_LISTENER = {"thou", "thee", "thy", "thine"}

PRONOUN_INSTRUCTIONS = """
Tag every pronoun in each chapter that points to an entity, with that entity. Names and titles are already tagged, so read each pronoun against the names around it.

Tag these pronouns and no others:

""" + "\n".join(f"{group}: " + ", ".join(f'"{word}"' for word in words) for group, words in PRONOUN_GROUPS.items()) + """

Leave out "that", "which", "this", "what", "whoso", and every other word, even when it stands for someone.

- Tag one word per mention, each pronoun on its own.
- "I", "me", "my", "mine" take the speaker of the innermost speech around them. "thou", "thee", "thy", "thine" take the speech's listener when it has exactly one. The script tags those for you, so they are not numbered. Tag the same words yourself only where it did not, such as in a speech with several listeners, using the speeches shown.
- "who", "whom", "whose": tag only when it points back to an entity ("Nephi, who ..."). Leave out a question ("Who is this?") and a general one ("he who believeth").
- "it" and "its": tag only when they stand for an entity on the list. "It came to pass" points to nothing.
- "we", "us", "our", "ye", "you", "your": tag with the group they mean. If that group is not on the list, write an unlisted line for it.
- A pronoun can point back into the chapter before.
- Under "Pronouns" is every such word still untagged, numbered verse by verse. Answer every number: with its entity, or "-" when it points to no entity.
"""

PRONOUN_FORMAT = """Write one line per verse under "Pronouns": the chapter and verse, then each number with "=" and its entity. Join numbers that share an entity with "-" for a run or "," for a list. "-" alone as the answer means the pronoun points to no entity.

3:7  1-4=nephi-son-of-lehi  5=jesus-christ  6=-
3:8  1=nephi-son-of-lehi  2,3=lehi"""

ABOUT_INSTRUCTIONS = """
Tag every passage in each chapter that is about an entity without naming it, with that entity. Topics attach this way: a verse about faith or repentance that never says the word.

- Pick the entity from the lists in this prompt. Topics are under Topics.
- Tag whole verses only: one verse, or a run of whole verses. Pick the fewest verses that are about the entity.
- Leave out a passage that names or points to the entity. Names and pronouns are already tagged.
- A passage can be about several entities. Give each its own object.

Answer with one object per entity per passage:

{ "entity": "faith", "passage": { "from": "Alma 32:21", "to": "Alma 32:43" } }
"""


class Mentions(Layer):
    """Layers that write the mention table, one kind each."""

    kind: str

    def parse(self, db, scope, answer):
        problems = Problems(db)
        tags = []
        for number, item in enumerate(problems.items(answer), 1):
            problems.at(where(number, item))
            if not problems.fields(item, ("entity", "passage")):
                continue
            entity = problems.entity(item["entity"])
            span = problems.passage(item["passage"], within=scope)
            if span and not self.accepts(db, problems, *span):
                span = None
            if entity and span:
                tags.append((entity, *span))
        problems.at("")
        self.reconcile(db, problems, tags)
        problems.raise_any()
        return tags

    def accepts(self, db: sqlite3.Connection, problems: Problems, first: int, last: int) -> bool:
        """Whether this layer tags the passage. Adds a problem when it does not."""
        return True

    def reconcile(self, db: sqlite3.Connection, problems: Problems, tags: list):
        """Add a problem for tags of one answer that cannot all be true."""

    def render(self, db, tag):
        entity, first, last = tag
        return {"entity": entity, "passage": passage_of(db, first, last)}

    def store(self, db, scope, tags):
        db.executemany(f"insert into mention (entity_id, kind_id, first_word_id, last_word_id) values (?, '{self.kind}', ?, ?)", tags)

    def unstore(self, db, scope, tags):
        db.executemany(f"delete from mention where entity_id = ? and kind_id = '{self.kind}' and first_word_id = ? and last_word_id = ?", tags)


class Pronouns(Mentions):
    name = "pronouns"
    step = 6
    kind = "names"
    instructions = PRONOUN_INSTRUCTIONS

    format = PRONOUN_FORMAT

    def extra(self, db, jobs, scope, batch=()):
        listing = self.listing(db, scope)
        _, chapter = split_chapter(scope)
        lines = [f"{chapter}:{verse}  " + "  ".join(f"{n} {text}" for n, (_, text) in enumerate(words, 1)) for verse, words in listing.items()]
        return "## Pronouns\n\n" + "\n".join(lines) if lines else "## Pronouns\n\nNone untagged. Leave this chapter's section empty."

    def listing(self, db, scope) -> dict[int, list[tuple[int, str]]]:
        """Each verse's untagged pronouns as (word id, text), in the order the prompt numbers them from 1."""
        first, last = scope_span(db, scope)
        tagged = {word for _, word, _ in self.fixed(db, scope) + self.given(db, scope)}
        verses = {}
        for word, verse, text in pronoun_words(db, first, last):
            if word not in tagged:
                verses.setdefault(verse, []).append((word, text))
        return verses

    def read(self, db, scope, lines):
        _, chapter = split_chapter(scope)
        listing = self.listing(db, scope)
        problems = Problems(db)
        reading = Reading()
        for number, line in enumerate(lines, 1):
            problems.at(f"line {number}")
            found = numbered(problems, line)
            if found is None:
                continue
            key, groups = found
            verse = verse_number(problems, key, chapter)
            if verse is None:
                continue
            words = listing.get(verse)
            if not words:
                problems.add(f"{key} has no numbered pronouns")
                continue
            for numbers, value, unsure in groups:
                for n in numbers:
                    if not 1 <= n <= len(words):
                        problems.add(f"{key} has pronouns 1 to {len(words)}, not {n}")
                        continue
                    word = words[n - 1][0]
                    if value == "-":
                        reading.skipped.append(word)
                        continue
                    reading.items.append({"entity": value, "passage": passage_of(db, word, word)})
                    if unsure:
                        reading.flagged.append(f"{key} {n}={value} ({words[n - 1][1]})")
        problems.raise_any()
        return reading

    def complete(self, db, scope, reading):
        quiet = Problems(db)
        answered = set(reading.skipped)
        for item in reading.items:
            span = quiet.passage(item["passage"], within=scope)
            if span:
                answered.add(span[0])
        _, chapter = split_chapter(scope)
        missing = [f"{chapter}:{verse} {n}" for verse, words in self.listing(db, scope).items() for n, (word, _) in enumerate(words, 1) if word not in answered]
        return [f"these pronouns have no answer. Answer each with its entity, or \"-\": {', '.join(missing)}"] if missing else []

    def fixed(self, db, scope):
        first, last = scope_span(db, scope)
        speeches = db.execute(
            "select id, speaker_id, first_word_id, last_word_id from speech where first_word_id <= ? and last_word_id >= ? order by last_word_id - first_word_id",
            (last, first),
        ).fetchall()
        listeners = {}
        for speech, entity in db.execute(
            "select l.speech_id, l.entity_id from speech_listener l join speech s on s.id = l.speech_id where s.first_word_id <= ? and s.last_word_id >= ?",
            (last, first),
        ):
            listeners.setdefault(speech, []).append(entity)
        mentioned = {word for _, word, _ in self.given(db, scope)}
        tags = []
        for word, _, text in pronoun_words(db, first, last):
            text = text.casefold()
            innermost = next((s for s in speeches if s[2] <= word <= s[3]), None)
            if word in mentioned or innermost is None:
                continue
            if text in POINT_TO_SPEAKER:
                tags.append((innermost[1], word, word))
            elif text in POINT_TO_LISTENER and len(listeners.get(innermost[0], ())) == 1:
                tags.append((listeners[innermost[0]][0], word, word))
        return tags

    def given(self, db, scope):
        first, last = scope_span(db, scope)
        return list(db.execute(
            "select m.entity_id, m.first_word_id, m.last_word_id from mention m join word_headword h on h.word_id = m.first_word_id "
            "where m.kind_id = 'names' and m.first_word_id = m.last_word_id and h.part_of_speech = 'pronoun' and m.first_word_id between ? and ? "
            "order by m.first_word_id, m.entity_id",
            (first, last),
        ))

    def accepts(self, db, problems, first, last):
        if first != last:
            problems.add("a pronoun mention is one word. Tag each pronoun on its own")
            return False
        text, part = db.execute("select w.text, h.part_of_speech from word w left join word_headword h on h.word_id = w.id where w.id = ?", (first,)).fetchone()
        if part != "pronoun":
            problems.add(f'"{text}" is not a pronoun. Names and titles belong to the names job')
        elif text.casefold() not in TAGGED:
            problems.add(f'"{text}" is not one of the pronouns this job tags. Leave it out')
        else:
            return True
        return False

    def reconcile(self, db, problems, tags):
        pointed = {}
        for entity, first, last in tags:
            other = pointed.setdefault(first, entity)
            if other != entity:
                problems.add(f"{self.render(db, (entity, first, last))['passage']} points to both {other} and {entity}. One pronoun points to one entity")


class About(Mentions):
    name = "about"
    step = 7
    kind = "about"
    instructions = ABOUT_INSTRUCTIONS

    def preamble(self, db, scopes):
        rows = db.execute("select id, name, description from entity where type_id = 'topic' order by name, id").fetchall()
        return "## Topics\n\n" + ("\n".join(f"{id} {name}. {description}" for id, name, description in rows) or "No topics are on the list yet.")

    def given(self, db, scope):
        first, last = scope_span(db, scope)
        return list(db.execute(
            "select entity_id, first_word_id, last_word_id from mention where kind_id = 'about' and first_word_id between ? and ? order by first_word_id, last_word_id, entity_id",
            (first, last),
        ))

    def accepts(self, db, problems, first, last):
        if whole_verses(db, first, last):
            return True
        problems.add('the passage must start where a verse starts and end where a verse ends. Use { "verse": ... } or { "from": ..., "to": ... } without "quote", "starts", or "ends"')
        return False


def pronoun_words(db: sqlite3.Connection, first: int, last: int) -> list[tuple[int, int, str]]:
    """(word id, verse, text) of each word in the span that the dictionary calls a pronoun and the pronouns job tags."""
    rows = db.execute(
        "select w.id, w.verse, w.text from word w join word_headword h on h.word_id = w.id where w.id between ? and ? and h.part_of_speech = 'pronoun' order by w.id",
        (first, last),
    )
    return [row for row in rows if row[2].casefold() in TAGGED]


def whole_verses(db: sqlite3.Connection, first: int, last: int) -> bool:
    """Whether words first through last begin a verse and end a verse."""
    starts = db.execute(
        "select w.position = (select min(position) from word where edition_id = w.edition_id and book_id = w.book_id and chapter = w.chapter and verse = w.verse) from word w where w.id = ?",
        (first,),
    ).fetchone()[0]
    ends = db.execute(
        "select w.position = (select max(position) from word where edition_id = w.edition_id and book_id = w.book_id and chapter = w.chapter and verse = w.verse) from word w where w.id = ?",
        (last,),
    ).fetchone()[0]
    return bool(starts and ends)


LAYERS = [Pronouns(), About()]

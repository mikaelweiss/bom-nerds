"""Speakers: who says or writes each passage, to whom, and in what mode. Speeches nest and run across chapters."""

import json
import sqlite3
from typing import NamedTuple

from ...passages import Rejected, book_name, chapter_numbers, chapter_span, chapter_verses, english_edition, locate, resolve
from ..jobs import Jobs
from ..layer import Layer, Problems, chapter_name, kinds, passage_of, scope_span, split_chapter, where

PEOPLE = ("person", "group")
PREVIEW = 8

INSTRUCTIONS = """
Tag every speech in each chapter: a passage that one speaker says or writes to listeners, in one mode. The modes are listed under Modes.

- The speaker and each listener are person or group entities. An unnamed speaker has an entity of its own, such as the Bible narrator. Pick it from the list, or write an unlisted line for it.
- Narration is a speech: the narrator is the speaker of the story they tell.
- The passage runs from the speech's first word to its last. Leave out the words that introduce it, such as "he spake unto them, saying:".
- Speeches nest. A speech quoted inside another sits inside its passage: Mormon narrates, quoting Alma, who quotes Zenos. Two speeches either share no words, or one sits wholly inside the other.
- When a prophet delivers the Lord's words ("thus saith the Lord"), the Lord is the speaker and the prophet goes in "through".
- "listeners" lists everyone the speech is addressed to. Use [] only when the text addresses no one, as in much narration.

A speech can run across chapters, but it ends at the end of its book.

- A speech that runs on past its chapter ends its passage at the chapter's last word and adds "open": true. The next chapter follows in this prompt, or its start is shown, so you can tell.
- A speech left open in the chapter before runs on into the next chapter. Include it in the next chapter's section too: keep its speaker, through, listeners, mode, and where its passage starts, and move where it ends to its last words in that chapter. Keep "open": true if it runs on past that chapter too. Speeches open from before the first chapter here are listed under "Open speeches".

Answer with one object per speech. In Mosiah 2, where King Benjamin's speech runs on:

{ "speaker": "king-benjamin", "listeners": ["people-of-king-benjamin"], "mode": "spoken",
  "passage": { "from": "Mosiah 2:9", "to": "Mosiah 2:41", "starts": "My brethren" }, "open": true }

In Mosiah 3, continuing it:

{ "speaker": "king-benjamin", "listeners": ["people-of-king-benjamin"], "mode": "spoken",
  "passage": { "from": "Mosiah 2:9", "to": "Mosiah 3:27", "starts": "My brethren" }, "open": true }

With the Lord speaking through a prophet:

{ "speaker": "jesus-christ", "through": "joseph-smith", "listeners": ["members-of-the-church"], "mode": "spoken",
  "passage": { "chapter": "D&C 1" } }
"""


class Speech(NamedTuple):
    speaker: str
    through: str | None
    listeners: tuple[str, ...]
    mode: str
    first: int
    last: int
    open: bool


class Speakers(Layer):
    name = "speakers"
    step = 5
    instructions = INSTRUCTIONS

    ordered = True

    def preamble(self, db, scopes):
        return "## Modes\n\n" + ", ".join(kinds(db, "speech_mode"))

    def extra(self, db, jobs, scope, batch=()):
        sections = []
        before, after = neighbor(db, scope, -1), neighbor(db, scope, 1)
        carried = open_from(db, jobs, before) if before not in batch else []
        if carried:
            lines = "\n".join(json.dumps(self.render(db, speech), ensure_ascii=False) for speech in carried)
            sections.append(f"## Open speeches\n\nThese began before {chapter_name(db, scope)} and run on into it. Continue each one in this chapter's section.\n\n{lines}")
        if after and after not in batch:
            book, chapter = split_chapter(after)
            verses = "\n".join(f"{verse} {text.strip()}" for verse, text in chapter_verses(db, english_edition(db, book), book, chapter)[:PREVIEW])
            sections.append(f"## The start of {chapter_name(db, after)}\n\nRead it to tell whether a speech runs on past this chapter. Tag nothing in it.\n\n{verses}")
        elif not after:
            book, _ = split_chapter(scope)
            sections.append(f"## End of the book\n\n{chapter_name(db, scope)} is the last chapter of {book_name(db, book)}, so every speech ends in it. Leave out \"open\".")
        return "\n\n".join(sections)

    def parse(self, db, scope, answer):
        problems = Problems(db)
        start, end = scope_span(db, scope)
        here = chapter_name(db, scope)
        before, after = neighbor(db, scope, -1), neighbor(db, scope, 1)
        carried = {speech.first: speech for speech in open_from(db, Jobs, before)}
        modes = kinds(db, "speech_mode")
        numbered, continued = [], set()
        for number, item in enumerate(problems.items(answer), 1):
            problems.at(where(number, item))
            if not problems.fields(item, ("speaker", "listeners", "mode", "passage"), ("through", "open")):
                continue
            count = len(problems.messages)
            speaker = problems.entity(item["speaker"], PEOPLE)
            through = problems.entity(item["through"], ("person",)) if "through" in item else None
            if through and through == speaker:
                problems.add('"through" names the prophet who delivers the speaker\'s words, so it cannot be the speaker')
            listeners = listener_ids(problems, item["listeners"])
            mode = problems.kind(item["mode"], modes, "mode")
            is_open = item.get("open") is True
            if "open" in item and not is_open:
                problems.add('"open" takes true. Leave it out when the speech ends in this chapter')
            span = problems.passage(item["passage"])
            if span:
                first, last = span
                if not start <= last <= end:
                    problems.add(f'the passage must end inside {here}. A speech that runs on past it ends at the chapter\'s last word, with "open": true')
                elif first < start:
                    continued.add(first)
                    if first not in carried:
                        problems.add(f"the passage starts before {here}, but no open speech starts there. A speech starts in the chapter that holds its first words. Only the speeches under Open speeches continue here")
                if is_open and after is None:
                    problems.add(f'a speech ends at the end of its book, and {here} is the last chapter of {book_name(db, split_chapter(scope)[0])}, so leave out "open"')
                elif is_open and last != end:
                    problems.add(f"an open speech runs on past {here}, so its passage ends at the chapter's last word")
            if len(problems.messages) == count:
                numbered.append((number, Speech(speaker, through, listeners, mode, *span, is_open)))

        for number, speech in numbered:
            other = carried.get(speech.first)
            if other and speech[:4] != other[:4]:
                problems.at(f"item {number}").add(f"this continues an open speech, so keep its speaker, through, listeners, and mode: {json.dumps(self.render(db, other), ensure_ascii=False)}")
        problems.at("")
        for first, speech in carried.items():
            if first not in continued:
                problems.add(f"this speech is open from before {here}, so continue it: {json.dumps(self.render(db, speech), ensure_ascii=False)}")
        self.check_nesting(db, problems, scope, numbered)
        if after:
            self.check_next(db, problems, after, [s for _, s in numbered if s.open])
        problems.raise_any()
        return [speech for _, speech in numbered]

    def check_nesting(self, db, problems, scope, numbered):
        """Two speeches share no words or one sits inside the other, counting what earlier chapters of the book stored."""
        start, _ = scope_span(db, scope)
        for i, (number, speech) in enumerate(numbered):
            for other_number, other in numbered[i + 1:]:
                if speech == other:
                    continue
                if (speech.first, speech.last) == (other.first, other.last):
                    problems.add(f"items {number} and {other_number} cover exactly the same words. One passage holds one speech")
                elif crosses(speech, other):
                    problems.add(f"items {number} and {other_number} overlap without one sitting inside the other. Speeches share no words, or one sits wholly inside the other")
        for speaker, first, last in stored_before(db, scope):
            for number, speech in numbered:
                if crosses(speech, Speech(speaker, None, (), "", first, last, False)):
                    problems.add(f"item {number} overlaps without nesting the speech by {speaker} stored from an earlier chapter, {json.dumps(passage_of(db, first, last), ensure_ascii=False)}")

    def check_next(self, db, problems, after, opened):
        """A speech may stay open only if the next chapter, when already settled, continued it."""
        settled = Jobs.get(self.name, after).settled()
        if settled is None:
            return
        continued = {resolve(db, item["passage"])[0] for item in settled}
        for speech in opened:
            if speech.first not in continued:
                problems.add(
                    f"{self.name}/{after} is stored without continuing {json.dumps(self.render(db, speech), ensure_ascii=False)}, "
                    f"so it cannot stay open. Close it in this chapter, or change {self.name}/{after} in the same review"
                )

    def render(self, db, tag):
        speech = Speech(*tag)
        item = {"speaker": speech.speaker}
        if speech.through:
            item["through"] = speech.through
        item.update(listeners=list(speech.listeners), mode=speech.mode, passage=passage_of(db, speech.first, speech.last))
        if speech.open:
            item["open"] = True
        return item

    def store(self, db, scope, tags):
        start, _ = scope_span(db, scope)
        for speech in map(Speech._make, tags):
            if speech.first < start:
                if not db.execute("update speech set last_word_id = ? where first_word_id = ? and last_word_id = ?", (speech.last, speech.first, end_before(db, scope))).rowcount:
                    raise Rejected(f"{json.dumps(self.render(db, speech), ensure_ascii=False)} continues a speech the database does not hold. Store {self.name}/{neighbor(db, scope, -1)} first")
                continue
            speech_id = db.execute(
                "insert into speech (speaker_id, through_id, mode_id, first_word_id, last_word_id) values (?, ?, ?, ?, ?)",
                (speech.speaker, speech.through, speech.mode, speech.first, speech.last),
            ).lastrowid
            db.executemany("insert into speech_listener (speech_id, entity_id) values (?, ?)", [(speech_id, listener) for listener in speech.listeners])

    def unstore(self, db, scope, tags):
        """Delete the speeches this chapter started and pull back the ones it continued, refusing while a later chapter continues one it left open."""
        speeches = list(map(Speech._make, tags))
        for speech in filter(lambda speech: speech.open, speeches):
            row = db.execute("select last_word_id from speech where first_word_id = ? and speaker_id = ? and last_word_id > ?", (speech.first, speech.speaker, speech.last)).fetchone()
            if row:
                _, book, chapter, verse = locate(db, row[0])
                later = f"{self.name}/{book}/{chapter}"
                raise Rejected(
                    f"{self.name}/{scope} left open {json.dumps(self.render(db, speech), ensure_ascii=False)}, and {later} continued it. "
                    f"Change {later} in the same review, so it no longer continues it"
                )
        start, _ = scope_span(db, scope)
        for speech in speeches:
            if speech.first < start:
                db.execute("update speech set last_word_id = ? where first_word_id = ? and last_word_id = ?", (end_before(db, scope), speech.first, speech.last))
            else:
                db.execute("delete from speech_listener where speech_id in (select id from speech where first_word_id = ? and last_word_id = ?)", (speech.first, speech.last))
                db.execute("delete from speech where first_word_id = ? and last_word_id = ?", (speech.first, speech.last))

    def shown(self, db, edition, book_id, chapter):
        first, last = chapter_span(db, edition, book_id, chapter)
        book_start, _ = chapter_span(db, edition, book_id, chapter_numbers(db, edition, book_id)[0])
        rows = db.execute(
            "select id, speaker_id, through_id, mode_id, first_word_id, last_word_id from speech "
            "where first_word_id between ? and ? and last_word_id >= ? order by first_word_id, last_word_id desc",
            (book_start, last, first),
        ).fetchall()
        listeners = {}
        for speech_id, entity in db.execute(
            f"select speech_id, entity_id from speech_listener where speech_id in ({','.join('?' * len(rows))}) order by entity_id", [row[0] for row in rows]
        ):
            listeners.setdefault(speech_id, []).append(entity)
        return [self.render(db, Speech(speaker, through, tuple(listeners.get(id, ())), mode, a, b, False)) for id, speaker, through, mode, a, b in rows]


def neighbor(db: sqlite3.Connection, scope: str, step: int) -> str | None:
    """The chapter scope `step` chapters away in the same book, or None past either end of the book."""
    book, chapter = split_chapter(scope)
    numbers = chapter_numbers(db, english_edition(db, book), book)
    at = numbers.index(chapter) + step
    return f"{book}/{numbers[at]}" if 0 <= at < len(numbers) else None


def end_before(db: sqlite3.Connection, scope: str) -> int:
    """The last word of the chapter before this one in its book."""
    return scope_span(db, neighbor(db, scope, -1))[1]


def open_from(db: sqlite3.Connection, jobs, scope: str | None) -> list[Speech]:
    """The speeches a settled chapter left open, as that chapter stored them."""
    settled = jobs.get(Speakers.name, scope).settled() if scope else None
    return [
        Speech(item["speaker"], item.get("through"), tuple(sorted(item["listeners"])), item["mode"], *resolve(db, item["passage"]), True)
        for item in settled or []
        if item.get("open")
    ]


def stored_before(db: sqlite3.Connection, scope: str) -> list[tuple[str, int, int]]:
    """Speeches stored from the book's earlier chapters, each cut off where this chapter begins, as those chapters left them."""
    before = neighbor(db, scope, -1)
    if before is None:
        return []
    book, _ = split_chapter(scope)
    book_start, _ = scope_span(db, f"{book}/{chapter_numbers(db, english_edition(db, book), book)[0]}")
    start, _ = scope_span(db, scope)
    end = end_before(db, scope)
    return [(speaker, first, min(last, end)) for speaker, first, last in db.execute("select speaker_id, first_word_id, last_word_id from speech where first_word_id between ? and ?", (book_start, start - 1))]


def listener_ids(problems: Problems, value) -> tuple[str, ...] | None:
    if not isinstance(value, list):
        problems.add('"listeners" must be a list of entity ids, or [] when the text addresses no one')
        return None
    found = [problems.entity(listener, PEOPLE) for listener in value]
    twice = sorted({listener for listener in found if listener and found.count(listener) > 1})
    if twice:
        problems.add(f"listeners names {', '.join(twice)} more than once")
    return tuple(sorted(found)) if None not in found and not twice else None


def crosses(one: Speech, other: Speech) -> bool:
    """Whether two passages share words without one sitting inside the other."""
    outer, inner = sorted([one, other], key=lambda speech: (speech.first, -speech.last))
    return inner.first <= outer.last < inner.last


LAYERS = [Speakers()]

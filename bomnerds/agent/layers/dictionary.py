"""Dictionary: headwords for the English words the taggers leave unsettled, the meanings of each headword, and the meaning each word carries.

A meanings scope names one headword: en/<text> for English, with each capital written as _ and its lowercase letter so scopes stay
distinct on case-insensitive disks, and <language>/<Strong's number> for Hebrew, Aramaic, and Greek, with -1, -2 when headwords share one.
A word-meanings scope is <edition>/<book>/<chapter>.

Function words and names take no meanings. Most uses of a function word differ only in grammar, which its part of speech already
records, and a name means the entity it names, which mentions record. Splitting either into senses would ask agents for thousands of
choices with no right answer.
"""

import json
import re
import sqlite3
import unicodedata
from collections import Counter, OrderedDict, defaultdict
from itertools import zip_longest

from ...passages import chapter_span, english_edition, load, reference, verse_text
from ...sentences import ENGLISH
from ...taggers import CACHE
from ..layer import Layer, Problems, Reading, chapter_scopes, kinds, numbered, passage_of, split_chapter, verse_number, where
from ..show import show

UNSETTLED = CACHE / "headwords-unsettled.jsonl"
ORIGINAL = ("wlc", "sblgnt")
LANGUAGES = {"en": "English", "hbo": "Hebrew", "arc": "Aramaic", "grc": "Greek"}
WORKS = {"bible": "Bible", "bom": "Book of Mormon", "dc": "Doctrine and Covenants", "pgp": "Pearl of Great Price"}
FUNCTION = ("article", "pronoun", "preposition", "conjunction", "particle")
GLOSS_WORDS = 5
DEFINITION_WORDS = 40
MOST_MEANINGS = 8
ENGLISH_SAMPLE = 40
ORIGINAL_SAMPLE = 30
LISTED = 20
AROUND = 25
# Hebrew cantillation marks and meteg, which split one form into many without changing the word.
CANTILLATION = re.compile("[\u0591-\u05af\u05bd]")
# Macula gives its senses a gloss and no definition, and every meaning a job writes has one, so a missing definition marks Macula's.
# Jobs pick only meanings jobs wrote, so a word pointing at one of Macula's senses always got it from Macula.
WRITTEN = "definition is not null"
MACULA_SENSE = "exists (select 1 from word_meaning wm join meaning m on m.id = wm.meaning_id where wm.word_id = {word} and m.definition is null)"

HEADWORDS = """
Give each word listed under Words to answer its headword and part of speech. spaCy, Stanza, and MorphAdorner disagreed on these words. Their guesses are shown beside each word, and any of them may be wrong, so check every word against its verse. Every other word in the chapter already has a headword.

- The headword is the word's dictionary form: "go" for "went", "child" for "children", "good" for "better" as an adjective, "well" for "better" as an adverb.
- Pronouns take their subject form, keeping singular and plural apart: "me" and "my" are "I", "thee" and "thine" are "thou", "ye" and "your" are "you".
- "These" is "this", and "those" is "that".
- Modals keep their own headword: "should" is "should", not "shall". Their inflections fold in: "shalt" is "shall", "wilt" is "will".
- Old verb endings fold into the verb: "hath" is "have", "saith" is "say", "goeth" is "go", "knowest" is "know". Old spellings stay: "shewed" is "shew", "wo" is "wo".
- A participle working as an adjective or noun is its own headword: "every living creature" is "living", adjective. Working as a verb it folds in: "they were living" is "live", verb.
- "One" standing for a person or thing, as in "one of them", is a pronoun. Counting, as in "one man", it is a numeral.
- Titles such as "Lord", "Father", and "Son" are nouns, not proper nouns. Mentions say who they name.
- Headwords are lowercase, except proper nouns, "I", and "O".
- Pick the part of speech by what the word does in its sentence, from the list under This job.

"""

HEADWORDS_FORMAT = """Write one line per verse under Words to answer: the chapter and verse, then each number with "=", its headword, and its part of speech.

1:21  1=living adjective  2=creature noun"""

MEANINGS = f"""
Write the meanings of one headword: the distinct senses it carries in scripture, such as "bear" the animal and "bear" to carry. A later job picks one of these meanings for every word with this headword, so the list must cover every use shown under Verses and keep the senses easy to tell apart.

- Number the meanings in order, starting where This job says. Put the most common meaning first.
- Each meaning has a gloss of one to {GLOSS_WORDS} words and a definition: one sentence in plain modern English, at most {DEFINITION_WORDS} words. Glosses differ from each other.
- Keep senses broad. Split only where a reader must tell the senses apart to understand a verse. Write at most {MOST_MEANINGS}, and one when the headword has a single sense.
- One list covers every part of speech: "will" as a noun and "will" as a modal verb are two meanings.
- Describe each sense as scripture uses it, including senses that have since changed: "let" meaning to hinder, "prevent" meaning to go before.
- For a Hebrew, Aramaic, or Greek headword, write the glosses and definitions in English. The KJV words matched to it show how its senses were translated.

Answer with one object per meaning:

{{ "number": 1, "gloss": "speak", "definition": "To put thoughts into words, aloud or in writing." }}
"""

WORD_MEANINGS = """
Pick the meaning each word listed under Words to answer carries in its verse, from its headword's meanings. Words whose headword has one meaning already have it, and function words and names take none.

- Words to answer lists each headword's meanings, then numbers the words to answer verse by verse, each with its headword.
- Read the whole verse, and the verses around it when the verse alone does not settle it.
- When no meaning fits exactly, pick the closest.
- Answer every listed word, and no others.
"""

WORD_MEANINGS_FORMAT = """Write one line per verse under Words to answer: the chapter and verse, then each number with "=" and the number of the meaning that fits it.

3:7  1=1  2=3"""


class Headwords(Layer):
    name = "headwords"
    step = 2
    entities = False
    instructions = HEADWORDS
    format = HEADWORDS_FORMAT

    def scopes(self, db):
        """Only chapters holding a word the taggers left unsettled."""
        return list(unsettled(db))

    def preamble(self, db, scopes):
        return "## Parts of speech\n\n" + ", ".join(kinds(db, "part_of_speech"))

    def text_chapters(self, db, scope):
        return []

    def extra(self, db, jobs, scope, batch=()):
        book, chapter = split_chapter(scope)
        edition = english_edition(db, book)
        records = listed(db, scope)
        blocks = []
        for verse, words in self.listing(db, scope).items():
            lines = [f"{reference(db, book, chapter, verse)} {verse_text(db, edition, book, chapter, verse).strip()}"]
            lines += [f"{chapter}:{verse}  {n} {text}  {guesses(records[word])}" for n, (word, text) in enumerate(words, 1)]
            blocks.append("\n".join(lines))
        return "## Words to answer\n\nEach verse, then its words to answer, numbered.\n\n" + "\n\n".join(blocks)

    def listing(self, db, scope) -> dict[int, list[tuple[int, str]]]:
        """Each verse's listed words as (word id, text), in the order the prompt numbers them from 1."""
        return verse_listing(db, list(listed(db, scope)))

    def read(self, db, scope, lines):
        return read_numbered(db, scope, lines, self.listing(db, scope), headword_item)

    def parse(self, db, scope, answer):
        words = listed(db, scope)
        parts = kinds(db, "part_of_speech")
        book, chapter = split_chapter(scope)
        edition = english_edition(db, book)
        problems = Problems(db)
        tags, answered = [], {}
        for number, item in enumerate(problems.items(answer), 1):
            problems.at(where(number, item))
            if not problems.fields(item, ("passage", "headword", "part_of_speech")):
                continue
            word = one_word(problems, item["passage"], edition, book, chapter)
            part = problems.kind(item["part_of_speech"], parts, "part_of_speech")
            headword = headword_text(problems, item["headword"], part)
            if word is not None and word not in words:
                problems.add("this word already has a headword. Answer only the words listed under Words to answer")
            elif word is not None and word in answered:
                problems.add(f"this word is answered twice, also by item {answered[word]}")
            elif word is not None and part and headword:
                answered[word] = number
                tags.append((word, headword, part))
        missing = [word for word in words if word not in answered]
        if missing:
            problems.at("").add("these listed words have no answer: " + ", ".join(json.dumps(passage_of(db, w, w), ensure_ascii=False) for w in missing))
        problems.raise_any()
        return tags

    def render(self, db, tag):
        word, headword, part = tag
        return {"passage": passage_of(db, word, word), "headword": headword, "part_of_speech": part}

    def store(self, db, scope, tags):
        for word, headword, part in tags:
            found = english_headword(db, headword)
            if found is None:
                found = db.execute("insert into headword (language, text) values ('en', ?)", (headword,)).lastrowid
            db.execute("insert into word_headword (word_id, headword_id, part_of_speech) values (?, ?, ?)", (word, found, part))

    def unstore(self, db, scope, tags):
        """Delete each word's headword, and the headword itself once no word or meaning uses it, since only a job creates such a headword."""
        for word, headword, part in tags:
            found = english_headword(db, headword)
            if found is None:
                continue
            db.execute("delete from word_headword where word_id = ? and headword_id = ? and part_of_speech = ?", (word, found, part))
            db.execute(
                "delete from headword where id = ? and not exists (select 1 from word_headword where headword_id = ?) and not exists (select 1 from meaning where headword_id = ?)",
                (found, found, found),
            )

    def shown(self, db, edition, book_id, chapter):
        """Only the headwords this layer settled. Every English word has one, so showing them all would bury the chapter."""
        if edition not in ENGLISH:
            return []
        words = list(listed(db, f"{book_id}/{chapter}"))
        rows = db.execute(
            "select wh.word_id, h.text, wh.part_of_speech from json_each(?) j join word_headword wh on wh.word_id = j.value join headword h on h.id = wh.headword_id order by wh.word_id",
            (json.dumps(words),),
        )
        return [self.render(db, row) for row in rows]


class Meanings(Layer):
    name = "meanings"
    step = 7
    scope = "headword"
    entities = False
    instructions = MEANINGS

    def scopes(self, db):
        """English headwords, then Hebrew, Aramaic, and Greek headwords with a word Macula gives no sense, leaving out function words and names."""
        skipped = meaningless(db)
        english = [
            english_scope(text)
            for id, text in db.execute("select id, text from headword h where language = 'en' and exists (select 1 from word_headword where headword_id = h.id) order by lower(text), text")
            if id not in skipped
        ]
        uncovered = {
            id
            for (id,) in db.execute(
                f"select distinct wh.headword_id from word_headword wh join word w on w.id = wh.word_id where w.edition_id in ({','.join('?' * len(ORIGINAL))}) and not {MACULA_SENSE.format(word='wh.word_id')}",
                ORIGINAL,
            )
        } - skipped
        keys = original_keys(db)[0]
        ordered = db.execute("select id from headword where language <> 'en' order by case language when 'grc' then 1 else 0 end, strongs, text, id")
        return english + [keys[id] for (id,) in ordered if id in uncovered]

    def chapters(self, db, scope):
        return list(db.execute(
            "select w.book_id, w.chapter from word_headword wh join word w on w.id = wh.word_id where wh.headword_id = ? group by w.book_id, w.chapter order by min(w.id)",
            (headword_of(db, scope),),
        ))

    def given(self, db, scope):
        return list(db.execute("select headword_id, number, gloss, definition from meaning where headword_id = ? and definition is null order by number", (headword_of(db, scope),)))

    def text_chapters(self, db, scope):
        return []

    def extra(self, db, jobs, scope, batch=()):
        headword = headword_of(db, scope)
        language, text, strongs, gloss = db.execute("select language, text, strongs, gloss from headword where id = ?", (headword,)).fetchone()
        start = next_number(db, headword)
        everything = occurrences(db, headword, False)
        if language == "en":
            uses = everything
            job = f"Headword: {text}, English. Number the meanings from 1."
        else:
            uses = occurrences(db, headword, True)
            job = f"Headword: {reference_prefix(language, text, strongs)}, {LANGUAGES[language]}. Macula glosses it \"{gloss}\"."
            if start > 1:
                job += (
                    f" Macula gives {len(everything) - len(uses)} of its {len(everything)} words a sense from the list under Already tagged. "
                    f"Write the meanings its other {len(uses)} words carry, numbered from {start}. The later job picks only from the meanings you write, "
                    "so repeat a sense from that list, with your own definition, when one of these words carries it."
                )
            else:
                job += " Number the meanings from 1."
        lines = [job, "", summary(db, uses, language)]
        if language != "en":
            renderings = kjv_renderings(db, [use[0] for use in uses])
            counts = Counter(" ".join(text.lower() for _, text in renderings.get(use[0], [])) or "(no matched word)" for use in uses)
            lines.append("The KJV translates them as: " + listing(counts) + ".")
            picked = sample(uses, ORIGINAL_SAMPLE, lambda use: " ".join(text.lower() for _, text in renderings.get(use[0], [])))
            verses = [original_line(db, use, renderings.get(use[0], [])) for use in picked]
            covered = "KJV translation"
        else:
            picked = sample(uses, ENGLISH_SAMPLE, lambda use: (use[6].lower(), use[7]))
            verses = [english_line(db, use) for use in picked]
            covered = "form and part of speech"
        lines += ["", "## Verses", "", f"{len(picked)} of the {len(uses):,} words: the first with each common {covered}, then the rest spread across every work and book that has one.", ""]
        return "\n".join(lines + verses)

    def parse(self, db, scope, answer):
        headword = headword_of(db, scope)
        start = next_number(db, headword)
        problems = Problems(db)
        items = problems.items(answer)
        glosses = set()
        tags = []
        for index, item in enumerate(items):
            problems.at(f"item {index + 1}")
            if not problems.fields(item, ("number", "gloss", "definition")):
                continue
            before = len(problems.messages)
            number = start + index
            if item["number"] != number or isinstance(item["number"], bool):
                problems.add(f"number must be {number}. Number the meanings {start}, {start + 1}, {start + 2} and so on, in order")
            gloss = words_of(problems, item["gloss"], "gloss", GLOSS_WORDS)
            definition = words_of(problems, item["definition"], "definition", DEFINITION_WORDS)
            if gloss and gloss.casefold() in glosses:
                problems.add(f'gloss "{gloss}" is used twice. Give each meaning its own gloss')
            if gloss:
                glosses.add(gloss.casefold())
            if len(problems.messages) == before:
                tags.append((headword, number, gloss, definition))
        if not items:
            problems.at("").add("write at least one meaning")
        if len(items) > MOST_MEANINGS:
            problems.at("").add(f"this answer has {len(items)} meanings. Write at most {MOST_MEANINGS}, merging senses a reader need not tell apart")
        problems.raise_any()
        return tags

    def render(self, db, tag):
        _, number, gloss, definition = tag
        return {"number": number, "gloss": gloss} | ({"definition": definition} if definition is not None else {})

    def store(self, db, scope, tags):
        db.executemany("insert into meaning (headword_id, number, gloss, definition) values (?, ?, ?, ?)", tags)

    def unstore(self, db, scope, tags):
        """Delete the meanings, and every word's choice of one, which cannot outlive it. Replay stores word meanings again after meanings."""
        for headword, number, _, _ in tags:
            db.execute("delete from word_meaning where meaning_id in (select id from meaning where headword_id = ? and number = ?)", (headword, number))
            db.execute("delete from meaning where headword_id = ? and number = ? and definition is not null", (headword, number))


class WordMeanings(Layer):
    name = "word-meanings"
    step = 7
    scope = "edition chapter"
    entities = False
    instructions = WORD_MEANINGS
    format = WORD_MEANINGS_FORMAT

    def scopes(self, db):
        """Every English chapter, then each Hebrew and Greek chapter with a word Macula gives no sense whose headword takes meanings."""
        english = [f"{english_edition(db, split_chapter(scope)[0])}/{scope}" for scope in chapter_scopes(db)]
        skipped = meaningless(db)
        original = {}
        for edition, book, chapter, headword in db.execute(
            f"select w.edition_id, w.book_id, w.chapter, wh.headword_id from word w join word_headword wh on wh.word_id = w.id "
            f"where w.edition_id in ({','.join('?' * len(ORIGINAL))}) and not {MACULA_SENSE.format(word='w.id')} order by w.id",
            ORIGINAL,
        ):
            if headword not in skipped:
                original.setdefault(f"{edition}/{book}/{chapter}", None)
        return english + list(original)

    def chapters(self, db, scope):
        _, book, chapter = target(scope)
        return [(book, chapter)]

    def label(self, db, scope):
        edition, book, chapter = target(scope)
        return f"{reference(db, book, chapter)} ({edition})"

    def text_chapters(self, db, scope):
        return []

    def fixed(self, db, scope):
        words = needs(db, scope)
        numbers = meaning_numbers(db, set(words.values()))
        return [(word, headword, numbers[headword][0]) for word, headword in words.items() if len(numbers.get(headword, ())) == 1]

    def already_shown(self, db, tags):
        return []

    def chosen(self, db, scope) -> dict[int, int]:
        """Each word that needs a meaning picked, mapped to its headword: its headword has more than one meaning."""
        words = needs(db, scope)
        numbers = meaning_numbers(db, set(words.values()))
        return {word: headword for word, headword in words.items() if len(numbers.get(headword, ())) > 1}

    def listing(self, db, scope) -> dict[int, list[tuple[int, str]]]:
        return verse_listing(db, list(self.chosen(db, scope)))

    def extra(self, db, jobs, scope, batch=()):
        edition, book, chapter = target(scope)
        chosen = self.chosen(db, scope)
        renderings = kjv_renderings(db, list(chosen)) if edition in ORIGINAL else {}
        blocks = []
        for headword in dict.fromkeys(chosen.values()):
            prefix = headword_prefix(db, headword)
            lines = [f"### {prefix}"]
            lines += [f"{number}: {gloss}. {definition}" for number, gloss, definition in db.execute(f"select number, gloss, definition from meaning where headword_id = ? and {WRITTEN} order by number", (headword,))]
            blocks.append("\n".join(lines))
        words = []
        for verse, listed_words in self.listing(db, scope).items():
            parts = []
            for n, (word, text) in enumerate(listed_words, 1):
                matched = renderings.get(word)
                kjv = f" KJV {' '.join(t for _, t in matched)}" if matched else ""
                parts.append(f"{n} {text} ({headword_prefix(db, chosen[word])}{kjv})")
            words.append(f"{chapter}:{verse}  " + "  ".join(parts))
        if not words:
            answer = "Nothing: every word here already has its meaning. Leave this section empty."
        else:
            answer = "\n\n".join(blocks) + "\n\n" + "\n".join(words)
        text = show(db, book, chapter, edition, layers=(), level=2)
        if edition in ORIGINAL:
            first, last = chapter_span(db, edition, book, chapter)
            text += "\n\n" + kjv_verses(db, list(range(first, last + 1)))
        return f"## Words to answer\n\n{answer}\n\n{text}"

    def read(self, db, scope, lines):
        edition, book, chapter = target(scope)
        chosen = self.chosen(db, scope)
        return read_numbered(db, scope, lines, self.listing(db, scope), lambda word, value: {"meaning": value if "." in value else f"{headword_prefix(db, chosen[word])}.{value}"}, chapter=chapter)

    def parse(self, db, scope, answer):
        edition, book, chapter = target(scope)
        words = needs(db, scope)
        numbers = meaning_numbers(db, set(words.values()))
        problems = Problems(db)
        tags, answered = [], {}
        for index, item in enumerate(problems.items(answer), 1):
            problems.at(where(index, item))
            if not problems.fields(item, ("passage", "meaning")):
                continue
            word = one_word(problems, item["passage"], edition, book, chapter)
            if word is None:
                continue
            headword = words.get(word)
            if headword is None:
                problems.add("this word takes no meaning here. Answer only the words listed under Words to answer")
            elif word in answered:
                problems.add(f"this word is answered twice, also by item {answered[word]}")
            elif not numbers.get(headword):
                problems.add("this word's headword has no meanings yet")
            else:
                number = meaning_number(problems, item["meaning"], headword_prefix(db, headword), numbers[headword])
                if number is not None:
                    answered[word] = index
                    tags.append((word, headword, number))
        missing = [word for word, headword in words.items() if len(numbers.get(headword, ())) > 1 and word not in answered]
        if missing:
            problems.at("").add("these listed words have no answer: " + ", ".join(json.dumps(passage_of(db, w, w), ensure_ascii=False) for w in missing))
        problems.raise_any()
        return tags

    def render(self, db, tag):
        word, headword, number = tag
        return {"passage": passage_of(db, word, word), "meaning": f"{headword_prefix(db, headword)}.{number}"}

    def store(self, db, scope, tags):
        db.executemany("insert into word_meaning (word_id, meaning_id) select ?, id from meaning where headword_id = ? and number = ?", tags)

    def unstore(self, db, scope, tags):
        db.executemany("delete from word_meaning where word_id = ? and meaning_id = (select id from meaning where headword_id = ? and number = ?)", tags)

    def shown(self, db, edition, book_id, chapter):
        """Only words whose headword has several meanings, Macula's included. A sole meaning tells a reader nothing the headword does not."""
        first, last = chapter_span(db, edition, book_id, chapter)
        rows = db.execute(
            "select wm.word_id, m.headword_id, m.number from word_meaning wm join meaning m on m.id = wm.meaning_id "
            "where wm.word_id between ? and ? and (select count(*) from meaning o where o.headword_id = m.headword_id) > 1 order by wm.word_id",
            (first, last),
        )
        return [self.render(db, row) for row in rows]


def verse_listing(db: sqlite3.Connection, words: list[int]) -> dict[int, list[tuple[int, str]]]:
    """Words grouped by verse as (word id, text), in reading order, as a prompt numbers them from 1 in each verse."""
    found: dict[int, list[tuple[int, str]]] = {}
    for word, verse, text in db.execute("select w.id, w.verse, w.text from json_each(?) j join word w on w.id = j.value order by w.id", (json.dumps(sorted(words)),)):
        found.setdefault(verse, []).append((word, text))
    return found


def headword_item(word: int, value: str) -> dict:
    headword, _, part = value.rpartition(" ")
    return {"headword": headword.strip(), "part_of_speech": part}


def read_numbered(db: sqlite3.Connection, scope: str, lines: list[str], listing: dict[int, list[tuple[int, str]]], item, chapter: int | None = None) -> Reading:
    """Turn numbered lines into items, one per listed word: its passage and the fields item(word, value) gives."""
    if chapter is None:
        chapter = split_chapter(scope)[1]
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
            problems.add(f"{key} has no numbered words")
            continue
        for numbers, value, unsure in groups:
            for n in numbers:
                if not 1 <= n <= len(words):
                    problems.add(f"{key} has words 1 to {len(words)}, not {n}")
                    continue
                word = words[n - 1][0]
                reading.items.append({"passage": passage_of(db, word, word), **item(word, value)})
                if unsure:
                    reading.flagged.append(f"{key} {n}={value} ({words[n - 1][1]})")
    problems.raise_any()
    return reading


MEMO: OrderedDict = OrderedDict()


def memo(db: sqlite3.Connection, key, compute):
    """compute(), kept per connection and key for the few connections a process holds."""
    wanted = (db, key)
    if wanted not in MEMO:
        MEMO[wanted] = compute()
        while len(MEMO) > 16:
            MEMO.popitem(last=False)
    return MEMO[wanted]


def unsettled(db: sqlite3.Connection) -> dict[str, dict[int, dict]]:
    """The words the headwords script left unsettled, by chapter scope in reading order, as it lists them in its cache."""
    try:
        stamp = UNSETTLED.stat().st_mtime_ns
    except FileNotFoundError:
        return {}
    return memo(db, ("unsettled", str(UNSETTLED), stamp), lambda: read_unsettled(db))


def read_unsettled(db: sqlite3.Connection) -> dict[str, dict[int, dict]]:
    records = {record["word"]: record for record in map(json.loads, UNSETTLED.read_text(encoding="utf-8").splitlines())}
    found = {}
    rows = db.execute(
        f"select w.id, w.book_id, w.chapter, w.text from json_each(?) j join word w on w.id = j.value where w.edition_id in ({','.join('?' * len(ENGLISH))}) order by w.id",
        (json.dumps(list(records)), *ENGLISH),
    )
    for id, book, chapter, text in rows:
        if text == records[id]["text"]:
            found.setdefault(f"{book}/{chapter}", {})[id] = records[id]
    return found


def listed(db: sqlite3.Connection, scope: str) -> dict[int, dict]:
    return unsettled(db).get(scope, {})


def guesses(record: dict) -> str:
    said = []
    for key, name in (("spacy", "spaCy"), ("stanza", "Stanza"), ("morphadorner", "MorphAdorner")):
        guess = record.get(key)
        said.append(f"{name}: {guess[0]}, {guess[1] or 'no part of speech'}" if guess else f"{name}: no guess")
    return ". ".join(said) + "."


def one_word(problems: Problems, passage, edition: str, book: str, chapter: int) -> int | None:
    span = problems.passage(passage, edition)
    if span is None:
        return None
    first, last = span
    if first != last:
        problems.add("the passage must be one word")
        return None
    start, end = chapter_span(problems.db, edition, book, chapter)
    if not start <= first <= end:
        problems.add(f"the word must sit inside {reference(problems.db, book, chapter)}")
        return None
    return first


def headword_text(problems: Problems, text, part: str | None) -> str | None:
    if not isinstance(text, str) or not text or len(text.split()) != 1 or text != text.strip():
        problems.add('headword must be one word, such as "go"')
        return None
    if part == "proper_noun" and not text[0].isupper():
        problems.add(f'a proper noun\'s headword is capitalized, such as "{text[:1].upper()}{text[1:]}"')
        return None
    if part != "proper_noun" and text not in ("I", "O") and text != text.lower():
        problems.add(f'headword "{text}" must be lowercase. Headwords are lowercase, except proper nouns, "I", and "O"')
        return None
    return text


def english_headword(db: sqlite3.Connection, text: str) -> int | None:
    row = db.execute("select id from headword where language = 'en' and text = ?", (text,)).fetchone()
    return row and row[0]


def meaningless(db: sqlite3.Connection) -> set[int]:
    """Headwords that take no meanings: function words and names, judged by what most of their words are."""

    def compute():
        function = ",".join(f"'{part}'" for part in FUNCTION)
        rows = db.execute(
            f"select headword_id, sum(part_of_speech in ({function})), sum(part_of_speech = 'proper_noun'), count(*) from word_headword group by headword_id"
        )
        return {headword for headword, functions, names, total in rows if 2 * functions > total or 2 * names > total}

    return memo(db, "meaningless", compute)


def english_scope(text: str) -> str:
    return "en/" + "".join(f"_{char.lower()}" if char.isupper() else char for char in text)


def original_keys(db: sqlite3.Connection) -> tuple[dict[int, str], dict[str, int]]:
    """Each Hebrew, Aramaic, and Greek headword's scope, and the headword of each scope."""

    def compute():
        groups = defaultdict(list)
        for id, language, strongs in db.execute("select id, language, strongs from headword where language <> 'en' order by language, strongs, text, id"):
            groups[(language, strongs or "none")].append(id)
        scopes = {}
        for (language, number), ids in groups.items():
            for n, id in enumerate(ids, 1):
                scopes[id] = f"{language}/{number}" if len(ids) == 1 else f"{language}/{number}-{n}"
        return scopes, {scope: id for id, scope in scopes.items()}

    return memo(db, "original keys", compute)


def headword_scope(db: sqlite3.Connection, headword: int) -> str:
    language, text = db.execute("select language, text from headword where id = ?", (headword,)).fetchone()
    return english_scope(text) if language == "en" else original_keys(db)[0][headword]


def headword_of(db: sqlite3.Connection, scope: str) -> int:
    language, _, key = scope.partition("/")
    if language == "en":
        found = english_headword(db, re.sub("_(.)", lambda match: match.group(1).upper(), key))
    else:
        found = original_keys(db)[1].get(scope)
    if found is None:
        raise ValueError(f"no headword for scope {scope!r}")
    return found


def reference_prefix(language: str, text: str, strongs: str | None) -> str:
    """What a meaning reference puts before its number: the text alone for English, unique by text, and the text with its Strong's number otherwise."""
    return text if language == "en" or not strongs else f"{text} {strongs}"


def headword_prefix(db: sqlite3.Connection, headword: int) -> str:
    return reference_prefix(*db.execute("select language, text, strongs from headword where id = ?", (headword,)).fetchone())


def next_number(db: sqlite3.Connection, headword: int) -> int:
    """The number a job's first meaning takes: 1, or the one after Macula's last sense."""
    return db.execute("select coalesce(max(number), 0) + 1 from meaning where headword_id = ? and definition is null", (headword,)).fetchone()[0]


def words_of(problems: Problems, value, field: str, most: int) -> str | None:
    if not isinstance(value, str) or not value.strip():
        problems.add(f"{field} must be text")
        return None
    words = value.split()
    if len(words) > most:
        problems.add(f"{field} has {len(words)} words. Keep it to {most}")
        return None
    return " ".join(words)


def occurrences(db: sqlite3.Connection, headword: int, uncovered: bool) -> list[tuple]:
    """Every word with the headword as (id, edition, work, book, chapter, verse, text, part of speech), only those Macula gives no sense when `uncovered`."""
    covered = f"and not {MACULA_SENSE.format(word='w.id')}" if uncovered else ""
    return list(db.execute(
        f"select w.id, w.edition_id, e.work_id, w.book_id, w.chapter, w.verse, w.text, wh.part_of_speech from word_headword wh "
        f"join word w on w.id = wh.word_id join edition e on e.id = w.edition_id where wh.headword_id = ? {covered} order by w.id",
        (headword,),
    ))


def summary(db: sqlite3.Connection, uses: list[tuple], language: str) -> str:
    works = Counter(WORKS[use[2]] for use in uses)
    where = ", ".join(f"{work} {count:,}" for work, count in works.items())
    forms = Counter(CANTILLATION.sub("", use[6]) if language != "en" else use[6].lower() for use in uses)
    parts = Counter(use[7] for use in uses)
    return f"{len(uses):,} words: {where}.\nForms: {listing(forms)}.\nParts of speech: {listing(parts)}."


def listing(counts: Counter) -> str:
    shown = ", ".join(f"{text} {count:,}" for text, count in counts.most_common(LISTED))
    return shown + (f", and {len(counts) - LISTED:,} more" if len(counts) > LISTED else "")


def spread(items: list) -> list:
    """The items reordered so that every prefix is spread evenly across the list."""
    bits = max(len(items) - 1, 0).bit_length()
    return [items[i] for i in sorted(range(len(items)), key=lambda i: int(format(i, f"0{bits}b")[::-1] or "0", 2))]


def interleave(streams) -> list:
    return [item for round in zip_longest(*streams) for item in round if item is not None]


def sample(uses: list[tuple], size: int, cover) -> list[tuple]:
    """Up to `size` uses in reading order: the first of each `cover` value, most common first, then the rest spread across works and books."""
    firsts = {}
    for use in uses:
        firsts.setdefault(cover(use), use)
    counts = Counter(cover(use) for use in uses)
    picked = {firsts[value][0]: firsts[value] for value, _ in counts.most_common(size * 2 // 3)}
    by_work = defaultdict(lambda: defaultdict(list))
    for use in uses:
        by_work[use[2]][use[3]].append(use)
    for use in interleave(interleave(spread(group) for group in spread(list(books.values()))) for books in by_work.values()):
        if len(picked) >= size:
            break
        picked.setdefault(use[0], use)
    return sorted(picked.values())


def marked(db: sqlite3.Connection, words: set[int], edition: str, book: str, chapter: int, verse: int) -> str:
    """The verse as printed with the given words in bold, cut to the words around them when the verse is long."""
    found = load(db, edition, book, chapter).verses[verse]
    places = [i for i, id in enumerate(found.ids) if id in words]
    low, high = 0, len(found.ids)
    if high > 2 * AROUND + 10:
        low, high = max(0, places[0] - AROUND), min(high, places[-1] + AROUND + 1)
    text = "".join(before + (f"**{text}**" if id in words else text) + after for id, (before, text, after) in zip(found.ids[low:high], found.words[low:high]))
    return ("… " if low else "") + " ".join(text.split()) + (" …" if high < len(found.ids) else "")


def kjv_renderings(db: sqlite3.Connection, words: list[int]) -> dict[int, list[tuple[int, str]]]:
    """The KJV words matched to each Hebrew or Greek word, as (id, text) in reading order."""
    found = defaultdict(list)
    rows = db.execute(
        "select j.value, k.id, k.text from json_each(?1) j join word_match m on m.word_id = j.value join word k on k.id = m.other_word_id where k.edition_id = 'kjv' "
        "union all select j.value, k.id, k.text from json_each(?1) j join word_match m on m.other_word_id = j.value join word k on k.id = m.word_id where k.edition_id = 'kjv' "
        "order by 2",
        (json.dumps(words),),
    )
    for word, id, text in rows:
        found[word].append((id, text))
    return found


def english_line(db: sqlite3.Connection, use: tuple) -> str:
    id, edition, _, book, chapter, verse = use[:6]
    return f"{reference(db, book, chapter, verse)}: {marked(db, {id}, edition, book, chapter, verse)}"


def original_line(db: sqlite3.Connection, use: tuple, matched: list[tuple[int, str]]) -> str:
    id, edition, _, book, chapter, verse = use[:6]
    line = f"{reference(db, book, chapter, verse)}: {marked(db, {id}, edition, book, chapter, verse)}"
    if not matched:
        return line + "\n  KJV: no matched word"
    _, kjv_book, kjv_chapter, kjv_verse = db.execute("select edition_id, book_id, chapter, verse from word where id = ?", (matched[0][0],)).fetchone()
    return line + f"\n  KJV {reference(db, kjv_book, kjv_chapter, kjv_verse)}: {marked(db, {i for i, _ in matched}, 'kjv', kjv_book, kjv_chapter, kjv_verse)}"


def kjv_verses(db: sqlite3.Connection, words: list[int]) -> str:
    """The KJV verses holding the words matched to these Hebrew or Greek words, which may be numbered differently."""
    verses = sorted({row for matched in kjv_renderings(db, words).values() for row in db.execute("select book_id, chapter, verse from word where id = ?", (matched[0][0],))})
    lines = [f"{reference(db, book, chapter, verse)} {load(db, 'kjv', book, chapter).verses[verse].text.strip()}" for book, chapter, verse in verses]
    return "# KJV verses matched to this chapter\n\n" + "\n".join(lines) if lines else ""


def target(scope: str) -> tuple[str, str, int]:
    edition, book, chapter = scope.split("/")
    return edition, book, int(chapter)


def needs(db: sqlite3.Connection, scope: str) -> dict[int, int]:
    """Each word in the chapter that takes a meaning, mapped to its headword: every word whose headword takes meanings, unless Macula gave it one."""
    edition, book, chapter = target(scope)
    first, last = chapter_span(db, edition, book, chapter)
    covered = f"and not {MACULA_SENSE.format(word='w.id')}" if edition in ORIGINAL else ""
    skipped = meaningless(db)
    rows = db.execute(f"select w.id, wh.headword_id from word w join word_headword wh on wh.word_id = w.id where w.id between ? and ? {covered} order by w.id", (first, last))
    return {word: headword for word, headword in rows if headword not in skipped}


def meaning_numbers(db: sqlite3.Connection, headwords: set[int]) -> dict[int, list[int]]:
    """The numbers of the meanings jobs wrote for each headword, the only ones a word-meanings job picks from."""
    found = defaultdict(list)
    for headword, number in db.execute(f"select m.headword_id, m.number from json_each(?) j join meaning m on m.headword_id = j.value where m.{WRITTEN} order by m.headword_id, m.number", (json.dumps(sorted(headwords)),)):
        found[headword].append(number)
    return found


def meaning_number(problems: Problems, value, prefix: str, numbers: list[int]) -> int | None:
    """The meaning number a reference such as "say.1" names, checked against the word's own headword."""
    if isinstance(value, str):
        head, dot, number = value.rpartition(".")
        if dot and number.isdigit() and unicodedata.normalize("NFC", head.strip()) == unicodedata.normalize("NFC", prefix) and int(number) in numbers:
            return int(number)
    choices = ", ".join(f'"{prefix}.{n}"' for n in numbers)
    problems.add(f"meaning {json.dumps(value, ensure_ascii=False)} is not one of this word's meanings: {choices}")
    return None


LAYERS = [Headwords(), Meanings(), WordMeanings()]

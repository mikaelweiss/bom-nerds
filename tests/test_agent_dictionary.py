import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bomnerds.agent import jobs
from bomnerds.agent.layers import LAYERS, dictionary
from bomnerds.agent.prompt import job_text
from bomnerds.agent.show import show
from bomnerds.passages import Rejected
from tests.agent_fixtures import database, job_folder

NEPHI = {(1, 1): "I, Nephi, having been born of goodly parents, I make a record.", (1, 2): "Yea, I make a record in the language of my father."}
GENESIS = {(1, 1): "In the beginning God created the heaven and the earth."}
HEBREW = {1: ["בְּ", "רֵאשִׁית", "בָּרָא", "אֱלֹהִים"], 2: ["אֱלֹהִים", "בָּרָא"]}
PARTS = {
    "I": ("I", "pronoun"), "Nephi": ("Nephi", "proper_noun"), "having": ("have", "verb"), "been": ("be", "verb"), "born": ("bear", "verb"),
    "of": ("of", "preposition"), "parents": ("parent", "noun"), "make": ("make", "verb"), "a": ("a", "article"), "record": ("record", "noun"),
    "Yea": ("yea", "interjection"), "in": ("in", "preposition"), "the": ("the", "article"), "language": ("language", "noun"), "my": ("I", "pronoun"),
    "father": ("father", "noun"), "In": ("in", "preposition"), "beginning": ("beginning", "noun"), "God": ("god", "noun"), "created": ("create", "verb"),
    "heaven": ("heaven", "noun"), "and": ("and", "conjunction"), "earth": ("earth", "noun"),
}
ORIGINAL = {"בְּ": ("H9003", "preposition"), "רֵאשִׁית": ("H7225", "noun"), "בָּרָא": ("H1254", "verb"), "אֱלֹהִים": ("H0430", "noun")}


def nephi(verse, quote, **more):
    return {"verse": f"1 Nephi 1:{verse}", "quote": quote, **more}


class DictionaryTest(unittest.TestCase):
    def setUp(self):
        self.db = database([("bom", "1 Nephi", NEPHI), ("bible", "Genesis", GENESIS)])
        self.addCleanup(self.db.close)
        self.add_hebrew()
        self.tag_words()
        self.goodly = self.word("goodly")
        self.unsettled = Path(tempfile.mkstemp(suffix=".jsonl")[1])
        self.unsettled.write_text(json.dumps({"word": self.goodly, "text": "goodly", "spacy": ["goodly", "adjective"], "stanza": ["good", "adjective"], "morphadorner": None}) + "\n")
        self.addCleanup(self.unsettled.unlink)
        patch = mock.patch.object(dictionary, "UNSETTLED", self.unsettled)
        patch.start()
        self.addCleanup(patch.stop)
        folder = job_folder()
        folder.__enter__()
        self.addCleanup(folder.__exit__, None, None, None)
        self.forget()
        self.addCleanup(self.forget)

    def forget(self):
        dictionary.MEMO.clear()
        for layer in LAYERS.values():
            layer.__dict__.pop("_scopes", None)

    def add_hebrew(self):
        self.db.execute("insert into edition_book (edition_id, book_id, position) values ('wlc', 'genesis', 1)")
        for verse, words in HEBREW.items():
            self.db.executemany(
                "insert into word (edition_id, book_id, chapter, verse, position, text, after) values ('wlc', 'genesis', 1, ?, ?, ?, ?)",
                [(verse, n, text, "" if text == "בְּ" or n == len(words) else " ") for n, text in enumerate(words, 1)],
            )
        for text, (strongs, _) in ORIGINAL.items():
            self.db.execute("insert into headword (language, text, strongs) values ('hbo', ?, ?)", (text, strongs))
        for id, text in self.db.execute("select id, text from word where edition_id = 'wlc'").fetchall():
            self.db.execute(
                "insert into word_headword (word_id, headword_id, part_of_speech) select ?, id, ? from headword where language = 'hbo' and text = ?", (id, ORIGINAL[text][1], text)
            )
        elohim = self.headword("hbo", "אֱלֹהִים")
        sense = self.db.execute("insert into meaning (headword_id, number, gloss) values (?, 1, 'God')", (elohim,)).lastrowid
        first = self.db.execute("select min(id) from word where edition_id = 'wlc' and text = 'אֱלֹהִים'").fetchone()[0]
        self.db.execute("insert into word_meaning (word_id, meaning_id) values (?, ?)", (first, sense))
        created = self.db.execute("select id from word where edition_id = 'kjv' and text = 'created'").fetchone()[0]
        bara = self.db.execute("select min(id) from word where edition_id = 'wlc' and text = 'בָּרָא'").fetchone()[0]
        self.db.execute("insert into word_match (word_id, other_word_id) values (?, ?)", (created, bara))

    def tag_words(self):
        for id, text in self.db.execute("select id, text from word where edition_id <> 'wlc'").fetchall():
            if text == "goodly":
                continue
            headword, part = PARTS[text]
            found = dictionary.english_headword(self.db, headword) or self.db.execute("insert into headword (language, text) values ('en', ?)", (headword,)).lastrowid
            self.db.execute("insert into word_headword (word_id, headword_id, part_of_speech) values (?, ?, ?)", (id, found, part))

    def word(self, text, edition="bom-2013"):
        return self.db.execute("select id from word where text = ? and edition_id = ?", (text, edition)).fetchone()[0]

    def headword(self, language, text):
        return self.db.execute("select id from headword where language = ? and text = ?", (language, text)).fetchone()[0]

    def rows(self):
        return [list(self.db.execute(f"select * from {table} order by 1, 2")) for table in ("headword", "word_headword", "meaning", "word_meaning")]

    def settle(self, layer, scope, answer):
        job = jobs.Job(LAYERS[layer], scope)
        jobs.submit(self.db, job, answer)
        return job

    def settle_headwords(self):
        self.settle("headwords", "1-nephi/1", [{"passage": nephi(1, "goodly"), "headword": "goodly", "part_of_speech": "adjective"}])
        self.forget()

    def write_meanings(self):
        """Settle the headwords job, then every meanings job: "record" and "make" get two meanings, the rest one."""
        self.settle_headwords()
        for scope in LAYERS["meanings"].scopes(self.db):
            senses = {"en/record": ["account", "writing"], "en/make": ["create", "cause"]}.get(scope, ["sole sense"])
            start = dictionary.next_number(self.db, dictionary.headword_of(self.db, scope))
            self.settle("meanings", scope, [{"number": start + i, "gloss": g, "definition": f"The {g} sense."} for i, g in enumerate(senses)])


class HeadwordsTest(DictionaryTest):
    def answer(self, **change):
        return [{"passage": nephi(1, "goodly"), "headword": "goodly", "part_of_speech": "adjective", **change}]

    def test_jobs_exist_only_for_chapters_with_unsettled_words(self):
        self.assertEqual(LAYERS["headwords"].scopes(self.db), ["1-nephi/1"])

    def test_an_answer_round_trips_through_render(self):
        layer = LAYERS["headwords"]
        tags = layer.parse(self.db, "1-nephi/1", self.answer())
        self.assertEqual(tags, [(self.goodly, "goodly", "adjective")])
        self.assertEqual(layer.parse(self.db, "1-nephi/1", [layer.render(self.db, t) for t in tags]), tags)

    def test_store_creates_the_headword_and_unstore_removes_it(self):
        before = self.rows()
        layer = LAYERS["headwords"]
        tags = layer.parse(self.db, "1-nephi/1", self.answer())
        layer.store(self.db, "1-nephi/1", tags)
        self.assertEqual(self.db.execute("select h.text from word_headword wh join headword h on h.id = wh.headword_id where wh.word_id = ?", (self.goodly,)).fetchone(), ("goodly",))
        layer.unstore(self.db, "1-nephi/1", tags)
        self.assertEqual(self.rows(), before)

    def test_store_reuses_an_existing_headword(self):
        layer = LAYERS["headwords"]
        layer.store(self.db, "1-nephi/1", layer.parse(self.db, "1-nephi/1", self.answer(headword="record", part_of_speech="noun")))
        self.assertEqual(self.db.execute("select count(*) from headword where text = 'record'").fetchone(), (1,))

    def test_rejects_every_problem_the_spec_names(self):
        check = lambda answer: jobs.check(self.db, jobs.Job(LAYERS["headwords"], "1-nephi/1"), answer)
        with self.assertRaisesRegex(Rejected, "already has a headword"):
            check(self.answer() + [{"passage": nephi(1, "parents"), "headword": "parent", "part_of_speech": "noun"}])
        with self.assertRaisesRegex(Rejected, "no answer"):
            check([])
        with self.assertRaisesRegex(Rejected, "not one of"):
            check(self.answer(part_of_speech="determiner"))
        with self.assertRaisesRegex(Rejected, "lowercase"):
            check(self.answer(headword="Goodly"))
        with self.assertRaisesRegex(Rejected, "capitalized"):
            check(self.answer(headword="goodly", part_of_speech="proper_noun"))
        with self.assertRaisesRegex(Rejected, "one word"):
            check(self.answer(passage=nephi(1, "goodly parents")))
        with self.assertRaisesRegex(Rejected, "answered twice"):
            check(self.answer() + self.answer(headword="good"))

    def test_show_prints_only_the_words_it_settled(self):
        self.settle("headwords", "1-nephi/1", self.answer())
        shown = show(self.db, "1-nephi", 1, layers=("headwords",)).split("## headwords")[1]
        self.assertEqual(shown.strip().splitlines(), [json.dumps(self.answer()[0], ensure_ascii=False)])

    def test_the_prompt_numbers_each_word_with_its_verse_and_the_taggers_guesses(self):
        text = job_text(self.db, jobs.Job(LAYERS["headwords"], "1-nephi/1"))
        self.assertIn("1 Nephi 1:1 I, Nephi, having been born of goodly parents, I make a record.\n1:1  1 goodly  spaCy: goodly, adjective. Stanza: good, adjective. MorphAdorner: no guess.", text)

    def test_numbered_lines_read_as_headwords(self):
        reading = LAYERS["headwords"].read(self.db, "1-nephi/1", ["1:1  1=goodly adjective?"])
        self.assertEqual(reading.items, self.answer())
        self.assertEqual(reading.flagged, ["1:1 1=goodly adjective (goodly)"])


class MeaningsTest(DictionaryTest):
    def meanings(self, *glosses, start=1):
        return [{"number": start + i, "gloss": gloss, "definition": f"The {gloss} sense."} for i, gloss in enumerate(glosses)]

    def test_jobs_leave_out_function_words_names_and_headwords_macula_covers(self):
        scopes = LAYERS["meanings"].scopes(self.db)
        self.assertIn("en/record", scopes)
        self.assertIn("hbo/H1254", scopes)
        self.assertIn("hbo/H0430", scopes)
        for skipped in ("en/the", "en/of", "en/_i", "en/_nephi", "hbo/H9003"):
            self.assertNotIn(skipped, scopes)

    def test_scopes_keep_capitals_apart_and_name_headwords_sharing_a_strongs_number(self):
        self.assertEqual(dictionary.english_scope("Babylon"), "en/_babylon")
        self.db.execute("insert into headword (language, text) values ('en', 'Babylon')")
        self.assertEqual(dictionary.headword_of(self.db, "en/_babylon"), self.headword("en", "Babylon"))
        self.db.execute("insert into headword (language, text, strongs) values ('hbo', 'בָּרָא2', 'H1254')")
        self.forget()
        self.assertEqual(dictionary.headword_scope(self.db, self.headword("hbo", "בָּרָא")), "hbo/H1254-1")

    def test_an_answer_round_trips_through_render(self):
        layer = LAYERS["meanings"]
        tags = layer.parse(self.db, "en/record", self.meanings("account", "writing"))
        self.assertEqual([t[1:3] for t in tags], [(1, "account"), (2, "writing")])
        self.assertEqual(layer.parse(self.db, "en/record", [layer.render(self.db, t) for t in tags]), tags)

    def test_numbers_follow_maculas_senses(self):
        layer = LAYERS["meanings"]
        self.assertEqual([layer.render(self.db, t) for t in layer.given(self.db, "hbo/H0430")], [{"number": 1, "gloss": "God"}])
        with self.assertRaisesRegex(Rejected, "number must be 2"):
            layer.parse(self.db, "hbo/H0430", self.meanings("God"))
        self.assertEqual(len(layer.parse(self.db, "hbo/H0430", self.meanings("God", start=2))), 1)

    def test_rejects_bad_lists(self):
        parse = lambda answer: LAYERS["meanings"].parse(self.db, "en/record", answer)
        with self.assertRaisesRegex(Rejected, "at least one"):
            parse([])
        with self.assertRaisesRegex(Rejected, "number must be 2"):
            parse(self.meanings("account") + self.meanings("writing", start=3))
        with self.assertRaisesRegex(Rejected, "used twice"):
            parse(self.meanings("account", "Account"))
        with self.assertRaisesRegex(Rejected, "Keep it to 5"):
            parse(self.meanings("an account of what happened to us"))
        with self.assertRaisesRegex(Rejected, "at most 8"):
            parse(self.meanings(*[f"sense {n}" for n in range(9)]))

    def test_check_mode_stores_the_checkers_list_and_unstore_takes_word_meanings_with_it(self):
        job = jobs.Job(LAYERS["meanings"], "en/record")
        jobs.submit(self.db, job, self.meanings("account", "writing"))
        self.assertEqual(list(self.db.execute("select number, gloss from meaning where headword_id = ?", (self.headword("en", "record"),))), [(1, "account"), (2, "writing")])
        before = self.rows()
        self.db.execute("insert into word_meaning (word_id, meaning_id) select ?, id from meaning where gloss = 'writing'", (self.word("record"),))
        jobs.reset(self.db, job)
        self.assertEqual(self.rows()[3], before[3])
        self.assertEqual(list(self.db.execute("select count(*) from meaning where headword_id = ?", (self.headword("en", "record"),))), [(0,)])

    def test_context_counts_every_word_and_shows_how_the_kjv_translates_it(self):
        english = job_text(self.db, jobs.Job(LAYERS["meanings"], "en/record"))
        self.assertIn("2 words: Book of Mormon 2.", english)
        self.assertIn("I make a **record**.", english)
        hebrew = job_text(self.db, jobs.Job(LAYERS["meanings"], "hbo/H1254"))
        self.assertIn("The KJV translates them as: created 1, (no matched word) 1.", hebrew)
        self.assertIn("KJV Genesis 1:1: In the beginning God **created** the heaven and the earth.", hebrew)


class WordMeaningsTest(DictionaryTest):
    def test_jobs_cover_english_chapters_and_original_chapters_with_uncovered_words(self):
        self.assertEqual(LAYERS["word-meanings"].scopes(self.db), ["bom-2013/1-nephi/1", "kjv/genesis/1", "wlc/genesis/1"])

    def test_fixed_gives_sole_meanings_and_the_agents_answer_the_rest(self):
        self.write_meanings()
        layer = LAYERS["word-meanings"]
        fixed = {layer.render(self.db, t)["meaning"] for t in layer.fixed(self.db, "kjv/genesis/1")}
        self.assertEqual(fixed, {"beginning.1", "god.1", "create.1", "heaven.1", "earth.1"})
        self.assertNotIn("the.1", fixed)
        scope = "bom-2013/1-nephi/1"
        answer = [{"passage": nephi(1, "record"), "meaning": "record.1"}, {"passage": nephi(2, "record"), "meaning": "record.2"}]
        answer += [{"passage": nephi(1, "make"), "meaning": "make.1"}, {"passage": nephi(2, "make"), "meaning": "make.1"}]
        tags = layer.parse(self.db, scope, answer)
        self.assertEqual(layer.parse(self.db, scope, [layer.render(self.db, t) for t in tags]), tags)
        with self.assertRaisesRegex(Rejected, "no answer"):
            layer.parse(self.db, scope, answer[1:])
        with self.assertRaisesRegex(Rejected, 'not one of this word\'s meanings: "record.1", "record.2"'):
            layer.parse(self.db, scope, [{"passage": nephi(1, "record"), "meaning": "record.3"}] + answer[1:])
        with self.assertRaisesRegex(Rejected, "takes no meaning"):
            layer.parse(self.db, scope, answer + [{"passage": nephi(2, "the"), "meaning": "the.1"}])

    def test_hebrew_references_carry_the_strongs_number_and_skip_words_macula_covers(self):
        self.write_meanings()
        layer = LAYERS["word-meanings"]
        self.assertEqual(
            [layer.render(self.db, t)["meaning"] for t in layer.fixed(self.db, "wlc/genesis/1")],
            ["רֵאשִׁית H7225.1", "בָּרָא H1254.1", "אֱלֹהִים H0430.2", "בָּרָא H1254.1"],
        )
        covered = {"passage": {"verse": "Genesis 1:1", "quote": "אֱלֹהִים"}, "meaning": "אֱלֹהִים H0430.2"}
        with self.assertRaisesRegex(Rejected, "takes no meaning"):
            layer.parse(self.db, "wlc/genesis/1", [covered])

    def test_runs_that_agree_store_and_reset_restores_the_tables(self):
        self.write_meanings()
        before = self.rows()
        answer = [{"passage": nephi(v, w), "meaning": f"{w}.1"} for v in (1, 2) for w in ("record", "make")]
        job = self.settle("word-meanings", "bom-2013/1-nephi/1", answer)
        self.assertIsNotNone(job.settled())
        shown = show(self.db, "1-nephi", 1, layers=("word-meanings",)).split("## word-meanings")[1].strip().splitlines()
        self.assertEqual(sorted(json.loads(line)["meaning"] for line in shown), ["make.1", "make.1", "record.1", "record.1"])
        jobs.reset(self.db, job)
        self.assertEqual(self.rows(), before)

    def test_the_prompt_groups_words_under_their_headwords_meanings(self):
        self.write_meanings()
        text = job_text(self.db, jobs.Job(LAYERS["word-meanings"], "bom-2013/1-nephi/1"))
        words = text.split("## Words to answer")[1]
        self.assertIn("### record\n1: account. The account sense.\n2: writing. The writing sense.", words)
        self.assertIn("1:1  1 make (make)  2 record (record)", words)

    def test_numbered_lines_read_as_meanings(self):
        self.write_meanings()
        reading = LAYERS["word-meanings"].read(self.db, "bom-2013/1-nephi/1", ["1:1  1=1  2=record.2"])
        self.assertEqual([item["meaning"] for item in reading.items], ["make.1", "record.2"])


if __name__ == "__main__":
    unittest.main()

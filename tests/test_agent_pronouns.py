import unittest

from bomnerds.agent import jobs
from bomnerds.agent.prompt import job_text
from bomnerds.agent.layers import LAYERS
from bomnerds.agent.layers.pronouns import TAGGED
from bomnerds.passages import Rejected
from tests.agent_fixtures import database, entity, job_folder

CHAPTER = {
    (3, 1): "And I, Nephi, said unto my father: I will go, for thou hast asked.",
    (3, 2): "And the Lord said unto me: I am with thee, and thy seed shall be blessed. He is mighty, and it is good.",
    (3, 3): "And Laban said unto Lehi and Nephi: Thou shalt not go, for that thou art wicked.",
    (3, 4): "And I went down.",
    (3, 5): "And I slept.",
    (4, 1): "He went up.",
}
SCOPE = "1-nephi/3"


def mention(entity_id, verse, quote, within=None):
    passage = {"verse": f"1 Nephi 3:{verse}", "quote": quote}
    if within:
        passage["in"] = within
    return {"entity": entity_id, "passage": passage}


class PronounTest(unittest.TestCase):
    def setUp(self):
        self.db = database([("bom", "1 Nephi", CHAPTER)])
        self.addCleanup(self.db.close)
        for id, type_id in (("nephi", "person"), ("lehi", "person"), ("laban", "person"), ("jesus-christ", "person"), ("readers", "group")):
            entity(self.db, id, type_id, id, books=("1-nephi",))
        for (text,) in self.db.execute("select distinct lower(text) from word").fetchall():
            part = "pronoun" if text in TAGGED | {"that", "which"} else "noun"
            headword = self.db.execute("insert into headword (language, text) values ('en', ?)", (text,)).lastrowid
            self.db.execute(
                "insert into word_headword (word_id, headword_id, part_of_speech) select id, ?, ? from word where lower(text) = ?", (headword, part, text)
            )
        self.speak("nephi", ["readers"], "narration", self.word("And", 0), self.word("down", 0))
        self.speak("nephi", ["lehi"], "spoken", self.word("I", 1), self.word("asked", 0))
        self.speak("jesus-christ", ["nephi"], "spoken", self.word("I", 2), self.word("blessed", 0))
        self.speak("laban", ["lehi", "nephi"], "spoken", self.word("Thou", 0), self.word("wicked", 0))
        self.folder = job_folder()
        self.folder.__enter__()
        self.addCleanup(self.folder.__exit__, None, None, None)
        self.layer = LAYERS["pronouns"]
        self.job = jobs.Job(self.layer, SCOPE)

    def word(self, text, nth):
        return self.db.execute("select id from word where text = ? order by id limit 1 offset ?", (text, nth)).fetchone()[0]

    def speak(self, speaker, listeners, mode, first, last):
        speech = self.db.execute("insert into speech (speaker_id, mode_id, first_word_id, last_word_id) values (?, ?, ?, ?)", (speaker, mode, first, last)).lastrowid
        self.db.executemany("insert into speech_listener (speech_id, entity_id) values (?, ?)", [(speech, listener) for listener in listeners])

    def settle_earlier(self, below, besides=()):
        for layer in LAYERS.values():
            if layer.step < below and layer.scope == "chapter" and layer.name not in besides:
                jobs.Job(layer, SCOPE).write("settled", [])

    def mentions(self):
        return self.db.execute("select * from mention order by id").fetchall()

    def fixed_words(self):
        return {(entity, self.db.execute("select text from word where id = ?", (word,)).fetchone()[0], word) for entity, word, _ in self.layer.fixed(self.db, SCOPE)}

    def test_a_valid_answer_round_trips(self):
        answer = [mention("jesus-christ", 2, "He"), mention("jesus-christ", 2, "it"), mention("lehi", 1, "thou")]
        tags = self.layer.parse(self.db, SCOPE, answer)
        self.assertEqual(len(tags), 3)
        self.assertEqual([self.layer.render(self.db, t) for t in tags], answer)
        self.assertEqual(self.layer.parse(self.db, SCOPE, [self.layer.render(self.db, t) for t in tags]), tags)

    def test_i_me_my_mine_point_to_the_speaker_of_the_innermost_speech(self):
        found = {(entity, text) for entity, text, _ in self.fixed_words()}
        self.assertIn(("nephi", "my"), found)
        self.assertIn(("nephi", "me"), found)
        self.assertIn(("jesus-christ", "I"), found)
        self.assertEqual(sorted(e for e, t, _ in self.fixed_words() if t == "I"), ["jesus-christ", "nephi", "nephi", "nephi"])

    def test_thou_thee_thy_point_to_a_single_listener(self):
        found = {(entity, text) for entity, text, _ in self.fixed_words()}
        self.assertIn(("lehi", "thou"), found)
        self.assertIn(("nephi", "thee"), found)
        self.assertIn(("nephi", "thy"), found)

    def test_thou_in_a_speech_with_several_listeners_is_left_to_the_agents(self):
        words = {word for _, word, _ in self.layer.fixed(self.db, SCOPE)}
        self.assertNotIn(self.word("Thou", 0), words)
        self.assertNotIn(self.word("thou", 1), words)

    def test_words_outside_every_speech_and_other_pronouns_are_left_to_the_agents(self):
        words = {word for _, word, _ in self.layer.fixed(self.db, SCOPE)}
        self.assertNotIn(self.word("I", 4), words)
        self.assertNotIn(self.word("He", 0), words)
        self.assertNotIn(self.word("it", 0), words)

    def test_fixed_skips_a_pronoun_that_already_has_a_mention(self):
        my = self.word("my", 0)
        self.db.execute("insert into mention (entity_id, kind_id, first_word_id, last_word_id) values ('lehi', 'names', ?, ?)", (my, my))
        self.assertNotIn(my, {word for _, word, _ in self.layer.fixed(self.db, SCOPE)})
        self.assertEqual(self.layer.given(self.db, SCOPE), [("lehi", my, my)])

    def test_given_holds_pronoun_mentions_and_not_names(self):
        nephi = self.word("Nephi", 0)
        self.db.execute("insert into mention (entity_id, kind_id, first_word_id, last_word_id) values ('nephi', 'names', ?, ?)", (nephi, nephi))
        self.assertEqual(self.layer.given(self.db, SCOPE), [])

    def test_rejects_what_is_not_a_pronoun(self):
        with self.assertRaisesRegex(Rejected, '"Nephi" is not a pronoun'):
            self.layer.parse(self.db, SCOPE, [mention("nephi", 1, "Nephi")])

    def test_rejects_a_pronoun_the_job_does_not_tag(self):
        with self.assertRaisesRegex(Rejected, '"that" is not one of the pronouns'):
            self.layer.parse(self.db, SCOPE, [mention("nephi", 3, "that")])

    def test_rejects_more_than_one_word(self):
        with self.assertRaisesRegex(Rejected, "one word"):
            self.layer.parse(self.db, SCOPE, [mention("nephi", 1, "I will go")])

    def test_rejects_a_passage_outside_the_chapter(self):
        with self.assertRaisesRegex(Rejected, "must sit inside"):
            self.layer.parse(self.db, SCOPE, [{"entity": "nephi", "passage": {"verse": "1 Nephi 4:1", "quote": "He"}}])

    def test_rejects_an_entity_not_on_the_list(self):
        with self.assertRaisesRegex(Rejected, "not on the entity list"):
            self.layer.parse(self.db, SCOPE, [mention("enos", 2, "He")])

    def test_rejects_a_quote_that_needs_in(self):
        with self.assertRaisesRegex(Rejected, "twice"):
            self.layer.parse(self.db, SCOPE, [mention("lehi", 1, "I")])

    def test_collects_every_problem(self):
        with self.assertRaises(Rejected) as caught:
            self.layer.parse(self.db, SCOPE, [mention("nephi", 1, "Nephi"), mention("enos", 2, "He")])
        self.assertIn("item 1", str(caught.exception))
        self.assertIn("item 2", str(caught.exception))

    def test_rejects_one_pronoun_pointing_to_two_entities(self):
        with self.assertRaisesRegex(Rejected, "points to both"):
            self.layer.parse(self.db, SCOPE, [mention("laban", 2, "He"), mention("lehi", 2, "He")])

    def test_check_rejects_the_same_fact_twice(self):
        self.settle_earlier(self.layer.step)
        with self.assertRaisesRegex(Rejected, "twice"):
            jobs.check(self.db, self.job, [mention("laban", 2, "He"), mention("laban", 2, "He")])

    def test_check_rejects_a_pronoun_the_script_settled(self):
        self.settle_earlier(self.layer.step)
        with self.assertRaisesRegex(Rejected, "already tagged"):
            jobs.check(self.db, self.job, [mention("nephi", 1, "my")])

    def test_check_rejects_a_pronoun_already_in_the_database(self):
        self.settle_earlier(self.layer.step)
        he = self.word("He", 0)
        self.db.execute("insert into mention (entity_id, kind_id, first_word_id, last_word_id) values ('jesus-christ', 'names', ?, ?)", (he, he))
        with self.assertRaisesRegex(Rejected, "already tagged"):
            jobs.check(self.db, self.job, [mention("jesus-christ", 2, "He")])

    def test_store_then_unstore_leaves_the_table_as_it_was(self):
        before = self.mentions()
        tags = self.layer.fixed(self.db, SCOPE) + self.layer.parse(self.db, SCOPE, [mention("jesus-christ", 2, "He")])
        with self.db:
            self.layer.store(self.db, SCOPE, tags)
        self.assertEqual(len(self.mentions()), len(tags))
        self.assertTrue(all(row[2] == "names" for row in self.mentions()))
        with self.db:
            self.layer.unstore(self.db, SCOPE, tags)
            self.layer.unstore(self.db, SCOPE, tags)
        self.assertEqual(self.mentions(), before)

    def test_two_agreeing_runs_store_the_script_tags_and_the_answers(self):
        self.settle_earlier(self.layer.step)
        answer = [mention("jesus-christ", 2, "He")]
        jobs.submit(self.db, self.job, answer)
        self.assertIsNotNone(self.job.settled())
        stored = {(entity, first) for entity, _, first in self.db.execute("select entity_id, kind_id, first_word_id from mention")}
        self.assertIn(("jesus-christ", self.word("He", 0)), stored)
        self.assertIn(("nephi", self.word("my", 0)), stored)
        self.assertEqual(len(stored), len(self.job.settled()))

    def test_reset_deletes_the_script_tags_and_the_answers(self):
        self.settle_earlier(self.layer.step)
        jobs.submit(self.db, self.job, [])
        self.assertTrue(self.mentions())
        jobs.reset(self.db, self.job)
        self.assertEqual(self.mentions(), [])

    def test_a_settled_job_replays(self):
        self.settle_earlier(self.layer.step)
        jobs.submit(self.db, self.job, [mention("jesus-christ", 2, "He")])
        rows = "select entity_id, kind_id, first_word_id, last_word_id from mention order by first_word_id, entity_id"
        before = self.db.execute(rows).fetchall()
        self.db.execute("delete from mention")
        jobs.replay(self.db, [self.layer])
        self.assertEqual(self.db.execute(rows).fetchall(), before)

    def test_context_numbers_the_pronouns_still_untagged(self):
        listed = job_text(self.db, jobs.Job(self.layer, SCOPE)).split("## Pronouns")[1].split("## Already stored")[0]
        self.assertIn("3:2  1 He  2 it", listed)
        self.assertIn("3:3  1 Thou  2 thou", listed)
        self.assertNotIn("3:1 ", listed)
        self.assertNotIn("that", listed)

    def test_numbered_lines_read_as_mentions_and_flags(self):
        reading = self.layer.read(self.db, SCOPE, ["3:2  1=jesus-christ  2=-", "3:3  1-2=lehi?"])
        self.assertEqual([item["entity"] for item in reading.items], ["jesus-christ", "lehi", "lehi"])
        self.assertEqual(len(reading.skipped), 1)
        self.assertEqual(reading.flagged, ["3:3 1=lehi (Thou)", "3:3 2=lehi (thou)"])
        self.assertEqual(self.layer.complete(self.db, SCOPE, reading), ['these pronouns have no answer. Answer each with its entity, or "-": 3:5 1'])

    def test_numbered_lines_name_only_listed_pronouns(self):
        with self.assertRaisesRegex(Rejected, "has pronouns 1 to 2, not 3"):
            self.layer.read(self.db, SCOPE, ["3:2  3=nephi"])
        with self.assertRaisesRegex(Rejected, "no numbered pronouns"):
            self.layer.read(self.db, SCOPE, ["3:1  1=nephi"])


class AboutTest(unittest.TestCase):
    def setUp(self):
        self.db = database([("bom", "1 Nephi", CHAPTER)])
        self.addCleanup(self.db.close)
        entity(self.db, "faith", "topic", "Faith")
        entity(self.db, "obedience", "topic", "Obedience")
        self.folder = job_folder()
        self.folder.__enter__()
        self.addCleanup(self.folder.__exit__, None, None, None)
        self.layer = LAYERS["about"]
        self.job = jobs.Job(self.layer, SCOPE)

    def test_a_valid_answer_round_trips(self):
        answer = [
            {"entity": "faith", "passage": {"verse": "1 Nephi 3:1"}},
            {"entity": "faith", "passage": {"from": "1 Nephi 3:2", "to": "1 Nephi 3:3"}},
            {"entity": "obedience", "passage": {"verse": "1 Nephi 3:1"}},
        ]
        tags = self.layer.parse(self.db, SCOPE, answer)
        self.assertEqual([self.layer.render(self.db, t) for t in tags], answer)

    def test_a_whole_chapter_is_whole_verses(self):
        tags = self.layer.parse(self.db, SCOPE, [{"entity": "faith", "passage": {"chapter": "1 Nephi 3"}}])
        self.assertEqual(self.layer.render(self.db, tags[0]), {"entity": "faith", "passage": {"chapter": "1 Nephi 3"}})

    def test_rejects_part_of_a_verse(self):
        with self.assertRaisesRegex(Rejected, "start where a verse starts"):
            self.layer.parse(self.db, SCOPE, [{"entity": "faith", "passage": {"verse": "1 Nephi 3:1", "quote": "I will go"}}])
        with self.assertRaisesRegex(Rejected, "start where a verse starts"):
            self.layer.parse(self.db, SCOPE, [{"entity": "faith", "passage": {"from": "1 Nephi 3:1", "to": "1 Nephi 3:2", "starts": "I will go"}}])

    def test_rejects_a_passage_outside_the_chapter(self):
        with self.assertRaisesRegex(Rejected, "must sit inside"):
            self.layer.parse(self.db, SCOPE, [{"entity": "faith", "passage": {"verse": "1 Nephi 4:1"}}])

    def test_rejects_an_entity_not_on_the_list(self):
        with self.assertRaisesRegex(Rejected, "not on the entity list"):
            self.layer.parse(self.db, SCOPE, [{"entity": "hope", "passage": {"verse": "1 Nephi 3:1"}}])

    def test_check_rejects_the_same_fact_twice(self):
        self.settle_earlier()
        item = {"entity": "faith", "passage": {"verse": "1 Nephi 3:1"}}
        with self.assertRaisesRegex(Rejected, "twice"):
            jobs.check(self.db, self.job, [item, item])

    def test_check_rejects_what_is_already_tagged(self):
        self.settle_earlier()
        first, last = self.db.execute("select min(id), max(id) from word where verse = 1 and chapter = 3").fetchone()
        self.db.execute("insert into mention (entity_id, kind_id, first_word_id, last_word_id) values ('faith', 'about', ?, ?)", (first, last))
        self.assertEqual(self.layer.given(self.db, SCOPE), [("faith", first, last)])
        with self.assertRaisesRegex(Rejected, "already tagged"):
            jobs.check(self.db, self.job, [{"entity": "faith", "passage": {"verse": "1 Nephi 3:1"}}])

    def test_store_then_unstore_leaves_the_table_as_it_was(self):
        tags = self.layer.parse(self.db, SCOPE, [{"entity": "faith", "passage": {"verse": "1 Nephi 3:1"}}, {"entity": "obedience", "passage": {"verse": "1 Nephi 3:1"}}])
        with self.db:
            self.layer.store(self.db, SCOPE, tags)
        self.assertEqual(self.db.execute("select count(*) from mention where kind_id = 'about'").fetchone()[0], 2)
        with self.db:
            self.layer.unstore(self.db, SCOPE, tags)
            self.layer.unstore(self.db, SCOPE, tags)
        self.assertEqual(self.db.execute("select count(*) from mention").fetchone()[0], 0)

    def test_two_agreeing_runs_store_the_answer(self):
        self.settle_earlier()
        answer = [{"entity": "faith", "passage": {"verse": "1 Nephi 3:2"}}]
        jobs.submit(self.db, self.job, answer)
        self.assertIsNotNone(self.job.settled())
        self.assertEqual(self.db.execute("select entity_id, kind_id from mention").fetchall(), [("faith", "about")])
    def settle_earlier(self, besides=()):
        for layer in LAYERS.values():
            if layer.step < self.layer.step and layer.scope == "chapter" and layer.name not in besides:
                jobs.Job(layer, SCOPE).write("settled", [])


if __name__ == "__main__":
    unittest.main()

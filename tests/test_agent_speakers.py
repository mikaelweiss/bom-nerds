import unittest

from bomnerds.agent import jobs
from bomnerds.agent.layers import LAYERS
from bomnerds.agent.prompt import prompt
from bomnerds.agent.show import show
from bomnerds.passages import Rejected
from tests.agent_fixtures import database, entity, job_folder

MOSIAH = {
    (1, 1): "And king Benjamin spake unto his people, saying: My brethren, hear my words.",
    (1, 2): "I have not commanded you to come up hither to trifle with my words.",
    (2, 1): "And again my brethren, I would call your attention.",
    (2, 2): "And the people cried aloud, saying: We believe all the words.",
    (2, 3): "And Benjamin said: Ye have spoken the words that I desired. Amen.",
    (3, 1): "And it came to pass that king Benjamin made an end of speaking.",
    (3, 2): "And he dismissed the multitude.",
}

OPENING = {"from": "Mosiah 1:1", "to": "Mosiah 1:2", "starts": "My brethren"}


def speech(passage, speaker="benjamin", listeners=("people",), mode="spoken", **extra):
    return {"speaker": speaker, "listeners": list(listeners), "mode": mode, "passage": passage, **extra}


class SpeakersTest(unittest.TestCase):
    def setUp(self):
        self.db = database([("bom", "Mosiah", MOSIAH)])
        self.addCleanup(self.db.close)
        entity(self.db, "benjamin", "person", "Benjamin", books=("mosiah",))
        entity(self.db, "mormon", "person", "Mormon", books=("mosiah",))
        entity(self.db, "lord", "person", "Lord", books=("mosiah",))
        entity(self.db, "people", "group", "People of Benjamin", books=("mosiah",))
        entity(self.db, "zarahemla", "city", "Zarahemla", books=("mosiah",))
        self.folder = job_folder()
        self.folder.__enter__()
        self.addCleanup(self.folder.__exit__, None, None, None)
        self.layer = LAYERS["speakers"]
        for scope in ("mosiah/1", "mosiah/2", "mosiah/3"):
            self.settle_earlier_steps(scope)

    def settle_earlier_steps(self, scope):
        for layer in LAYERS.values():
            if layer.step < self.layer.step and layer.scope == "chapter":
                jobs.Job(layer, scope).write("settled", [])

    def job(self, chapter):
        return jobs.Job(self.layer, f"mosiah/{chapter}")

    def settle(self, chapter, answer):
        jobs.submit(self.db, self.job(chapter), "a", answer)
        return jobs.submit(self.db, self.job(chapter), "b", answer)

    def check(self, chapter, answer):
        return jobs.check(self.db, self.job(chapter), "a", answer)

    def speeches(self):
        return list(self.db.execute("select speaker_id, first_word_id, last_word_id from speech order by first_word_id"))

    def tables(self):
        return self.speeches(), list(self.db.execute("select * from speech_listener order by speech_id, entity_id"))

    def word(self, chapter, verse, text):
        return self.db.execute("select id from word where chapter = ? and verse = ? and text = ?", (chapter, verse, text)).fetchone()[0]

    def test_a_valid_answer_round_trips_through_render(self):
        answer = [
            speech({"chapter": "Mosiah 1"}, "mormon", (), "narration", open=True),
            speech(OPENING, listeners=("people", "benjamin"), through="lord", open=True),
        ]
        tags = self.layer.parse(self.db, "mosiah/1", answer)
        self.assertEqual(tags[1].listeners, ("benjamin", "people"))
        self.assertEqual(self.layer.parse(self.db, "mosiah/1", [self.layer.render(self.db, t) for t in tags]), tags)

    def test_rejects_a_speaker_or_listener_who_is_not_a_person_or_group(self):
        with self.assertRaisesRegex(Rejected, "zarahemla is a city"):
            self.check(1, [speech(OPENING, "zarahemla")])
        with self.assertRaisesRegex(Rejected, "zarahemla is a city"):
            self.check(1, [speech(OPENING, listeners=("zarahemla",))])

    def test_rejects_an_entity_not_on_the_list(self):
        with self.assertRaisesRegex(Rejected, "'zeniff' is not on the entity list"):
            self.check(1, [speech(OPENING, listeners=("zeniff",))])

    def test_rejects_a_mode_not_on_the_list(self):
        with self.assertRaisesRegex(Rejected, "mode 'sermon' is not one of: narration, spoken"):
            self.check(1, [speech(OPENING, mode="sermon")])

    def test_rejects_a_quote_not_in_its_verse_and_a_passage_that_runs_backward(self):
        with self.assertRaisesRegex(Rejected, "is not in Mosiah 1:1"):
            self.check(1, [speech({"verse": "Mosiah 1:1", "quote": "Amen"})])
        with self.assertRaisesRegex(Rejected, "runs backward"):
            self.check(1, [speech({"from": "Mosiah 1:2", "to": "Mosiah 1:1"})])

    def test_rejects_the_same_speech_twice(self):
        with self.assertRaisesRegex(Rejected, "twice"):
            self.check(1, [speech(OPENING), speech(OPENING)])

    def test_rejects_through_naming_the_speaker(self):
        with self.assertRaisesRegex(Rejected, "cannot be the speaker"):
            self.check(1, [speech(OPENING, through="benjamin")])

    def test_rejects_a_listener_named_twice(self):
        with self.assertRaisesRegex(Rejected, "people more than once"):
            self.check(1, [speech(OPENING, listeners=("people", "people"))])

    def test_speeches_nest_but_never_overlap(self):
        narration = speech({"chapter": "Mosiah 2"}, "mormon", (), "narration")
        people = speech({"verse": "Mosiah 2:2", "quote": "We believe all the words"}, "people", ("benjamin",))
        self.settle(1, [])
        self.check(2, [narration, people])
        crossing = speech({"from": "Mosiah 2:2", "to": "Mosiah 2:3", "starts": "all the words", "ends": "Ye have spoken"}, "benjamin")
        with self.assertRaisesRegex(Rejected, "items 2 and 3 overlap without one sitting inside the other"):
            self.check(2, [narration, people, crossing])

    def test_rejects_two_speeches_on_the_same_words(self):
        with self.assertRaisesRegex(Rejected, "cover exactly the same words"):
            self.check(1, [speech(OPENING), speech(OPENING, "mormon")])

    def test_rejects_a_passage_ending_outside_the_chapter(self):
        with self.assertRaisesRegex(Rejected, "must end inside Mosiah 1"):
            self.check(1, [speech({"from": "Mosiah 1:1", "to": "Mosiah 2:3", "starts": "My brethren"})])

    def test_an_open_speech_runs_to_the_chapter_end(self):
        with self.assertRaisesRegex(Rejected, "ends at the chapter's last word"):
            self.check(1, [speech({"verse": "Mosiah 1:1", "quote": "My brethren"}, open=True)])

    def test_open_takes_only_true(self):
        with self.assertRaisesRegex(Rejected, '"open" takes true'):
            self.check(1, [speech(OPENING, open=False)])

    def test_a_speech_ends_at_the_end_of_its_book(self):
        self.settle(1, [])
        self.settle(2, [])
        with self.assertRaisesRegex(Rejected, "last chapter of Mosiah"):
            self.check(3, [speech({"from": "Mosiah 3:1", "to": "Mosiah 3:2"}, "mormon", (), "narration", open=True)])
        self.assertIn("## End of the book", prompt(self.db, self.job(3), "a"))

    def test_a_chapter_waits_for_the_one_before_it_and_for_earlier_steps(self):
        self.assertIsNone(self.layer.ready(self.db, jobs.Jobs, "mosiah/1"))
        self.assertIn("speakers/mosiah/1 must settle first", self.layer.ready(self.db, jobs.Jobs, "mosiah/2"))
        with self.assertRaisesRegex(Rejected, "cannot start yet"):
            self.check(2, [])
        self.settle(1, [])
        self.assertIsNone(self.layer.ready(self.db, jobs.Jobs, "mosiah/2"))
        earlier = [layer for layer in LAYERS.values() if layer.step < self.layer.step and layer.scope == "chapter"]
        for layer in earlier:
            (jobs.Job(layer, "mosiah/2").path / "settled.json").unlink()
        if earlier:
            self.assertIn("must settle first", self.layer.ready(self.db, jobs.Jobs, "mosiah/2"))

    def test_a_continued_speech_is_stored_as_one_row_across_chapters(self):
        self.settle(1, [speech(OPENING, open=True)])
        self.assertEqual(self.speeches(), [("benjamin", self.word(1, 1, "My"), self.word(1, 2, "words"))])
        context = prompt(self.db, self.job(2), "a")
        self.assertIn('## Open speeches', context)
        self.assertIn('"starts": "My brethren"', context.split("## Open speeches")[1])
        self.settle(2, [speech({"from": "Mosiah 1:1", "to": "Mosiah 2:3", "starts": "My brethren"})])
        self.assertEqual(self.speeches(), [("benjamin", self.word(1, 1, "My"), self.word(2, 3, "Amen"))])
        self.assertIn('"to": "Mosiah 2:3"', show(self.db, "mosiah", 1))
        self.assertIn('"to": "Mosiah 2:3"', show(self.db, "mosiah", 2))
        self.assertNotIn("benjamin", show(self.db, "mosiah", 3).split("## speakers")[-1])

    def test_an_open_speech_must_be_continued(self):
        self.settle(1, [speech(OPENING, open=True)])
        with self.assertRaisesRegex(Rejected, "open from before Mosiah 2, so continue it"):
            self.check(2, [])

    def test_a_continued_speech_keeps_its_speaker_listeners_and_mode(self):
        self.settle(1, [speech(OPENING, open=True)])
        with self.assertRaisesRegex(Rejected, "keep its speaker, through, listeners, and mode"):
            self.check(2, [speech({"from": "Mosiah 1:1", "to": "Mosiah 2:3", "starts": "My brethren"}, listeners=())])

    def test_only_an_open_speech_starts_before_the_chapter(self):
        self.settle(1, [])
        with self.assertRaisesRegex(Rejected, "no open speech starts there"):
            self.check(2, [speech({"from": "Mosiah 1:1", "to": "Mosiah 2:3", "starts": "My brethren"})])

    def test_rejects_overlap_with_a_speech_stored_from_an_earlier_chapter(self):
        self.settle(1, [speech(OPENING), speech({"verse": "Mosiah 1:2"}, "mormon", (), "narration", open=True)])
        continuing = speech({"from": "Mosiah 1:2", "to": "Mosiah 2:1"}, "mormon", (), "narration")
        with self.assertRaisesRegex(Rejected, "overlaps without nesting the speech by benjamin stored from an earlier chapter"):
            self.check(2, [continuing])

    def test_store_then_unstore_leaves_the_tables_as_they_were(self):
        self.settle(1, [speech(OPENING, open=True)])
        before = self.tables()
        tags = self.layer.parse(self.db, "mosiah/2", [speech({"from": "Mosiah 1:1", "to": "Mosiah 2:3", "starts": "My brethren"}), speech({"verse": "Mosiah 2:2", "quote": "We believe all the words"}, "people", ("benjamin",))])
        self.layer.store(self.db, "mosiah/2", tags)
        self.assertNotEqual(self.tables(), before)
        self.layer.unstore(self.db, "mosiah/2", tags)
        self.assertEqual(self.tables(), before)

    def test_reset_waits_for_the_chapter_that_continued_a_speech(self):
        self.settle(1, [speech(OPENING, open=True)])
        self.settle(2, [speech({"from": "Mosiah 1:1", "to": "Mosiah 2:3", "starts": "My brethren"})])
        with self.assertRaisesRegex(Rejected, "Reset speakers/mosiah/2 first"):
            jobs.reset(self.db, self.job(1))
        self.assertEqual(self.job(1).state(self.db), "settled")
        jobs.reset(self.db, self.job(2))
        self.assertEqual(self.speeches(), [("benjamin", self.word(1, 1, "My"), self.word(1, 2, "words"))])
        jobs.reset(self.db, self.job(1))
        self.assertEqual(self.tables(), ([], []))

    def test_a_speech_cannot_stay_open_when_the_next_chapter_settled_without_it(self):
        self.settle(1, [])
        self.settle(2, [])
        jobs.reset(self.db, self.job(1))
        with self.assertRaisesRegex(Rejected, "speakers/mosiah/2 is settled without continuing"):
            self.check(1, [speech(OPENING, open=True)])

    def test_has_nothing_fixed_or_given(self):
        self.settle(1, [speech(OPENING)])
        self.assertEqual(self.layer.fixed(self.db, "mosiah/1"), [])
        self.assertEqual(self.layer.given(self.db, "mosiah/1"), [])
        self.assertEqual(len(self.layer.parse(self.db, "mosiah/1", self.job(1).settled())), 1)

    def test_replay_stores_a_chapter_again(self):
        self.settle(1, [speech(OPENING, through="lord")])
        before = self.tables()
        self.db.execute("delete from speech_listener")
        self.db.execute("delete from speech")
        jobs.replay(self.db, [self.layer])
        self.assertEqual(self.tables(), before)

    def test_a_spanning_speech_stores_again_when_later_chapters_unstore_first(self):
        self.settle(1, [speech(OPENING, open=True)])
        self.settle(2, [speech({"from": "Mosiah 1:1", "to": "Mosiah 2:3", "starts": "My brethren"})])
        before = self.tables()
        settled = [(scope, self.layer.parse(self.db, scope, jobs.Job(self.layer, scope).settled())) for scope in ("mosiah/1", "mosiah/2")]
        for scope, tags in reversed(settled):
            self.layer.unstore(self.db, scope, tags)
        self.assertEqual(self.tables(), ([], []))
        for scope, tags in settled:
            self.layer.store(self.db, scope, tags)
        self.assertEqual(self.tables(), before)

    def test_the_prompt_shows_the_start_of_the_next_chapter_and_the_modes(self):
        text = prompt(self.db, self.job(1), "a")
        self.assertIn("## The start of Mosiah 2", text)
        self.assertIn("1 And again my brethren", text)
        self.assertIn("narration, spoken, written, prayer, song", text)


if __name__ == "__main__":
    unittest.main()

import json
import unittest
from unittest import mock

from bomnerds.agent import batch, jobs, review
from bomnerds.agent import plan as plans
from bomnerds.agent.layers import LAYERS
from bomnerds.agent.plan import Pass, Session
from bomnerds.passages import Rejected
from tests.agent_fixtures import database, entity, job_folder

GENESIS = {(5, 1): "This is the book of the generations of Adam.", (5, 3): "And Adam lived an hundred and thirty years, and begat a son, and called his name Seth:"}
NEPHI = {(1, 1): "I, Nephi, went forth.", (2, 1): "And Nephi went back.", (3, 1): "And Lehi rested."}
PEOPLE = Session("people-001", "people", "sonnet", ("names", "speakers"), "genesis/5", "genesis/5", "Genesis 5", ())
REVIEW = Session("review-people-1", "people", "opus", ("names", "speakers"), "genesis/5", "genesis/5", "Genesis 5", ("people:*",))
NAMES = "# Genesis 5\n5:1 | Adam | adam\n5:3 | Adam | adam?\n5:3 | Seth | seth\n"


def mention(name, verse, quote):
    return {"entity": name, "passage": {"verse": f"Genesis 5:{verse}", "quote": quote}}


class Database(unittest.TestCase):
    def setUp(self):
        self.db = database([("bible", "Genesis", GENESIS), ("bom", "1 Nephi", NEPHI)])
        entity(self.db, "adam", "person", "Adam", books=("genesis",))
        entity(self.db, "seth", "person", "Seth", books=("genesis",))
        self.folder = job_folder()
        self.path = self.folder.__enter__()
        self.addCleanup(self.folder.__exit__, None, None, None)
        self.addCleanup(plans.CACHE.clear)

    def mentions(self):
        return list(self.db.execute("select entity_id, first_word_id, last_word_id from mention order by first_word_id"))


class JobsTest(Database):
    def setUp(self):
        super().setUp()
        self.job = jobs.Job(LAYERS["names"], "genesis/5")

    def test_submit_stores_once(self):
        jobs.submit(self.db, self.job, [mention("adam", 1, "Adam"), mention("seth", 3, "Seth")])
        self.assertEqual(len(self.mentions()), 2)
        with self.assertRaisesRegex(Rejected, "already stored"):
            jobs.submit(self.db, self.job, [])

    def test_reset_deletes_what_the_job_stored(self):
        jobs.submit(self.db, self.job, [mention("adam", 3, "Adam")])
        self.assertEqual(jobs.reset(self.db, self.job), 1)
        self.assertEqual(self.mentions(), [])
        self.assertIsNone(self.job.settled())

    def test_replay_stores_settled_jobs_again(self):
        jobs.submit(self.db, self.job, [mention("adam", 3, "Adam")])
        self.db.execute("delete from mention")
        jobs.replay(self.db, [LAYERS["names"]])
        self.assertEqual(len(self.mentions()), 1)

    def test_rejects_a_fact_twice_and_a_quote_not_in_its_verse(self):
        with self.assertRaisesRegex(Rejected, "twice"):
            jobs.check(self.db, self.job, [mention("adam", 1, "Adam"), mention("adam", 1, "Adam")])
        with self.assertRaisesRegex(Rejected, "item 1, Genesis 5:1 \"Eve\""):
            jobs.check(self.db, self.job, [mention("adam", 1, "Eve")])

    def test_rejects_an_entity_not_on_the_list(self):
        with self.assertRaisesRegex(Rejected, "not on the entity list. Pick one from the list, or write an unlisted line"):
            jobs.check(self.db, self.job, [mention("enos", 3, "Seth")])

    def test_rejects_what_is_already_tagged(self):
        first, last = self.db.execute("select id, id from word where text = 'Seth'").fetchone()
        self.db.execute("insert into mention (entity_id, kind_id, first_word_id, last_word_id) values ('seth', 'names', ?, ?)", (first, last))
        with self.assertRaisesRegex(Rejected, "already tagged"):
            jobs.check(self.db, self.job, [mention("seth", 3, "Seth")])


class PlanTest(Database):
    def test_batches_stay_near_the_target_end_at_books_and_never_cross_works(self):
        p = Pass("test", ("names",), "sonnet", 2, ())
        units = ["genesis/5", "1-nephi/1", "1-nephi/2", "1-nephi/3"]
        batches = plans.cut(self.db, p, units, {u: 1 for u in units})
        self.assertEqual(batches, [["genesis/5"], ["1-nephi/1", "1-nephi/2"], ["1-nephi/3"]])
        batches = plans.cut(self.db, Pass("test", ("names",), "sonnet", 1, ()), units, {u: 1 for u in units})
        self.assertEqual(batches, [["genesis/5"], ["1-nephi/1"], ["1-nephi/2"], ["1-nephi/3"]])

    def test_people_sessions_in_one_book_wait_for_the_one_before(self):
        with mock.patch.object(plans, "PASSES", (Pass("people", ("names", "speakers"), "sonnet", 1, (), chained="book"),)):
            sessions = plans.make(self.db)
        self.assertEqual([(s.id, s.after) for s in sessions if not s.review], [
            ("people-001", ()), ("people-002", ()), ("people-003", ("people-002",)), ("people-004", ("people-003",)),
        ])
        self.assertEqual([(s.id, s.first, s.last, s.after) for s in sessions if s.review], [("review-people-1", "genesis/5", "1-nephi/3", ("people:*",))])

    def test_the_plan_file_round_trips_and_says_what_waits(self):
        path = self.path / "plan.tsv"
        plans.write([PEOPLE, REVIEW], path)
        loaded = plans.load(path)
        self.assertEqual(loaded, [PEOPLE, REVIEW])
        self.assertEqual(plans.waiting_on(REVIEW, loaded), ["people-001"])
        PEOPLE.folder.mkdir(parents=True)
        (PEOPLE.folder / "done").write_text("")
        self.assertEqual(plans.waiting_on(REVIEW, loaded), [])


class Sessions(Database):
    def setUp(self):
        super().setUp()
        plan = self.path / "plan.tsv"
        plans.write([PEOPLE, REVIEW], plan)
        patch = mock.patch.object(plans, "PLAN", plan)
        patch.start()
        self.addCleanup(patch.stop)

    def answer(self, name, text):
        PEOPLE.folder.mkdir(parents=True, exist_ok=True)
        batch.answer_path(PEOPLE, name).write_text(text, encoding="utf-8")


class SessionTest(Sessions):
    def test_the_prompt_holds_every_layer_and_the_capitalized_words(self):
        message = batch.write_prompt(self.db, "people-001")
        self.assertIn("Read all of it", message)
        text = (PEOPLE.folder / "prompt.md").read_text()
        self.assertIn("1. names: write", text)
        self.assertIn("2. speakers: write", text)
        self.assertIn("## Capitalized words\n\n5:1 Adam\n5:3 Adam, Seth", text)
        self.assertIn("adam (person) Adam.", text)

    def test_submit_stores_short_lines_and_keeps_flags(self):
        self.answer("names", NAMES)
        report = batch.submit(self.db, "people-001", "names")
        self.assertIn("Stored 1 sections: Genesis 5.", report)
        self.assertIn("Next, answer speakers", report)
        self.assertEqual(len(self.mentions()), 3)
        self.assertEqual(jobs.Job(LAYERS["names"], "genesis/5").read("flagged"), ["5:3 | Adam | adam"])

    def test_submit_lists_capitalized_words_left_out(self):
        self.answer("names", "# Genesis 5\n5:1 | Adam | adam\n")
        report = batch.submit(self.db, "people-001", "names")
        self.assertIn("these capitalized words are in no tag", report)
        self.assertIn("5:3 Adam, Seth", report)
        self.assertEqual(self.mentions(), [])

    def test_unlisted_lines_cover_their_words_and_wait_for_review(self):
        self.answer("names", "# Genesis 5\n5:1 | Adam | adam\n5:3 | Adam | adam\nunlisted | 5:3 | Seth | person | Son of Adam.\n")
        batch.submit(self.db, "people-001", "names")
        self.assertEqual(jobs.Job(LAYERS["names"], "genesis/5").read("unlisted"), [{"passage": {"verse": "Genesis 5:3", "quote": "Seth"}, "type": "person", "description": "Son of Adam."}])

    def test_a_heading_not_in_the_session_is_refused(self):
        self.answer("names", "# Genesis 6\n")
        with self.assertRaisesRegex(Rejected, "no section of people-001 names is headed 'Genesis 6'"):
            batch.submit(self.db, "people-001", "names")

    def test_done_waits_for_every_layer_and_reset_deletes_it_all(self):
        self.answer("names", NAMES)
        batch.submit(self.db, "people-001", "names")
        with self.assertRaisesRegex(Rejected, "still has sections to store: speakers Genesis 5"):
            batch.done(self.db, "people-001")
        self.answer("speakers", "# Genesis 5\n")
        self.assertIn("Every layer is stored", batch.submit(self.db, "people-001", "speakers"))
        batch.done(self.db, "people-001")
        self.assertTrue(PEOPLE.done())
        self.assertIn("3 tags deleted", batch.reset(self.db, "people-001"))
        self.assertEqual(self.mentions(), [])
        self.assertFalse(PEOPLE.done())

    def test_a_review_waits_for_its_pass(self):
        with self.assertRaisesRegex(Rejected, "review-people-1 waits for people-001"):
            batch.write_prompt(self.db, "review-people-1")


class ReviewTest(Sessions):
    def setUp(self):
        super().setUp()
        self.answer("names", NAMES.replace("5:3 | Seth | seth", "5:3 | Seth | adam"))
        batch.submit(self.db, "people-001", "names")
        self.answer("speakers", "# Genesis 5\n")
        batch.submit(self.db, "people-001", "speakers")
        batch.done(self.db, "people-001")

    def fix(self, text):
        REVIEW.folder.mkdir(parents=True, exist_ok=True)
        (REVIEW.folder / "review.txt").write_text(text, encoding="utf-8")
        return batch.submit(self.db, "review-people-1", None)

    def test_the_prompt_shows_flags_findings_and_the_sample(self):
        batch.write_prompt(self.db, "review-people-1")
        text = (REVIEW.folder / "prompt.md").read_text()
        self.assertIn("# names: Genesis 5\n5:3 | Adam | adam\n    Genesis 5:3: And Adam lived", text)
        self.assertIn("## Sample sections", text)
        self.assertIn('{"entity": "adam", "passage": {"verse": "Genesis 5:3", "quote": "Seth"}}', text)

    def test_fixes_replace_stored_lines(self):
        wrong = json.dumps(mention("adam", 3, "Seth"))
        right = json.dumps(mention("seth", 3, "Seth"))
        report = self.fix(f"# names: Genesis 5\n- {wrong}\n+ {right}\n\n# error rates\nnames 1/3\nspeakers 0/0\n")
        self.assertIn("Fixed names: Genesis 5.", report)
        self.assertIn(("seth",), [row[:1] for row in self.mentions()])
        self.assertNotIn(mention("adam", 3, "Seth"), jobs.Job(LAYERS["names"], "genesis/5").settled())
        self.assertEqual(json.loads((REVIEW.folder / "rates.json").read_text()), {"names": [1, 3], "speakers": [0, 0]})

    def test_a_line_to_remove_must_be_stored(self):
        report = self.fix(f"# names: Genesis 5\n- {json.dumps(mention('seth', 1, 'Adam'))}\n")
        self.assertIn("this line is not stored", report)

    def test_new_entities_join_the_book_that_names_them(self):
        report = self.fix('# new entities\n{"id": "seth-son-of-adam", "type": "person", "name": "Seth", "other_names": [], "description": "Son of Adam.", "verse": "Genesis 5:3"}\n')
        self.assertIn("Added 1 entities: seth-son-of-adam.", report)
        self.assertIn(("seth-son-of-adam", "genesis"), list(self.db.execute("select * from entity_book")))
        self.assertEqual(jobs.Job(LAYERS["entities"], "scripture").settled()[0]["books"], ["genesis"])


if __name__ == "__main__":
    unittest.main()

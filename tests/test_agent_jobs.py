import unittest

from bomnerds.agent import jobs
from bomnerds.agent.layers import LAYERS
from bomnerds.agent.prompt import prompt
from bomnerds.passages import Rejected
from tests.agent_fixtures import database, entity, job_folder

GENESIS = {(5, 1): "This is the book of the generations of Adam.", (5, 3): "And Adam lived an hundred and thirty years, and begat a son, and called his name Seth:"}


def mention(name, verse, quote):
    return {"entity": name, "passage": {"verse": f"Genesis 5:{verse}", "quote": quote}}


class JobsTest(unittest.TestCase):
    def setUp(self):
        self.db = database([("bible", "Genesis", GENESIS)])
        entity(self.db, "adam", "person", "Adam", books=("genesis",))
        entity(self.db, "seth", "person", "Seth", books=("genesis",))
        self.folder = job_folder()
        self.folder.__enter__()
        self.addCleanup(self.folder.__exit__, None, None, None)
        self.job = jobs.Job(LAYERS["names"], "genesis/5")

    def mentions(self):
        return list(self.db.execute("select entity_id, first_word_id, last_word_id from mention order by first_word_id"))

    def test_agreeing_runs_settle_and_store(self):
        answer = [mention("adam", 1, "Adam"), mention("seth", 3, "Seth")]
        jobs.submit(self.db, self.job, "a", answer)
        self.assertEqual(self.mentions(), [])
        jobs.submit(self.db, self.job, "b", list(reversed(answer)))
        self.assertEqual(self.job.state(self.db), "settled")
        self.assertEqual(len(self.mentions()), 2)

    def test_a_decider_settles_what_the_runs_differ_on(self):
        jobs.submit(self.db, self.job, "a", [mention("adam", 1, "Adam"), mention("seth", 3, "Seth")])
        jobs.submit(self.db, self.job, "b", [mention("adam", 1, "Adam"), mention("adam", 3, "Seth")])
        self.assertEqual(self.job.state(self.db), "needs decider")
        self.assertIn('"seth"', prompt(self.db, self.job, "decider").split("## Only the first run")[1])
        jobs.submit(self.db, self.job, "decider", [mention("seth", 3, "Seth")])
        self.assertEqual([m[0] for m in self.mentions()], ["adam", "seth"])

    def test_reset_deletes_what_the_job_stored(self):
        answer = [mention("adam", 3, "Adam")]
        jobs.submit(self.db, self.job, "a", answer)
        jobs.submit(self.db, self.job, "b", answer)
        jobs.reset(self.db, self.job)
        self.assertEqual(self.mentions(), [])
        self.assertEqual(self.job.state(self.db), "needs a and b")

    def test_replay_stores_settled_jobs_again(self):
        answer = [mention("adam", 3, "Adam")]
        jobs.submit(self.db, self.job, "a", answer)
        jobs.submit(self.db, self.job, "b", answer)
        self.db.execute("delete from mention")
        jobs.replay(self.db, [LAYERS["names"]])
        self.assertEqual(len(self.mentions()), 1)

    def test_rejects_a_fact_twice_and_a_quote_not_in_its_verse(self):
        with self.assertRaisesRegex(Rejected, "twice"):
            jobs.check(self.db, self.job, "a", [mention("adam", 1, "Adam"), mention("adam", 1, "Adam")])
        with self.assertRaisesRegex(Rejected, "item 1"):
            jobs.check(self.db, self.job, "a", [mention("adam", 1, "Eve")])

    def test_rejects_an_entity_not_on_the_list(self):
        with self.assertRaisesRegex(Rejected, "not on the entity list"):
            jobs.check(self.db, self.job, "a", [mention("enos", 3, "Seth")])

    def test_rejects_what_is_already_tagged(self):
        first, last = self.db.execute("select id, id from word where text = 'Seth'").fetchone()
        self.db.execute("insert into mention (entity_id, kind_id, first_word_id, last_word_id) values ('seth', 'names', ?, ?)", (first, last))
        with self.assertRaisesRegex(Rejected, "already tagged"):
            jobs.check(self.db, self.job, "a", [mention("seth", 3, "Seth")])

    def test_a_settled_job_takes_no_more_answers(self):
        jobs.submit(self.db, self.job, "a", [])
        jobs.submit(self.db, self.job, "b", [])
        with self.assertRaisesRegex(Rejected, "settled"):
            jobs.submit(self.db, self.job, "decider", [])


if __name__ == "__main__":
    unittest.main()

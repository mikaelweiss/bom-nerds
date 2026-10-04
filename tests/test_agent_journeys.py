import unittest

from bomnerds.agent import jobs
from bomnerds.agent.layers import LAYERS
from bomnerds.agent.prompt import prompt
from bomnerds.passages import Rejected
from tests.agent_fixtures import database, entity, job_folder

GENESIS = {
    (12, 1): "Now the LORD had said unto Abram, Get thee out of thy country.",
    (12, 4): "So Abram departed, and Lot went with him.",
    (12, 5): "And they went forth to go into the land of Canaan.",
    (13, 1): "And Abram went up out of Egypt, into the south, and Lot with him.",
    (13, 3): "And he went on his journeys three days and a half from the south even to Bethel.",
}


def passage(verse, quote):
    return {"verse": f"Genesis {verse}", "quote": quote}


def journey(traveler, to, quote, verse="12:5", **more):
    return {"traveler": traveler, "to": to, "passage": passage(verse, quote), **more}


TO_CANAAN = journey("abram", "canaan", "went forth to go into the land of Canaan")


class JourneysTest(unittest.TestCase):
    def setUp(self):
        self.db = database([("bible", "Genesis", GENESIS)])
        for id, type_id in (("abram", "person"), ("lot", "person"), ("family-of-abram", "group"), ("canaan", "land"), ("egypt", "land"), ("bethel", "city"), ("haran", "city"), ("the-lord", "topic")):
            entity(self.db, id, type_id, id.title(), books=("genesis",))
        folder = job_folder()
        folder.__enter__()
        self.addCleanup(folder.__exit__, None, None, None)
        self.layer = LAYERS["journeys"]
        self.job = jobs.Job(self.layer, "genesis/12")

    def settle_earlier(self, scope):
        for layer in LAYERS.values():
            if layer.step < self.layer.step and layer.scope == "chapter" and scope in layer.scope_set(self.db):
                jobs.Job(layer, scope).write("settled", [])

    def parse(self, answer, scope="genesis/12"):
        return self.layer.parse(self.db, scope, answer)

    def rejection(self, answer):
        with self.assertRaises(Rejected) as caught:
            self.parse(answer)
        return str(caught.exception)

    def rows(self):
        return list(self.db.execute("select traveler_id, from_id, to_id, days, first_word_id, last_word_id from journey order by id"))

    def test_a_valid_answer_round_trips_through_render(self):
        there = journey("family-of-abram", "bethel", "from the south even to Bethel", "13:3", **{"from": "egypt", "days": 3.5})
        for scope, answer in (("genesis/12", [TO_CANAAN]), ("genesis/13", [there])):
            tag = self.parse(answer, scope)[0]
            self.assertEqual(self.layer.render(self.db, tag), answer[0])
            self.assertEqual(self.parse([self.layer.render(self.db, tag)], scope), [tag])

    def test_render_leaves_out_what_is_empty_and_writes_whole_days_as_integers(self):
        tag = self.parse([journey("abram", "canaan", "went forth", days=3)])[0]
        self.assertEqual(self.layer.render(self.db, tag), journey("abram", "canaan", "went forth", days=3))
        self.assertNotIn("from", self.layer.render(self.db, tag))
        self.assertIsInstance(self.layer.render(self.db, tag)["days"], int)

    def test_from_and_days_may_be_null(self):
        self.assertEqual(self.parse([journey("abram", "canaan", "went forth", **{"from": None, "days": None})]), self.parse([journey("abram", "canaan", "went forth")]))

    def test_places_include_their_subtypes(self):
        answer = [journey("abram", "haran", "went forth", **{"from": "canaan"}), journey("lot", "canaan", "departed", "12:4", **{"from": "haran"})]
        self.assertEqual(len(self.parse(answer)), 2)

    def test_rejects_a_traveler_that_is_not_a_person_or_group(self):
        self.assertIn("the-lord is a topic, but this must be a person or group", self.rejection([journey("the-lord", "canaan", "went forth")]))
        self.assertIn("canaan is a land, but this must be a person or group", self.rejection([journey("canaan", "egypt", "went forth")]))

    def test_rejects_places_that_are_not_places(self):
        message = self.rejection([journey("abram", "lot", "went forth", **{"from": "family-of-abram"})])
        self.assertIn("lot is a person, but this must be a place", message)
        self.assertIn("family-of-abram is a group, but this must be a place", message)

    def test_rejects_an_entity_not_on_the_list(self):
        self.assertIn("'ur' is not on the entity list", self.rejection([journey("abram", "ur", "went forth")]))

    def test_rejects_the_same_place_as_start_and_destination(self):
        self.assertIn("from and to are both canaan", self.rejection([journey("abram", "canaan", "went forth", **{"from": "canaan"})]))

    def test_rejects_days_that_are_not_a_positive_number(self):
        for days in (0, -2, "3", True, float("nan"), float("inf"), [3]):
            self.assertIn("days must be a positive number", self.rejection([journey("abram", "canaan", "went forth", days=days)]), days)

    def test_rejects_a_passage_outside_the_chapter_or_not_in_its_verse(self):
        self.assertIn("must sit inside Genesis 12", self.rejection([journey("abram", "canaan", "went up out of Egypt", "13:1")]))
        self.assertIn("is not in Genesis 12:5", self.rejection([journey("abram", "canaan", "Egypt")]))

    def test_rejects_a_missing_destination_and_an_unknown_field(self):
        self.assertIn("missing to", self.rejection([{"traveler": "abram", "passage": passage("12:5", "went forth")}]))
        self.assertIn("unknown field by", self.rejection([journey("abram", "canaan", "went forth", by="foot")]))

    def test_rejects_the_same_journey_twice(self):
        self.assertIn("appears twice", self.rejection([TO_CANAAN, dict(TO_CANAAN)]))

    def test_the_same_trip_with_different_passages_is_two_journeys(self):
        tags = self.parse([TO_CANAAN, journey("abram", "canaan", "departed", "12:4")])
        self.assertEqual(len(tags), 2)
        with self.db:
            self.layer.store(self.db, "genesis/12", tags)
        self.assertEqual(len(self.rows()), 2)

    def test_store_then_unstore_leaves_the_table_as_it_was(self):
        tags = self.parse([TO_CANAAN, journey("lot", "canaan", "departed", "12:4", **{"from": "haran", "days": 2})])
        with self.db:
            self.layer.store(self.db, "genesis/12", tags)
        self.assertEqual(len(self.rows()), 2)
        self.assertEqual(self.rows()[1][3], 2.0)
        with self.db:
            self.layer.unstore(self.db, "genesis/12", tags)
        self.assertEqual(self.rows(), [])

    def test_unstore_removes_only_the_matching_journey_and_ignores_what_is_gone(self):
        tags = self.parse([TO_CANAAN, journey("abram", "canaan", "departed", "12:4")])
        with self.db:
            self.layer.store(self.db, "genesis/12", tags)
            self.layer.unstore(self.db, "genesis/12", tags[:1])
            self.layer.unstore(self.db, "genesis/12", tags[:1])
        self.assertEqual(len(self.rows()), 1)

    def test_a_settled_job_shows_its_journeys_in_reading_order(self):
        self.settle_earlier("genesis/12")
        answer = [journey("lot", "canaan", "departed", "12:4", **{"from": "haran", "days": 2.5}), TO_CANAAN]
        jobs.submit(self.db, self.job, "a", answer)
        jobs.submit(self.db, self.job, "b", list(reversed(answer)))
        self.assertEqual(self.job.state(self.db), "settled")
        self.assertEqual(self.layer.shown(self.db, "kjv", "genesis", 12), [answer[0], answer[1]])
        self.assertEqual(self.layer.shown(self.db, "kjv", "genesis", 13), [])

    def test_a_decider_settles_what_the_runs_differ_on(self):
        self.settle_earlier("genesis/12")
        jobs.submit(self.db, self.job, "a", [TO_CANAAN])
        jobs.submit(self.db, self.job, "b", [journey("abram", "canaan", "went forth to go into the land of Canaan", days=2)])
        self.assertEqual(self.job.state(self.db), "needs decider")
        jobs.submit(self.db, self.job, "decider", [TO_CANAAN])
        self.assertEqual(len(self.rows()), 1)
        self.assertIsNone(self.rows()[0][3])

    def test_reset_deletes_what_the_job_stored(self):
        self.settle_earlier("genesis/12")
        jobs.submit(self.db, self.job, "a", [TO_CANAAN])
        jobs.submit(self.db, self.job, "b", [TO_CANAAN])
        jobs.reset(self.db, self.job)
        self.assertEqual(self.rows(), [])

    def test_replay_stores_settled_jobs_again(self):
        self.settle_earlier("genesis/12")
        jobs.submit(self.db, self.job, "a", [TO_CANAAN])
        jobs.submit(self.db, self.job, "b", [TO_CANAAN])
        before = self.rows()
        self.db.execute("delete from journey")
        jobs.replay(self.db, [self.layer])
        self.assertEqual(self.rows(), before)

    def test_waits_for_every_earlier_chapter_job_on_the_chapter(self):
        self.assertIn("must settle first", self.layer.ready(self.db, jobs.Jobs, "genesis/12"))
        self.assertTrue(self.job.state(self.db).startswith("waiting"))
        self.settle_earlier("genesis/12")
        self.assertIsNone(self.layer.ready(self.db, jobs.Jobs, "genesis/12"))
        self.assertEqual(self.job.state(self.db), "needs a and b")

    def test_the_prompt_asks_the_question_and_shows_the_chapter(self):
        self.settle_earlier("genesis/12")
        text = prompt(self.db, self.job, "a")
        self.assertIn("Tag every journey in this chapter", text)
        self.assertIn("Now the LORD had said unto Abram", text)
        self.assertNotIn("Already tagged", text)


if __name__ == "__main__":
    unittest.main()

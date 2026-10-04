import unittest
from unittest import mock

from bomnerds.agent import jobs
from bomnerds.agent.layer import Layer
from bomnerds.agent.layers import LAYERS
from bomnerds.agent.layers.dates import Dates
from bomnerds.agent.layers.names import Names
from bomnerds.agent.prompt import prompt
from bomnerds.passages import Rejected
from tests.agent_fixtures import database, entity, job_folder

ALMA = {
    (1, 1): "In the first year of the reign of the judges, Nephi went to Zarahemla.",
    (1, 2): "And in the second year the people rested, and Helaman was born.",
    (1, 3): "Now the battle was fierce.",
}
ALMA_2 = {(2, 1): "And in the third year the people rested."}
DC = {(20, 1): "The rise of the Church, in the fourth month, and on the sixth day of the month which is called April."}

FIRST_YEAR = {"verse": "Alma 1:1", "quote": "first year of the reign of the judges"}
SECOND_YEAR = {"verse": "Alma 1:2", "quote": "second year"}


def date(on, system="reign_of_judges", start=1, end=None, evidence=FIRST_YEAR, **more):
    answer = {"on": on, "system": system, "from": start, "to": start if end is None else end, **more}
    if evidence:
        answer["evidence"] = evidence
    return answer


class DatesTest(unittest.TestCase):
    def setUp(self):
        self.db = database([("bom", "Alma", {**ALMA, **ALMA_2}), ("dc", "Doctrine and Covenants", DC)])
        entity(self.db, "battle-of-alma", "event", "Battle", books=("alma",))
        entity(self.db, "helaman", "person", "Helaman", books=("alma",))
        entity(self.db, "alma", "person", "Alma", books=("alma",))
        self.db.execute("insert into relationship (subject_id, kind_id, object_id) values ('helaman', 'child_of', 'alma')")
        self.db.execute("insert into relationship (subject_id, kind_id, object_id) values ('helaman', 'spouse_of', 'alma')")
        self.layer = Dates()
        layers = mock.patch.dict(LAYERS, {"names": Names(), "dates": self.layer}, clear=True)
        layers.start()
        self.addCleanup(layers.stop)
        self.folder = job_folder()
        self.folder.__enter__()
        self.addCleanup(self.folder.__exit__, None, None, None)
        self.job = jobs.Job(self.layer, "alma/1")
        jobs.Job(LAYERS["names"], "alma/1").write("settled", [])

    def parse(self, *answer):
        return self.layer.parse(self.db, "alma/1", list(answer))

    def rejects(self, pattern, *answer):
        with self.assertRaisesRegex(Rejected, pattern):
            self.parse(*answer)

    def word(self, text):
        return self.db.execute("select id from word where text = ?", (text,)).fetchone()[0]

    def rows(self):
        return list(self.db.execute("select * from date order by id"))

    def test_every_target_round_trips_through_render(self):
        answer = [
            date({"verse": "Alma 1:2"}, evidence=SECOND_YEAR, start=2),
            date({"entity": "battle-of-alma"}, start=5, end=6, from_month=2, from_day=3, to_month=4, to_day=5),
            date({"relationship": {"subject": "helaman", "kind": "child_of", "object": "alma"}}, evidence=SECOND_YEAR, start=2),
            date({"chapter": "Alma 1"}, "bc_ad", -599, evidence=None),
        ]
        tags = self.parse(*answer)
        self.assertEqual([self.layer.render(self.db, t) for t in tags], answer)
        self.assertEqual(self.layer.parse(self.db, "alma/1", answer), tags)

    def test_a_bc_ad_year_the_text_states_cites_its_words(self):
        tags = self.layer.parse(self.db, "doctrine-and-covenants/20", [
            date({"verse": "D&C 20:1"}, "bc_ad", 1830, from_month=4, from_day=6, to_month=4, to_day=6, evidence={"verse": "D&C 20:1", "quote": "sixth day of the month which is called April"})
        ])
        self.assertEqual(len(tags), 1)

    def test_only_a_bc_ad_estimate_goes_without_evidence(self):
        self.rejects('"evidence" is required', date({"chapter": "Alma 1"}, evidence=None))
        self.assertEqual(len(self.parse(date({"chapter": "Alma 1"}, "bc_ad", -599, evidence=None))), 1)

    def test_rejects_evidence_or_a_passage_outside_the_chapter(self):
        self.rejects("must sit inside Alma 1", date({"chapter": "Alma 1"}, evidence={"verse": "Alma 2:1"}))
        self.rejects("must sit inside Alma 1", date({"verse": "Alma 2:1"}))

    def test_rejects_an_entity_that_is_not_an_event(self):
        self.rejects("helaman is a person", date({"entity": "helaman"}))
        self.rejects("not on the entity list", date({"entity": "flood"}))

    def test_a_relationship_must_be_stored(self):
        self.rejects("no relationship helaman sibling_of alma is stored", date({"relationship": {"subject": "helaman", "kind": "sibling_of", "object": "alma"}}))
        self.rejects("runs the other way: helaman child_of alma", date({"relationship": {"subject": "alma", "kind": "child_of", "object": "helaman"}}))

    def test_a_two_way_relationship_is_read_in_its_stored_direction(self):
        reversed_ = date({"relationship": {"subject": "alma", "kind": "spouse_of", "object": "helaman"}})
        tag = self.parse(reversed_)[0]
        self.assertEqual(tag[0], ("relationship", "helaman", "spouse_of", "alma"))

    def test_rejects_a_bad_on(self):
        self.rejects('"on" takes one of', date({"entity": "battle-of-alma", "verse": "Alma 1:1"}))
        self.rejects("takes", date({"relationship": "helaman"}))

    def test_rejects_every_calendar_mistake(self):
        self.rejects('"from" must be a whole number', date({"chapter": "Alma 1"}, start="1"))
        self.rejects('"from" must be a whole number', date({"chapter": "Alma 1"}, start=True))
        self.rejects('"from" must be a whole number', date({"chapter": "Alma 1"}, start=1.5))
        self.rejects("runs backward", date({"chapter": "Alma 1"}, start=5, end=4))
        self.rejects("runs backward", date({"chapter": "Alma 1"}, start=5, from_month=3, to_month=2))
        self.rejects("runs backward", date({"chapter": "Alma 1"}, start=5, from_month=3, from_day=9, to_month=3, to_day=8))
        self.rejects('"from_month" must be 1 to 12', date({"chapter": "Alma 1"}, from_month=13, to_month=13))
        self.rejects('"to_day" must be 1 to 31', date({"chapter": "Alma 1"}, from_month=1, from_day=1, to_month=1, to_day=32))
        self.rejects("month 2 has no day 30", date({"chapter": "Alma 1"}, from_month=2, from_day=30, to_month=2, to_day=30))
        self.rejects("from_day needs from_month", date({"chapter": "Alma 1"}, from_day=3, to_day=3))
        self.rejects("from_month and to_month together", date({"chapter": "Alma 1"}, from_month=3))
        self.rejects("from_day and to_day together", date({"chapter": "Alma 1"}, from_month=3, to_month=3, from_day=1))

    def test_rejects_an_unknown_system_missing_and_unknown_fields(self):
        self.rejects("system 'calendar' is not one of", date({"chapter": "Alma 1"}, "calendar"))
        self.rejects("missing to", {"on": {"chapter": "Alma 1"}, "system": "bc_ad", "from": 1})
        self.rejects("unknown field note", date({"chapter": "Alma 1"}, note="x"))

    def test_rejects_every_problem_in_one_answer(self):
        with self.assertRaises(Rejected) as caught:
            self.parse(date({"entity": "helaman"}), date({"verse": "Alma 2:1"}, start="x"))
        self.assertIn("item 1", str(caught.exception))
        self.assertIn("item 2", str(caught.exception))

    def test_rejects_a_fact_twice_and_one_thing_dated_twice_in_a_system(self):
        self.rejects("twice", date({"chapter": "Alma 1"}), date({"chapter": "Alma 1"}))
        self.rejects("two dates in reign_of_judges", date({"chapter": "Alma 1"}), date({"chapter": "Alma 1"}, start=2))
        self.assertEqual(len(self.parse(date({"chapter": "Alma 1"}), date({"chapter": "Alma 1"}, "bc_ad", -599, evidence=None))), 2)

    def test_store_then_unstore_leaves_the_table_as_it_was(self):
        tags = self.parse(
            date({"verse": "Alma 1:2"}, evidence=SECOND_YEAR, start=2),
            date({"entity": "battle-of-alma"}, from_month=2, to_month=2),
            date({"relationship": {"subject": "helaman", "kind": "child_of", "object": "alma"}}, evidence=SECOND_YEAR),
            date({"chapter": "Alma 1"}, "bc_ad", -599, evidence=None),
        )
        self.layer.store(self.db, "alma/1", tags)
        self.assertEqual(len(self.rows()), 4)
        self.layer.unstore(self.db, "alma/1", tags)
        self.assertEqual(self.rows(), [])
        self.layer.unstore(self.db, "alma/1", tags)

    def test_unstore_takes_one_row_of_a_date_two_jobs_stored(self):
        tags = self.parse(date({"entity": "battle-of-alma"}, "bc_ad", -72, evidence=None))
        self.layer.store(self.db, "alma/1", tags)
        self.layer.store(self.db, "alma/2", tags)
        self.layer.unstore(self.db, "alma/1", tags)
        self.assertEqual(len(self.rows()), 1)

    def test_unstore_skips_a_relationship_that_is_gone(self):
        tags = self.parse(date({"relationship": {"subject": "helaman", "kind": "child_of", "object": "alma"}}, evidence=SECOND_YEAR))
        self.layer.store(self.db, "alma/1", tags)
        self.db.execute("delete from relationship where kind_id = 'child_of'")
        self.assertEqual(self.rows(), [])
        self.layer.unstore(self.db, "alma/1", tags)

    def test_given_holds_the_dates_a_script_stored_for_the_chapter(self):
        first, last = self.word("In"), self.word("Zarahemla")
        evidence = self.db.execute("select min(id), max(id) from word where verse = 1 and chapter = 1 and text in ('first', 'judges')").fetchone()
        self.db.execute(
            "insert into date (first_word_id, last_word_id, system_id, from_year, to_year, evidence_first_word_id, evidence_last_word_id) values (?, ?, 'reign_of_judges', 1, 1, ?, ?)",
            (first, last, *evidence),
        )
        given = self.layer.given(self.db, "alma/1")
        self.assertEqual(len(given), 1)
        self.assertEqual(self.layer.given(self.db, "alma/2"), [])
        with self.assertRaisesRegex(Rejected, "already tagged"):
            jobs.check(self.db, self.job, "a", [self.layer.render(self.db, given[0])])
        self.assertIn('"from": 1', prompt(self.db, self.job, "a"))

    def test_given_follows_an_event_named_and_a_relationship_cited_in_the_chapter(self):
        self.db.execute("insert into date (entity_id, system_id, from_year, to_year) values ('battle-of-alma', 'bc_ad', -72, -72)")
        self.db.execute("insert into date (relationship_id, system_id, from_year, to_year, evidence_first_word_id, evidence_last_word_id) values (1, 'bc_ad', -90, -90, ?, ?)", (self.word("Helaman"),) * 2)
        self.assertEqual(len(self.layer.given(self.db, "alma/1")), 1)
        mentioned = self.word("fierce")
        self.db.execute("insert into mention (entity_id, kind_id, first_word_id, last_word_id) values ('battle-of-alma', 'names', ?, ?)", (mentioned, mentioned))
        self.assertEqual(len(self.layer.given(self.db, "alma/1")), 2)
        self.assertEqual(len(self.layer.given(self.db, "alma/2")), 0)

    def test_shown_prints_the_chapters_dates_as_answers(self):
        self.layer.store(self.db, "alma/1", self.parse(date({"verse": "Alma 1:2"}, evidence=SECOND_YEAR, start=2)))
        shown = self.layer.shown(self.db, "bom-2013", "alma", 1)
        self.assertEqual(shown, [date({"verse": "Alma 1:2"}, evidence=SECOND_YEAR, start=2)])
        self.assertEqual(self.layer.shown(self.db, "bom-2013", "alma", 2), [])

    def test_context_lists_the_events_the_chapter_names(self):
        fierce = self.word("fierce")
        self.db.execute("insert into mention (entity_id, kind_id, first_word_id, last_word_id) values ('battle-of-alma', 'names', ?, ?)", (fierce, fierce))
        text = prompt(self.db, self.job, "a")
        self.assertIn("## Events named in this chapter\n\nbattle-of-alma Battle.", text)
        self.assertNotIn("## Events named", prompt(self.db, jobs.Job(self.layer, "alma/2"), "a"))

    def test_waits_for_the_relationships_job_when_there_is_one(self):
        self.assertIsNone(self.layer.ready(self.db, jobs.Jobs, "alma/1"))

        class Relationships(Layer):
            name = "relationships"
            step = 7

        with mock.patch.dict(LAYERS, {"relationships": Relationships()}):
            self.assertEqual(self.layer.ready(self.db, jobs.Jobs, "alma/1"), "relationships/alma/1 must settle first")
            jobs.Job(LAYERS["relationships"], "alma/1").write("settled", [])
            self.assertIsNone(self.layer.ready(self.db, jobs.Jobs, "alma/1"))

    def test_waits_for_the_earlier_steps(self):
        self.assertEqual(self.layer.ready(self.db, jobs.Jobs, "alma/2"), "names/alma/2 must settle first")

    def test_agreeing_runs_settle_store_and_replay(self):
        answer = [date({"verse": "Alma 1:2"}, evidence=SECOND_YEAR, start=2), date({"chapter": "Alma 1"}, "bc_ad", -599, evidence=None)]
        jobs.submit(self.db, self.job, "a", answer)
        jobs.submit(self.db, self.job, "b", list(reversed(answer)))
        self.assertEqual(self.job.state(self.db), "settled")
        self.assertEqual(len(self.rows()), 2)
        self.db.execute("delete from date")
        jobs.replay(self.db, [self.layer])
        self.assertEqual(len(self.rows()), 2)
        jobs.reset(self.db, self.job)
        self.assertEqual(self.rows(), [])

    def test_a_decider_settles_the_dates_the_runs_differ_on(self):
        agreed = date({"chapter": "Alma 1"}, "bc_ad", -599, evidence=None)
        jobs.submit(self.db, self.job, "a", [agreed, date({"verse": "Alma 1:2"}, evidence=SECOND_YEAR, start=2)])
        jobs.submit(self.db, self.job, "b", [agreed, date({"verse": "Alma 1:2"}, evidence=SECOND_YEAR, start=3)])
        self.assertEqual(self.job.state(self.db), "needs decider")
        jobs.submit(self.db, self.job, "decider", [date({"verse": "Alma 1:2"}, evidence=SECOND_YEAR, start=2)])
        self.assertEqual([year for (year,) in self.db.execute("select from_year from date order by id")], [-599, 2])


if __name__ == "__main__":
    unittest.main()

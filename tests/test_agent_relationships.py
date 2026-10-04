import unittest
from unittest import mock

from bomnerds.agent import jobs
from bomnerds.agent.layers import LAYERS, relationships
from bomnerds.agent.prompt import job_text
from bomnerds.passages import Rejected, resolve
from tests.agent_fixtures import database, entity, job_folder

GENESIS = {
    (5, 3): "And Adam lived an hundred and thirty years, and begat a son, and called his name Seth:",
    (5, 6): "And Seth lived an hundred and five years, and begat Enos:",
    (5, 7): "And Adam knew Eve his wife.",
    (6, 1): "These are the sons of Adam, even Seth.",
    (6, 2): "And Babylon was north of Eden.",
}


def passage(verse, quote):
    return {"verse": f"Genesis {verse}", "quote": quote}


def relationship(subject, kind, object, *evidence):
    return {"subject": subject, "kind": kind, "object": object, "evidence": list(evidence)}


SETH_CHILD_OF_ADAM = relationship("seth", "child_of", "adam", passage("5:3", "begat a son"))
ENOS_CHILD_OF_SETH = relationship("enos", "child_of", "seth", passage("5:6", "begat Enos"))


class RelationshipsTest(unittest.TestCase):
    def setUp(self):
        self.db = database([("bible", "Genesis", GENESIS)])
        for id, type_id in (("adam", "person"), ("eve", "person"), ("seth", "person"), ("enos", "person"), ("babylon", "city"), ("eden", "land")):
            entity(self.db, id, type_id, id.title(), books=("genesis",))
        folder = job_folder()
        folder.__enter__()
        self.addCleanup(folder.__exit__, None, None, None)
        self.layer = LAYERS["relationships"]
        self.job = jobs.Job(self.layer, "genesis/5")
        self.second = jobs.Job(self.layer, "genesis/6")

    def settle_earlier(self, scope):
        for layer in LAYERS.values():
            if layer.step < self.layer.step and layer.scope == "chapter" and scope in layer.scope_set(self.db):
                jobs.Job(layer, scope).write("settled", [])

    def parse(self, answer, scope="genesis/5"):
        return self.layer.parse(self.db, scope, answer)

    def rejection(self, answer, scope="genesis/5"):
        with self.assertRaises(Rejected) as caught:
            self.parse(answer, scope)
        return str(caught.exception)

    def span(self, verse, quote):
        return resolve(self.db, passage(verse, quote))

    def rows(self):
        return (
            list(self.db.execute("select subject_id, kind_id, object_id from relationship order by id")),
            list(self.db.execute("select relationship_id, first_word_id, last_word_id from relationship_evidence order by 1, 2, 3")),
        )

    def script_relationship(self, subject, kind, object, *spans):
        id = self.db.execute("insert into relationship (subject_id, kind_id, object_id) values (?, ?, ?)", (subject, kind, object)).lastrowid
        self.db.executemany("insert into relationship_evidence values (?, ?, ?)", [(id, first, last) for first, last in spans])

    def test_a_valid_answer_round_trips_through_render(self):
        answer = [SETH_CHILD_OF_ADAM, relationship("enos", "child_of", "seth", passage("5:6", "begat Enos"), passage("5:6", "Seth lived"))]
        tags = self.parse(answer)
        self.assertEqual(len(tags), 2)
        for tag in tags:
            self.assertEqual(self.parse([self.layer.render(self.db, tag)]), [tag])

    def test_evidence_order_does_not_make_a_difference(self):
        one = relationship("enos", "child_of", "seth", passage("5:6", "begat Enos"), passage("5:6", "Seth lived"))
        other = relationship("enos", "child_of", "seth", passage("5:6", "Seth lived"), passage("5:6", "begat Enos"))
        self.assertEqual(self.parse([one]), self.parse([other]))

    def test_two_way_kinds_agree_whichever_way_they_are_written(self):
        evidence = passage("5:7", "Adam knew Eve his wife")
        self.assertEqual(self.parse([relationship("adam", "spouse_of", "eve", evidence)]), self.parse([relationship("eve", "spouse_of", "adam", evidence)]))
        self.assertEqual(self.parse([relationship("eve", "spouse_of", "adam", evidence)])[0][:3], ("adam", "spouse_of", "eve"))

    def test_a_one_way_kind_keeps_its_direction(self):
        self.assertNotEqual(self.parse([SETH_CHILD_OF_ADAM]), self.parse([relationship("adam", "child_of", "seth", passage("5:3", "begat a son"))]))

    def test_rejects_a_kind_and_an_entity_that_are_not_listed(self):
        message = self.rejection([relationship("seth", "cousin_of", "adam", passage("5:3", "Seth")), relationship("noah", "child_of", "adam", passage("5:3", "Adam"))])
        self.assertIn("item 1: kind 'cousin_of' is not one of", message)
        self.assertIn("item 2: 'noah' is not on the entity list", message)

    def test_rejects_a_subject_equal_to_its_object(self):
        self.assertIn("cannot be near itself", self.rejection([relationship("eden", "near", "eden", passage("6:2", "Eden"))]))

    def test_rejects_a_family_kind_joining_something_other_than_two_people(self):
        message = self.rejection([relationship("babylon", "sibling_of", "eden", passage("6:2", "Babylon"))])
        self.assertIn("babylon is a city, but this must be a person", message)
        self.assertIn("eden is a land, but this must be a person", message)

    def test_places_may_take_other_kinds(self):
        self.assertEqual(len(self.parse([relationship("babylon", "north_of", "eden", passage("6:2", "Babylon was north of Eden"))], "genesis/6")), 1)

    def test_rejects_evidence_that_is_missing_empty_outside_the_chapter_or_repeated(self):
        self.assertIn("missing evidence", self.rejection([{"subject": "seth", "kind": "child_of", "object": "adam"}]))
        self.assertIn("at least one passage", self.rejection([relationship("seth", "child_of", "adam")]))
        self.assertIn("item 1, evidence 1: the passage must sit inside Genesis 5", self.rejection([relationship("seth", "child_of", "adam", passage("6:1", "sons of Adam"))]))
        self.assertIn("same passage twice", self.rejection([relationship("seth", "child_of", "adam", passage("5:3", "Seth"), passage("5:3", "Seth"))]))
        self.assertIn("item 1, evidence 2", self.rejection([relationship("seth", "child_of", "adam", passage("5:3", "Seth"), passage("5:3", "Noah"))]))

    def test_rejects_an_unknown_field(self):
        self.assertIn("unknown field when", self.rejection([{**SETH_CHILD_OF_ADAM, "when": "long ago"}]))

    def test_rejects_the_same_relationship_twice_in_an_answer(self):
        other = relationship("seth", "child_of", "adam", passage("5:3", "Adam lived"))
        self.assertIn("item 2: this is the same subject, kind, and object as item 1", self.rejection([SETH_CHILD_OF_ADAM, other]))

    def test_rejects_a_two_way_kind_written_both_ways(self):
        evidence = passage("5:7", "Adam knew Eve his wife")
        self.assertIn("same subject, kind, and object as item 1", self.rejection([relationship("adam", "spouse_of", "eve", evidence), relationship("eve", "spouse_of", "adam", evidence)]))

    def test_rejects_a_one_way_kind_running_both_ways_in_an_answer(self):
        message = self.rejection([SETH_CHILD_OF_ADAM, relationship("adam", "child_of", "seth", passage("5:3", "Adam lived"))])
        self.assertIn("item 2: child_of runs both ways with item 1, which says seth child_of adam", message)

    def test_rejects_a_one_way_kind_running_the_other_way_from_what_is_stored(self):
        self.script_relationship("adam", "child_of", "seth", self.span("5:3", "Seth"))
        self.assertIn("adam child_of seth is already stored", self.rejection([SETH_CHILD_OF_ADAM]))

    def test_accepts_a_stored_relationship_in_the_same_direction_so_it_gains_evidence(self):
        self.script_relationship("seth", "child_of", "adam", self.span("5:3", "Seth"))
        self.assertEqual(len(self.parse([SETH_CHILD_OF_ADAM])), 1)

    def test_store_then_unstore_leaves_the_tables_as_they_were(self):
        self.script_relationship("seth", "child_of", "adam", self.span("5:3", "Seth"))
        before = self.rows()
        tags = self.parse([SETH_CHILD_OF_ADAM, ENOS_CHILD_OF_SETH, relationship("eve", "spouse_of", "adam", passage("5:7", "Adam knew Eve his wife"))])
        with self.db:
            self.layer.store(self.db, "genesis/5", tags)
        self.assertEqual(len(self.rows()[0]), 3)
        with self.db:
            self.layer.unstore(self.db, "genesis/5", tags)
        self.assertEqual(self.rows(), before)

    def test_a_relationship_found_in_two_chapters_is_one_relationship_with_more_evidence(self):
        here = self.parse([SETH_CHILD_OF_ADAM])
        there = self.parse([relationship("seth", "child_of", "adam", passage("6:1", "sons of Adam, even Seth"))], "genesis/6")
        with self.db:
            self.layer.store(self.db, "genesis/5", here)
            self.layer.store(self.db, "genesis/6", there)
        relationships, evidence = self.rows()
        self.assertEqual(relationships, [("seth", "child_of", "adam")])
        self.assertEqual(len(evidence), 2)
        with self.db:
            self.layer.unstore(self.db, "genesis/5", here)
        relationships, evidence = self.rows()
        self.assertEqual(relationships, [("seth", "child_of", "adam")])
        self.assertEqual([e[1:] for e in evidence], [self.span("6:1", "sons of Adam, even Seth")])
        with self.db:
            self.layer.unstore(self.db, "genesis/6", there)
        self.assertEqual(self.rows(), ([], []))

    def test_storing_a_two_way_kind_either_way_reuses_the_row(self):
        evidence = passage("5:7", "Adam knew Eve his wife")
        with self.db:
            self.layer.store(self.db, "genesis/5", self.parse([relationship("eve", "spouse_of", "adam", evidence)]))
            self.layer.store(self.db, "genesis/6", [("eve", "spouse_of", "adam", ((1, 1),))])
        self.assertEqual(self.rows()[0], [("adam", "spouse_of", "eve")])

    def test_storing_a_one_way_kind_against_the_stored_direction_is_rejected(self):
        self.script_relationship("adam", "child_of", "seth", self.span("5:3", "Seth"))
        with self.assertRaisesRegex(Rejected, "contradicts the stored"), self.db:
            self.layer.store(self.db, "genesis/5", [("seth", "child_of", "adam", (self.span("5:3", "Adam"),))])

    def test_unstoring_what_is_gone_is_fine(self):
        with self.db:
            self.layer.unstore(self.db, "genesis/5", self.parse([SETH_CHILD_OF_ADAM]))
        self.assertEqual(self.rows(), ([], []))

    def test_script_relationships_are_given_for_the_chapters_their_evidence_sits_in(self):
        self.script_relationship("seth", "child_of", "adam", self.span("5:3", "Seth"), self.span("6:1", "Seth"))
        given = self.layer.given(self.db, "genesis/5")
        self.assertEqual(given, [("seth", "child_of", "adam", (self.span("5:3", "Seth"),))])
        self.assertEqual(self.layer.given(self.db, "genesis/6"), [("seth", "child_of", "adam", (self.span("6:1", "Seth"),))])
        self.assertEqual(self.layer.render(self.db, given[0])["evidence"], [passage("5:3", "Seth")])

    def test_what_is_given_is_rejected_but_extra_evidence_for_it_is_not(self):
        self.script_relationship("seth", "child_of", "adam", self.span("5:3", "Seth"))
        self.settle_earlier("genesis/5")
        with self.assertRaisesRegex(Rejected, "already tagged"):
            jobs.check(self.db, self.job, [relationship("seth", "child_of", "adam", passage("5:3", "Seth"))])
        more = relationship("seth", "child_of", "adam", passage("5:3", "Adam lived"))
        self.assertEqual(len(jobs.check(self.db, self.job, [more])), 1)
        self.assertIn("Already stored", job_text(self.db, self.job))

    def test_a_settled_job_adds_evidence_to_a_script_relationship_and_shows_it(self):
        self.script_relationship("seth", "child_of", "adam", self.span("5:3", "Seth"))
        self.settle_earlier("genesis/5")
        answer = [relationship("seth", "child_of", "adam", passage("5:3", "Adam lived")), ENOS_CHILD_OF_SETH]
        jobs.submit(self.db, self.job, answer)
        self.assertIsNotNone(self.job.settled())
        shown = self.layer.shown(self.db, "kjv", "genesis", 5)
        self.assertEqual([(s["subject"], s["object"], len(s["evidence"])) for s in shown], [("seth", "adam", 2), ("enos", "seth", 1)])
        self.assertEqual(shown[0]["evidence"], [passage("5:3", "Adam lived"), passage("5:3", "Seth")])

    def test_reset_deletes_only_this_jobs_evidence(self):
        self.settle_earlier("genesis/5")
        self.settle_earlier("genesis/6")
        other = relationship("seth", "child_of", "adam", passage("6:1", "sons of Adam, even Seth"))
        for job, answer in ((self.job, [SETH_CHILD_OF_ADAM]), (self.second, [other])):
            jobs.submit(self.db, job, answer)
        jobs.reset(self.db, self.job)
        self.assertEqual(self.rows()[0], [("seth", "child_of", "adam")])
        self.assertEqual(len(self.rows()[1]), 1)
        jobs.reset(self.db, self.second)
        self.assertEqual(self.rows(), ([], []))

    def test_reset_keeps_a_script_relationship_that_had_no_evidence_before(self):
        self.db.execute("insert into relationship (subject_id, kind_id, object_id) values ('seth', 'child_of', 'adam')")
        self.settle_earlier("genesis/5")
        jobs.submit(self.db, self.job, [SETH_CHILD_OF_ADAM])
        with mock.patch.object(relationships, "script_facts", return_value={("seth", "child_of", "adam")}):
            jobs.reset(self.db, self.job)
        self.assertEqual(self.rows(), ([("seth", "child_of", "adam")], []))

    def test_replay_stores_settled_jobs_again(self):
        self.settle_earlier("genesis/5")
        jobs.submit(self.db, self.job, [SETH_CHILD_OF_ADAM])
        before = self.rows()
        self.db.execute("delete from relationship")
        jobs.replay(self.db, [self.layer])
        self.assertEqual(self.rows(), before)

    def test_the_prompt_lists_every_kind_with_how_it_reads(self):
        self.settle_earlier("genesis/5")
        text = job_text(self.db, self.job)
        self.assertIn("child_of: subject, child of, object (reads back as parent of)", text)
        self.assertIn("spouse_of: subject, spouse of, object (two-way, stored once)", text)
        self.assertIn("And Seth lived", text)


if __name__ == "__main__":
    unittest.main()

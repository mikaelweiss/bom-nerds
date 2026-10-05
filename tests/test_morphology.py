import csv
import sqlite3
import unittest
from pathlib import Path

from bomnerds import morphology
from bomnerds.sources import fetch

ROOT = Path(__file__).resolve().parent.parent


class HebrewTest(unittest.TestCase):
    def test_a_finite_verb(self):
        self.assertEqual(
            morphology.hebrew("Vqp3ms", aramaic=False),
            {"part_of_speech": "Verb", "stem": "Qal", "verb_form": "Perfect", "person": 3, "gender": "Masculine", "grammatical_number": "Singular"},
        )

    def test_a_participle_takes_a_state_and_no_person(self):
        self.assertEqual(
            morphology.hebrew("Vqrmpc", aramaic=False),
            {"part_of_speech": "Verb", "stem": "Qal", "verb_form": "Active participle", "gender": "Masculine", "grammatical_number": "Plural", "state": "Construct"},
        )

    def test_aramaic_reads_stem_letters_its_own_way(self):
        self.assertEqual(morphology.hebrew("Vhp3ms", aramaic=False)["stem"], "Hiphil")
        self.assertEqual(morphology.hebrew("Vhp3ms", aramaic=True)["stem"], "Haphel")

    def test_x_leaves_a_feature_out(self):
        self.assertEqual(morphology.hebrew("Pdxms", aramaic=True), {"part_of_speech": "Pronoun", "word_type": "Demonstrative", "gender": "Masculine", "grammatical_number": "Singular"})

    def test_a_proper_name_is_a_proper_noun(self):
        self.assertEqual(morphology.hebrew("Np", aramaic=False), {"part_of_speech": "Proper noun"})

    def test_an_article_and_an_interjection_take_their_own_parts_of_speech(self):
        self.assertEqual(morphology.hebrew("Td", aramaic=False), {"part_of_speech": "Article"})
        self.assertEqual(morphology.hebrew("Tj", aramaic=False), {"part_of_speech": "Interjection"})
        self.assertEqual(morphology.hebrew("Rd", aramaic=False), {"part_of_speech": "Preposition", "word_type": "Definite article"})

    def test_rejects_what_it_cannot_read(self):
        for code in ("Xc", "Tdx", "Vqz3ms", "Ncfsaa", "Ncqsa", "Vq"):
            with self.subTest(code=code), self.assertRaises(ValueError):
                morphology.hebrew(code, aramaic=False)


class GreekTest(unittest.TestCase):
    def test_a_second_aorist(self):
        features = morphology.greek("V-2AAI-3S")
        self.assertEqual(
            {k: v for k, v in features.items() if v is not False},
            {"part_of_speech": "Verb", "second_form": True, "tense": "Aorist", "voice": "Active", "mood": "Indicative", "person": 3, "grammatical_number": "Singular"},
        )

    def test_a_participle(self):
        features = morphology.greek("V-PAP-NSM")
        self.assertEqual((features["mood"], features["grammatical_case"], features["gender"]), ("Participle", "Nominative", "Masculine"))
        self.assertNotIn("person", features)

    def test_a_possessive_pronoun_has_its_possessors_number(self):
        features = morphology.greek("S-1PASF")
        self.assertEqual(
            (features["word_type"], features["person"], features["possessor_number"], features["grammatical_case"], features["grammatical_number"], features["gender"]),
            ("Possessive", 1, "Plural", "Accusative", "Singular", "Feminine"),
        )

    def test_suffixes(self):
        self.assertEqual(morphology.greek("A-NSM-C")["degree"], "Comparative")
        self.assertEqual(morphology.greek("PRT-N")["word_type"], "Negative")
        self.assertTrue(morphology.greek("P-1NS-K")["crasis"])
        self.assertTrue(morphology.greek("V-RAI-3S-ATT")["attic_form"])

    def test_indeclinable_and_transliterated_words(self):
        self.assertEqual((morphology.greek("N-PRI")["part_of_speech"], morphology.greek("N-PRI")["indeclinable"]), ("Proper noun", True))
        self.assertEqual(morphology.greek("HEB")["transliterated_from"], "hbo")
        self.assertNotIn("part_of_speech", morphology.greek("ARAM"))

    def test_rejects_what_it_cannot_read(self):
        for code in ("Z-NSM", "N-NSX", "V-PAI", "V-PAN-3S", "A-NSM-Q", "P-1SNSM", "V-PAI-3SX"):
            with self.subTest(code=code), self.assertRaises(ValueError):
                morphology.greek(code)


class MaculaTest(unittest.TestCase):

    def codes(self, name):
        with open(fetch(name), encoding="utf-8") as rows:
            return {(row["morph"], row.get("lang")) for row in csv.DictReader(rows, delimiter="\t", quoting=csv.QUOTE_NONE)}

    def test_every_hebrew_and_aramaic_code(self):
        codes = self.codes("macula-hebrew.tsv")
        self.assertGreater(len(codes), 800)
        for code, language in codes:
            with self.subTest(code=code, language=language):
                morphology.hebrew(code, aramaic=language == "A")

    def test_every_greek_code(self):
        codes = self.codes("macula-greek-SBLGNT.tsv")
        self.assertGreater(len(codes), 1000)
        for code, _ in codes:
            with self.subTest(code=code):
                morphology.greek(code)

    def test_every_value_is_in_its_list(self):
        db = sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        db.executescript((ROOT / "db/schema.sql").read_text())
        db.executescript((ROOT / "db/seed.sql").read_text())
        lists = {"possessor_number": "grammatical_number", "part_of_speech": "part_of_speech"}
        found = set()
        for code, language in self.codes("macula-hebrew.tsv"):
            found.update(morphology.hebrew(code, aramaic=language == "A").items())
        for code, _ in self.codes("macula-greek-SBLGNT.tsv"):
            found.update(morphology.greek(code).items())
        for feature, value in found:
            if isinstance(value, str) and feature != "transliterated_from":
                table = lists.get(feature, feature)
                with self.subTest(table=table, value=value):
                    self.assertIsNotNone(db.execute(f"select id from {table} where name = ?", (value,)).fetchone())


if __name__ == "__main__":
    unittest.main()

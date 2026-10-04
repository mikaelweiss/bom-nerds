import unittest

from bomnerds import dates, entities, grammar, headwords, links, mentions, sentences, strongs, tipnr, versification


def words(text: str) -> list[tuple[int, str]]:
    return list(enumerate(text.lower().split(), 1))


class DatesTest(unittest.TestCase):
    def test_reads_number_words(self):
        self.assertEqual(dates.number("an hundred and ninety and four".split()), 194)
        self.assertEqual(dates.number("four hundred and seventy-six".split()), 476)
        self.assertEqual(dates.number("one thousand eight hundred and thirty-two".split()), 1832)
        self.assertEqual(dates.number("twenty and first".split()), 21)

    def test_finds_the_year_a_verse_takes_place_in(self):
        [date] = dates.dates_in(words("Now it came to pass in the first year of the reign of the judges"))
        self.assertEqual(date[2:4], ("reign_of_judges", 1))

    def test_a_year_counted_toward_is_not_when(self):
        self.assertEqual(dates.dates_in(words("there was much peace until the fifth year of the reign of the judges")), [])

    def test_a_year_covers_what_follows_until_it_ends(self):
        verses = [words(t) for t in ("in the first year of the reign of the judges there was peace", "and Alma taught", "and thus ended the first year", "in the second year")]
        ids = iter(range(1, 100))
        verses = [[(next(ids), t) for _, t in v] for v in verses]
        [date] = dates.dates_in(verses[0])
        self.assertEqual(dates.extend(date, verses[1:], verses[0])[:2], (1, verses[2][-1][0]))

    def test_reads_the_day_and_month(self):
        [date] = dates.dates_in(words("on the sixteenth day of February in the year of our Lord one thousand eight hundred and thirty-two"))
        self.assertEqual(date[2:6], ("bc_ad", 1832, 2, 16))


class VersificationTest(unittest.TestCase):
    def test_expands_titles_and_ranges_across_chapters(self):
        known = {"psalms": [("psalms", 3, n) for n in range(0, 9)], "revelation": [("revelation", 12, 17), ("revelation", 12, 18), ("revelation", 13, 1)]}
        books = {"PSA": "psalms", "REV": "revelation"}
        self.assertEqual(versification.expand("Psa.3:Title", books, known), [("psalms", 3, 0)])
        self.assertEqual(versification.expand("Rev.12:18-13:1", books, known), [("revelation", 12, 18), ("revelation", 13, 1)])
        self.assertEqual(versification.expand("Absent [=Psa.3:1]", books, known), [])


class StrongsTest(unittest.TestCase):
    def test_a_tagged_phrase_is_one_translation(self):
        units = strongs.translation_units([(1, ("G1125",)), (2, ("G1125",)), (3, ("G1125",)), (4, ()), (5, ("G0444",))])
        self.assertEqual(units, {"G1125": [[1, 2, 3]], "G0444": [[5]]})


class LinksTest(unittest.TestCase):
    def test_runs_allow_an_added_verse(self):
        followed = {("2-nephi", 12, 1): ("isaiah", 2, 1), ("2-nephi", 12, 2): ("isaiah", 2, 2), ("2-nephi", 12, 4): ("isaiah", 2, 3), ("2-nephi", 12, 9): ("isaiah", 9, 1)}
        self.assertEqual([len(run) for run in links.runs(followed)], [3, 1])

    def test_a_lone_verse_must_share_more_than_stock_words(self):
        rarity = {"the": 0.1, "lord": 1.5, "spake": 2.5, "unto": 0.6, "saying": 2.0, "in": 0.5, "and": 0.1, "it": 1.0, "not": 1.0, "light": 6.0, "shineth": 9.0, "darkness": 6.0}
        self.assertFalse(links.distinctive(words("the lord spake unto them saying"), words("the lord spake unto me saying"), rarity))
        self.assertTrue(links.distinctive(
            words("the light shineth in darkness and the darkness comprehendeth it not"), words("the light shineth in darkness and the darkness comprehended it not"), rarity
        ))


class EntitiesTest(unittest.TestCase):
    def test_names_a_people_by_its_gentilic(self):
        def record(name, *renderings):
            return tipnr.Record(f"{name}@Gen.1.1", "PERSON(s)", "Male", [], forms=[tipnr.NameForm("Group", "H1", r, []) for r in renderings])

        self.assertEqual(entities.people_name(record("Levi", "Levite")), "Levites")
        self.assertEqual(entities.people_name(record("Ishvi", "Jesui")), "Jesuites")
        self.assertEqual(entities.people_name(record("Cush", "Cushi,Ethiopian", "Cushitess")), "Ethiopians")
        self.assertIsNone(entities.people_name(record("Esau", "Esau")))

    def test_splits_names_tipnr_lists_together(self):
        self.assertEqual(entities.split_names("Ammonite,Ammon"), ["Ammonite", "Ammon"])
        self.assertEqual(entities.split_names("City of/ the Lord"), ["City of the Lord"])


class MentionsTest(unittest.TestCase):
    JUDAH = mentions.Name("judah-son-of-israel", "jews", frozenset({"Jew", "Jews"}), "Judah@Gen.29.35-Rev")

    def meaning(self, text, book="isaiah", chapter=1):
        texts = dict(enumerate(text.split(), 1))
        return mentions.meaning(self.JUDAH, max(id for id, t in texts.items() if t.startswith(("Judah", "Jew"))), texts, book, chapter)

    def test_the_words_before_an_eponym_settle_what_it_means(self):
        self.assertEqual(self.meaning("the tribe of Judah"), "tribe-of-judah")
        self.assertEqual(self.meaning("the cities of Judah"), "land-of-judah")
        self.assertEqual(self.meaning("Hezekiah king of Judah"), "land-of-judah")

    def test_an_eponym_with_nothing_to_settle_it_is_left_for_the_ai(self):
        self.assertIsNone(self.meaning("concerning Judah and Jerusalem"))

    def test_genesis_names_the_man(self):
        self.assertEqual(self.meaning("and Judah said", "genesis", 38), "judah-son-of-israel")
        self.assertIsNone(self.meaning("Judah is a lion's whelp", "genesis", 49))

    def test_a_gentilic_word_names_the_people(self):
        self.assertEqual(self.meaning("the Jews"), "jews")


class SentencesTest(unittest.TestCase):
    def test_ends_at_a_period_but_not_after_an_initial_or_jun(self):
        chapter = [
            (1, "dc", "doctrine-and-covenants", 102, 1, "Samuel", " "), (2, "dc", "doctrine-and-covenants", 102, 1, "H", ". "),
            (3, "dc", "doctrine-and-covenants", 102, 1, "Smith", ", "), (4, "dc", "doctrine-and-covenants", 102, 1, "Jun", "., "),
            (5, "dc", "doctrine-and-covenants", 102, 1, "spoke", ": "), (6, "dc", "doctrine-and-covenants", 102, 1, "Amen", ". "),
            (7, "dc", "doctrine-and-covenants", 102, 1, "Then", " "), (8, "dc", "doctrine-and-covenants", 102, 1, "rose", "."),
        ]
        self.assertEqual(sentences.split(chapter), [(1, 6), (7, 8)])


class HeadwordsTest(unittest.TestCase):
    def test_archaic_verb_forms(self):
        verbs = {"give", "love", "sit", "cry"}
        self.assertEqual(headwords.archaic_verb("giveth", "lord", set(), verbs, None), "give")
        self.assertEqual(headwords.archaic_verb("sitteth", "he", set(), verbs, None), "sit")
        self.assertEqual(headwords.archaic_verb("crieth", "he", set(), verbs, None), "cry")
        self.assertEqual(headwords.archaic_verb("lovest", "thou", {"thou", "lovest"}, verbs, None), "love")
        self.assertIsNone(headwords.archaic_verb("greatest", "the", {"thou", "greatest"}, verbs, None))

    def test_a_one_letter_stem_is_not_a_verb(self):
        verbs = {"se", "be", "see"}
        self.assertIsNone(headwords.archaic_verb("seth", "and", set(), verbs, None))
        self.assertIsNone(headwords.archaic_verb("best", "thy", {"thou", "best"}, verbs, None))
        self.assertEqual(headwords.archaic_verb("seeth", "he", set(), verbs, None), "see")

    def test_a_name_in_capitals_shares_the_names_headword(self):
        self.assertEqual(headwords.spelled("babylon", "proper_noun", "BABYLON"), "Babylon")
        self.assertEqual(headwords.spelled("Babylon", "proper_noun", "Babylon"), "Babylon")

    def test_two_runs_agree_or_morphadorner_breaks_the_tie(self):
        self.assertEqual(headwords.vote("go", "go", "went"), "go")
        self.assertEqual(headwords.vote("go", "went", "go"), "go")
        self.assertIsNone(headwords.vote("go", "went", "goes"))

    def test_nupos_tags(self):
        self.assertEqual(headwords.nupos("pp-f", "of"), "preposition")
        self.assertEqual(headwords.nupos("pns11", "i"), "pronoun")
        self.assertEqual(headwords.nupos("np1", "Nephi"), "proper_noun")
        self.assertEqual(headwords.nupos("vvz", "give"), "verb")
        self.assertEqual(headwords.nupos("dt", "the"), "article")


class GrammarTest(unittest.TestCase):
    def test_verb_with_auxiliary_and_not(self):
        children = {3: [1, 2]}
        tags = {1: ("AUX", "aux"), 2: ("PART", "neg"), 3: ("VERB", "ROOT")}
        texts = {1: "shalt", 2: "not", 3: "kill"}
        self.assertEqual(grammar.verb_span(3, children, tags, texts), (1, 3))

    def test_no_verb_part_when_the_subject_splits_it(self):
        children = {4: [1, 3]}
        tags = {1: ("AUX", "aux"), 2: ("DET", "det"), 3: ("PROPN", "nsubj"), 4: ("VERB", "ROOT")}
        texts = {1: "hath", 2: "the", 3: "lord", 4: "commanded"}
        self.assertIsNone(grammar.verb_span(4, children, tags, texts))

    def test_drops_agreed_parts_that_overlap(self):
        parts = {("subject", (1, 3)), ("verb", (3, 3)), ("subject", (5, 6))}
        self.assertEqual(grammar.apart(parts), [("subject", (5, 6))])


if __name__ == "__main__":
    unittest.main()

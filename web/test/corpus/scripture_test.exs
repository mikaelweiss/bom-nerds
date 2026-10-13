defmodule Corpus.ScriptureTest do
  use CorpusWeb.ConnCase, async: false

  alias Corpus.{Fixture, Scripture, Spans}

  @moduletag :tmp_dir
  @moduletag :reader

  setup :serve_fixture

  describe "verse/1" do
    test "a speech, link, and mention that start in an earlier verse show on the verses they cover" do
      verse = Scripture.verse(3)

      assert verse.reference == "Genesis 1:2"

      assert [
               %{mode: "Spoken", speakers: [%{name: "God"}], listeners: [%{name: "Moses"}]} =
                 speech
             ] =
               verse.speeches

      assert speech.through == %{id: 1, name: "Nephi"}
      assert speech.range.reference == "Genesis 1:1-2"

      assert [%{kind: "Parallel", text: "Thus the heavens were finished."} = link] = verse.links
      assert link.range.reference == "Genesis 2:1"
      assert link.range.first.book == "genesis"

      assert [%{id: 2, name: "Moses"}] = verse.about
      assert [%{name: "Jerusalem"}] = verse.settings
      assert [%{kind: "Chiasm"}] = verse.structures
      assert [%{name: "The Creation"}] = verse.passages
    end

    test "a speech, link, and mention that end before a verse do not show on it" do
      verse = Scripture.verse(4)

      assert verse.speeches == []
      assert verse.about == []
      assert verse.structures == []
      assert [%{kind: "Parallel", text: "the beginning. And the" <> _} = link] = verse.links
      assert link.range.reference == "Genesis 1:1-2"
    end

    test "names the people, setting, and date of a verse" do
      verse = Scripture.verse(5)

      assert [%{speakers: [%{name: "Nephi"}], listeners: [%{name: "Lehi"}]}] = verse.speeches
      assert [%{id: 1, name: "Nephi"}] = verse.named
      assert [%{name: "Jerusalem"}] = verse.settings
      assert [%{text: "600 to 592 BC", system: "BC/AD"}] = verse.dates

      assert [%{kind: "Cross-reference", text: "In the beginning."}] = verse.links
    end

    test "is nil for a verse that does not exist" do
      assert Scripture.verse(999) == nil
    end
  end

  describe "word/1" do
    test "a KJV word has its definition, the Greek it translates, and that word's other renderings" do
      word = Scripture.word(Fixture.word(Fixture.sequence(:beginning)))

      assert word.headword.text == "beginning"
      assert word.meaning.gloss == "That which is first"
      assert word.location.verse == 1

      assert [greek] = word.originals
      assert greek.text == "ἀρχῇ"
      assert greek.headword == %{text: "ἀρχή", strongs: "G0746", gloss: "beginning"}
      assert greek.grammar == ["Noun", "Dative", "Feminine", "Singular"]
      assert %{phrase: "the beginning", count: 1} in greek.renderings
      assert %{phrase: "magistrates", count: 1} in greek.renderings
    end

    test "an original word has its grammar and its KJV renderings" do
      word = Scripture.word(Fixture.word(Fixture.sequence(:reshit)))

      assert word.rtl
      assert word.headword.strongs == "H7225"
      assert word.grammar == ["Noun", "Common", "Feminine", "Singular", "Absolute"]

      assert %{text: "beginning.", location: %{edition: "kjv", verse: 1}, position: 3} =
               word.translations

      assert word.parallels == []
      assert word.renderings == [%{phrase: "beginning.", count: 1}]
      assert word.originals == []
    end

    test "names the entity a word refers to" do
      word = Scripture.word(Fixture.word(Fixture.sequence(:word)))

      assert [%{name: "God"}] = word.refers_to
      assert [%{text: "λόγος"}] = word.originals
    end

    test "a word with no original shows only what it has" do
      word = Scripture.word(Fixture.word(1))

      assert word.headword == nil
      assert word.originals == []
      assert word.refers_to == []
    end
  end

  describe "entity/1" do
    test "lists the verses that name it, book by book" do
      entity = Scripture.entity(1)

      assert [%{book_name: "1 Nephi", count: 1, verses: [%{chapter: 3, verse: 7}]}] = entity.named
      assert [%{label: "child of", other: %{name: "Lehi"}}] = entity.relationships
      assert Scripture.entity_verses(1, 2, 2) == hd(entity.named).verses
    end

    test "is nil for an entity that does not exist" do
      assert Scripture.entity(999) == nil
    end
  end

  test "measures the longest range of each kind once per release" do
    database = Corpus.Database.get("v1")

    assert Spans.longest(database, :mention) == 7
    assert Spans.longest(database, :link_to) == 4
    assert %{speech: 6} = Corpus.Cache.get({:spans, "data-1"})
  end

  describe "chapter/3" do
    test "rebuilds the text and finds the neighboring chapters" do
      chapter = Scripture.chapter("kjv", "genesis", 2)

      assert chapter.previous.chapter == 1
      assert %{book: "luke", chapter: 12} = chapter.next
      assert Scripture.chapter("kjv", "genesis", 3) == nil
      assert Scripture.chapter("kjv", "exodus", 1) == nil
    end

    test "finds one verse with its location" do
      verse = Scripture.find_verse("sblgnt", "john", 1, 1)

      assert Enum.map_join(verse.words, &(&1.before <> &1.text <> &1.after)) ==
               "Ἐν ἀρχῇ ἦν ὁ λόγος, "

      assert verse.location.book_name == "John"
    end
  end
end

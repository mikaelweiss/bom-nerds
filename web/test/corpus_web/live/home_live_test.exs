defmodule CorpusWeb.HomeLiveTest do
  use CorpusWeb.ConnCase, async: false

  import Phoenix.LiveViewTest

  alias Corpus.Fixture

  @moduletag :tmp_dir

  @stepbible_and_isaiah """
  alter table entity add column tipnr text;
  update entity set tipnr = 'Moses|1' where id = 2;
  update entity set tipnr = 'Jerusalem|1' where id = 5;
  delete from passage_link;
  insert into book values (900, 1, 'Isaiah');
  insert into edition_book values (1, 900, 9);
  insert into chapter values (900, 1, 900, 40);
  insert into verse values (900, 900, 1);
  insert into word (id, verse_id, position, sequence, text, before, after)
    values (9001, 900, 1, 9001, 'Comfort', '', ' ');
  insert into passage_link values
    (1, 1, #{Fixture.word(16)}, #{Fixture.word(17)}, 9001, 9001),
    (2, 6, #{Fixture.word(16)}, #{Fixture.word(17)}, 9001, 9001),
    (3, 6, #{Fixture.word(2)}, #{Fixture.word(4)}, 9001, 9001);
  """

  describe "with a release installed" do
    @describetag :reader
    @describetag fixture_sql: @stepbible_and_isaiah
    setup :serve_fixture

    test "shows the headline and none of the old slogan", %{conn: conn} do
      {:ok, view, html} = live(conn, "/")

      assert has_element?(view, "h1", "The Scriptures Demystified")
      assert page_title(view) =~ "The Scriptures Demystified"
      refute html =~ "connected"
      refute html =~ "Every word of the standard works"
    end

    test "the hero buttons go to the reader and the data browser", %{conn: conn} do
      {:ok, view, _html} = live(conn, "/")

      assert has_element?(view, ~s(#start-reading[href="/read"]), "Start reading")
      assert has_element?(view, ~s(#browse-data[href="/data"]), "Browse the data")
    end

    test "the hero verse opens with a word selected", %{conn: conn} do
      {:ok, view, _html} = live(conn, "/")

      assert has_element?(view, "#hero-verse", "John 1:1")
      assert has_element?(view, ~s(#hero-verse section[aria-label="About the word Word"]))
      assert has_element?(view, "#hero-verse", "λόγος")
      assert has_element?(view, ~s(#hero-verse section[aria-label="About John 1:1"]))
    end

    test "clicking a word in the hero verse opens its panel", %{conn: conn} do
      {:ok, view, _html} = live(conn, "/")

      view
      |> element(~s(#hero-verse [data-word="#{Fixture.word(Fixture.sequence(:beginning))}"]))
      |> render_click()

      assert has_element?(view, ~s(#hero-verse section[aria-label="About the word beginning"]))
      assert has_element?(view, "#hero-verse", "ἀρχή")
      assert has_element?(view, "#hero-verse", "That which is first")
      refute has_element?(view, ~s(#hero-verse section[aria-label="About the word Word"]))
    end

    test "study cards show the fixture's findings and leave out the rest", %{conn: conn} do
      {:ok, view, _html} = live(conn, "/")

      assert has_element?(view, ~s(#finding-lehi[href="/entities/4"]), "Lehi had 1 child: Nephi.")
      assert has_element?(view, "#finding-lehi", "the record names 1 of his descendants")

      assert has_element?(
               view,
               ~s(#finding-beginning[href="/read/kjv/genesis/1?v=1"]),
               "first appears in Genesis 1:1. The KJV translates it once"
             )

      assert has_element?(view, "#finding-beginning", "H7225")

      assert has_element?(
               view,
               ~s(#finding-isaiah[href="/examples/isaiah"]),
               "quotes Isaiah in 1 passage, spread over 1 of its chapters. 1 Nephi holds 1 of them."
             )

      for id <- ~w(moroni alma) do
        refute has_element?(view, "#finding-#{id}")
      end
    end

    test "the scholars section shows the fixture's counts and links on", %{conn: conn} do
      {:ok, view, _html} = live(conn, "/")

      assert has_element?(view, "#scholars-alignment", "5 KJV words are aligned")
      assert has_element?(view, "#scholars-links", "3 typed links between passages")
      assert has_element?(view, "#scholars-links div", "Cross-reference 2")
      assert has_element?(view, "#scholars-links div", "Quotes 1")
      assert has_element?(view, "#scholars-entities", "7 people, places, groups, and more")
      assert has_element?(view, "#scholars-entities", "2 carry a STEPBible id")
      assert has_element?(view, "#scholars-entities div", "Person 6")
      assert has_element?(view, "#scholars-evidence div", "Relationships 2")

      assert has_element?(
               view,
               "#scholars-text",
               "10 verses and 40 words, counted across 4 editions"
             )

      assert has_element?(view, ~s(#scholars-sources a[href$="/CREDITS.md"]))
      assert has_element?(view, ~s(#scholars-data[href="/data"]))
      assert has_element?(view, ~s(#scholars-build[href="/build"]))
      refute render(view) =~ "study notes"
    end
  end

  test "renders the headline and buttons without a release installed", %{conn: conn} do
    {:ok, view, _html} = live(conn, "/")

    assert has_element?(view, "h1", "The Scriptures Demystified")
    assert has_element?(view, ~s(#start-reading[href="/read"]))
    assert has_element?(view, ~s(#browse-data[href="/data"]))
    refute has_element?(view, "#hero-verse")
    refute has_element?(view, "#study")
    refute has_element?(view, "#scholars")
  end
end

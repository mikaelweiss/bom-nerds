defmodule CorpusWeb.ChapterLiveTest do
  use CorpusWeb.ConnCase, async: false

  import Phoenix.LiveViewTest

  alias Corpus.{Fixture, Scripture}

  @moduletag :tmp_dir

  describe "with a release installed" do
    @describetag :reader
    setup :serve_fixture

    test "rebuilds the chapter's text exactly, with the heading above verse 1", %{conn: conn} do
      {:ok, view, html} = live(conn, "/read/kjv/genesis/1")

      assert words(conn, "/read/kjv/genesis/1", "#v1") == "In the beginning. "
      assert words(conn, "/read/kjv/genesis/1", "#v2") == "And the earth was void. "
      assert has_element?(view, "#v2 span.italic", "was")

      assert has_element?(view, "#v", "Genesis")
      assert :binary.match(html, ~s(id="v")) < :binary.match(html, ~s(id="v1"))
    end

    test "reads Hebrew right to left, joining prefixes to their words", %{conn: conn} do
      {:ok, view, _html} = live(conn, "/read/wlc/genesis/1")

      assert has_element?(view, ~s(#chapter-text[dir="rtl"][lang="hbo"]))
      assert words(conn, "/read/wlc/genesis/1", "#v1") == "בְּרֵאשִׁית בָּרָא "
    end

    test "the arrows reach the neighboring chapters across a book boundary", %{conn: conn} do
      {:ok, view, _html} = live(conn, "/read/kjv/genesis/2")

      assert has_element?(view, ~s(a[rel="prev"][href="/read/kjv/genesis/1"]))
      assert has_element?(view, ~s(a[rel="next"][href="/read/kjv/luke/12"]), "Luke 12")

      {:ok, view, _html} = live(conn, "/read/kjv/luke/12")

      assert has_element?(view, ~s(a[rel="prev"][href="/read/kjv/genesis/2"]))
      assert has_element?(view, ~s(a[rel="next"][href="/read/kjv/john/1"]))

      {:ok, view, _html} = live(conn, "/read/kjv/john/1")

      refute has_element?(view, ~s(a[rel="next"]))
    end

    test "a missing book or chapter is not found", %{conn: conn} do
      for path <- [
            "/read/kjv/genesis/3",
            "/read/kjv/exodus/1",
            "/read/nope/genesis/1",
            "/read/kjv/genesis/one"
          ] do
        assert_raise CorpusWeb.NotFoundError, fn -> live(conn, path) end
      end
    end

    test "a verse in the address opens its panel", %{conn: conn} do
      {:ok, view, _html} = live(conn, "/read/kjv/genesis/1?v=2")

      assert has_element?(view, "#v2[data-selected]")
      assert has_element?(view, "aside h2", "Genesis 1:2")
      assert has_element?(view, ~s(aside a[href="/entities/6"]), "God")
      assert has_element?(view, ~s(aside a[href="/entities/2"]), "Moses")
      assert has_element?(view, ~s(aside a[href="/read/kjv/genesis/2?v=1"]), "Genesis 2:1")
    end

    test "clicking a verse and a word puts them in the address", %{conn: conn} do
      {:ok, view, _html} = live(conn, "/read/kjv/john/1")

      view |> element("#v1 button") |> render_click()
      assert_patch(view, "/read/kjv/john/1?v=1")
      assert has_element?(view, "aside h2", "John 1:1")

      view
      |> element(~s([data-word="#{Fixture.word(Fixture.sequence(:beginning))}"]))
      |> render_click()

      assert_patch(view, "/read/kjv/john/1?v=1&w=3")
      assert has_element?(view, "aside", "That which is first")
      assert has_element?(view, "aside", "G0746")
      assert has_element?(view, "aside", "magistrates")

      view |> element(~s(aside button[aria-label="Close"])) |> render_click()
      assert_patch(view, "/read/kjv/john/1")
      refute has_element?(view, "aside h2")
    end

    test "a single verse renders with its panels outside the reader" do
      verse = Scripture.find_verse("kjv", "john", 1, 1)
      word = Scripture.word(Fixture.word(Fixture.sequence(:beginning)))

      html =
        render_component(&CorpusWeb.Scripture.verse_card/1,
          verse: verse,
          details: Scripture.verse(verse.id),
          word: word
        )

      assert html =~ ~s(href="/read/kjv/john/1?v=1")
      assert html =~ ~s(phx-click="select")
      assert html =~ "That which is first"
      assert html =~ "G0746"
    end

    test "the back button restores the selection", %{conn: conn} do
      {:ok, view, _html} = live(conn, "/read/kjv/john/1?v=1&w=3")
      assert has_element?(view, "aside", "That which is first")

      render_patch(view, "/read/kjv/john/1?v=1")
      refute has_element?(view, "aside", "That which is first")
      assert has_element?(view, "aside h2", "John 1:1")
    end
  end

  test "renders without a release installed", %{conn: conn} do
    {:ok, _view, html} = live(conn, "/read/kjv/genesis/1")

    assert html =~ "The scripture text is not installed yet."
  end

  # LiveViewTest drops whitespace-only text, so the spacing is read from the
  # page as first served.
  defp words(conn, path, verse) do
    conn
    |> get(path)
    |> html_response(200)
    |> LazyHTML.from_document()
    |> LazyHTML.query("#{verse} > span")
    |> LazyHTML.text()
  end
end

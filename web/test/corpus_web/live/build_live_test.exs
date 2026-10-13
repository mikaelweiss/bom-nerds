defmodule CorpusWeb.BuildLiveTest do
  use CorpusWeb.ConnCase, async: true

  import Phoenix.LiveViewTest

  alias CorpusWeb.Layouts

  @guide CorpusWeb.api_url("/v2")

  test "links the latest release and both downloads", %{conn: conn} do
    {:ok, view, _html} = live(conn, "/build")

    release = ~s(a[href="#{Layouts.repository()}/releases/latest"])

    assert has_element?(view, release, "scripture-db.zip")
    assert has_element?(view, release, "scripture-json.zip")
    assert has_element?(view, release, "Get the latest release")
  end

  test "shows the SQLite, JavaScript, and curl snippets", %{conn: conn} do
    {:ok, view, _html} = live(conn, "/build")

    assert has_element?(view, "button", "SQLite")
    assert has_element?(view, "button", "JavaScript")
    assert has_element?(view, "button", "curl")
    assert has_element?(view, "code", ~s(sqlite3 scripture.db "select name))
    assert has_element?(view, "code", "fetch(\"#{@guide}/sql?q=")
    assert has_element?(view, "code", "curl -G #{@guide}/sql")
  end

  test "states the API limits", %{conn: conn} do
    {:ok, view, _html} = live(conn, "/build")

    assert has_element?(view, "li", "at most 10,000 rows")
    assert has_element?(view, "li", "5 seconds")
    assert has_element?(view, "li", "60 queries a minute")
    assert has_element?(view, "li", "Repeating a query someone already ran is free")
  end

  test "links the API guide and the examples", %{conn: conn} do
    {:ok, view, _html} = live(conn, "/build")

    assert has_element?(view, ~s(#api-guide[href="#{@guide}"]), "Read the API guide")
    assert has_element?(view, ~s(#examples[href="/examples"]), "See the examples")
  end

  test "the nav links each page in order", %{conn: conn} do
    {:ok, view, _html} = live(conn, "/build")

    links =
      view
      |> element("header nav")
      |> render()
      |> LazyHTML.from_fragment()
      |> LazyHTML.query("a")
      |> Enum.map(&{LazyHTML.text(&1) |> String.trim(), LazyHTML.attribute(&1, "href")})

    assert links == [
             {"Standard Works Corpus", ["/"]},
             {"Read", ["/read"]},
             {"Data", ["/data"]},
             {"Examples", ["/examples"]},
             {"Build", ["/build"]},
             {"GitHub", [Layouts.repository()]}
           ]
  end
end

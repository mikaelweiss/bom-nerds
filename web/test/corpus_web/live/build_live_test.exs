defmodule CorpusWeb.BuildLiveTest do
  use CorpusWeb.ConnCase, async: true

  import Phoenix.LiveViewTest

  alias CorpusWeb.Layouts

  @guide CorpusWeb.api_url("/v2")

  test "links the latest release and both downloads", %{conn: conn} do
    {:ok, view, _html} = live(conn, "/build")

    release = ~s(#download a[href="#{Layouts.repository()}/releases/latest"])

    assert has_element?(view, release, "scripture-db.zip")
    assert has_element?(view, release, "scripture-json.zip")
    assert has_element?(view, release, "Get the latest release")
  end

  test "puts the API section before the download section", %{conn: conn} do
    {:ok, view, html} = live(conn, "/build")

    headings =
      view
      |> element("main")
      |> render()
      |> LazyHTML.from_fragment()
      |> LazyHTML.query("h2")
      |> Enum.map(&(LazyHTML.text(&1) |> String.trim()))

    assert headings == ["Use the API", "API guide", "Examples", "Prefer to download it?"]
    assert has_element?(view, "h1", "Query the scriptures from your code")
    assert {api, _} = :binary.match(html, "Use the API")
    assert {download, _} = :binary.match(html, "Prefer to download it?")
    assert api < download
  end

  test "shows the JavaScript and curl snippets with JavaScript first", %{conn: conn} do
    {:ok, view, _html} = live(conn, "/build")

    assert render(view) =~ "defaultValue&quot;:&quot;fetch&quot;"
    assert has_element?(view, "#usage button", "JavaScript")
    assert has_element?(view, "button", "curl")
    refute has_element?(view, "#usage button", "SQLite")
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

  test "keeps the SQLite snippet in the download section", %{conn: conn} do
    {:ok, view, _html} = live(conn, "/build")

    assert has_element?(view, "#download code", ~s(sqlite3 scripture.db "select name))
    refute has_element?(view, "#usage code", "sqlite3")
  end

  test "links the API guide, the SQL editor, and the examples", %{conn: conn} do
    {:ok, view, _html} = live(conn, "/build")

    assert has_element?(view, ~s(#api-guide[href="#{@guide}"]), "Read the API guide")
    assert has_element?(view, ~s(#sql-editor[href="/sql"]), "SQL editor")
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

defmodule CorpusWeb.DataLiveTest do
  use CorpusWeb.ConnCase, async: false

  import Phoenix.LiveViewTest

  alias CorpusWeb.DataLive

  @moduletag :tmp_dir

  describe "with the fixture installed" do
    setup :serve_fixture

    test "lists every table with its row count", %{conn: conn} do
      {:ok, view, _html} = live(conn, "/data")

      assert has_element?(view, ~s(nav[aria-label="Tables"] a[href="/data/word"]), "19")
      assert has_element?(view, ~s(nav[aria-label="Tables"] a[href="/data/entity"]), "3")
    end

    test "shows a table's rows and marks it active", %{conn: conn} do
      {:ok, view, _html} = live(conn, "/data/entity")

      assert has_element?(view, ~s(a[aria-current="page"][href="/data/entity"]))
      assert has_element?(view, "#row-2", "Moses")
      assert has_element?(view, "#row-1 td", "NULL")
    end

    test "filters and sorts from the address", %{conn: conn} do
      {:ok, view, _html} = live(conn, "/data/entity?title=eq.Nephi&order=id.desc")

      assert has_element?(view, "#row-1")
      assert has_element?(view, "#row-3")
      refute has_element?(view, "#row-2")
      assert view |> element("tbody tr:first-child") |> render() =~ ~s(id="row-3")
    end

    test "adding a filter puts it in the address", %{conn: conn} do
      {:ok, view, _html} = live(conn, "/data/entity")

      view
      |> form("#filter-form", column: "title", operator: "like", value: "mos")
      |> render_submit()

      assert_patch(view, "/data/entity?title=like.mos")
      assert has_element?(view, "#row-2")
      refute has_element?(view, "#row-1")
    end

    test "a column that is not real shows a message", %{conn: conn} do
      {:ok, view, _html} = live(conn, "/data/entity?name=eq.Nephi")

      assert has_element?(view, ~s([role="alert"]), "There is no column named name.")
      assert render(view) =~ "Data"

      {:ok, view, _html} = live(conn, "/data/nope")
      assert has_element?(view, ~s([role="alert"]), "There is no table named nope.")
    end

    test "clicking a row opens it", %{conn: conn} do
      {:ok, view, _html} = live(conn, "/data/entity")

      view |> element("#row-2") |> render_click()

      assert_patch(view, "/data/entity?row=2")
      assert has_element?(view, "#row-drawer", "Moses")
    end

    test "a speech shows its words and links its speaker", %{conn: conn} do
      {:ok, view, _html} = live(conn, "/data/speech?row=1")

      assert has_element?(view, "#row-drawer", "In the beginning. And the earth was")

      assert has_element?(
               view,
               ~s(#row-drawer a[href="/read/kjv/genesis/1?v=1"]),
               "Genesis 1:1-2"
             )

      assert has_element?(view, ~s(#row-drawer a[href="/data/entity?id=eq.1"]), "1")
    end

    test "an entity lists the rows that point at it", %{conn: conn} do
      {:ok, view, _html} = live(conn, "/data/entity?row=1")

      assert has_element?(
               view,
               ~s(#referenced-by-speech a[href="/data/speech?through_id=eq.1"]),
               "through_id"
             )

      assert has_element?(
               view,
               ~s(#referenced-by-entity_name a[href="/data/entity_name?entity_id=eq.1"])
             )
    end

    test "runs a query into the grid", %{conn: conn} do
      {:ok, view, _html} = live(conn, "/sql")

      view |> form("#sql-form", q: "select id, title from entity order by id") |> render_submit()

      assert_patch(view, "/sql?q=select+id%2C+title+from+entity+order+by+id")
      assert has_element?(view, "#sql-results th", "title")
      assert has_element?(view, "#sql-results td", "Moses")
    end

    test "a shared query runs when the page opens", %{conn: conn} do
      assert html_response(get(conn, "/sql?q=select title from entity where id = 2"), 200) =~
               "select title from entity where id = 2"

      {:ok, view, _html} = live(conn, "/sql?q=select title from entity where id = 2")

      assert has_element?(view, "#sql-editor", "select title from entity where id = 2")
      assert has_element?(view, "#sql-results td", "Moses")
    end

    test "a write is refused with the database's message", %{conn: conn} do
      {:ok, view, _html} = live(conn, "/sql")

      view |> form("#sql-form", q: "delete from word") |> render_submit()

      assert has_element?(view, ~s([role="alert"]), "not authorized")
    end

    test "the 61st query in a minute is refused", %{conn: conn} do
      {:ok, view, _html} = live(%{conn | remote_ip: {10, 9, 0, 61}}, "/sql")

      for n <- 1..60 do
        view |> form("#sql-form", q: "select #{n} as n") |> render_submit()
        refute has_element?(view, ~s([role="alert"]))
      end

      view |> form("#sql-form", q: "select 61 as n") |> render_submit()

      assert has_element?(view, ~s([role="alert"]), "Too many queries. Try again in")
    end
  end

  test "says when no data is installed", %{conn: conn, tmp_dir: tmp_dir} do
    previous = Application.fetch_env!(:corpus, :data_dir)
    Application.put_env(:corpus, :data_dir, tmp_dir)
    restart_database()

    on_exit(fn ->
      Application.put_env(:corpus, :data_dir, previous)
      restart_database()
    end)

    for path <- ["/data", "/data/word", "/sql?q=select 1"] do
      {:ok, view, _html} = live(conn, path)
      assert render(view) =~ "No data is installed on this server yet."
    end
  end

  test "reads the example queries from the API guide" do
    examples =
      DataLive.examples(File.read!(Application.app_dir(:corpus, "priv/versions/v1/guide.md")))

    assert {"A verse", "select group_concat(" <> _} = hd(examples)
    assert length(examples) >= 5
    refute Enum.any?(examples, fn {label, _sql} -> String.ends_with?(label, ":") end)
  end

  test "slugs match the reader's addresses" do
    assert DataLive.slug("King James Version (1769)") == "kjv"
    assert DataLive.slug("Book of Mormon (2013)") == "book-of-mormon"
    assert DataLive.slug("Doctrine and Covenants (2013)") == "doctrine-and-covenants"
    assert DataLive.slug("1 Nephi") == "1-nephi"
    assert DataLive.slug("Song of Solomon") == "song-of-solomon"
  end
end

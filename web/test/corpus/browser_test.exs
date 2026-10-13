defmodule Corpus.BrowserTest do
  use CorpusWeb.ConnCase, async: false

  alias Corpus.{Browser, Database, Fixture}
  alias Exqlite.Sqlite3

  @moduletag :tmp_dir

  describe "paging" do
    setup %{tmp_dir: tmp_dir} do
      path = Path.join(tmp_dir, "paging.db")
      {:ok, db} = Sqlite3.open(path)
      :ok = Sqlite3.execute(db, "create table item (id integer primary key, label text) strict")

      :ok =
        Sqlite3.execute(db, """
        with recursive n(x) as (select 1 union all select x + 1 from n where x < 120)
        insert into item select x * 3, 'item ' || x from n
        """)

      :ok = Sqlite3.close(db)

      pool = :"browser_test_#{System.unique_integer([:positive])}"
      start_supervised!({Exqlite, name: pool, database: path, mode: :readonly, pool_size: 1})

      {:ok,
       database: %{
         pool: pool,
         path: path,
         release: %{"tag" => "paging"},
         tables: Database.tables(path)
       }}
    end

    test "pages forward and back 50 rows at a time", %{database: database} do
      assert {:ok, first} = Browser.page(database, "item")
      assert first.columns == ["id", "label"]
      assert ids(first) == Enum.map(1..50, &(&1 * 3))
      assert first.prev == nil

      assert {:ok, second} = Browser.page(database, "item", cursor: first.next)
      assert ids(second) == Enum.map(51..100, &(&1 * 3))

      assert {:ok, third} = Browser.page(database, "item", cursor: second.next)
      assert ids(third) == Enum.map(101..120, &(&1 * 3))
      assert third.next == nil

      assert {:ok, back} = Browser.page(database, "item", cursor: third.prev)
      assert ids(back) == ids(second)

      assert {:ok, start} = Browser.page(database, "item", cursor: back.prev)
      assert ids(start) == ids(first)
      assert start.prev == nil
    end

    test "a sorted table pages by offset", %{database: database} do
      assert {:ok, first} = Browser.page(database, "item", order: {"id", :desc})
      assert ids(first) == Enum.map(120..71//-1, &(&1 * 3))
      assert first.next == {:offset, 50}

      assert {:ok, last} =
               Browser.page(database, "item", order: {"id", :desc}, cursor: {:offset, 100})

      assert ids(last) == Enum.map(20..1//-1, &(&1 * 3))
      assert last.prev == {:offset, 50}
      assert last.next == nil
    end
  end

  test "a span across verses puts a space between them", %{tmp_dir: tmp_dir} do
    path = Path.join(tmp_dir, "verses.db")
    {:ok, db} = Sqlite3.open(path)

    :ok =
      Sqlite3.execute(db, """
      create table edition (id integer primary key, name text);
      create table book (id integer primary key, name text);
      create table chapter (id integer primary key, edition_id integer, book_id integer, number integer);
      create table verse (id integer primary key, chapter_id integer, number integer);
      create table word (id integer primary key, verse_id integer, sequence integer, text text, before text, after text);
      insert into edition values (1, 'King James Version (1769)');
      insert into book values (1, 'Matthew');
      insert into chapter values (1, 1, 1, 5);
      insert into verse values (1, 1, 3), (2, 1, 12);
      insert into word values (30, 1, 1, 'Blessed', '', ' '), (20, 1, 2, 'are.', '', ''), (10, 2, 3, 'Rejoice.', '', '');
      """)

    :ok = Sqlite3.close(db)
    pool = :"browser_test_#{System.unique_integer([:positive])}"
    start_supervised!({Exqlite, name: pool, database: path, mode: :readonly, pool_size: 1})

    database = %{
      pool: pool,
      path: path,
      release: %{"tag" => "verses"},
      tables: Database.tables(path)
    }

    span = Browser.span(database, 30, 10)

    assert span.text == "Blessed are. Rejoice."
    assert Browser.reference(span) == "Matthew 5:3-12"
  end

  describe "with the fixture installed" do
    setup :serve_fixture
    setup do: {:ok, database: Database.get("v2")}

    test "lists every table with its row count, counted once per release", %{database: database} do
      tables = Browser.tables(database)

      assert {"word", 19} in tables
      assert {"entity", 3} in tables
      assert {"entity_name", 3} in tables
      assert Enum.map(tables, &elem(&1, 0)) == Enum.sort(Map.keys(database.tables))

      assert Browser.tables(%{database | pool: :no_such_pool}) == tables
    end

    test "filters narrow the rows", %{database: database} do
      assert titles(database, [{"title", "eq", "Nephi"}]) == ["Nephi", "Nephi"]
      assert titles(database, [{"title", "neq", "Nephi"}]) == ["Moses"]
      assert titles(database, [{"title", "like", "OSE"}]) == ["Moses"]
      assert titles(database, [{"latitude", "gt", "30"}]) == ["Moses"]
      assert titles(database, [{"latitude", "lt", "30"}]) == []
      assert titles(database, [{"latitude", "empty", ""}]) == ["Nephi", "Nephi"]
      assert titles(database, [{"latitude", "notempty", ""}]) == ["Moses"]
      assert titles(database, [{"title", "eq", "Nephi"}, {"id", "gt", "1"}]) == ["Nephi"]
      assert titles(database, [{"title", "like", "%"}]) == []
      assert titles(database, [{"title", "eq", "Nephi' or 1 = 1 --"}]) == []
    end

    test "sorts on any column", %{database: database} do
      assert {:ok, page} = Browser.page(database, "entity", order: {"title", :desc})
      assert ids(page) == [1, 3, 2]
    end

    test "rejects names that are not real without running a query", %{database: database} do
      offline = %{database | pool: :no_such_pool}

      assert Browser.page(offline, "nope") == {:error, "There is no table named nope."}

      assert Browser.page(offline, "entity", filters: [{"name", "eq", "Nephi"}]) ==
               {:error, "There is no column named name."}

      assert Browser.page(offline, "entity", filters: [{"title", "drop", "x"}]) ==
               {:error, "There is no filter named drop."}

      assert Browser.page(offline, "entity", order: {"id; drop table word", :asc}) ==
               {:error, "There is no column named id; drop table word."}

      assert Browser.row(offline, "nope", 1) == {:error, "There is no table named nope."}
    end

    test "a speech shows its words as text and links its speaker", %{database: database} do
      assert {:ok, speech} = Browser.row(database, "speech", 1)

      assert [%{prefix: "", text: "In the beginning. And the earth was"} = span] = speech.spans
      assert Browser.reference(span) == "Genesis 1:1-2"
      assert CorpusWeb.DataLive.read_path(span.start) == "/read/kjv/genesis/1?v=1"

      assert %{table: "entity", columns: ["through_id"], filters: [{"id", 1}]} in speech.references

      assert {:ok, %{spans: [other]}} = Browser.row(database, "speech", 2)
      assert other.text == "and do."
      assert Browser.reference(other) == "1 Nephi 3:7"
      assert CorpusWeb.DataLive.read_path(other.start) == "/read/book-of-mormon/1-nephi/3?v=7"
    end

    test "an entity lists the rows that point at it", %{database: database} do
      assert {:ok, entity} = Browser.row(database, "entity", 1)

      assert entity.referenced_by == [
               %{
                 table: "entity_name",
                 count: 1,
                 links: [%{table: "entity_name", filters: [{"entity_id", 1}], count: 1}]
               },
               %{
                 table: "speech",
                 count: 1,
                 links: [%{table: "speech", filters: [{"through_id", 1}], count: 1}]
               }
             ]

      assert {:ok, %{referenced_by: []}} = Browser.row(database, "entity", 3)
    end

    test "prefixed word pairs each show their text", %{database: database} do
      assert {:ok, link} = Browser.row(database, "passage_link", 1)

      assert [%{prefix: "from_", text: "In the beginning."}, %{prefix: "to_", text: "and do."}] =
               link.spans
    end

    test "keys over several columns link with every column", %{database: database} do
      assert {:ok, chapter} = Browser.row(database, "chapter", 3)

      assert chapter.references == [
               %{
                 table: "edition_book",
                 columns: ["edition_id", "book_id"],
                 filters: [{"edition_id", 2}, {"book_id", 2}]
               }
             ]
    end

    test "a missing row says so", %{database: database} do
      assert Browser.row(database, "entity", 99) == {:error, "There is no row 99 in entity."}
    end

    test "word ids are not reading order", %{database: database} do
      assert Fixture.word(2) > Fixture.word(8)

      assert %{text: "In the beginning. And the earth was"} =
               Browser.span(database, Fixture.word(8), Fixture.word(2))
    end
  end

  defp ids({:ok, page}), do: ids(page)
  defp ids(page), do: Enum.map(page.rows, &elem(&1, 0))

  defp titles(database, filters) do
    {:ok, page} = Browser.page(database, "entity", filters: filters)
    title = Enum.find_index(page.columns, &(&1 == "title"))
    Enum.map(page.rows, fn {_rowid, values} -> Enum.at(values, title) end)
  end
end

defmodule Corpus.HighlightsTest do
  use CorpusWeb.ConnCase, async: false

  alias Corpus.{Database, Fixture, Highlights, Query}
  alias Exqlite.Sqlite3

  @moduletag :tmp_dir

  @isaiah """
  drop table if exists link_kind;
  create table link_kind (id integer primary key, name text not null);
  insert into link_kind values (1, 'Quotes'), (2, 'Cross-reference');
  drop table if exists passage_link;
  create table passage_link (
    id integer primary key,
    link_kind_id integer not null,
    from_first_word_id integer not null,
    from_last_word_id integer not null,
    to_first_word_id integer not null,
    to_last_word_id integer not null
  );
  insert into book values (900, 1, 'Isaiah');
  insert into edition_book values (1, 900, 2);
  insert into chapter values (900, 1, 900, 40);
  insert into verse values (900, 900, 1);
  insert into word (id, verse_id, position, sequence, text, before, after)
    values (9001, 900, 1, 9001, 'Comfort', '', ' ');
  insert into passage_link values
    (1, 1, #{Fixture.word(16)}, #{Fixture.word(17)}, 9001, 9001),
    (2, 2, #{Fixture.word(16)}, #{Fixture.word(17)}, 9001, 9001);
  """

  describe "with no release installed" do
    setup %{tmp_dir: tmp_dir} do
      install(tmp_dir, nil)
    end

    test "has no numbers and no findings" do
      assert Highlights.scholars() == %{}
      assert Highlights.findings() == []
    end
  end

  describe "with a release installed" do
    test "counts what the release has", %{tmp_dir: tmp_dir} do
      install(tmp_dir, "")

      assert %{counts: %{words: words, verses: verses}} = Highlights.scholars()
      assert words == count("select count(*) as n from word")
      assert verses == count("select count(*) as n from verse where number is not null")
    end

    test "leaves out tables the release lacks", %{tmp_dir: tmp_dir} do
      install(tmp_dir, """
      drop table if exists summary;
      drop table if exists word_match;
      drop table if exists passage_link;
      drop table if exists link_kind;
      """)

      scholars = Highlights.scholars()

      refute Map.has_key?(scholars, :aligned_words)
      refute Map.has_key?(scholars, :links)
      refute Map.has_key?(scholars, :entities)
      refute Map.has_key?(scholars.counts, :summaries)
    end

    test "leaves out tables that hold no rows", %{tmp_dir: tmp_dir} do
      install(tmp_dir, """
      drop table if exists summary;
      create table summary (id integer primary key);
      drop table if exists word_match;
      create table word_match (id integer primary key, word_id integer, other_word_id integer);
      """)

      scholars = Highlights.scholars()

      refute Map.has_key?(scholars, :aligned_words)
      refute Map.has_key?(scholars.counts, :summaries)
    end

    test "counts aligned words", %{tmp_dir: tmp_dir} do
      install(tmp_dir, """
      drop table if exists word_match;
      create table word_match (id integer primary key, word_id integer, other_word_id integer);
      insert into word_match values (1, 1, 2), (2, 3, 4), (3, 5, 6);
      """)

      assert %{aligned_words: 3} = Highlights.scholars()
    end

    test "counts links by kind", %{tmp_dir: tmp_dir} do
      install(
        tmp_dir,
        @isaiah <> "insert into passage_link select id + 10, 2, 1, 1, 1, 1 from passage_link;"
      )

      assert %{
               links: [%{kind: "Cross-reference", count: 3}, %{kind: "Quotes", count: 1}],
               link_total: 4
             } = Highlights.scholars()
    end

    test "counts entities by top-level type", %{tmp_dir: tmp_dir} do
      install(tmp_dir, """
      drop table if exists entity;
      create table entity (
        id integer primary key,
        entity_type_id integer not null,
        name text not null,
        description text not null,
        tipnr text,
        latitude real
      );
      drop table if exists entity_type;
      create table entity_type (id integer primary key, parent_id integer, name text not null);
      insert into entity_type values (1, null, 'Person'), (2, null, 'Place'), (3, 2, 'City');
      insert into entity values
        (1, 1, 'Moses', '', 'Moses|1', null),
        (2, 1, 'Nephi', '', null, null),
        (3, 2, 'Salem', '', null, null),
        (4, 3, 'Ur', '', 'Ur|1', null);
      """)

      assert %{
               entities: [
                 %{type: "Person", count: 2, tipnr: 1},
                 %{type: "Place", count: 2, tipnr: 1}
               ],
               entity_total: 4,
               tipnr_total: 2
             } = Highlights.scholars()
    end

    test "runs the queries once per release", %{tmp_dir: tmp_dir} do
      install(tmp_dir, @isaiah)

      scholars = Highlights.scholars()
      findings = Highlights.findings()
      assert [_ | _] = findings

      :ok = Supervisor.terminate_child(Corpus.Supervisor, Database)

      assert Highlights.scholars() == scholars
      assert Highlights.findings() == findings
    end

    test "keys the cache by release", %{tmp_dir: tmp_dir} do
      install(tmp_dir, "")
      Highlights.scholars()
      Highlights.findings()

      assert Cachex.exists?(Corpus.Cache, {:highlights, "data-1", :scholars}) == {:ok, true}
      assert Cachex.exists?(Corpus.Cache, {:highlights, "data-1", :findings}) == {:ok, true}
    end

    test "finds where the Book of Mormon quotes Isaiah", %{tmp_dir: tmp_dir} do
      install(tmp_dir, @isaiah)

      assert [
               %{
                 id: :isaiah,
                 quotes: 1,
                 chapters: 1,
                 books: [%{book: "1 Nephi", quotes: 1}],
                 link: "/examples/isaiah"
               }
             ] = Highlights.findings()
    end

    test "leaves out findings with no rows", %{tmp_dir: tmp_dir} do
      install(tmp_dir, @isaiah <> "delete from passage_link;")

      assert Highlights.findings() == []
    end
  end

  defp install(tmp_dir, nil) do
    use_data_dir(tmp_dir)
  end

  defp install(tmp_dir, sql) do
    use_data_dir(tmp_dir)

    path = tmp_dir |> Path.join("scripture.db") |> Fixture.database!()
    {:ok, db} = Sqlite3.open(path)
    :ok = Sqlite3.execute(db, sql)
    :ok = Sqlite3.close(db)

    Fixture.publish("data-1", Fixture.zip!(path))
    {:ok, _release} = Corpus.Install.run()
    restart_database()
  end

  defp use_data_dir(tmp_dir) do
    previous = Application.fetch_env!(:corpus, :data_dir)
    Application.put_env(:corpus, :data_dir, Path.join(tmp_dir, "data"))
    restart_database()

    on_exit(fn ->
      Application.put_env(:corpus, :data_dir, previous)
      restart_database()
    end)
  end

  defp count(sql) do
    {:ok, %{rows: [%{"n" => n}]}} = Query.run(Database.get("v1"), sql)
    n
  end
end

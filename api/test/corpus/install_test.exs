defmodule Corpus.InstallTest do
  use ExUnit.Case, async: false

  alias Corpus.{Fixture, Install}
  alias Exqlite.Sqlite3

  @moduletag :tmp_dir

  setup %{tmp_dir: tmp_dir} do
    previous = Application.fetch_env!(:corpus, :data_dir)
    data_dir = Path.join(tmp_dir, "data")
    Application.put_env(:corpus, :data_dir, data_dir)
    on_exit(fn -> Application.put_env(:corpus, :data_dir, previous) end)

    database = Fixture.database!(Path.join(tmp_dir, "scripture.db"))
    %{data_dir: data_dir, database: database, zip: Fixture.zip!(database)}
  end

  test "builds a database for each version and points current at the release", %{
    data_dir: data_dir,
    zip: zip
  } do
    Fixture.publish("data-1", zip)

    assert {:ok, %{"tag" => "data-1"}} = Install.run()
    assert File.read_link!(Path.join(data_dir, "current")) == "data-1"
    assert query(data_dir, "v1", "select name from entity where id = 2") == [["Moses"]]
    assert query(data_dir, "v2", "select title from entity where id = 2") == [["Moses"]]
  end

  test "downloads a release once", %{zip: zip} do
    Fixture.publish("data-1", zip)
    {:ok, _} = Install.run()
    {:ok, _} = Install.run()

    assert_received {:downloaded, "data-1"}
    refute_received {:downloaded, "data-1"}
  end

  test "replaces the previous release", %{data_dir: data_dir, zip: zip} do
    Fixture.publish("data-1", zip)
    {:ok, _} = Install.run()
    Fixture.publish("data-2", zip)
    {:ok, _} = Install.run()

    assert File.read_link!(Path.join(data_dir, "current")) == "data-2"
    assert File.ls!(data_dir) |> Enum.sort() == ["current", "data-2"]
  end

  test "keeps the current release when a new one breaks a version's promise", %{
    tmp_dir: tmp_dir,
    data_dir: data_dir,
    zip: zip
  } do
    Fixture.publish("data-1", zip)
    {:ok, _} = Install.run()

    broken = Fixture.database!(Path.join(tmp_dir, "broken.db"))
    {:ok, db} = Sqlite3.open(broken)
    :ok = Sqlite3.execute(db, "alter table word rename column text to body")
    :ok = Sqlite3.close(db)
    Fixture.publish("data-2", Fixture.zip!(broken))

    assert {:error, "v1: The release lacks word.text."} = Install.run()
    assert File.read_link!(Path.join(data_dir, "current")) == "data-1"
    assert query(data_dir, "v1", "select count(*) from word") == [[19]]
  end

  defp query(data_dir, version, sql) do
    {:ok, db} = Sqlite3.open(Path.join([data_dir, "current", version <> ".db"]), mode: :readonly)
    {:ok, statement} = Sqlite3.prepare(db, sql)
    {:ok, rows} = Sqlite3.fetch_all(db, statement)
    :ok = Sqlite3.close(db)
    rows
  end
end

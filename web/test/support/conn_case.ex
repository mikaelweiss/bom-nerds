defmodule CorpusWeb.ConnCase do
  @moduledoc """
  Tests that call the API with the fixture release installed and served.
  """

  use ExUnit.CaseTemplate

  alias Corpus.Fixture

  using do
    quote do
      @endpoint CorpusWeb.Endpoint

      import Plug.Conn
      import Phoenix.ConnTest
      import CorpusWeb.ConnCase
    end
  end

  setup do
    Cachex.clear(Corpus.Cache)
    {:ok, conn: Phoenix.ConnTest.build_conn()}
  end

  @doc """
  Installs the fixture release into the test's data directory and serves it.
  Tag a test or module `:reader` to install the reader's fixture, and
  `fixture_sql: sql` to run `sql` against the fixture before it is published.
  """
  def serve_fixture(%{tmp_dir: tmp_dir} = context) do
    previous = Application.fetch_env!(:corpus, :data_dir)
    Application.put_env(:corpus, :data_dir, Path.join(tmp_dir, "data"))

    tmp_dir
    |> Path.join("scripture.db")
    |> Fixture.database!(reader: Map.get(context, :reader, false))
    |> tap(&execute(&1, context[:fixture_sql]))
    |> Fixture.zip!()
    |> then(&Fixture.publish("data-1", &1))

    {:ok, _release} = Corpus.Install.run()
    restart_database()

    on_exit(fn ->
      Application.put_env(:corpus, :data_dir, previous)
      restart_database()
    end)

    :ok
  end

  defp execute(_path, nil), do: :ok

  defp execute(path, sql) do
    {:ok, db} = Exqlite.Sqlite3.open(path)
    :ok = Exqlite.Sqlite3.execute(db, sql)
    :ok = Exqlite.Sqlite3.close(db)
  end

  def restart_database do
    :ok = Supervisor.terminate_child(Corpus.Supervisor, Corpus.Database)
    {:ok, _} = Supervisor.restart_child(Corpus.Supervisor, Corpus.Database)
  end
end

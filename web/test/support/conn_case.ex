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

  @doc "Installs the fixture release into the test's data directory and serves it."
  def serve_fixture(%{tmp_dir: tmp_dir}) do
    previous = Application.fetch_env!(:corpus, :data_dir)
    Application.put_env(:corpus, :data_dir, Path.join(tmp_dir, "data"))

    tmp_dir
    |> Path.join("scripture.db")
    |> Fixture.database!()
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

  def restart_database do
    :ok = Supervisor.terminate_child(Corpus.Supervisor, Corpus.Database)
    {:ok, _} = Supervisor.restart_child(Corpus.Supervisor, Corpus.Database)
  end
end

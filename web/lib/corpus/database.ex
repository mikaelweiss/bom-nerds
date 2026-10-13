defmodule Corpus.Database do
  @moduledoc """
  One read-only connection pool per installed API version.

  `mix corpus.install` builds `<data_dir>/current/<version>.db`. A deploy
  restarts the app, which opens whatever is installed.
  """

  use Supervisor

  @key {__MODULE__, :installed}

  # Queries may only read. A denied action fails when the statement is prepared.
  @denied [
    :attach,
    :detach,
    :pragma,
    :transaction,
    :savepoint,
    :analyze,
    :reindex,
    :insert,
    :update,
    :delete,
    :alter_table,
    :create_table,
    :create_index,
    :create_trigger,
    :create_view,
    :create_vtable,
    :create_temp_table,
    :create_temp_index,
    :create_temp_trigger,
    :create_temp_view,
    :drop_table,
    :drop_index,
    :drop_trigger,
    :drop_view,
    :drop_vtable,
    :drop_temp_table,
    :drop_temp_index,
    :drop_temp_trigger,
    :drop_temp_view
  ]

  def start_link(_opts), do: Supervisor.start_link(__MODULE__, :ok, name: __MODULE__)

  @doc "The pool and release serving `version`, or nil when it is not installed."
  def get(version), do: :persistent_term.get(@key, %{})[version]

  def current_dir, do: Path.join(data_dir(), "current")

  def data_dir, do: Application.fetch_env!(:corpus, :data_dir)

  @impl true
  def init(:ok) do
    installed =
      for version <- Corpus.Versions.all(),
          path = Path.join(current_dir(), version <> ".db"),
          File.exists?(path),
          into: %{} do
        {version, %{pool: :"corpus_#{version}", path: path, release: release()}}
      end

    :persistent_term.put(@key, installed)

    installed
    |> Enum.map(fn {version, %{pool: pool, path: path}} ->
      Supervisor.child_spec(
        {Exqlite,
         name: pool,
         database: path,
         mode: :readonly,
         pool_size: System.schedulers_online() * 2,
         authorizer: @denied},
        id: version
      )
    end)
    |> Supervisor.init(strategy: :one_for_one)
  end

  defp release do
    current_dir() |> Path.join("release.json") |> File.read!() |> Jason.decode!()
  end
end

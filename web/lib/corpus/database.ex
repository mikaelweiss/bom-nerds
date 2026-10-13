defmodule Corpus.Database do
  @moduledoc """
  One read-only connection pool per installed API version.

  `mix corpus.install` builds `<data_dir>/current/<version>.db`. A deploy
  restarts the app, which opens whatever is installed.
  """

  use Supervisor

  alias Exqlite.Sqlite3

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
        {version,
         %{pool: :"corpus_#{version}", path: path, release: release(), tables: tables(path)}}
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

  @doc """
  Each table's columns, primary key, and foreign keys, by table name.

  The pool's authorizer denies PRAGMA, so this reads them on its own
  connection. A foreign key's `to` columns are always named, even when the
  schema leaves them to the parent's primary key.
  """
  def tables(path) do
    {:ok, db} = Sqlite3.open(path, mode: :readonly)

    try do
      names =
        for [name] <-
              all(
                db,
                "select name from sqlite_master where type = 'table' and name not like 'sqlite_%' order by name"
              ),
            do: name

      columns = Map.new(names, &{&1, all(db, "select name, pk from pragma_table_info(?)", [&1])})

      Map.new(names, fn name ->
        {name,
         %{
           columns: Enum.map(columns[name], &hd/1),
           primary_key: primary_key(columns[name]),
           foreign_keys: foreign_keys(db, name, columns)
         }}
      end)
    after
      Sqlite3.close(db)
    end
  end

  defp primary_key(columns) do
    for [name, pk] <- Enum.sort_by(columns, &List.last/1), pk > 0, do: name
  end

  defp foreign_keys(db, table, columns) do
    db
    |> all(
      ~s[select id, "table", "from", "to" from pragma_foreign_key_list(?) order by id, seq],
      [table]
    )
    |> Enum.chunk_by(&hd/1)
    |> Enum.flat_map(fn [[_id, parent | _] | _] = rows ->
      from = Enum.map(rows, &Enum.at(&1, 2))

      to =
        if Enum.any?(rows, &is_nil(List.last(&1))),
          do: primary_key(Map.get(columns, parent, [])),
          else: Enum.map(rows, &List.last/1)

      if Map.has_key?(columns, parent) and length(to) == length(from),
        do: [%{table: parent, from: from, to: to}],
        else: []
    end)
  end

  defp all(db, sql, params \\ []) do
    {:ok, statement} = Sqlite3.prepare(db, sql)

    try do
      :ok = Sqlite3.bind(statement, params)
      {:ok, rows} = Sqlite3.fetch_all(db, statement)
      rows
    after
      Sqlite3.release(db, statement)
    end
  end

  defp release do
    current_dir() |> Path.join("release.json") |> File.read!() |> Jason.decode!()
  end
end

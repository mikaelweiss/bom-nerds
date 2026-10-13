defmodule Corpus.Install do
  @moduledoc """
  Installs the latest data release into the data directory.

  The release is downloaded once into `<data_dir>/<tag>/`. Each API version
  gets its own database built from it, which must hold every table and column
  the version promises. Only then does `current` point at the new release, so
  a failed install leaves the served data untouched.
  """

  alias Corpus.{Database, GitHub, Versions}
  alias Exqlite.Sqlite3

  def run do
    data_dir = Database.data_dir()
    File.mkdir_p!(data_dir)

    with {:ok, %{"tag" => tag} = release} <- GitHub.latest_release(),
         dir = Path.join(data_dir, tag),
         :ok <- download(release, dir),
         :ok <- build_versions(dir) do
      point_current(data_dir, tag)
      remove_others(data_dir, tag)
      {:ok, release}
    end
  end

  defp download(release, dir) do
    if File.exists?(Path.join(dir, "scripture.db")) do
      :ok
    else
      staging = dir <> ".download"
      zip = Path.join(staging, "scripture-db.zip")
      File.rm_rf!(staging)
      File.mkdir_p!(staging)

      with :ok <- GitHub.download(release["download_url"], zip),
           {:ok, [_]} <- unzip(zip, staging) do
        File.rm!(zip)
        File.write!(Path.join(staging, "release.json"), Jason.encode!(release))
        File.rm_rf!(dir)
        File.rename!(staging, dir)
      else
        {:ok, []} -> {:error, "The zip holds no scripture.db."}
        {:error, reason} when is_binary(reason) -> {:error, reason}
        {:error, reason} -> {:error, inspect(reason)}
      end
    end
  end

  defp unzip(zip, dir) do
    :zip.unzip(String.to_charlist(zip),
      file_list: [~c"scripture.db"],
      cwd: String.to_charlist(dir)
    )
  end

  defp build_versions(dir) do
    Enum.reduce_while(Versions.all(), :ok, fn version, :ok ->
      case build(dir, version) do
        :ok -> {:cont, :ok}
        {:error, reason} -> {:halt, {:error, "#{version}: #{reason}"}}
      end
    end)
  end

  defp build(dir, version) do
    building = Path.join(dir, version <> ".db.building")
    File.cp!(Path.join(dir, "scripture.db"), building)
    {:ok, db} = Sqlite3.open(building)

    result =
      with :ok <- migrate(db, Versions.migration(version)) do
        check(db, Versions.schema(version))
      end

    :ok = Sqlite3.close(db)

    case result do
      :ok ->
        File.rename!(building, Path.join(dir, version <> ".db"))

      error ->
        File.rm!(building)
        error
    end
  end

  defp migrate(_db, nil), do: :ok
  defp migrate(db, sql), do: Sqlite3.execute(db, sql)

  defp check(db, schema) do
    missing =
      for {table, columns} <- schema,
          present = columns(db, table),
          column <- columns,
          column not in present,
          do: "#{table}.#{column}"

    case missing do
      [] -> :ok
      missing -> {:error, "The release lacks #{Enum.join(missing, ", ")}."}
    end
  end

  defp columns(db, table) do
    {:ok, statement} = Sqlite3.prepare(db, "select name from pragma_table_info(?1)")
    :ok = Sqlite3.bind(statement, [table])
    {:ok, rows} = Sqlite3.fetch_all(db, statement)
    :ok = Sqlite3.release(db, statement)
    List.flatten(rows)
  end

  defp point_current(data_dir, tag) do
    link = Path.join(data_dir, ".current")
    File.rm_rf!(link)
    File.ln_s!(tag, link)
    File.rename!(link, Path.join(data_dir, "current"))
  end

  defp remove_others(data_dir, tag) do
    for entry <- File.ls!(data_dir), entry not in [tag, "current"] do
      File.rm_rf!(Path.join(data_dir, entry))
    end
  end
end

defmodule Corpus.Versions do
  @moduledoc """
  The public API versions, one folder each in `priv/versions`.

  A version is a promise about tables and columns. `schema.json` lists every
  table and column the version guarantees. `migrate.sql`, when present,
  reshapes a data release into those tables. `guide.md` is the documentation
  served at `/<version>`.
  """

  def all, do: dir() |> File.ls!() |> Enum.sort()

  def exists?(version), do: version in all()

  def latest, do: List.last(all())

  def guide(version), do: File.read!(path(version, "guide.md"))

  def schema(version), do: path(version, "schema.json") |> File.read!() |> Jason.decode!()

  def migration(version) do
    case File.read(path(version, "migrate.sql")) do
      {:ok, sql} -> sql
      {:error, :enoent} -> nil
    end
  end

  defp path(version, file), do: Path.join([dir(), version, file])

  defp dir do
    Application.get_env(:corpus, :versions_dir) || Application.app_dir(:corpus, "priv/versions")
  end
end

defmodule Corpus.Query do
  @moduledoc """
  Runs one read-only SQL query against an installed version.
  """

  def run(%{pool: pool, release: release}, sql) do
    %{timeout: timeout, max_rows: max_rows} = Map.new(Application.fetch_env!(:corpus, :query))

    case String.trim_trailing(sql, ";") |> String.trim() do
      "" ->
        {:error, "Pass a SQL query in q."}

      sql ->
        try do
          pool
          |> DBConnection.run(&capped(&1, sql, max_rows, timeout), timeout: timeout)
          |> result(release, max_rows, timeout)
        rescue
          error in DBConnection.ConnectionError ->
            if error.reason == :queue_timeout,
              do: {:busy, "The server is busy. Try again shortly."},
              else: too_long(timeout)
        end
    end
  end

  # Wrapping caps the rows SQLite produces, so a huge result never reaches
  # memory. A query that compiles alone has balanced parentheses, so it cannot
  # close the wrapper early and escape the cap. The newline keeps a trailing
  # -- comment from swallowing the wrapper.
  defp capped(conn, sql, max_rows, timeout) do
    with {:ok, query} <- DBConnection.prepare(conn, %Exqlite.Query{statement: sql}),
         {:ok, _} <- DBConnection.close(conn, query) do
      Exqlite.query(conn, "select * from (#{sql}\n) limit #{max_rows + 1}", [], timeout: timeout)
    end
  end

  defp result({:ok, %{columns: columns, rows: rows}}, release, max_rows, _timeout) do
    {:ok,
     %{
       release: release["tag"],
       columns: columns,
       rows: Enum.map(Enum.take(rows, max_rows), &(columns |> Enum.zip(&1) |> Map.new())),
       truncated: length(rows) > max_rows
     }}
  end

  defp result({:error, %Exqlite.Error{message: "interrupted"}}, _release, _max_rows, timeout),
    do: too_long(timeout)

  defp result({:error, %Exqlite.Error{message: message}}, _release, _max_rows, _timeout),
    do: {:error, message}

  defp too_long(timeout), do: {:error, "The query ran longer than #{div(timeout, 1000)} seconds."}
end

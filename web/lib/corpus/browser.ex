defmodule Corpus.Browser do
  @moduledoc """
  Reads tables a page at a time for the data browser.

  Table and column names are checked against the installed schema before any
  SQL is built, and filter values are always bound parameters. Every table is
  a rowid table, so unsorted pages step by rowid and stay fast at any depth.
  """

  @page_size 50
  @span_words 200

  @operators [
    {"eq", "equals"},
    {"neq", "not equals"},
    {"like", "contains"},
    {"gt", "greater than"},
    {"lt", "less than"},
    {"empty", "is empty"},
    {"notempty", "is not empty"}
  ]

  def page_size, do: @page_size

  @doc "Filter operators as `{key, label}` pairs."
  def operators, do: @operators

  @doc "Operators that take no value."
  def unary?(operator), do: operator in ["empty", "notempty"]

  @doc "The columns of `table`, or nil when there is no such table."
  def columns(database, table) do
    with %{columns: columns} <- database.tables[table], do: columns
  end

  @doc """
  Every table with its row count, counted once per installed release. A count
  is nil when counting failed.
  """
  def tables(database) do
    names = database.tables |> Map.keys() |> Enum.sort()
    key = {__MODULE__, :row_counts, database.path, database.release["tag"]}

    {_status, counts} =
      Cachex.fetch(Corpus.Cache, key, fn ->
        case count_rows(database, names) do
          {:ok, counts} -> {:commit, counts}
          {:error, _message} -> {:ignore, %{}}
        end
      end)

    Enum.map(names, &{&1, counts[&1]})
  end

  defp count_rows(database, names) do
    sql = Enum.map_join(names, " union all ", &"select ?, count(*) from #{quote_name(&1)}")

    with {:ok, rows} <- query(database, sql, names) do
      {:ok, Map.new(rows, fn [name, count] -> {name, count} end)}
    end
  end

  @doc """
  One page of `table`.

  Options:

    * `:filters` - `{column, operator, value}` triples, combined with and
    * `:order` - `{column, :asc | :desc}`, or nil for rowid order
    * `:cursor` - `{:after, rowid}` or `{:before, rowid}` when unsorted,
      `{:offset, n}` when sorted

  Returns the rows as `{rowid, values}` and the cursors for the pages either
  side, nil at an end.
  """
  def page(database, table, opts \\ []) do
    filters = Keyword.get(opts, :filters, [])
    order = Keyword.get(opts, :order)
    cursor = Keyword.get(opts, :cursor)

    with {:ok, columns} <- table_columns(database, table),
         {:ok, where, params} <- where(filters, columns),
         :ok <- check_order(order, columns, table) do
      select =
        "select rowid, #{Enum.map_join(columns, ", ", &quote_name/1)} from #{quote_name(table)}"

      fetch_page(database, select, where, params, order, cursor)
      |> case do
        {:ok, page} -> {:ok, Map.put(page, :columns, columns)}
        error -> error
      end
    end
  end

  defp fetch_page(database, select, where, params, nil, {:before, rowid})
       when is_integer(rowid) do
    sql =
      "#{select} where #{and_all(["rowid < ?" | where])} order by rowid desc limit #{@page_size + 1}"

    with {:ok, rows} <- query(database, sql, params ++ [rowid]) do
      {page, more} = split(rows)
      page = Enum.reverse(page)

      {:ok,
       %{
         rows: page,
         prev: if(more, do: {:before, first_rowid(page)}),
         next: if(page != [], do: {:after, last_rowid(page)})
       }}
    end
  end

  defp fetch_page(database, select, where, params, nil, cursor) do
    {where, params} =
      case cursor do
        {:after, rowid} when is_integer(rowid) -> {["rowid > ?" | where], params ++ [rowid]}
        _ -> {where, params}
      end

    sql = "#{select} where #{and_all(where)} order by rowid limit #{@page_size + 1}"

    with {:ok, rows} <- query(database, sql, params) do
      {page, more} = split(rows)

      {:ok,
       %{
         rows: page,
         prev: if(match?({:after, _}, cursor) and page != [], do: {:before, first_rowid(page)}),
         next: if(more, do: {:after, last_rowid(page)})
       }}
    end
  end

  defp fetch_page(database, select, where, params, {column, direction}, cursor) do
    offset =
      case cursor do
        {:offset, n} when is_integer(n) and n > 0 -> n
        _ -> 0
      end

    sql =
      "#{select} where #{and_all(where)} order by #{quote_name(column)} #{direction}, rowid " <>
        "limit #{@page_size + 1} offset #{offset}"

    with {:ok, rows} <- query(database, sql, params) do
      {page, more} = split(rows)

      {:ok,
       %{
         rows: page,
         prev: if(offset > 0, do: {:offset, max(offset - @page_size, 0)}),
         next: if(more, do: {:offset, offset + @page_size})
       }}
    end
  end

  defp split(rows) do
    page = rows |> Enum.take(@page_size) |> Enum.map(fn [rowid | values] -> {rowid, values} end)
    {page, length(rows) > @page_size}
  end

  defp first_rowid([{rowid, _} | _]), do: rowid
  defp last_rowid(page), do: page |> List.last() |> elem(0)

  defp and_all([]), do: "1"
  defp and_all(conditions), do: Enum.join(conditions, " and ")

  defp table_columns(database, table) do
    case columns(database, table) do
      nil -> {:error, "There is no table named #{table}."}
      columns -> {:ok, columns}
    end
  end

  defp where(filters, columns) do
    Enum.reduce_while(filters, {:ok, [], []}, fn {column, operator, value},
                                                 {:ok, conditions, params} ->
      case condition(column, operator, value, columns) do
        {:ok, condition, new} -> {:cont, {:ok, conditions ++ [condition], params ++ new}}
        error -> {:halt, error}
      end
    end)
  end

  defp condition(column, operator, value, columns) do
    name = quote_name(column)

    cond do
      column not in columns ->
        {:error, "There is no column named #{column}."}

      operator == "eq" ->
        {:ok, "#{name} = ?", [value]}

      operator == "neq" ->
        {:ok, "#{name} <> ?", [value]}

      operator == "like" ->
        {:ok, "#{name} like ? escape '\\'", ["%" <> escape_like(value) <> "%"]}

      operator == "gt" ->
        {:ok, "#{name} > ?", [value]}

      operator == "lt" ->
        {:ok, "#{name} < ?", [value]}

      operator == "empty" ->
        {:ok, "(#{name} is null or #{name} = '')", []}

      operator == "notempty" ->
        {:ok, "(#{name} is not null and #{name} <> '')", []}

      true ->
        {:error, "There is no filter named #{operator}."}
    end
  end

  defp escape_like(value), do: String.replace(value, ["\\", "%", "_"], &("\\" <> &1))

  defp check_order(nil, _columns, _table), do: :ok

  defp check_order({column, direction}, columns, _table) when direction in [:asc, :desc] do
    if column in columns, do: :ok, else: {:error, "There is no column named #{column}."}
  end

  @doc """
  One row of `table` by rowid, with where its foreign keys point, the rows in
  other tables that point at it, and the text of each first and last word pair.
  """
  def row(database, table, rowid) do
    sql = "select rowid, * from #{quote_name(table)} where rowid = ?"

    with {:ok, columns} <- table_columns(database, table),
         {:ok, [[_rowid | values]]} <- query(database, sql, [rowid]),
         row = columns |> Enum.zip(values) |> Map.new(),
         {:ok, referenced_by} <- referenced_by(database, table, row) do
      {:ok,
       %{
         rowid: rowid,
         columns: Enum.zip(columns, values),
         references: references(database, table, row),
         referenced_by: referenced_by,
         spans: spans(database, columns, row)
       }}
    else
      {:ok, []} -> {:error, "There is no row #{rowid} in #{table}."}
      error -> error
    end
  end

  defp references(database, table, row) do
    for %{table: parent, from: from, to: to} <- database.tables[table].foreign_keys,
        values = Enum.map(from, &row[&1]),
        nil not in values do
      %{table: parent, columns: from, filters: Enum.zip(to, values)}
    end
  end

  defp referenced_by(database, table, row) do
    links =
      for {child, %{foreign_keys: foreign_keys}} <- Enum.sort(database.tables),
          %{table: ^table, from: from, to: to} <- foreign_keys,
          values = Enum.map(to, &row[&1]),
          nil not in values do
        %{table: child, filters: Enum.zip(from, values)}
      end

    if links == [] do
      {:ok, []}
    else
      sql =
        Enum.map_join(links, " union all ", fn %{table: child, filters: filters} ->
          conditions =
            Enum.map_join(filters, " and ", fn {column, _} -> "#{quote_name(column)} = ?" end)

          "select count(*) from #{quote_name(child)} where #{conditions}"
        end)

      params = Enum.flat_map(links, fn %{filters: filters} -> Enum.map(filters, &elem(&1, 1)) end)

      with {:ok, counts} <- query(database, sql, params) do
        {:ok,
         links
         |> Enum.zip(counts)
         |> Enum.flat_map(fn {link, [count]} ->
           if count > 0, do: [Map.put(link, :count, count)], else: []
         end)
         |> Enum.chunk_by(& &1.table)
         |> Enum.map(fn [%{table: child} | _] = group ->
           %{table: child, count: group |> Enum.map(& &1.count) |> Enum.sum(), links: group}
         end)}
      end
    end
  end

  defp spans(database, columns, row) do
    for first <- columns,
        String.ends_with?(first, "first_word_id"),
        prefix = String.replace_suffix(first, "first_word_id", ""),
        last = prefix <> "last_word_id",
        last in columns,
        row[first] != nil and row[last] != nil do
      Map.put(span(database, row[first], row[last]), :prefix, prefix)
    end
  end

  @location """
  select w.sequence, e.name, b.name, c.number, v.number
  from word w
  join verse v on v.id = w.verse_id
  join chapter c on c.id = v.chapter_id
  join book b on b.id = c.book_id
  join edition e on e.id = c.edition_id
  where w.id = ?
  """

  @doc """
  The words from `first_word_id` to `last_word_id` in reading order, with
  where they start and end.
  """
  def span(database, first_word_id, last_word_id) do
    with {:ok, [[first_sequence | first]]} <- query(database, @location, [first_word_id]),
         {:ok, [[last_sequence | last]]} <- query(database, @location, [last_word_id]),
         {from, to} = Enum.min_max([first_sequence, last_sequence]),
         {:ok, words} <-
           query(
             database,
             "select verse_id, before || text || after from word where sequence between ? and ? order by sequence limit ?",
             [from, to, @span_words + 1]
           ) do
      text = words |> Enum.take(@span_words) |> join_verses()
      text = if length(words) > @span_words, do: text <> " …", else: text
      {start, finish} = if first_sequence <= last_sequence, do: {first, last}, else: {last, first}

      %{text: text, start: location(start), finish: location(finish)}
    else
      {:ok, []} -> %{error: "The words are not in this release."}
      {:error, message} -> %{error: message}
    end
  end

  # Verses carry no space between them, so a span across verses joins them with one.
  defp join_verses(words) do
    words
    |> Enum.chunk_by(&hd/1)
    |> Enum.map_join(" ", fn verse -> verse |> Enum.map_join(&List.last/1) |> String.trim() end)
  end

  defp location([edition, book, chapter, verse]),
    do: %{edition: edition, book: book, chapter: chapter, verse: verse}

  @doc ~S|A reference like "Alma 32:21" or "Alma 32:21-33:2" for a span.|
  def reference(%{start: start, finish: finish}) do
    cond do
      start.book != finish.book -> "#{reference(start)} - #{reference(finish)}"
      start.chapter != finish.chapter -> "#{reference(start)}-#{chapter_verse(finish)}"
      start.verse != finish.verse and finish.verse -> "#{reference(start)}-#{finish.verse}"
      true -> reference(start)
    end
  end

  def reference(%{book: book} = location), do: "#{book} #{chapter_verse(location)}"

  defp chapter_verse(%{chapter: chapter, verse: nil}), do: "#{chapter}"
  defp chapter_verse(%{chapter: chapter, verse: verse}), do: "#{chapter}:#{verse}"

  defp quote_name(name), do: ~s("#{String.replace(name, ~s("), ~s(""))}")

  defp query(%{pool: pool}, sql, params) do
    %{timeout: timeout} = Map.new(Application.fetch_env!(:corpus, :query))

    try do
      case Exqlite.query(pool, sql, params, timeout: timeout) do
        {:ok, %{rows: rows}} -> {:ok, rows}
        {:error, %Exqlite.Error{message: "interrupted"}} -> too_long(timeout)
        {:error, %Exqlite.Error{message: message}} -> {:error, message}
      end
    rescue
      error in DBConnection.ConnectionError ->
        if error.reason == :queue_timeout,
          do: {:error, "The server is busy. Try again shortly."},
          else: too_long(timeout)
    end
  end

  defp too_long(timeout),
    do:
      {:error,
       "The query ran longer than #{div(timeout, 1000)} seconds. Try a filter or another sort."}
end

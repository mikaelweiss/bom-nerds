defmodule Corpus.Spans do
  @moduledoc """
  The longest word range in each range table of an installed release.

  Finding every range that overlaps a verse needs a lower bound on where such a
  range can start. A range that covers a verse starts at most its own length
  before the verse, so the longest range of each kind bounds the search. Each
  release computes these once and keeps them in `Corpus.Cache`.
  """

  @tables [
    mention: {"mention", "first_word_id", "last_word_id"},
    speech: {"speech", "first_word_id", "last_word_id"},
    setting: {"setting", "first_word_id", "last_word_id"},
    date: {"date", "first_word_id", "last_word_id"},
    structure: {"structure", "first_word_id", "last_word_id"},
    verse_range: {"verse_range", "first_word_id", "last_word_id"},
    link_from: {"passage_link", "from_first_word_id", "from_last_word_id"},
    link_to: {"passage_link", "to_first_word_id", "to_last_word_id"}
  ]

  @doc "The longest range of `kind` in the release `database` serves, in words."
  def longest(%{release: %{"tag" => tag}} = database, kind) do
    {_status, spans} =
      Cachex.fetch(Corpus.Cache, {:spans, tag}, fn -> {:commit, measure(database)} end)

    Map.fetch!(spans, kind)
  end

  defp measure(%{pool: pool}) do
    columns =
      Enum.map_join(@tables, ", ", fn {kind, {table, first, last}} ->
        """
        (select coalesce(max(l.sequence - f.sequence), 0)
         from #{table} t join word f on f.id = t.#{first} join word l on l.id = t.#{last}) as #{kind}
        """
      end)

    %{columns: names, rows: [values]} = Exqlite.query!(pool, "select " <> columns, [])
    names |> Enum.map(&String.to_existing_atom/1) |> Enum.zip(values) |> Map.new()
  end
end

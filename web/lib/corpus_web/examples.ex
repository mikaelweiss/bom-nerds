defmodule CorpusWeb.Examples do
  @moduledoc """
  Visualizations drawn from API queries, each one a module with a query and a
  chart. Charts are plain SVG rendered on the server, so they need no client
  library and the same component draws both the full chart and its preview.
  """

  use Phoenix.Component

  alias Corpus.{Database, Query, Versions}

  @callback slug() :: String.t()
  @callback title() :: String.t()
  @callback description() :: String.t()
  @callback sql() :: String.t()
  @callback chart(map()) :: Phoenix.LiveView.Rendered.t()

  @examples [
    CorpusWeb.Examples.PaulsJourneys,
    CorpusWeb.Examples.AbrahamsFamily,
    CorpusWeb.Examples.Timeline,
    CorpusWeb.Examples.WhoSpeaks,
    CorpusWeb.Examples.Isaiah,
    CorpusWeb.Examples.MostNamed
  ]

  def all, do: @examples

  def get(slug), do: Enum.find(@examples, &(&1.slug() == slug))

  attr :example, :atom, required: true
  attr :rows, :list, required: true
  attr :preview, :boolean, default: false

  def chart(assigns), do: assigns.example.chart(assigns)

  @doc "The example's rows from the latest release, or none when no release is installed."
  def rows(example) do
    case Database.get(Versions.latest()) do
      nil ->
        []

      database ->
        {_status, rows} =
          Cachex.fetch(Corpus.Cache, {:example, example}, fn ->
            {:ok, %{rows: rows}} = Query.run(database, example.sql())
            {:commit, rows}
          end)

        rows
    end
  end

  @doc "The API URL that runs the example's query."
  def api_url(example),
    do: CorpusWeb.api_url("/#{Versions.latest()}/sql?" <> URI.encode_query(q: example.sql()))

  @doc "Maps `value` from the `domain` range onto the `range` range."
  def scale(_value, {d0, d1}, {r0, r1}) when d0 == d1, do: (r0 + r1) / 2
  def scale(value, {d0, d1}, {r0, r1}), do: r0 + (value - d0) / (d1 - d0) * (r1 - r0)

  @doc "Rounds a coordinate so the SVG stays small."
  def px(value), do: Float.round(value / 1, 1)
end

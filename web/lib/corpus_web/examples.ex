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

  @doc """
  A chart you can drag to pan and scroll or pinch to zoom, driven by the
  `PanZoom` hook. The inner block draws in layer coordinates, and `view` places
  the layer in the `width` by `height` viewport as `{x, y, scale}`.

  Inside the layer, an element with `data-pan-zoom-fixed` and `data-x`/`data-y`
  keeps its starting screen size around that point, and one with
  `data-pan-zoom-reveal={n}` shows once the view is zoomed `n` times past the
  start.
  """
  attr :id, :string, required: true
  attr :label, :string, required: true
  attr :width, :integer, required: true
  attr :height, :integer, required: true
  attr :view, :any, required: true
  attr :min_zoom, :float, required: true
  attr :max_zoom, :float, required: true
  attr :class, :string, default: nil
  slot :inner_block, required: true

  def pan_zoom(assigns) do
    {x, y, k} = assigns.view
    assigns = assign(assigns, x: px(x), y: px(y), k: Float.round(k / 1, 4))

    ~H"""
    <div
      id={@id}
      phx-hook="PanZoom"
      phx-update="ignore"
      data-view={"#{@x} #{@y} #{@k}"}
      data-min-zoom={@min_zoom}
      data-max-zoom={@max_zoom}
      class="relative"
    >
      <svg
        viewBox={"0 0 #{@width} #{@height}"}
        class={["block w-full cursor-grab touch-none select-none rounded-lg", @class]}
        role="img"
        aria-label={@label}
      >
        <g data-pan-zoom-layer transform={"translate(#{@x} #{@y}) scale(#{@k})"}>
          {render_slot(@inner_block)}
        </g>
      </svg>
      <div class="absolute right-2 top-2 flex flex-col overflow-hidden rounded-md border bg-background/90 shadow-sm">
        <.zoom_button action="in" label="Zoom in" icon="M12 5v14M5 12h14" />
        <.zoom_button action="out" label="Zoom out" icon="M5 12h14" />
        <.zoom_button
          action="reset"
          label="Reset view"
          icon="M3 12a9 9 0 1 0 3-6.7M3 4v5h5"
        />
      </div>
      <p class="mt-3 text-sm text-muted-foreground">Drag to move. Scroll or pinch to zoom.</p>
    </div>
    """
  end

  attr :action, :string, required: true
  attr :label, :string, required: true
  attr :icon, :string, required: true

  defp zoom_button(assigns) do
    ~H"""
    <button
      type="button"
      data-zoom={@action}
      aria-label={@label}
      title={@label}
      class="flex size-9 items-center justify-center border-b last:border-b-0 hover:bg-accent"
    >
      <svg
        viewBox="0 0 24 24"
        class="size-4"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
        stroke-linejoin="round"
      >
        <path d={@icon} />
      </svg>
    </button>
    """
  end

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

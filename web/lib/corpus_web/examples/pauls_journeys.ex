defmodule CorpusWeb.Examples.PaulsJourneys.Geography do
  @moduledoc false

  import CorpusWeb.Examples, only: [px: 1]

  @source Path.expand("../../../priv/maps/eastern_mediterranean.json", __DIR__)
  @external_resource @source

  %{"bounds" => [lon0, lat0, lon1, lat1], "land" => land, "lakes" => lakes} =
    @source |> File.read!() |> Jason.decode!()

  @lon0 lon0
  @lat1 lat1
  @land land
  @lakes lakes
  @unit 40
  # An equirectangular projection, with longitude narrowed by the cosine of
  # the middle latitude so distances look right this far from the equator.
  @squeeze :math.cos((lat0 + lat1) / 2 * :math.pi() / 180)
  @width px((lon1 - lon0) * @squeeze * @unit)
  @height px((lat1 - lat0) * @unit)

  def width, do: @width
  def height, do: @height

  def project(lat, lon), do: {px((lon - @lon0) * @squeeze * @unit), px((@lat1 - lat) * @unit)}

  def land, do: path(@land)
  def lakes, do: path(@lakes)

  defp path(rings) do
    Enum.map_join(rings, fn [first | rest] ->
      {x, y} = tenths(first)

      {steps, _} =
        Enum.map_reduce(rest, {x, y}, fn point, {x0, y0} ->
          {x1, y1} = tenths(point)
          {"#{number(x1 - x0)},#{number(y1 - y0)}", {x1, y1}}
        end)

      "M#{number(x)},#{number(y)}l#{Enum.join(steps, " ")}z"
    end)
  end

  defp tenths([lon, lat]) do
    {x, y} = project(lat, lon)
    {round(x * 10), round(y * 10)}
  end

  defp number(tenths) when rem(tenths, 10) == 0, do: Integer.to_string(div(tenths, 10))
  defp number(tenths), do: :erlang.float_to_binary(tenths / 10, decimals: 1)
end

defmodule CorpusWeb.Examples.PaulsJourneys do
  @behaviour CorpusWeb.Examples

  use Phoenix.Component

  import CorpusWeb.Examples, only: [pan_zoom: 1, px: 1]

  alias CorpusWeb.Examples.PaulsJourneys.Geography, as: Geo

  @width 800
  @height 500
  @pad {80, 30}
  @font 13
  @letter 7.4
  @zoom_levels [1, 2, 4, 8]
  @land Geo.land()
  @lakes Geo.lakes()

  def slug, do: "pauls-journeys"
  def title, do: "Paul's journeys"

  def description,
    do:
      "Every trip Paul takes in Acts, drawn from city to city across the eastern Mediterranean. " <>
        "The busiest places are the largest. Zoom in to see more names."

  def sql do
    """
    select f.name as from_place, f.latitude as from_lat, f.longitude as from_lon,
           t.name as to_place, t.latitude as to_lat, t.longitude as to_lon
    from journey j
    join entity p on p.id = j.traveler_id
    join entity_type pt on pt.id = p.entity_type_id
    join entity f on f.id = j.from_id
    join entity t on t.id = j.to_id
    join word w on w.id = j.first_word_id
    where p.name = 'Paul' and pt.name = 'Person'
      and f.latitude is not null and t.latitude is not null
    order by w.sequence
    """
  end

  attr :rows, :list, required: true
  attr :preview, :boolean, default: false

  def chart(%{preview: true} = assigns) do
    places = places(assigns.rows)
    {x, y, width, height} = frame(places, {20, 20})

    assigns =
      assign(assigns,
        trips: trips(assigns.rows),
        places: places,
        view_box: "#{x} #{y} #{width} #{height}"
      )

    ~H"""
    <svg
      viewBox={@view_box}
      class="h-full w-full rounded-md"
      role="img"
      aria-label="Map of Paul's journeys"
    >
      <.map_layers trips={@trips} places={@places} radius_scale={1.6} route_width={1.5} />
    </svg>
    """
  end

  def chart(assigns) do
    places = places(assigns.rows)
    {x, y, width, height} = frame(places, @pad)
    k = min(@width / width, @height / height)
    view = {(@width - width * k) / 2 - x * k, (@height - height * k) / 2 - y * k, k}
    fit = min(@width / Geo.width(), @height / Geo.height())

    assigns =
      assign(assigns,
        trips: trips(assigns.rows),
        places: places,
        width: @width,
        height: @height,
        view: view,
        labels: labels(places, view),
        font: @font,
        min_zoom: Float.round(min(fit, k), 3),
        max_zoom: Float.round(k * List.last(@zoom_levels), 3)
      )

    ~H"""
    <.pan_zoom
      id="pauls-journeys-map"
      label="Map of Paul's journeys"
      width={@width}
      height={@height}
      view={@view}
      min_zoom={@min_zoom}
      max_zoom={@max_zoom}
      class={water()}
    >
      <.map_layers trips={@trips} places={@places} radius_scale={1.0} route_width={2.0} />
      <g
        font-size={@font}
        class={["fill-foreground", halo()]}
        stroke-width="3.5"
        stroke-linejoin="round"
        paint-order="stroke"
      >
        <g :for={label <- @labels} data-pan-zoom-fixed data-x={label.x} data-y={label.y}>
          <text
            x={label.text_x}
            y={px(label.y + 4)}
            text-anchor={label.anchor}
            data-pan-zoom-reveal={if label.zoom > 1, do: label.zoom}
            visibility={if label.zoom > 1, do: "hidden"}
          >
            {label.name}
          </text>
        </g>
      </g>
    </.pan_zoom>
    """
  end

  attr :trips, :list, required: true
  attr :places, :list, required: true
  attr :radius_scale, :float, required: true
  attr :route_width, :float, required: true

  defp map_layers(assigns) do
    assigns =
      assign(assigns,
        land: @land,
        lakes: @lakes,
        map_width: Geo.width(),
        map_height: Geo.height()
      )

    ~H"""
    <rect width={@map_width} height={@map_height} class={water()} />
    <path d={@land} class={land()} />
    <path d={@lakes} class={water()} />
    <path
      :for={trip <- @trips}
      d={trip}
      fill="none"
      class="stroke-chart-1 dark:stroke-chart-3"
      stroke-width={@route_width}
      stroke-opacity="0.45"
      stroke-linecap="round"
      vector-effect="non-scaling-stroke"
    />
    <g
      :for={place <- @places}
      data-pan-zoom-fixed
      data-x={place.x}
      data-y={place.y}
    >
      <circle
        cx={place.x}
        cy={place.y}
        r={px(place.radius * @radius_scale)}
        class="fill-chart-2 stroke-background"
        stroke-width="1.5"
      >
        <title>{place.name}</title>
      </circle>
    </g>
    """
  end

  defp water, do: "fill-[oklch(0.93_0.028_230)] dark:fill-[oklch(0.2_0.02_245)]"
  defp land, do: "fill-[oklch(0.985_0.008_85)] dark:fill-[oklch(0.285_0.004_60)]"
  defp halo, do: "stroke-[oklch(0.985_0.008_85)] dark:stroke-[oklch(0.285_0.004_60)]"

  # Each trip bows a little to its left, so a trip out and the trip back
  # between the same two cities draw as two arcs instead of one line.
  defp trips(rows) do
    for row <- rows do
      {x1, y1} = Geo.project(row["from_lat"], row["from_lon"])
      {x2, y2} = Geo.project(row["to_lat"], row["to_lon"])
      {cx, cy} = {(x1 + x2) / 2 + (y2 - y1) * 0.15, (y1 + y2) / 2 - (x2 - x1) * 0.15}
      "M#{x1},#{y1}Q#{px(cx)},#{px(cy)} #{x2},#{y2}"
    end
  end

  defp places(rows) do
    rows
    |> Enum.flat_map(
      &[
        {&1["from_place"], &1["from_lat"], &1["from_lon"]},
        {&1["to_place"], &1["to_lat"], &1["to_lon"]}
      ]
    )
    |> Enum.frequencies()
    |> Enum.map(fn {{name, lat, lon}, visits} ->
      {x, y} = Geo.project(lat, lon)
      %{name: name, x: x, y: y, radius: px(2.5 + :math.sqrt(visits) * 2), visits: visits}
    end)
    |> Enum.sort_by(&{-&1.visits, &1.name})
  end

  # Names the busiest places first. A name that would cover another name or a
  # dot, or run off the starting view, waits for the first zoom level where it
  # fits, and a name that never fits is left to the dot's tooltip. Markers
  # keep their screen size as the map zooms, so only their positions spread.
  defp labels(places, {x, y, k}) do
    on_screen? = fn {left, top, right, bottom} ->
      left + x >= 0 and right + x <= @width and top + y >= 0 and bottom + y <= @height
    end

    Enum.reduce(@zoom_levels, [], fn zoom, placed ->
      scale = k * zoom
      dots = Enum.map(places, &{&1.name, dot_box(&1, k, scale)})

      Enum.reduce(places, placed, fn place, placed ->
        taken = Enum.map(placed, &label_box(&1, k, scale))
        others = for {name, box} <- dots, name != place.name, do: box

        if Enum.any?(placed, &(&1.name == place.name)) do
          placed
        else
          [:start, :end]
          |> Enum.map(&label(place, &1, zoom))
          |> Enum.find(fn label ->
            box = label_box(label, k, scale)
            (zoom > 1 or on_screen?.(box)) and not Enum.any?(taken ++ others, &overlap?(box, &1))
          end)
          |> case do
            nil -> placed
            label -> placed ++ [label]
          end
        end
      end)
    end)
  end

  defp label(place, anchor, zoom) do
    offset = if anchor == :start, do: place.radius + 5, else: -(place.radius + 5)

    %{
      name: place.name,
      x: place.x,
      y: place.y,
      radius: place.radius,
      text_x: px(place.x + offset),
      anchor: Atom.to_string(anchor),
      zoom: zoom
    }
  end

  defp label_box(label, k, scale) do
    {x, y} = {label.x * scale, label.y * scale}
    gap = (label.radius + 5) * k
    width = String.length(label.name) * @letter * k

    left = if label.anchor == "start", do: x + gap, else: x - gap - width
    {left - 2, y - 10 * k, left + width + 2, y + 5 * k}
  end

  defp dot_box(place, k, scale) do
    {x, y, r} = {place.x * scale, place.y * scale, place.radius * k}
    {x - r, y - r, x + r, y + r}
  end

  defp overlap?({a0, b0, a1, b1}, {c0, d0, c1, d1}),
    do: a0 < c1 and c0 < a1 and b0 < d1 and d0 < b1

  defp frame([], _pad), do: {0, 0, Geo.width(), Geo.height()}

  defp frame(places, {pad_x, pad_y}) do
    {x0, x1} = places |> Enum.map(& &1.x) |> Enum.min_max()
    {y0, y1} = places |> Enum.map(& &1.y) |> Enum.min_max()
    {px(x0 - pad_x), px(y0 - pad_y), px(x1 - x0 + 2 * pad_x), px(y1 - y0 + 2 * pad_y)}
  end
end

defmodule CorpusWeb.Examples.PaulsJourneys do
  @behaviour CorpusWeb.Examples

  use Phoenix.Component

  import CorpusWeb.Examples, only: [scale: 3, px: 1]

  @width 800
  @height 500
  @pad 30

  def slug, do: "pauls-journeys"
  def title, do: "Paul's journeys"

  def description,
    do:
      "Every trip Paul takes in Acts, drawn from city to city. The busiest places are the largest."

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

  def chart(assigns) do
    project = projection(assigns.rows)

    trips =
      for row <- assigns.rows do
        {x1, y1} = project.(row["from_lat"], row["from_lon"])
        {x2, y2} = project.(row["to_lat"], row["to_lon"])
        %{x1: x1, y1: y1, x2: x2, y2: y2}
      end

    places =
      assigns.rows
      |> Enum.flat_map(
        &[
          {&1["from_place"], &1["from_lat"], &1["from_lon"]},
          {&1["to_place"], &1["to_lat"], &1["to_lon"]}
        ]
      )
      |> Enum.frequencies()
      |> Enum.map(fn {{name, lat, lon}, visits} ->
        {x, y} = project.(lat, lon)
        radius = px(2.5 + :math.sqrt(visits) * 2)
        right? = x < @width * 0.8

        %{
          name: name,
          x: x,
          y: y,
          radius: radius,
          label_x: if(right?, do: px(x + radius + 5), else: px(x - radius - 5)),
          anchor: if(right?, do: "start", else: "end")
        }
      end)
      |> Enum.sort_by(& &1.radius, :desc)

    assigns =
      assign(assigns,
        trips: trips,
        places: places,
        labeled: Enum.take(places, 10),
        width: @width,
        height: @height
      )

    ~H"""
    <svg
      viewBox={"0 0 #{@width} #{@height}"}
      class="w-full"
      role="img"
      aria-label="Map of Paul's journeys"
    >
      <line
        :for={trip <- @trips}
        x1={trip.x1}
        y1={trip.y1}
        x2={trip.x2}
        y2={trip.y2}
        class="stroke-chart-1"
        stroke-width="2"
        stroke-opacity="0.35"
        stroke-linecap="round"
      />
      <circle
        :for={place <- @places}
        cx={place.x}
        cy={place.y}
        r={place.radius}
        class="fill-chart-2 stroke-background"
        stroke-width="1.5"
      >
        <title>{place.name}</title>
      </circle>
      <text
        :for={place <- @labeled}
        :if={!@preview}
        x={place.label_x}
        y={px(place.y + 4)}
        text-anchor={place.anchor}
        font-size="13"
        class="fill-foreground"
      >
        {place.name}
      </text>
    </svg>
    """
  end

  # An equirectangular projection, with longitude narrowed by the cosine of the
  # mean latitude so distances look right this far from the equator.
  defp projection([]), do: fn _lat, _lon -> {0, 0} end

  defp projection(rows) do
    lats = Enum.flat_map(rows, &[&1["from_lat"], &1["to_lat"]])
    lons = Enum.flat_map(rows, &[&1["from_lon"], &1["to_lon"]])
    squeeze = :math.cos(Enum.sum(lats) / length(lats) * :math.pi() / 180)

    {lat0, lat1} = Enum.min_max(lats)
    {lon0, lon1} = Enum.min_max(lons)
    map_width = (lon1 - lon0) * squeeze
    map_height = lat1 - lat0
    unit = min((@width - 2 * @pad) / map_width, (@height - 2 * @pad) / map_height)
    left = (@width - map_width * unit) / 2
    top = (@height - map_height * unit) / 2

    fn lat, lon ->
      {px(left + scale(lon, {lon0, lon1}, {0, map_width}) * unit),
       px(top + scale(lat, {lat1, lat0}, {0, map_height}) * unit)}
    end
  end
end

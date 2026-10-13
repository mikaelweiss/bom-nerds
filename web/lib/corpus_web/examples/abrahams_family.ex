defmodule CorpusWeb.Examples.AbrahamsFamily do
  @behaviour CorpusWeb.Examples

  use Phoenix.Component

  import CorpusWeb.Examples, only: [pan_zoom: 1, px: 1]

  @width 800
  @height 560
  @margin 24
  @row 18
  @gap 36
  @letter 6.8
  @preview_generations 3
  @preview_row 26

  def slug, do: "abrahams-family"
  def title, do: "Abraham's family"

  def description,
    do:
      "Every descendant of Abraham the scriptures name, from parent to child. " <>
        "Someone descended from him by more than one line appears once."

  def sql do
    """
    with recursive line(id, parent_id, generation, path) as (
      select e.id, null, 0, '/' || e.id || '/'
      from entity e
      join entity_type t on t.id = e.entity_type_id
      where e.name = 'Abraham' and t.name = 'Person'
      union all
      select r.subject_id, r.object_id, l.generation + 1, l.path || r.subject_id || '/'
      from line l
      cross join relationship r on r.object_id = l.id
      cross join relationship_kind k on k.id = r.relationship_kind_id
      where k.name = 'child of' and instr(l.path, '/' || r.subject_id || '/') = 0
    ),
    family as (
      select id, parent_id, generation,
             row_number() over (partition by id order by generation, parent_id) as nth
      from line
    )
    select f.id, f.parent_id, f.generation, e.name, t.name as type
    from family f
    join entity e on e.id = f.id
    join entity_type t on t.id = e.entity_type_id
    where f.nth = 1
    order by f.generation, f.id
    """
  end

  attr :rows, :list, required: true
  attr :preview, :boolean, default: false

  def chart(%{preview: true} = assigns) do
    people = Enum.filter(assigns.rows, &(&1["generation"] <= @preview_generations))
    tree = layout(people, @preview_row, fn _generation -> nil end)
    column = (tree.height * 1.6 - 2 * @margin) / max(tree.generations, 1)
    tree = layout(people, @preview_row, &if(&1 < tree.generations, do: column))

    assigns = assign(assigns, tree: tree)

    ~H"""
    <svg
      viewBox={"0 0 #{@tree.width} #{@tree.height}"}
      class="h-full w-full"
      role="img"
      aria-label="The first generations of Abraham's family"
    >
      <path d={@tree.links} fill="none" class="stroke-border" stroke-width="3" />
      <g class="fill-chart-1">
        <circle :for={node <- @tree.nodes} cx={node.x} cy={node.y} r="7" />
      </g>
    </svg>
    """
  end

  def chart(assigns) do
    tree = layout(assigns.rows, @row, &column_width(assigns.rows, &1))
    fit = min(@width / max(tree.width, 1), @height / max(tree.height, 1))

    assigns =
      assign(assigns,
        tree: tree,
        width: @width,
        height: @height,
        view: {0, 0, 1},
        min_zoom: Float.round(min(fit * 0.9, 1), 3)
      )

    ~H"""
    <.pan_zoom
      id="abrahams-family-tree"
      label="Abraham's family tree"
      width={@width}
      height={@height}
      view={@view}
      min_zoom={@min_zoom}
      max_zoom={3.0}
      class="bg-background"
    >
      <path d={@tree.links} fill="none" class="stroke-border" stroke-width="1.5" />
      <g class="fill-chart-1">
        <circle :for={node <- @tree.nodes} :if={!node.group?} cx={node.x} cy={node.y} r="4" />
      </g>
      <g class="fill-background stroke-chart-1" stroke-width="1.5">
        <circle :for={node <- @tree.nodes} :if={node.group?} cx={node.x} cy={node.y} r="4" />
      </g>
      <g
        font-size="12"
        class="stroke-background"
        stroke-width="4"
        stroke-linejoin="round"
        paint-order="stroke"
      >
        <text
          :for={node <- @tree.nodes}
          x={node.x + 8}
          y={node.y + 4}
          class={if node.group?, do: "fill-muted-foreground italic", else: "fill-foreground"}
        >
          {node.name}
        </text>
      </g>
    </.pan_zoom>
    """
  end

  defp column_width(rows, generation) do
    longest =
      rows
      |> Enum.filter(&(&1["generation"] == generation))
      |> Enum.map(&String.length(&1["name"]))
      |> Enum.max(fn -> 0 end)

    8 + longest * @letter + @gap
  end

  # A tidy tree: each subtree packs as close to the one above it as its
  # widest generation allows, and each parent sits level with its first child,
  # so the eldest line reads straight across. Generations run left to right in
  # columns sized to their names.
  defp layout(rows, row, column_width) do
    children = Enum.group_by(rows, & &1["parent_id"])

    case children[nil] do
      [root] ->
        {placed, contour} = subtree(root, children, row)
        {top, bottom} = contour |> Map.values() |> Enum.reduce(&extent/2)
        generations = Enum.max(Map.keys(contour))

        columns =
          Enum.scan(0..generations, {@margin, 0}, fn generation, {x, width} ->
            {x + width, column_width.(generation) || 0}
          end)

        {last_x, last_width} = List.last(columns)
        xs = columns |> Enum.map(&elem(&1, 0)) |> List.to_tuple()

        nodes =
          for {person, y} <- placed do
            %{
              id: person["id"],
              parent_id: person["parent_id"],
              name: person["name"],
              group?: person["type"] == "Group",
              x: px(elem(xs, person["generation"])),
              y: px(y - top + @margin)
            }
          end

        %{
          nodes: nodes,
          links: links(nodes),
          generations: generations,
          width: px(last_x + last_width + @margin),
          height: px(bottom - top + 2 * @margin)
        }

      _ ->
        %{nodes: [], links: "", generations: 0, width: @width, height: @height}
    end
  end

  # The subtree's people with each one's height relative to `person`, and its
  # contour: the highest and lowest height in each generation.
  defp subtree(person, children, row) do
    {placed, contour} =
      children
      |> Map.get(person["id"], [])
      |> Enum.reduce({[], %{}}, fn kid, {placed, contour} ->
        {kid_placed, kid_contour} = subtree(kid, children, row)

        shift =
          kid_contour
          |> Enum.filter(fn {generation, _} -> Map.has_key?(contour, generation) end)
          |> Enum.map(fn {generation, {top, _}} -> elem(contour[generation], 1) + row - top end)
          |> Enum.max(fn -> 0 end)

        {
          placed ++ Enum.map(kid_placed, fn {p, y} -> {p, y + shift} end),
          Map.merge(contour, shift_contour(kid_contour, shift), fn _, a, b -> extent(a, b) end)
        }
      end)

    {[{person, 0} | placed], Map.put(contour, person["generation"], {0, 0})}
  end

  defp shift_contour(contour, shift),
    do:
      Map.new(contour, fn {generation, {top, bottom}} ->
        {generation, {top + shift, bottom + shift}}
      end)

  defp extent({top_a, bottom_a}, {top_b, bottom_b}),
    do: {min(top_a, top_b), max(bottom_a, bottom_b)}

  defp links(nodes) do
    positions = Map.new(nodes, &{&1.id, &1})

    Enum.map_join(nodes, fn node ->
      case positions[node.parent_id] do
        nil ->
          ""

        parent ->
          middle = px((parent.x + node.x) / 2)
          "M#{parent.x},#{parent.y}C#{middle},#{parent.y} #{middle},#{node.y} #{node.x},#{node.y}"
      end
    end)
  end
end

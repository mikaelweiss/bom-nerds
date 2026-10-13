defmodule CorpusWeb.Examples.AbrahamsFamily do
  @behaviour CorpusWeb.Examples

  use Phoenix.Component

  import CorpusWeb.Examples, only: [px: 1]

  @width 800
  @row 20
  @column 190
  @top 20

  def slug, do: "abrahams-family"
  def title, do: "Abraham's family"
  def description, do: "Abraham's children, grandchildren, and great-grandchildren."

  def sql do
    """
    with recursive family(id, parent_id, generation) as (
      select e.id, null, 0
      from entity e
      join entity_type t on t.id = e.entity_type_id
      where e.name = 'Abraham' and t.name = 'Person'
      union
      select r.subject_id, r.object_id, f.generation + 1
      from relationship r
      join relationship_kind k on k.id = r.relationship_kind_id and k.name = 'child of'
      join family f on f.id = r.object_id
      where f.generation < 3
    )
    select f.id, f.parent_id, f.generation, e.name
    from family f
    join entity e on e.id = f.id
    order by f.generation, f.id
    """
  end

  attr :rows, :list, required: true
  attr :preview, :boolean, default: false

  def chart(assigns) do
    # A person descended from Abraham twice keeps only the first line found.
    people = Enum.uniq_by(assigns.rows, & &1["id"])
    children = Enum.group_by(people, & &1["parent_id"])

    {nodes, leaves} =
      case children[nil] do
        [root] -> place(root, children, 0)
        _ -> {[], 0}
      end

    positions = Map.new(nodes, &{&1.id, &1})

    links =
      for node <- nodes, parent = positions[node.parent_id] do
        middle = (parent.x + node.x) / 2

        "M#{parent.x},#{parent.y} C#{px(middle)},#{parent.y} #{px(middle)},#{node.y} #{node.x},#{node.y}"
      end

    assigns =
      assign(assigns,
        nodes: nodes,
        links: links,
        width: @width,
        height: leaves * @row + 2 * @top
      )

    ~H"""
    <svg
      viewBox={"0 0 #{@width} #{@height}"}
      class="w-full"
      role="img"
      aria-label="Abraham's family tree"
    >
      <path :for={link <- @links} d={link} fill="none" class="stroke-border" stroke-width="1.5" />
      <circle :for={node <- @nodes} cx={node.x} cy={node.y} r="4" class="fill-chart-1" />
      <text
        :for={node <- @nodes}
        :if={!@preview}
        x={node.x + 8}
        y={node.y + 4}
        font-size="12"
        class="fill-foreground"
      >
        {node.name}
      </text>
    </svg>
    """
  end

  # Leaves take the next row down and each parent sits beside the middle of
  # its children.
  defp place(person, children, next_row) do
    x = 20 + person["generation"] * @column
    node = &%{id: person["id"], parent_id: person["parent_id"], name: person["name"], x: x, y: &1}

    case Map.get(children, person["id"], []) do
      [] ->
        {[node.(@top + next_row * @row + @row / 2)], next_row + 1}

      kids ->
        {placed, next_row} =
          Enum.reduce(kids, {[], next_row}, fn kid, {placed, row} ->
            {nodes, row} = place(kid, children, row)
            {placed ++ nodes, row}
          end)

        ys = for kid <- kids, n <- placed, n.id == kid["id"], do: n.y
        {[node.(px((List.first(ys) + List.last(ys)) / 2)) | placed], next_row}
    end
  end
end

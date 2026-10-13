defmodule CorpusWeb.DataLive do
  use CorpusWeb, :live_view

  import SaladUI.Helpers, only: [button_variant: 1]

  alias Corpus.{Browser, Database, Query, RateLimit, Versions}

  @control ~w(order cursor row)
  @shown_rows 1_000

  @doc "Adds the visitor's address to the LiveView session, so the SQL editor limits it like the API."
  def session(conn), do: %{"client" => CorpusWeb.SqlController.client(conn)}

  def mount(_params, session, socket) do
    database = Database.get(Versions.latest())

    {:ok,
     assign(socket,
       database: database,
       tables: if(database, do: Browser.tables(database), else: []),
       search: "",
       client: session["client"],
       examples: examples(Versions.guide(Versions.latest())),
       ran: nil,
       result: nil
     )}
  end

  # The browser pipeline does not fetch query params, and filters may repeat a
  # column, so the query string is read from the URI.
  def handle_params(params, uri, socket) do
    pairs =
      case URI.parse(uri).query do
        nil -> []
        query -> query |> URI.query_decoder() |> Enum.to_list()
      end

    {:noreply, handle_pairs(socket, socket.assigns.live_action, params, pairs)}
  end

  defp handle_pairs(socket, :sql, _params, pairs) do
    q = pairs |> List.keyfind("q", 0, {"q", ""}) |> elem(1)
    socket = assign(socket, page_title: "SQL", draft: q)

    if q != "" and q != socket.assigns.ran and connected?(socket),
      do: run(socket, q),
      else: socket
  end

  defp handle_pairs(socket, :table, params, pairs) do
    control = pairs |> Enum.filter(&(elem(&1, 0) in @control)) |> Map.new()

    state = %{
      table: params["table"],
      filters: for({column, value} <- pairs, column not in @control, do: filter(column, value)),
      order: order(control["order"]),
      cursor: cursor(control["cursor"]),
      row: integer(control["row"])
    }

    assign(socket,
      page_title: state.table || "Data",
      state: state,
      page: page(socket.assigns.database, state),
      row: row(socket.assigns.database, state)
    )
  end

  defp filter(column, value) do
    case String.split(value, ".", parts: 2) do
      [operator, value] -> {column, operator, value}
      [operator] -> {column, operator, ""}
    end
  end

  defp order(nil), do: nil

  defp order(value) do
    case Regex.run(~r/^(.*)\.(asc|desc)$/, value) do
      [_, column, direction] -> {column, String.to_existing_atom(direction)}
      nil -> {value, :asc}
    end
  end

  defp cursor(nil), do: nil

  defp cursor(value) do
    with [kind, n] when kind in ~w(after before offset) <- String.split(value, ".", parts: 2),
         n when is_integer(n) <- integer(n) do
      {String.to_existing_atom(kind), n}
    else
      _ -> nil
    end
  end

  defp integer(nil), do: nil

  defp integer(value) do
    case Integer.parse(value) do
      {n, ""} -> n
      _ -> nil
    end
  end

  defp page(nil, _state), do: nil
  defp page(_database, %{table: nil}), do: nil

  defp page(database, state),
    do:
      Browser.page(database, state.table,
        filters: state.filters,
        order: state.order,
        cursor: state.cursor
      )

  defp row(database, %{table: table, row: rowid})
       when database != nil and table != nil and rowid != nil,
       do: Browser.row(database, table, rowid)

  defp row(_database, _state), do: nil

  def handle_event("search", %{"search" => search}, socket),
    do: {:noreply, assign(socket, search: search)}

  def handle_event("open_row", %{"rowid" => rowid}, socket),
    do: {:noreply, push_patch(socket, to: data_path(socket.assigns.state, row: integer(rowid)))}

  def handle_event("add_filter", %{"column" => column, "operator" => operator} = params, socket) do
    state = socket.assigns.state
    filters = state.filters ++ [{column, operator, params["value"] || ""}]
    {:noreply, push_patch(socket, to: data_path(state, filters: filters, cursor: nil, row: nil))}
  end

  def handle_event("draft", %{"q" => q}, socket), do: {:noreply, assign(socket, draft: q)}

  def handle_event("example", %{"example" => index}, socket) do
    case integer(index) && Enum.at(socket.assigns.examples, integer(index)) do
      {_label, sql} -> {:noreply, assign(socket, draft: sql)}
      nil -> {:noreply, socket}
    end
  end

  def handle_event("run", %{"q" => q}, socket) do
    q = String.trim(q)
    socket = socket |> assign(draft: q) |> run(q)
    {:noreply, push_patch(socket, to: sql_path(q))}
  end

  defp run(%{assigns: %{database: nil}} = socket, _q), do: socket

  defp run(socket, "") do
    assign(socket, ran: "", result: {:error, "Write a query to run."})
  end

  defp run(socket, q) do
    %{database: database, client: client} = socket.assigns

    result =
      case RateLimit.run(client, fn -> Query.run(database, q) end) do
        {:ok, {:ok, result}} -> {:ok, result}
        {:ok, {_status, message}} -> {:error, message}
        {:deny, message} -> {:error, message}
      end

    assign(socket, ran: q, result: result)
  end

  @doc """
  The guide's example queries as `{label, sql}`: each sql block under
  "## Examples", labeled by the line before it.
  """
  def examples(guide) do
    with [_, rest] <- Regex.split(~r/^## Examples[ \t]*$/m, guide, parts: 2) do
      section = rest |> String.split(~r/^## /m, parts: 2) |> hd()

      for [label, sql] <-
            Regex.scan(~r/^([^\n]+)\n\n```sql\n(.*?)\n```/ms, section, capture: :all_but_first),
          do: {label |> String.trim() |> String.trim_trailing(":"), sql}
    else
      _ -> []
    end
  end

  @doc """
  Where the reader shows `location`, a map of edition and book names, chapter
  number, and verse number.
  """
  def read_path(%{edition: edition, book: book, chapter: chapter, verse: verse}) do
    path = "/read/#{slug(edition)}/#{slug(book)}/#{chapter}"
    if verse, do: path <> "?v=#{verse}", else: path
  end

  @doc ~S|The reader's address segment for an edition or book name, like "book-of-mormon".|
  def slug("King James Version" <> _), do: "kjv"

  def slug(name) do
    name
    |> String.replace(~r/\s*\(.*\)\s*$/, "")
    |> String.downcase()
    |> String.replace(~r/[^a-z0-9]+/, "-")
    |> String.trim("-")
  end

  defp data_path(state, changes) do
    state = Map.merge(state, Map.new(changes))

    query =
      Enum.map(state.filters, fn {column, operator, value} ->
        {column, if(Browser.unary?(operator), do: operator, else: "#{operator}.#{value}")}
      end) ++
        Enum.reject(
          [
            {"order", with({column, direction} <- state.order, do: "#{column}.#{direction}")},
            {"cursor", with({kind, n} <- state.cursor, do: "#{kind}.#{n}")},
            {"row", state.row}
          ],
          &is_nil(elem(&1, 1))
        )

    table_path(state.table, query)
  end

  defp table_path(table, []), do: ~p"/data/#{table}"
  defp table_path(table, query), do: ~p"/data/#{table}?#{query}"

  defp filters_path(table, filters),
    do: table_path(table, for({column, value} <- filters, do: {column, "eq.#{value}"}))

  defp sql_path(""), do: ~p"/sql"
  defp sql_path(q), do: ~p"/sql?#{[q: q]}"

  defp next_order(%{order: {column, :asc}}, column), do: {column, :desc}
  defp next_order(%{order: {column, :desc}}, column), do: nil
  defp next_order(_state, column), do: {column, :asc}

  defp delimit(nil), do: ""

  defp delimit(n) do
    n
    |> Integer.to_string()
    |> String.reverse()
    |> String.replace(~r/(\d{3})(?=\d)/, "\\1,")
    |> String.reverse()
  end

  defp visible_tables(tables, ""), do: tables

  defp visible_tables(tables, search) do
    search = String.downcase(search)
    Enum.filter(tables, fn {name, _count} -> String.contains?(name, search) end)
  end

  defp operator_label(operator) do
    case List.keyfind(Browser.operators(), operator, 0) do
      {_, label} -> label
      nil -> operator
    end
  end

  defp span_label(""), do: "Words"
  defp span_label(prefix), do: prefix |> String.trim_trailing("_") |> String.capitalize()

  def render(assigns) do
    ~H"""
    <Layouts.app>
      <section class="mx-auto max-w-[96rem] px-4 py-6 sm:px-6">
        <div class="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 class="font-serif text-3xl font-semibold tracking-tight">Data</h1>
            <p :if={@database} class="mt-1 text-sm text-muted-foreground">
              Every table in release {@database.release["tag"]}, read-only.
            </p>
          </div>
          <nav class="inline-flex rounded-md border bg-muted p-1 text-sm" aria-label="Data views">
            <.link
              patch={~p"/data"}
              class={[
                "rounded px-3 py-1",
                @live_action == :table && "bg-background font-medium shadow-sm"
              ]}
            >
              Tables
            </.link>
            <.link
              patch={~p"/sql"}
              class={[
                "rounded px-3 py-1",
                @live_action == :sql && "bg-background font-medium shadow-sm"
              ]}
            >
              SQL
            </.link>
          </nav>
        </div>

        <p :if={!@database} class="mt-10 rounded-lg border p-6 text-muted-foreground">
          No data is installed on this server yet.
        </p>

        <.tables :if={@database && @live_action == :table} {assigns} />
        <.sql :if={@database && @live_action == :sql} {assigns} />
      </section>

      <.drawer :if={@database && @live_action == :table && @row} row={@row} state={@state} />
    </Layouts.app>
    """
  end

  defp tables(assigns) do
    ~H"""
    <div class="mt-6 grid h-[calc(100vh-13rem)] min-h-[28rem] grid-cols-[14rem_1fr] overflow-hidden rounded-lg border">
      <aside class="flex min-h-0 flex-col border-r bg-muted/30">
        <form id="table-search" phx-change="search" class="border-b p-2">
          <input
            type="search"
            name="search"
            value={@search}
            placeholder="Find a table"
            aria-label="Find a table"
            phx-debounce="100"
            class="w-full rounded-md border bg-background px-2 py-1 text-sm"
          />
        </form>
        <nav class="min-h-0 flex-1 overflow-y-auto py-1" aria-label="Tables">
          <.link
            :for={{name, count} <- visible_tables(@tables, @search)}
            patch={~p"/data/#{name}"}
            aria-current={if name == @state.table, do: "page"}
            class={[
              "flex items-center justify-between gap-2 px-3 py-1 font-mono text-xs hover:bg-muted",
              name == @state.table && "bg-muted font-semibold text-foreground"
            ]}
          >
            <span class="truncate">{name}</span>
            <span class="shrink-0 text-muted-foreground">{delimit(count)}</span>
          </.link>
        </nav>
      </aside>

      <div class="flex min-h-0 min-w-0 flex-col">
        <p :if={!@state.table} class="p-6 text-muted-foreground">
          Choose a table to browse its rows.
        </p>
        <.grid :if={@state.table} {assigns} />
      </div>
    </div>
    """
  end

  defp grid(assigns) do
    assigns =
      assign(assigns,
        columns: Browser.columns(assigns.database, assigns.state.table) || [],
        count: assigns.tables |> List.keyfind(assigns.state.table, 0, {nil, nil}) |> elem(1)
      )

    ~H"""
    <div class="flex flex-wrap items-center gap-2 border-b px-3 py-2 text-sm">
      <h2 class="font-mono font-semibold">{@state.table}</h2>
      <span :if={@state.filters == [] and @count} class="text-xs text-muted-foreground">
        {delimit(@count)} rows
      </span>
      <span
        :for={{{column, operator, value}, index} <- Enum.with_index(@state.filters)}
        class="inline-flex items-center gap-1 rounded-full border bg-muted/50 px-2 py-0.5 font-mono text-xs"
      >
        {column} {operator_label(operator)} {if !Browser.unary?(operator), do: value}
        <.link
          patch={data_path(@state, filters: List.delete_at(@state.filters, index), cursor: nil)}
          aria-label={"Remove filter on #{column}"}
          class="text-muted-foreground hover:text-foreground"
        >
          ×
        </.link>
      </span>
      <form
        :if={@columns != []}
        id="filter-form"
        phx-submit="add_filter"
        class="ml-auto flex items-center gap-1"
      >
        <select
          name="column"
          aria-label="Column"
          class="rounded-md border bg-background px-2 py-1 font-mono text-xs"
        >
          <option :for={column <- @columns} value={column}>{column}</option>
        </select>
        <select
          name="operator"
          aria-label="Operator"
          class="rounded-md border bg-background px-2 py-1 text-xs"
        >
          <option :for={{key, label} <- Browser.operators()} value={key}>{label}</option>
        </select>
        <input
          type="text"
          name="value"
          placeholder="Value"
          aria-label="Value"
          class="w-36 rounded-md border bg-background px-2 py-1 font-mono text-xs"
        />
        <button type="submit" class={button_variant(%{variant: "outline", size: "sm"})}>
          Add filter
        </button>
      </form>
    </div>

    <div class="min-h-0 flex-1 overflow-auto">
      <p
        :if={match?({:error, _}, @page)}
        role="alert"
        class="m-4 rounded-md border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive"
      >
        {elem(@page, 1)}
      </p>
      <table
        :if={match?({:ok, _}, @page)}
        class="min-w-full border-separate border-spacing-0 font-mono text-xs"
      >
        <thead>
          <tr>
            <th
              :for={column <- @columns}
              class="sticky top-0 z-10 border-r border-b bg-muted px-2 py-1.5 text-left font-semibold whitespace-nowrap"
            >
              <.link
                patch={data_path(@state, order: next_order(@state, column), cursor: nil)}
                class="inline-flex items-center gap-1 hover:text-foreground"
              >
                {column}
                <span :if={@state.order == {column, :asc}} aria-label="sorted ascending">↑</span>
                <span :if={@state.order == {column, :desc}} aria-label="sorted descending">↓</span>
              </.link>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr
            :for={{rowid, values} <- elem(@page, 1).rows}
            id={"row-#{rowid}"}
            phx-click="open_row"
            phx-value-rowid={rowid}
            class={["cursor-pointer hover:bg-muted/60", @state.row == rowid && "bg-muted"]}
          >
            <td :for={value <- values} class="max-w-xs truncate border-r border-b px-2 py-1">
              <.value value={value} />
            </td>
          </tr>
        </tbody>
      </table>
      <p :if={match?({:ok, %{rows: []}}, @page)} class="p-6 text-sm text-muted-foreground">
        No rows match.
      </p>
    </div>

    <div :if={match?({:ok, _}, @page)} class="flex items-center justify-end gap-2 border-t px-3 py-2">
      <.link
        :if={elem(@page, 1).prev}
        patch={data_path(@state, cursor: elem(@page, 1).prev, row: nil)}
        class={button_variant(%{variant: "outline", size: "sm"})}
      >
        Previous
      </.link>
      <.link
        :if={elem(@page, 1).next}
        patch={data_path(@state, cursor: elem(@page, 1).next, row: nil)}
        class={button_variant(%{variant: "outline", size: "sm"})}
      >
        Next
      </.link>
    </div>
    """
  end

  attr :value, :any, required: true

  defp value(%{value: nil} = assigns) do
    ~H|<span class="text-muted-foreground/60 italic">NULL</span>|
  end

  defp value(assigns) do
    ~H"{format(@value)}"
  end

  defp format(value) when is_binary(value) do
    if String.valid?(value), do: value, else: "x'#{Base.encode16(value)}'"
  end

  defp format(value), do: to_string(value)

  defp drawer(assigns) do
    assigns =
      case assigns.row do
        {:ok, row} ->
          assign(assigns,
            links:
              for(%{columns: [column]} = ref <- row.references, into: %{}, do: {column, ref}),
            composite: Enum.filter(row.references, &match?(%{columns: [_, _ | _]}, &1))
          )

        _ ->
          assigns
      end

    ~H"""
    <aside
      id="row-drawer"
      class="fixed inset-y-0 right-0 z-40 flex w-full max-w-xl flex-col border-l bg-background shadow-2xl"
      aria-label="Row"
    >
      <div class="flex items-center justify-between border-b px-5 py-3">
        <h2 class="font-mono text-sm font-semibold">
          {@state.table} <span class="font-normal text-muted-foreground">row {@state.row}</span>
        </h2>
        <.link
          patch={data_path(@state, row: nil)}
          aria-label="Close row"
          class={button_variant(%{variant: "ghost", size: "sm"})}
        >
          Close
        </.link>
      </div>

      <div class="min-h-0 flex-1 overflow-y-auto px-5 py-4">
        <p :if={match?({:error, _}, @row)} role="alert" class="text-sm text-destructive">
          {elem(@row, 1)}
        </p>

        <div :if={match?({:ok, _}, @row)} class="space-y-8">
          <section :for={span <- elem(@row, 1).spans} class="space-y-1">
            <h3 class="text-xs font-medium tracking-wide text-muted-foreground uppercase">
              {span_label(span.prefix)}
            </h3>
            <p :if={span[:error]} class="text-sm text-destructive">{span.error}</p>
            <div :if={!span[:error]}>
              <p class="font-serif text-base leading-relaxed">{span.text}</p>
              <.link navigate={read_path(span.start)} class="inline-block text-sm underline">
                {Browser.reference(span)}
              </.link>
            </div>
          </section>

          <dl class="divide-y rounded-md border font-mono text-xs">
            <div
              :for={{column, value} <- elem(@row, 1).columns}
              class="grid grid-cols-[10rem_1fr] gap-3 px-3 py-1.5"
            >
              <dt class="truncate text-muted-foreground">{column}</dt>
              <dd class="break-words">
                <.link
                  :if={@links[column]}
                  patch={filters_path(@links[column].table, @links[column].filters)}
                  class="inline-block underline"
                >
                  {value}
                </.link>
                <.value :if={!@links[column]} value={value} />
              </dd>
            </div>
          </dl>

          <section :if={@composite != []}>
            <h3 class="text-xs font-medium tracking-wide text-muted-foreground uppercase">
              Keys over several columns
            </h3>
            <ul class="mt-2 space-y-1 font-mono text-xs">
              <li :for={ref <- @composite}>
                <.link patch={filters_path(ref.table, ref.filters)} class="inline-block underline">
                  {ref.table}
                </.link>
                <span class="text-muted-foreground">
                  ({Enum.map_join(ref.filters, ", ", fn {column, value} -> "#{column} #{value}" end)})
                </span>
              </li>
            </ul>
          </section>

          <section>
            <h3 class="text-xs font-medium tracking-wide text-muted-foreground uppercase">
              Rows that point here
            </h3>
            <p :if={elem(@row, 1).referenced_by == []} class="mt-2 text-sm text-muted-foreground">
              No rows in other tables point at this row.
            </p>
            <ul class="mt-2 space-y-2 font-mono text-xs">
              <li :for={group <- elem(@row, 1).referenced_by} id={"referenced-by-#{group.table}"}>
                <span class="font-semibold">{group.table}</span>
                <span class="text-muted-foreground">{delimit(group.count)}</span>
                <ul class="mt-1 ml-3 space-y-0.5">
                  <li :for={link <- group.links}>
                    <.link
                      patch={filters_path(link.table, link.filters)}
                      class="inline-block underline"
                    >
                      {Enum.map_join(link.filters, ", ", &elem(&1, 0))}
                    </.link>
                    <span class="text-muted-foreground">{delimit(link.count)}</span>
                  </li>
                </ul>
              </li>
            </ul>
          </section>
        </div>
      </div>
    </aside>
    """
  end

  defp sql(assigns) do
    ~H"""
    <div class="mt-6 space-y-4">
      <form
        :if={@examples != []}
        id="example-form"
        phx-change="example"
        class="flex items-center gap-2 text-sm"
      >
        <label for="example" class="text-muted-foreground">Load an example</label>
        <select id="example" name="example" class="rounded-md border bg-background px-2 py-1 text-sm">
          <option value="">Choose a query</option>
          <option :for={{{label, _sql}, index} <- Enum.with_index(@examples)} value={index}>
            {label}
          </option>
        </select>
      </form>

      <form id="sql-form" phx-change="draft" phx-submit="run" class="space-y-2">
        <textarea
          id="sql-editor"
          name="q"
          rows="10"
          spellcheck="false"
          aria-label="SQL query"
          phx-hook=".RunShortcut"
          class="w-full rounded-lg border bg-muted/30 p-3 font-mono text-sm leading-relaxed"
        >{@draft}</textarea>
        <script :type={Phoenix.LiveView.ColocatedHook} name=".RunShortcut">
          export default {
            mounted() {
              this.el.addEventListener("keydown", event => {
                if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
                  event.preventDefault()
                  this.el.form.requestSubmit()
                }
              })
            }
          }
        </script>
        <div class="flex items-center gap-3">
          <button type="submit" class={button_variant(%{size: "sm"})}>Run</button>
          <span class="text-xs text-muted-foreground">
            Read-only. Up to {delimit(max_rows())} rows and {div(timeout(), 1000)} seconds a query.
          </span>
        </div>
      </form>

      <p
        :if={match?({:error, _}, @result)}
        role="alert"
        class="rounded-md border border-destructive/40 bg-destructive/5 p-4 font-mono text-sm text-destructive"
      >
        {elem(@result, 1)}
      </p>

      <.results :if={match?({:ok, _}, @result)} result={elem(@result, 1)} />
    </div>
    """
  end

  defp results(assigns) do
    assigns =
      assign(assigns, shown: Enum.take(assigns.result.rows, @shown_rows), limit: @shown_rows)

    ~H"""
    <div class="space-y-2">
      <p class="text-xs text-muted-foreground">
        {delimit(length(@result.rows))} rows{if @result.truncated, do: ", cut off at the row limit"}.
        <span :if={length(@result.rows) > @limit}>
          Showing the first {delimit(@limit)}. Add a limit, or use the API for every row.
        </span>
      </p>
      <div class="max-h-[60vh] overflow-auto rounded-lg border">
        <table id="sql-results" class="min-w-full border-separate border-spacing-0 font-mono text-xs">
          <thead>
            <tr>
              <th
                :for={column <- @result.columns}
                class="sticky top-0 border-r border-b bg-muted px-2 py-1.5 text-left font-semibold whitespace-nowrap"
              >
                {column}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr :for={row <- @shown} class="hover:bg-muted/60">
              <td
                :for={column <- @result.columns}
                class="max-w-xs truncate border-r border-b px-2 py-1"
              >
                <.value value={row[column]} />
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
    """
  end

  defp max_rows, do: Application.fetch_env!(:corpus, :query)[:max_rows]
  defp timeout, do: Application.fetch_env!(:corpus, :query)[:timeout]
end

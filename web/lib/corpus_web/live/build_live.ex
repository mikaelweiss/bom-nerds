defmodule CorpusWeb.BuildLive do
  use CorpusWeb, :live_view

  import SaladUI.Tabs
  import SaladUI.Helpers, only: [button_variant: 1]

  @query "select name, description from entity where name = 'Nephi'"

  def mount(_params, _session, socket) do
    guide = CorpusWeb.api_url("/#{Corpus.Versions.latest()}")

    {:ok,
     assign(socket,
       page_title: "Build with the data",
       release: "#{Layouts.repository()}/releases/latest",
       guide: guide,
       sqlite: ~s(sqlite3 scripture.db "#{@query}"),
       fetch: """
       const sql = "#{@query}"
       const response = await fetch("#{guide}/sql?q=" + encodeURIComponent(sql))
       const { rows } = await response.json()\
       """,
       curl: ~s(curl -G #{guide}/sql --data-urlencode "q=#{@query}")
     )}
  end

  def render(assigns) do
    ~H"""
    <Layouts.app>
      <section class="mx-auto max-w-5xl px-6 py-20 sm:py-28">
        <h1 class="max-w-3xl font-serif text-4xl font-semibold tracking-tight sm:text-6xl">
          Build with the data.
        </h1>
        <p class="mt-6 max-w-2xl text-lg text-muted-foreground">
          Download the whole database, or send it read-only SQL over HTTP from any website or
          script. Both hold the same tables.
        </p>
      </section>

      <section class="border-t">
        <div class="mx-auto max-w-5xl px-6 py-20">
          <h2 class="font-serif text-3xl font-semibold">Download</h2>
          <p class="mt-4 max-w-2xl text-lg text-muted-foreground">
            Each release is a SQLite database and a set of JSON files.
          </p>
          <ul class="mt-6 space-y-2 text-lg">
            <li>
              <a href={@release} class="underline">scripture-db.zip</a> holds the SQLite database.
            </li>
            <li>
              <a href={@release} class="underline">scripture-json.zip</a> holds the same data as JSON.
            </li>
          </ul>
          <div class="mt-6">
            <a href={@release} class={button_variant(%{size: "lg"})}>
              Get the latest release
            </a>
          </div>
        </div>
      </section>

      <section class="border-t bg-muted/40">
        <div class="mx-auto max-w-5xl px-6 py-20">
          <h2 class="font-serif text-3xl font-semibold">Query it</h2>
          <p class="mt-4 max-w-2xl text-lg text-muted-foreground">
            The API takes one read-only SQL statement and always serves the latest release.
            The same query works in the SQLite file, in the browser, and from the command line.
          </p>

          <.tabs id="usage" default="sqlite" class="mt-10">
            <.tabs_list>
              <.tabs_trigger value="sqlite">SQLite</.tabs_trigger>
              <.tabs_trigger value="fetch">JavaScript</.tabs_trigger>
              <.tabs_trigger value="curl">curl</.tabs_trigger>
            </.tabs_list>
            <.tabs_content
              :for={{value, code} <- [sqlite: @sqlite, fetch: @fetch, curl: @curl]}
              value={"#{value}"}
            >
              <pre class="overflow-x-auto rounded-lg border bg-muted p-4 text-sm"><code>{code}</code></pre>
            </.tabs_content>
          </.tabs>

          <h3 class="mt-12 text-xl font-semibold">Limits</h3>
          <ul class="mt-4 max-w-2xl list-disc space-y-1 pl-6 text-lg">
            <li>A query returns at most 10,000 rows.</li>
            <li>A query may run for 5 seconds.</li>
            <li>Each client may run 60 queries a minute.</li>
            <li>Repeating a query someone already ran is free.</li>
          </ul>
        </div>
      </section>

      <section class="border-t">
        <div class="mx-auto grid max-w-5xl gap-10 px-6 py-20 md:grid-cols-2">
          <div>
            <h2 class="font-serif text-3xl font-semibold">API guide</h2>
            <p class="mt-4 text-lg text-muted-foreground">
              The guide is the reference for every table, how they fit together, and example
              queries. People and AI agents both read it.
            </p>
            <a
              id="api-guide"
              href={@guide}
              class={button_variant(%{variant: "outline", size: "lg"}) <> " mt-6"}
            >
              Read the API guide
            </a>
          </div>
          <div>
            <h2 class="font-serif text-3xl font-semibold">Examples</h2>
            <p class="mt-4 text-lg text-muted-foreground">
              Charts drawn from single queries, such as Paul's journeys, a timeline, and who
              speaks to whom. Each one shows the query behind it.
            </p>
            <.link
              id="examples"
              navigate={~p"/examples"}
              class={button_variant(%{variant: "outline", size: "lg"}) <> " mt-6"}
            >
              See the examples
            </.link>
          </div>
        </div>
      </section>
    </Layouts.app>
    """
  end
end

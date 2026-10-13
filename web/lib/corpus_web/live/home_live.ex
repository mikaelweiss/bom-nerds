defmodule CorpusWeb.HomeLive do
  use CorpusWeb, :live_view

  import SaladUI.Card
  import SaladUI.Tabs
  import SaladUI.Helpers, only: [button_variant: 1]

  @query "select name, description from entity where name = 'Nephi'"

  @contents [
    {"Text",
     "Every verse, word by word, with the Hebrew and Greek originals linked to the English."},
    {"Original words", "Headwords, Strong's numbers, meanings, and full grammar for each word."},
    {"People, places, and things",
     "Every person, group, city, land, event, and topic, tagged everywhere the text names them, pronouns included."},
    {"Relationships",
     "Family trees, who led whom, and what lies north of what, each backed by the verse that says it."},
    {"Speeches", "Who is speaking, to whom, and through which prophet."},
    {"Journeys", "Who traveled where, and how long it took."},
    {"Settings", "Where each passage takes place, even when the verse does not name the place."},
    {"Dates", "BC/AD and the Book of Mormon's own calendars."},
    {"Links", "Cross-references, quotes, parallels, and fulfilled prophecies."},
    {"Structure", "Sentences, clauses, chiasms, and parallelisms."},
    {"Study notes", "Each chapter's key verses, doctrine, symbols, and setting."}
  ]

  @uses [
    {"Study",
     "Read every verse about Moroni, every word Alma spoke, or every place the Book of Mormon quotes Isaiah."},
    {"Visualize",
     "Draw family trees, map journeys, plot a timeline, or graph who talks to whom."},
    {"Search the originals",
     "Find every use of a Hebrew or Greek word, whatever the English says."},
    {"Build", "Power a study app, a game, a chatbot, or a research project."}
  ]

  def mount(_params, _session, socket) do
    guide = CorpusWeb.api_url("/#{Corpus.Versions.latest()}")

    {:ok,
     assign(socket,
       page_title: "Every word of the standard works, connected",
       contents: @contents,
       uses: @uses,
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
          Every word of the standard works, connected.
        </h1>
        <p class="mt-6 max-w-2xl text-lg text-muted-foreground">
          One open database of the Bible, Book of Mormon, Doctrine and Covenants, and Pearl of
          Great Price. Every word is linked to the people, places, and ideas it talks about.
        </p>
        <div class="mt-10 flex flex-wrap gap-3">
          <a
            href={"#{Layouts.repository()}/releases/latest"}
            class={button_variant(%{size: "lg"})}
          >
            Download the data
          </a>
          <a href={@guide} class={button_variant(%{variant: "outline", size: "lg"})}>
            Read the API guide
          </a>
        </div>
      </section>

      <section class="border-t bg-muted/40">
        <div class="mx-auto grid max-w-5xl gap-10 px-6 py-20 md:grid-cols-[1fr_2fr]">
          <h2 class="font-serif text-3xl font-semibold">Why I built this</h2>
          <div class="space-y-4 text-lg leading-relaxed">
            <p>
              I want to ask the scriptures questions a concordance can't answer. Who did Alma
              speak to? Where did Lehi's family travel, and how long did it take? Which English
              words come from the same Hebrew word, from Genesis to Isaiah to Nephi's quotations
              of him?
            </p>
            <p>
              The answers are all in the text, scattered across thousands of verses. This project
              gathers them into one place, ties each one to the verse that says it, and gives it
              away so anyone can study it, map it, and build on it.
            </p>
          </div>
        </div>
      </section>

      <section class="border-t">
        <div class="mx-auto max-w-5xl px-6 py-20">
          <h2 class="font-serif text-3xl font-semibold">What's inside</h2>
          <div class="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <.card :for={{title, description} <- @contents}>
              <.card_header>
                <.card_title>{title}</.card_title>
                <.card_description>{description}</.card_description>
              </.card_header>
            </.card>
          </div>
        </div>
      </section>

      <section class="border-t bg-muted/40">
        <div class="mx-auto max-w-5xl px-6 py-20">
          <h2 class="font-serif text-3xl font-semibold">What you can do with it</h2>
          <dl class="mt-10 grid gap-8 sm:grid-cols-2">
            <div :for={{title, description} <- @uses}>
              <dt class="font-semibold">{title}</dt>
              <dd class="mt-2 text-muted-foreground">{description}</dd>
            </div>
          </dl>
        </div>
      </section>

      <section class="border-t">
        <div class="mx-auto max-w-5xl px-6 py-20">
          <h2 class="font-serif text-3xl font-semibold">How to use it</h2>
          <p class="mt-4 max-w-2xl text-lg text-muted-foreground">
            Download the latest
            <a href={"#{Layouts.repository()}/releases/latest"} class="underline">release</a>
            as a SQLite database or as JSON, or query it from any website through the API. The API
            takes read-only SQL and always serves the latest release.
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

          <p class="mt-6 text-muted-foreground">
            The <a href={@guide} class="underline">API guide</a>
            explains every table and how they fit together, with example queries for family trees,
            journeys, timelines, and more.
          </p>
        </div>
      </section>
    </Layouts.app>
    """
  end
end

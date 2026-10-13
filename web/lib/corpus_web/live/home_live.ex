defmodule CorpusWeb.HomeLive do
  use CorpusWeb, :live_view

  import SaladUI.Card
  import SaladUI.Helpers, only: [button_variant: 1]
  import CorpusWeb.Scripture, only: [verse_card: 1, reader_path: 1]

  alias Corpus.{Highlights, Scripture}
  alias CorpusWeb.Examples

  # John 3:16 shows a speaker, a listener, a setting, and the Greek under every
  # word. The later entries cover releases that lack it.
  @hero_verses [
    {"kjv", "john", 3, 16, "loved"},
    {"kjv", "john", 1, 1, "Word"}
  ]

  @hero_links 3

  @evidence [
    relationships: "relationships",
    speeches: "speeches",
    journeys: "journeys",
    settings: "settings",
    dates: "dates",
    structures: "literary structures"
  ]

  def mount(_params, _session, socket) do
    {verse, word} = hero_verse()

    socket =
      assign(socket,
        page_title: "The Scriptures Demystified",
        examples: Examples.with_rows(),
        verse: verse,
        findings: Highlights.findings(),
        scholars: Highlights.scholars(),
        editions: length(Scripture.editions()),
        credits: "#{Layouts.repository()}/blob/main/CREDITS.md"
      )

    {:ok, select(socket, verse && verse.id, word && word.id)}
  end

  def handle_event("select", params, socket) do
    {verse_id, word_id} = CorpusWeb.Scripture.selection(params)
    {:noreply, select(socket, verse_id, word_id)}
  end

  defp hero_verse do
    Enum.find_value(@hero_verses, {nil, nil}, fn {edition, book, chapter, number, text} ->
      with %{} = verse <- Scripture.find_verse(edition, book, chapter, number) do
        {verse, Enum.find(verse.words, &(&1.text == text))}
      end
    end)
  end

  defp select(socket, nil, _word_id), do: assign(socket, details: nil, word: nil, link_count: 0)

  defp select(socket, verse_id, word_id) do
    details = Scripture.verse(verse_id)
    links = (details && details.links) || []

    assign(socket,
      details: details && %{details | links: Enum.take(links, @hero_links)},
      word: word_id && Scripture.word(word_id),
      link_count: length(links)
    )
  end

  def render(assigns) do
    ~H"""
    <Layouts.app>
      <section class="mx-auto max-w-5xl px-6 pb-8 pt-16 sm:pt-24">
        <h1 class="max-w-3xl font-serif text-4xl font-semibold tracking-tight sm:text-6xl">
          The Scriptures Demystified
        </h1>
        <div class="mt-8 flex flex-wrap gap-3">
          <.link id="start-reading" navigate={~p"/read"} class={button_variant(%{size: "lg"})}>
            Start reading
          </.link>
          <.link
            id="browse-data"
            navigate={~p"/data"}
            class={button_variant(%{variant: "outline", size: "lg"})}
          >
            Browse the data
          </.link>
        </div>
      </section>

      <section id="examples" class="mx-auto max-w-5xl px-6 py-8">
        <Examples.card_grid examples={@examples} />
      </section>

      <section :if={@verse} id="hero" class="mx-auto max-w-5xl px-6 pb-16 pt-8 sm:pb-24">
        <p class="max-w-2xl text-lg text-muted-foreground">
          Click any word or verse to see who is speaking, where it happens, the Hebrew or Greek
          underneath, and every verse that points to it. It covers the Bible, the Book of Mormon,
          the Doctrine and Covenants, and the Pearl of Great Price.
        </p>
        <div id="hero-verse" class="mt-8 rounded-xl border bg-card p-5 sm:p-8">
          <p class="mb-6 text-sm text-muted-foreground">
            Click any word, or the verse number for the whole verse.
          </p>
          <.verse_card verse={@verse} details={@details} word={@word} on_select="select" />
          <p :if={@details && @link_count > length(@details.links)} class="mt-6 text-sm md:text-right">
            <.link navigate={reader_path(@details.location)} class="font-medium hover:underline">
              See all {delimit(@link_count)} linked passages in the reader
            </.link>
          </p>
        </div>
      </section>

      <section :if={@findings != []} id="study" class="border-t bg-muted/40">
        <div class="mx-auto max-w-5xl px-6 py-20">
          <h2 class="font-serif text-3xl font-semibold">For your study</h2>
          <p class="mt-4 max-w-2xl text-lg text-muted-foreground">
            A few things the data shows. Each card opens the verses behind it.
          </p>
          <div class="mt-10 grid gap-4 sm:grid-cols-2">
            <.link
              :for={finding <- @findings}
              id={"finding-#{finding.id}"}
              navigate={finding.link}
              class="group rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <.card class="flex h-full flex-col transition-shadow group-hover:shadow-md">
                <.card_header>
                  <.card_title class="font-serif text-xl">
                    <.finding_title finding={finding} />
                  </.card_title>
                </.card_header>
                <.card_content class="flex-1 leading-relaxed">
                  {finding_body(finding)}
                </.card_content>
                <.card_footer class="text-sm font-medium">
                  {finding_action(finding)} <span aria-hidden="true">→</span>
                </.card_footer>
              </.card>
            </.link>
          </div>
        </div>
      </section>

      <section :if={@scholars != %{}} id="scholars" class="border-t">
        <div class="mx-auto max-w-5xl px-6 py-20">
          <h2 class="font-serif text-3xl font-semibold">For scholars</h2>
          <p class="mt-4 max-w-2xl text-lg text-muted-foreground">
            Every number here is a live row count from the current release. Check any of them in
            the data browser or with your own SQL.
          </p>

          <div class="mt-10 grid gap-x-10 gap-y-10 md:grid-cols-2">
            <div :if={@scholars[:aligned_words]} id="scholars-alignment">
              <h3 class="font-semibold">The originals under the English</h3>
              <p class="mt-2 text-muted-foreground">
                {delimit(@scholars.aligned_words)} KJV words are aligned to the Hebrew of the
                Westminster Leningrad Codex and the Greek of the SBL Greek New Testament. Each
                original word carries its Strong's number, its headword, and full morphology.
              </p>
            </div>

            <div :if={@scholars[:links]} id="scholars-links">
              <h3 class="font-semibold">
                {delimit(@scholars.link_total)} typed links between passages
              </h3>
              <.counts rows={for link <- @scholars.links, do: {link.kind, link.count}} />
            </div>

            <div :if={@scholars[:entities]} id="scholars-entities">
              <h3 class="font-semibold">
                {delimit(@scholars.entity_total)} people, places, groups, and more
              </h3>
              <p class="mt-2 text-muted-foreground">
                Tagged wherever the text refers to them.
                <span :if={@scholars.tipnr_total > 0}>
                  {delimit(@scholars.tipnr_total)} carry a STEPBible id, so you can join outside
                  data on them.
                </span>
              </p>
              <.counts rows={for entity <- @scholars.entities, do: {entity.type, entity.count}} />
            </div>

            <div :if={evidence(@scholars) != []} id="scholars-evidence">
              <h3 class="font-semibold">Every claim tied to its verse</h3>
              <p class="mt-2 text-muted-foreground">
                Each record points to the words that state it.
              </p>
              <.counts rows={evidence(@scholars)} />
            </div>

            <div :if={@scholars[:counts][:verses]} id="scholars-text">
              <h3 class="font-semibold">The text itself</h3>
              <p class="mt-2 text-muted-foreground">{text_claim(@scholars.counts, @editions)}</p>
            </div>

            <div id="scholars-sources">
              <h3 class="font-semibold">Sources and versions</h3>
              <p class="mt-2 text-muted-foreground">
                Every source and its license is listed in the <a href={@credits} class="underline">credits</a>. Each API version is a fixed
                promise about tables and columns, so a query you write today keeps working.
              </p>
            </div>
          </div>

          <div class="mt-12 flex flex-wrap gap-3">
            <.link id="scholars-data" navigate={~p"/data"} class={button_variant(%{size: "lg"})}>
              Browse the data
            </.link>
            <.link
              id="scholars-build"
              navigate={~p"/build"}
              class={button_variant(%{variant: "outline", size: "lg"})}
            >
              Download or query it
            </.link>
          </div>
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
    </Layouts.app>
    """
  end

  attr :rows, :list, required: true

  defp counts(assigns) do
    ~H"""
    <dl class="mt-3 divide-y text-sm">
      <div :for={{label, count} <- @rows} class="flex justify-between gap-4 py-1.5">
        <dt>{label}</dt>
        <dd class="tabular-nums text-muted-foreground">{delimit(count)}</dd>
      </div>
    </dl>
    """
  end

  defp evidence(%{counts: counts}) do
    for {key, label} <- @evidence, counts[key], do: {String.capitalize(label), counts[key]}
  end

  defp evidence(_scholars), do: []

  defp text_claim(counts, editions) do
    words = if counts[:words], do: " and #{count(counts.words, "word", "words")}", else: ""

    "#{count(counts.verses, "verse", "verses")}#{words}, counted across " <>
      "#{count(editions, "edition", "editions")}, the Hebrew and Greek included."
  end

  attr :finding, :map, required: true

  defp finding_title(%{finding: %{id: :beginning}} = assigns) do
    ~H"""
    <span lang="hbo" dir="rtl">{@finding.hebrew}</span>, “{@finding.gloss}”
    """
  end

  defp finding_title(assigns) do
    ~H"""
    {title(@finding.id)}
    """
  end

  defp title(:moroni), do: "Moroni, son of Mormon"
  defp title(:isaiah), do: "Isaiah in the Book of Mormon"
  defp title(:alma), do: "Who Alma spoke to"
  defp title(:lehi), do: "Lehi's family"

  defp finding_body(%{id: :moroni} = finding) do
    books = length(finding.books)
    top = finding.books |> Enum.sort_by(&(-&1.mentions)) |> Enum.take(3)

    "The record refers to him #{times(finding.mentions)} in #{count(books, "book", "books")}, " <>
      "counting every “I” and “he” that means him. The most are in " <>
      "#{sentence_list(for book <- top, do: "#{book.book} (#{delimit(book.mentions)})")}."
  end

  defp finding_body(%{id: :isaiah} = finding) do
    top = Enum.max_by(finding.books, & &1.quotes)

    "The Book of Mormon quotes Isaiah in #{count(finding.quotes, "passage", "passages")}, " <>
      "spread over #{delimit(finding.chapters)} of its chapters. " <>
      "#{top.book} holds #{delimit(top.quotes)} of them."
  end

  defp finding_body(%{id: :alma} = finding) do
    [top | rest] = Enum.chunk_by(finding.listeners, & &1.speeches)
    each = if length(top) > 1, do: " each", else: ""

    then =
      for listener <- List.flatten(rest),
          do: ", then #{listener.name}, #{times(listener.speeches)}"

    "The record holds #{count(finding.speeches, "speech", "speeches")} by Alma the Younger. " <>
      plural(length(top), "His most frequent listener is ", "His most frequent listeners are ") <>
      "#{sentence_list(Enum.map(top, & &1.name))}, #{times(hd(top).speeches)}#{each}#{then}."
  end

  defp finding_body(%{id: :lehi} = finding) do
    children = Enum.map(finding.children, & &1.name)

    "Lehi had #{count(length(children), "child", "children")}: #{sentence_list(children)}. " <>
      "Down to his great-grandchildren, the record names #{delimit(finding.descendants)} of his " <>
      "descendants, each tied to the verse that says so."
  end

  defp finding_body(%{id: :beginning} = finding) do
    {top, rest} = Enum.split(finding.translations, 4)
    renderings = for t <- top, do: "“#{t.english}” #{delimit(t.uses)}"
    renderings = if rest == [], do: renderings, else: renderings ++ ["#{length(rest)} other ways"]

    "The Hebrew word #{finding.hebrew} (Strong's #{finding.strongs}) first appears in " <>
      "#{verse_reference(finding.verse)}. The KJV translates it #{times(finding.uses)}: " <>
      "#{sentence_list(renderings)}."
  end

  defp finding_action(%{id: :moroni}), do: "See where he appears"
  defp finding_action(%{id: :isaiah}), do: "See every quote"
  defp finding_action(%{id: :alma}), do: "Open Alma's page"
  defp finding_action(%{id: :lehi}), do: "See the family tree"

  defp finding_action(%{id: :beginning, verse: verse}),
    do: "Open #{verse_reference(verse)}"

  defp verse_reference(verse), do: "#{verse.book} #{verse.chapter}:#{verse.verse}"

  defp times(1), do: "once"
  defp times(n), do: "#{delimit(n)} times"

  defp count(n, singular, plural), do: "#{delimit(n)} #{plural(n, singular, plural)}"

  defp plural(1, singular, _plural), do: singular
  defp plural(_n, _singular, plural), do: plural

  defp sentence_list([only]), do: only
  defp sentence_list([first, second]), do: "#{first} and #{second}"

  defp sentence_list(items),
    do: "#{Enum.join(Enum.drop(items, -1), ", ")}, and #{List.last(items)}"

  defp delimit(n) do
    n
    |> Integer.to_string()
    |> String.reverse()
    |> String.replace(~r/(\d{3})(?=\d)/, "\\1,")
    |> String.reverse()
  end
end

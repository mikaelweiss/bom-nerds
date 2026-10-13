defmodule CorpusWeb.Scripture do
  @moduledoc """
  Components for reading scripture: verse text with clickable words, and the
  panels that show what the data knows about a verse or a word.

  Clicking a verse number or a word sends the `on_select` event with
  `"verse"` (the verse id) and, for a word, `"word"` (the word id). The
  LiveView answers with `Corpus.Scripture.verse/1` and `Corpus.Scripture.word/1`.

  `verse_card/1` shows one verse with its panels from plain assigns, for a page
  that is not the reader:

      verse = Corpus.Scripture.find_verse("kjv", "john", 1, 1)

      <.verse_card verse={@verse} details={@details} word={@word} on_select="select" />

      def handle_event("select", params, socket) do
        {verse_id, word_id} = CorpusWeb.Scripture.selection(params)

        {:noreply,
         assign(socket,
           details: Corpus.Scripture.verse(verse_id),
           word: word_id && Corpus.Scripture.word(word_id)
         )}
      end
  """

  use CorpusWeb, :html

  alias Corpus.Scripture

  @doc "The verse and word ids an `on_select` event carries. The word id is nil for a verse."
  def selection(params) do
    word = with id when is_binary(id) <- params["word"], do: String.to_integer(id)
    {String.to_integer(params["verse"]), word}
  end

  @doc "The reader's address for a location, selecting its verse when it has one."
  def reader_path(%{edition: edition, book: book, chapter: chapter, verse: nil}),
    do: ~p"/read/#{edition}/#{book}/#{chapter}"

  def reader_path(%{edition: edition, book: book, chapter: chapter, verse: verse}),
    do: ~p"/read/#{edition}/#{book}/#{chapter}?#{[v: verse]}"

  @doc "The reader's address for a word, selecting it and its verse."
  def reader_path(location, position),
    do:
      ~p"/read/#{location.edition}/#{location.book}/#{location.chapter}?#{[v: location.verse, w: position]}"

  @doc """
  One verse as a block: its number, then its words. Words the translators
  supplied are italic.
  """
  attr :verse, :map, required: true, doc: "`%{id, number, words}` from `Corpus.Scripture`"
  attr :selected, :boolean, default: false, doc: "highlights the verse"
  attr :selected_word, :integer, default: nil, doc: "the id of the word to highlight"
  attr :on_select, :string, default: nil, doc: "the event a click sends, or nil for plain text"
  attr :class, :any, default: nil

  def verse(assigns) do
    ~H"""
    <p
      id={"v#{@verse.number}"}
      data-selected={@selected}
      class={[
        "-mx-2 scroll-mt-24 rounded-md px-2 py-1 transition-colors",
        @selected && "bg-accent",
        @class
      ]}
    >
      <button
        :if={@verse.number && @on_select}
        type="button"
        phx-click={@on_select}
        phx-value-verse={@verse.id}
        aria-label={"Verse #{@verse.number}"}
        class="me-1 align-super font-sans text-xs font-medium text-muted-foreground hover:text-foreground"
      >{@verse.number}</button>
      <sup :if={@verse.number && !@on_select} class="me-1 font-sans text-xs text-muted-foreground">{@verse.number}</sup>
      <.words verse={@verse} selected_word={@selected_word} on_select={@on_select} />
    </p>
    """
  end

  attr :verse, :map, required: true
  attr :selected_word, :integer, default: nil
  attr :on_select, :string, default: nil

  defp words(assigns) do
    ~H"""
    <span phx-no-format><span :for={word <- @verse.words}>{word.before}<span data-word={word.id} phx-click={@on_select} phx-value-verse={@verse.id} phx-value-word={word.id} class={word_class(word, @selected_word, @on_select)}>{word.text}</span>{word.after}</span></span>
    """
  end

  defp word_class(word, selected_word, on_select) do
    [
      word.supplied && "italic",
      on_select && "cursor-pointer rounded-sm hover:bg-primary/10",
      word.id == selected_word &&
        "bg-primary/15 underline decoration-2 underline-offset-4 decoration-primary/60"
    ]
  end

  @doc "Everything the data records about a verse, from `Corpus.Scripture.verse/1`."
  attr :details, :map, required: true
  attr :on_close, :string, default: nil, doc: "the event the close button sends, or nil for none"
  attr :link, :boolean, default: false, doc: "links the heading to the verse in the reader"

  def verse_panel(assigns) do
    assigns =
      assign(assigns,
        empty?:
          Enum.all?(
            [:speeches, :settings, :dates, :named, :about, :links, :structures, :passages],
            &(assigns.details[&1] == [])
          )
      )

    ~H"""
    <section aria-label={"About #{@details.reference}"} class="space-y-6">
      <.panel_heading on_close={@on_close}>
        <.link :if={@link} navigate={reader_path(@details.location)} class="hover:underline">
          {@details.reference}
        </.link>
        <span :if={!@link}>{@details.reference}</span>
      </.panel_heading>

      <p :if={@empty?} class="text-sm text-muted-foreground">
        No speakers, places, people, or links are recorded for this verse.
      </p>

      <.section :if={@details.speeches != []} title="Speaking">
        <div :for={speech <- @details.speeches} class="text-sm">
          <p :if={speech.speakers != [] or speech.listeners != []}>
            <.entities entities={speech.speakers} />
            <span :if={speech.listeners != []} class="text-muted-foreground">to</span>
            <.entities entities={speech.listeners} />
          </p>
          <p class="text-muted-foreground">{speech.mode}, {speech.range.reference}</p>
          <p :if={speech.through} class="text-muted-foreground">
            Through <.entity_link entity={speech.through} />
          </p>
        </div>
      </.section>

      <.section :if={@details.settings != []} title="Setting">
        <p class="text-sm"><.entities entities={@details.settings} /></p>
      </.section>

      <.section :if={@details.dates != []} title="Date">
        <p :for={date <- @details.dates} class="text-sm">
          {date.text}
          <span :if={date.system != "BC/AD"} class="block text-muted-foreground">
            {date.system}
          </span>
        </p>
      </.section>

      <.section :if={@details.named != []} title="Named here">
        <p class="text-sm"><.entities entities={@details.named} /></p>
      </.section>

      <.section :if={@details.about != []} title="About">
        <p class="text-sm"><.entities entities={@details.about} /></p>
      </.section>

      <.section :if={@details.links != []} title="Linked passages">
        <div :for={link <- @details.links} class="text-sm">
          <p>
            <span class="text-muted-foreground">{link.kind}</span>
            <.link navigate={reader_path(link.range.first)} class="font-medium hover:underline">
              {link.range.reference}
            </.link>
          </p>
          <p class="mt-1 font-serif text-base leading-relaxed text-muted-foreground">{link.text}</p>
        </div>
      </.section>

      <.section :if={@details.structures != []} title="Structure">
        <p :for={structure <- @details.structures} class="text-sm">
          {structure.kind},
          <.link navigate={reader_path(structure.range.first)} class="hover:underline">
            {structure.range.reference}
          </.link>
        </p>
      </.section>

      <.section :if={@details.passages != []} title="Passage">
        <p :for={passage <- @details.passages} class="text-sm">
          {passage.name},
          <.link navigate={reader_path(passage.range.first)} class="hover:underline">
            {passage.range.reference}
          </.link>
        </p>
      </.section>
    </section>
    """
  end

  @doc "Everything the data records about a word, from `Corpus.Scripture.word/1`."
  attr :word, :map, required: true
  attr :on_close, :string, default: nil, doc: "the event the close button sends, or nil for none"

  def word_panel(assigns) do
    ~H"""
    <section aria-label={"About the word #{@word.text}"} class="space-y-6">
      <.panel_heading on_close={@on_close}>
        <span lang={@word.language} dir={@word.rtl && "rtl"} class={@word.supplied && "italic"}>
          {@word.text}
        </span>
        <span class="ms-2 font-sans text-sm font-normal text-muted-foreground">
          {Scripture.reference(@word.location)}
        </span>
      </.panel_heading>

      <p :if={@word.supplied} class="text-sm text-muted-foreground">
        Supplied by the translators, with no word under it in the original.
      </p>

      <.section :if={@word.language == "en" && @word.headword} title="Dictionary">
        <p class="text-sm">
          <span class="font-medium">{@word.headword.text}</span>
          <span :if={@word.part_of_speech} class="text-muted-foreground">
            {String.downcase(@word.part_of_speech)}
          </span>
        </p>
        <div :if={@word.meaning} class="text-sm">
          <p>{@word.meaning.gloss}</p>
          <p
            :if={@word.meaning.definition && @word.meaning.definition != @word.meaning.gloss}
            class="mt-1 text-muted-foreground"
          >
            {@word.meaning.definition}
          </p>
          <p class="mt-1 text-xs text-muted-foreground">Webster's dictionary, 1828</p>
        </div>
      </.section>

      <.section :for={original <- @word.originals} title={original_title(original)}>
        <.original word={original} />
        <.renderings renderings={original.renderings} />
      </.section>

      <.section :if={@word.language != "en"} title={original_title(@word)}>
        <.original word={@word} />
        <p :if={@word.translations} class="text-sm">
          <span class="text-muted-foreground">Here in the KJV:</span>
          <.link
            navigate={reader_path(@word.translations.location, @word.translations.position)}
            class="font-medium hover:underline"
          >
            {@word.translations.text}
          </.link>
        </p>
        <.renderings renderings={@word.renderings} />
      </.section>

      <.section :if={@word.refers_to != []} title="Refers to">
        <p class="text-sm"><.entities entities={@word.refers_to} /></p>
      </.section>

      <.section :if={@word.parallels != []} title="Matching word">
        <p class="text-sm">
          <.link
            :for={location <- @word.parallels}
            navigate={reader_path(location)}
            class="me-3 hover:underline"
          >
            {Scripture.reference(location)}
          </.link>
        </p>
      </.section>
    </section>
    """
  end

  defp original_title(%{rtl: true}), do: "Hebrew"
  defp original_title(_word), do: "Greek"

  attr :word, :map, required: true

  defp original(assigns) do
    ~H"""
    <div class="text-sm">
      <p class="flex flex-wrap items-baseline gap-x-3">
        <span
          lang={if @word.rtl, do: "hbo", else: "grc"}
          dir={@word.rtl && "rtl"}
          class="font-serif text-2xl"
        >
          {@word.text}
        </span>
        <span :if={@word.headword} class="text-muted-foreground">
          from
          <span
            lang={if @word.rtl, do: "hbo", else: "grc"}
            class="font-serif text-base text-foreground"
          >
            {@word.headword.text}
          </span>
          <span :if={@word.headword.strongs}>{@word.headword.strongs}</span>
        </span>
      </p>
      <p :if={@word.headword && @word.headword.gloss} class="mt-1">“{@word.headword.gloss}”</p>
      <ul :if={@word.grammar != []} class="mt-2 flex flex-wrap gap-1.5">
        <li :for={label <- @word.grammar} class="rounded-full border px-2 py-0.5 text-xs">
          {label}
        </li>
      </ul>
    </div>
    """
  end

  attr :renderings, :list, required: true

  defp renderings(assigns) do
    ~H"""
    <div :if={@renderings != []} class="text-sm">
      <p class="text-muted-foreground">How the KJV translates it</p>
      <ul class="mt-1 flex flex-wrap gap-x-4 gap-y-1">
        <li :for={rendering <- @renderings}>
          {rendering.phrase} <span class="text-muted-foreground">{rendering.count}</span>
        </li>
      </ul>
    </div>
    """
  end

  @doc """
  One verse with its panels, from plain assigns, for pages other than the
  reader. Shows the word panel when `word` is set and the verse panel when
  `details` is set.
  """
  attr :verse, :map, required: true, doc: "from `Corpus.Scripture.find_verse/4`"
  attr :details, :map, default: nil, doc: "from `Corpus.Scripture.verse/1`, or nil"
  attr :word, :map, default: nil, doc: "from `Corpus.Scripture.word/1`, or nil"
  attr :on_select, :string, default: "select", doc: "the event a click on a word or number sends"
  attr :class, :any, default: nil

  def verse_card(assigns) do
    ~H"""
    <div class={["grid gap-8 md:grid-cols-[minmax(0,1fr)_20rem]", @class]}>
      <div>
        <.link
          navigate={reader_path(@verse.location)}
          class="text-sm text-muted-foreground hover:underline"
        >
          {Scripture.reference(@verse.location)}
        </.link>
        <div
          lang={@verse.language}
          dir={@verse.rtl && "rtl"}
          class="mt-2 font-serif text-2xl leading-relaxed"
        >
          <.verse
            verse={@verse}
            selected={@details != nil}
            selected_word={@word && @word.id}
            on_select={@on_select}
          />
        </div>
      </div>
      <div :if={@word || @details} class="space-y-8">
        <.word_panel :if={@word} word={@word} />
        <.verse_panel :if={@details} details={@details} link />
      </div>
    </div>
    """
  end

  attr :on_close, :string, default: nil
  slot :inner_block, required: true

  defp panel_heading(assigns) do
    ~H"""
    <div class="flex items-start justify-between gap-4">
      <h2 class="font-serif text-2xl font-semibold">{render_slot(@inner_block)}</h2>
      <button
        :if={@on_close}
        type="button"
        phx-click={@on_close}
        aria-label="Close"
        class="-me-2 inline-flex size-9 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
      >
        <svg
          viewBox="0 0 24 24"
          class="size-5"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
        >
          <path d="M18 6 6 18M6 6l12 12" />
        </svg>
      </button>
    </div>
    """
  end

  attr :title, :string, required: true
  slot :inner_block, required: true

  defp section(assigns) do
    ~H"""
    <div class="space-y-2">
      <h3 class="text-xs font-medium uppercase tracking-wide text-muted-foreground">{@title}</h3>
      {render_slot(@inner_block)}
    </div>
    """
  end

  attr :entities, :list, required: true

  defp entities(assigns) do
    ~H"""
    <span phx-no-format><span :for={{entity, index} <- Enum.with_index(@entities)}><span :if={index > 0}>, </span><.entity_link entity={entity} /></span></span>
    """
  end

  @doc "A link to an entity's page."
  attr :entity, :map, required: true, doc: "`%{id, name}`, with an optional `description`"

  def entity_link(assigns) do
    ~H"""
    <.link
      navigate={~p"/entities/#{@entity.id}"}
      title={@entity[:description]}
      class="font-medium underline decoration-muted-foreground/40 underline-offset-4 hover:decoration-foreground"
    >{@entity.name}</.link>
    """
  end
end

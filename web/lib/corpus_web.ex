defmodule CorpusWeb do
  @moduledoc false

  def static_paths, do: ~w(assets)

  @doc "A URL on the API's host, which is the site's host under `api.`."
  def api_url(path \\ "") do
    url = CorpusWeb.Endpoint.struct_url()
    URI.to_string(%{url | host: "api." <> url.host, path: path})
  end

  def router do
    quote do
      use Phoenix.Router, helpers: false

      import Plug.Conn
      import Phoenix.Controller
      import Phoenix.LiveView.Router
    end
  end

  def controller do
    quote do
      use Phoenix.Controller, formats: [:json]

      import Plug.Conn
    end
  end

  def live_view do
    quote do
      use Phoenix.LiveView

      unquote(html_helpers())
    end
  end

  def html do
    quote do
      use Phoenix.Component

      import Phoenix.Controller, only: [get_csrf_token: 0]

      unquote(html_helpers())
    end
  end

  defp html_helpers do
    quote do
      import Phoenix.HTML

      alias CorpusWeb.Layouts

      use Phoenix.VerifiedRoutes,
        endpoint: CorpusWeb.Endpoint,
        router: CorpusWeb.Router,
        statics: CorpusWeb.static_paths()
    end
  end

  defmacro __using__(which) when is_atom(which) do
    apply(__MODULE__, which, [])
  end
end

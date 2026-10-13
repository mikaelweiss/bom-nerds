defmodule CorpusWeb.Endpoint do
  use Phoenix.Endpoint, otp_app: :corpus

  @session_options [
    store: :cookie,
    key: "_corpus_key",
    signing_salt: "pL7wD2xe",
    same_site: "Lax"
  ]

  socket "/live", Phoenix.LiveView.Socket,
    websocket: [connect_info: [session: @session_options]],
    longpoll: [connect_info: [session: @session_options]]

  plug Plug.Static,
    at: "/",
    from: :corpus,
    gzip: not code_reloading?,
    only: CorpusWeb.static_paths(),
    raise_on_missing_only: code_reloading?

  if code_reloading? do
    socket "/phoenix/live_reload/socket", Phoenix.LiveReloader.Socket
    plug Phoenix.LiveReloader
    plug Phoenix.CodeReloader
  end

  plug Plug.RequestId
  plug Plug.Telemetry, event_prefix: [:phoenix, :endpoint]

  plug Plug.Head
  plug Plug.Session, @session_options
  plug CorpusWeb.Router
end

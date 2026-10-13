defmodule CorpusWeb.Endpoint do
  use Phoenix.Endpoint, otp_app: :corpus

  if code_reloading? do
    plug Phoenix.CodeReloader
  end

  plug Plug.RequestId
  plug Plug.Telemetry, event_prefix: [:phoenix, :endpoint]

  plug Plug.Head
  plug CorpusWeb.Router
end

import Config

config :corpus,
  repository: "mikaelweiss/standard-works-corpus",
  data_dir: "data",
  query: [timeout: 5_000, max_rows: 10_000],
  cache: [entries: 1_000, max_bytes: 1_000_000],
  rate_limit: [queries_per_minute: 60, queries_at_once: 2],
  client_ip_header: nil

config :corpus, CorpusWeb.Endpoint,
  url: [host: "localhost"],
  adapter: Bandit.PhoenixAdapter,
  render_errors: [formats: [json: CorpusWeb.ErrorJSON], layout: false]

config :logger, :default_formatter,
  format: "$time $metadata[$level] $message\n",
  metadata: [:request_id]

config :phoenix, :json_library, Jason

import_config "#{config_env()}.exs"

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
  render_errors: [
    formats: [html: CorpusWeb.ErrorHTML, json: CorpusWeb.ErrorJSON],
    layout: false
  ],
  pubsub_server: Corpus.PubSub,
  live_view: [signing_salt: "Rz4q8kVn"]

config :esbuild,
  version: "0.25.4",
  corpus: [
    args:
      ~w(js/app.js --bundle --target=es2022 --outdir=../priv/static/assets/js --external:/fonts/* --external:/images/* --alias:@=.),
    cd: Path.expand("../assets", __DIR__),
    env: %{"NODE_PATH" => [Path.expand("../deps", __DIR__), Mix.Project.build_path()]}
  ]

config :tailwind,
  version: "4.3.0",
  corpus: [
    args: ~w(
      --input=assets/css/app.css
      --output=priv/static/assets/css/app.css
    ),
    cd: Path.expand("..", __DIR__),
    env: %{"NODE_PATH" => [Path.expand("../deps", __DIR__), Mix.Project.build_path()]}
  ]

config :logger, :default_formatter,
  format: "$time $metadata[$level] $message\n",
  metadata: [:request_id]

config :phoenix, :json_library, Jason

import_config "#{config_env()}.exs"

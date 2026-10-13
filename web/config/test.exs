import Config

config :corpus, CorpusWeb.Endpoint,
  http: [ip: {127, 0, 0, 1}, port: 4002],
  secret_key_base: "Tgt/eYOpUU56REp48u+rcqu8m1vhgvArbS7DvGudqCn1UVFwnxlP/r35pEKR/URG",
  server: false

config :logger, level: :warning

config :phoenix, :plug_init_mode, :runtime

config :corpus,
  data_dir: "tmp/data",
  versions_dir: "test/support/versions",
  query: [timeout: 1_000, max_rows: 5],
  req_options: [plug: {Req.Test, Corpus.GitHub}, retry: false]

config :phoenix_live_view, enable_expensive_runtime_checks: true

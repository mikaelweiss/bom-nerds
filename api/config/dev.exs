import Config

config :corpus, CorpusWeb.Endpoint,
  http: [ip: {127, 0, 0, 1}],
  check_origin: false,
  code_reloader: true,
  debug_errors: true,
  secret_key_base: "WcXycErOJUQG7qOQXqmrxEQPlw+JCiTNYRsrmy5Bsdbqyb7VybRCBfn/rLncGA2C"

config :logger, :default_formatter, format: "[$level] $message\n"

config :phoenix, :stacktrace_depth, 20

config :phoenix, :plug_init_mode, :runtime

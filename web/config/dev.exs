import Config

config :corpus, CorpusWeb.Endpoint,
  http: [ip: {127, 0, 0, 1}],
  check_origin: false,
  code_reloader: true,
  debug_errors: true,
  secret_key_base: "WcXycErOJUQG7qOQXqmrxEQPlw+JCiTNYRsrmy5Bsdbqyb7VybRCBfn/rLncGA2C",
  watchers: [
    esbuild: {Esbuild, :install_and_run, [:corpus, ~w(--sourcemap=inline --watch)]},
    tailwind: {Tailwind, :install_and_run, [:corpus, ~w(--watch)]}
  ],
  live_reload: [
    patterns: [
      ~r"priv/static/(?!uploads/).*\.(js|css|png|jpeg|jpg|gif|svg)$",
      ~r"lib/corpus_web/(?:controllers|live|components)/?.*\.(ex|heex)$"
    ]
  ]

config :logger, :default_formatter, format: "[$level] $message\n"

config :phoenix, :stacktrace_depth, 20

config :phoenix, :plug_init_mode, :runtime

config :phoenix_live_view,
  debug_heex_annotations: true,
  debug_attributes: true,
  enable_expensive_runtime_checks: true

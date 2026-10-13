# Standard Works Corpus Web

The project's website and its API, read-only SQL over the latest data release. The site serves its own host and the API serves `api.` under it, so in development the site is `localhost:4000` and the API is `api.localhost:4000`. The API guide is [`priv/versions/v1/guide.md`](priv/versions/v1/guide.md), served at `/v1`.

Each example in `lib/corpus_web/examples` is a query and the SVG chart drawn from its rows.

## Run

```sh
mix setup
mix phx.server
```

`mix setup` downloads the latest release into `data/` and builds the assets. Run `mix corpus.install` again for a newer one, then restart.

## Versions

Each folder in `priv/versions` is a public version:

- `schema.json` lists every table and column the version promises. An install fails, and the current data keeps serving, if a release breaks that promise.
- `migrate.sql` (optional) reshapes a release into the version's tables, such as renaming a column back.
- `guide.md` documents it.

When a release changes the schema, add a `migrate.sql` to each older version so it keeps its promise. When the public shape itself should change, add the next version folder.

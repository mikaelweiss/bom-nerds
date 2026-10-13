# Standard Works Corpus API

Read-only SQL over the latest data release. The guide for people using it is [`priv/versions/v1/guide.md`](priv/versions/v1/guide.md), served at `/v1`.

## Run

```sh
mix setup
mix phx.server
```

`mix setup` downloads the latest release into `data/`. Run `mix corpus.install` again for a newer one, then restart.

## Versions

Each folder in `priv/versions` is a public version:

- `schema.json` lists every table and column the version promises. An install fails, and the current data keeps serving, if a release breaks that promise.
- `migrate.sql` (optional) reshapes a release into the version's tables, such as renaming a column back.
- `guide.md` documents it.

When a release changes the schema, add a `migrate.sql` to each older version so it keeps its promise. When the public shape itself should change, add the next version folder.

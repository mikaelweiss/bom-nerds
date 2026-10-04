# Intro

Hi there. If you like... LOVE the Book of Mormon, this project is for YOU!
Enjoy!

- Mikael Weiss

# Build

The text needs Python 3.10 or later and nothing else. The other layers also need the packages in `requirements.txt` and Java on the path, for MorphAdorner.

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m bomnerds.text    # creates scripture.db with every word of all four works
.venv/bin/python -m bomnerds.build   # runs every script layer, or name steps to run only those
python3 -m unittest discover tests
```

Sources download into `sources/` on first use. The English taggers take hours, so their output is kept in `cache/` and reused.

Claude Code sessions tag the rest through the agent CLI, following `plan.tsv`: every session of the build, cut once from counts in the database. `python3 -m bomnerds.agent --help` lists the commands.

```sh
python3 -m bomnerds.agent plan     # cuts plan.tsv
python3 -m bomnerds.agent status   # how far each pass is, with each review's error counts
scripts/run-plan entities-001      # runs one session
scripts/run-plan --parallel 3      # runs every session in order, three at a time
```

Stored answers live in `jobs/`. Rebuilding a script layer can delete AI tags in the tables it shares with them, so run `python3 -m bomnerds.agent replay` afterward to store every answer again.

`scripts/release.sh` publishes your `scripture.db` and a JSON export of every table as a GitHub release of the current commit. Pass `--no-upload` to build the zips in `dist/` without releasing.

# Plans for now:

1. Run the first session and check its answers
2. Run the rest of the plan

Visualizations and the API that serves the data are separate projects.

# License

The code is [Apache 2.0](LICENSE.md). The dataset is [CC BY 4.0](LICENSE-DATA.txt). [CREDITS.md](CREDITS.md) lists every source and the credit it requires.

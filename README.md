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

Agents tag the rest through the agent CLI. `python3 -m bomnerds.agent --help` lists its commands, and `python3 -m bomnerds.agent job <job> --role <role>` prints everything an agent needs for one job. Answers wait in `jobs/` until they settle. Rebuilding a script layer can delete AI tags in the tables it shares with them, so run `python3 -m bomnerds.agent replay` afterward to store every settled job again.

`scripts/release.sh` publishes your `scripture.db` and a JSON export of every table as a GitHub release of the current commit. Pass `--no-upload` to build the zips in `dist/` without releasing.

# Plans for now:

1. Run every layer on the pilot set and review the output
2. Run the full tagging

Visualizations and the API that serves the data are separate projects.

# License

The code is [Apache 2.0](LICENSE.md). The dataset is [CC BY 4.0](LICENSE-DATA.txt). [CREDITS.md](CREDITS.md) lists every source and the credit it requires.

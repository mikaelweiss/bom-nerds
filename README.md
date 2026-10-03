# Intro

Hi there. If you like... LOVE the Book of Mormon, this project is for YOU!
Enjoy!

- Mikael Weiss

# Build

Needs Python 3.10 or later and nothing else.

```sh
python3 -m bomnerds.text            # creates scripture.db with every word of all four works
python3 -m unittest discover tests
```

# Plans for now:

1. Sign off on the dataset spec in [docs/decisions.md](docs/decisions.md)
2. Build the CLI and the text scripts
3. Run every layer on the pilot set and review the output
4. Run the full tagging

Visualizations and the API that serves the data are separate projects.

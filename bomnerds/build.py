"""Runs every script layer on scripture.db, in build order. Name steps to run only those."""

import sqlite3
import sys
import time

from . import checks, dates, entities, family, grammar, headwords, links, macula, mentions, sentences, strongs, taggers
from .text import DATABASE

STEPS = {
    "macula": macula,
    "strongs": strongs,
    "entities": entities,
    "mentions": mentions,
    "family": family,
    "links": links,
    "dates": dates,
    "sentences": sentences,
    "taggers": taggers,
    "headwords": headwords,
    "grammar": grammar,
    "checks": checks,
}


def main(names: list[str]):
    unknown = set(names) - STEPS.keys()
    if unknown:
        sys.exit(f"unknown steps: {', '.join(sorted(unknown))}. Steps: {', '.join(STEPS)}")
    if not DATABASE.exists():
        sys.exit(f"{DATABASE.name} does not exist. Build the text first: python3 -m bomnerds.text")
    chosen = [name for name in STEPS if name in names or not names]
    db = sqlite3.connect(DATABASE)
    db.execute("pragma foreign_keys = on")
    with db:
        for name in reversed(chosen):
            STEPS[name].clear(db)
    for name in chosen:
        started = time.monotonic()
        with db:
            STEPS[name].run(db)
        print(f"{name}: done in {time.monotonic() - started:.0f}s")


if __name__ == "__main__":
    main(sys.argv[1:])

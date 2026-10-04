"""The only way agents read and write the dataset. Run with --help for every command."""

import argparse
import json
import os
import sqlite3
import sys
from collections import Counter
from pathlib import Path

from ..passages import Rejected, parse_reference
from ..text import DATABASE
from . import jobs
from .layers import LAYERS
from .prompt import prompt
from .search import format_results, search
from .show import show


def connect() -> sqlite3.Connection:
    path = Path(os.environ.get("BOMNERDS_DATABASE", DATABASE))
    if not path.exists():
        sys.exit(f"{path} does not exist. Build it first: python3 -m bomnerds.text")
    db = sqlite3.connect(path, timeout=120)
    db.execute("pragma foreign_keys = on")
    return db


def load(path: str):
    try:
        return json.load(sys.stdin if path == "-" else open(path, encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise Rejected(f"the answer is not valid JSON: {error}")
    except OSError as error:
        raise Rejected(f"cannot read the answer: {error}")


def run_show(db, args):
    book, chapter, verse = parse_reference(db, args.chapter)
    if verse is not None:
        raise Rejected("show takes a chapter, such as \"1 Nephi 3\"")
    layers = tuple(args.layers.split(",")) if args.layers else None
    print(show(db, book, chapter, args.edition, layers))


def run_search(db, args):
    book = parse_reference(db, f"{args.book} 1")[0] if args.book else None
    name = db.execute("select name from book where id = ?", (book,)).fetchone()[0] if book else None
    print(format_results(search(db, args.text, book, args.type, args.limit), name))


def run_job(db, args):
    print(prompt(db, jobs.find(db, args.job), args.role))


def run_check(db, args):
    job = jobs.find(db, args.job)
    tags = jobs.check(db, job, args.role, load(args.answer))
    print(f"the answer passes: {len(tags)} tags")


def run_submit(db, args):
    job = jobs.find(db, args.job)
    print(jobs.submit(db, job, args.role, load(args.answer)))


def run_missing(db, args):
    job = jobs.find(db, args.job)
    types = [row[0] for row in db.execute("select id from entity_type")]
    if args.type not in types:
        raise Rejected(f"type {args.type!r} is not one of: {', '.join(types)}")
    parse_reference(db, args.verse)
    print(jobs.report_missing(db, job, {"name": args.name, "type": args.type, "description": args.description, "verse": args.verse}))


def run_layers(db, args):
    for layer in LAYERS.values():
        states = Counter(job.state(db).split(":")[0] for job in jobs.listed(db, layer, args.pilot))
        print(f"step {layer.step} {layer.name} ({layer.mode}, one job per {layer.scope}): " + ", ".join(f"{n} {s}" for s, n in sorted(states.items())))


def run_jobs(db, args):
    layer = LAYERS.get(args.layer)
    if layer is None:
        raise Rejected(f"no layer {args.layer!r}. Layers: {', '.join(LAYERS)}")
    for job in jobs.listed(db, layer, args.pilot):
        state = job.state(db)
        if args.state is None or state.startswith(args.state):
            print(f"{job.id}\t{state}")


def run_reset(db, args):
    print(jobs.reset(db, jobs.find(db, args.job)))


def run_replay(db, args):
    unknown = set(args.layers) - LAYERS.keys()
    if unknown:
        raise Rejected(f"no layer {', '.join(sorted(unknown))}. Layers: {', '.join(LAYERS)}")
    print(jobs.replay(db, [layer for name, layer in LAYERS.items() if name in args.layers or not args.layers]))


def run_reports(db, args):
    for report in jobs.missing_reports():
        print(json.dumps(report, ensure_ascii=False))


def parser() -> argparse.ArgumentParser:
    main = argparse.ArgumentParser(prog="python3 -m bomnerds.agent", description=__doc__)
    commands = main.add_subparsers(required=True, metavar="command")

    command = commands.add_parser("show", help="print a chapter with every tag placed on it")
    command.add_argument("chapter", help='such as "1 Nephi 3"')
    command.add_argument("--edition", help="such as wlc or sblgnt. The English edition by default")
    command.add_argument("--layers", help="comma-separated layers to show. Every layer by default")
    command.set_defaults(run=run_show)

    command = commands.add_parser("search", help="find entities by name")
    command.add_argument("text")
    command.add_argument("--book", help="list the entities already found in this book first")
    command.add_argument("--type", help="only this type and its subtypes")
    command.add_argument("--limit", type=int, default=20)
    command.set_defaults(run=run_search)

    for name, run, help in (("job", run_job, "print what an agent reads to do a job"), ("check", run_check, "check an answer without storing it"), ("submit", run_submit, "check an answer and store it")):
        command = commands.add_parser(name, help=help)
        command.add_argument("job", help="such as names/1-nephi/3")
        command.add_argument("--role", required=True, choices=["a", "b", "decider", "writer", "checker"])
        if name != "job":
            command.add_argument("answer", help="a JSON file, or - for standard input")
        command.set_defaults(run=run)

    command = commands.add_parser("missing", help="report an entity the list lacks")
    command.add_argument("job")
    command.add_argument("--name", required=True)
    command.add_argument("--type", required=True)
    command.add_argument("--description", required=True)
    command.add_argument("--verse", required=True, help="a verse that names it")
    command.set_defaults(run=run_missing)

    command = commands.add_parser("layers", help="list the layers in build order with how many jobs are in each state")
    command.add_argument("--pilot", action="store_true", help="only jobs in the pilot set")
    command.set_defaults(run=run_layers)

    command = commands.add_parser("jobs", help="list a layer's jobs and their states")
    command.add_argument("layer")
    command.add_argument("--pilot", action="store_true", help="only jobs in the pilot set")
    command.add_argument("--state", help="only jobs whose state starts with this, such as settled or needs")
    command.set_defaults(run=run_jobs)

    command = commands.add_parser("reset", help="delete a job's stored tags and answers so it runs again")
    command.add_argument("job")
    command.set_defaults(run=run_reset)

    command = commands.add_parser("replay", help="store every settled job again, after a script layer rebuilds a table")
    command.add_argument("layers", nargs="*")
    command.set_defaults(run=run_replay)

    command = commands.add_parser("reports", help="list entities agents reported missing")
    command.set_defaults(run=run_reports)

    for layer in LAYERS.values():
        layer.commands(commands)
    return main


def main(argv: list[str]):
    args = parser().parse_args(argv)
    db = connect()
    try:
        args.run(db, args)
    except Rejected as error:
        sys.exit(str(error))


if __name__ == "__main__":
    main(sys.argv[1:])

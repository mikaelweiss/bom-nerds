"""The only way agents read and write the dataset. Run with --help for every command."""

import argparse
import json
import os
import sqlite3
import sys
from collections import Counter
from pathlib import Path

from ..passages import Rejected
from ..text import DATABASE
from . import batch, jobs
from . import plan as plans
from .layers import LAYERS


def connect() -> sqlite3.Connection:
    path = Path(os.environ.get("BOMNERDS_DATABASE", DATABASE))
    if not path.exists():
        sys.exit(f"{path} does not exist. Build it first: python3 -m bomnerds.text")
    db = sqlite3.connect(path, timeout=120)
    db.execute("pragma foreign_keys = on")
    return db


def run_plan(db, args):
    sessions = plans.make(db, pilot=args.pilot)
    path = plans.PILOT_PLAN if args.pilot else plans.PLAN
    plans.write(sessions, path)
    counts = Counter(s.pass_name for s in sessions if not s.review)
    reviews = sum(s.review for s in sessions)
    print(f"Wrote {path.name}: {len(sessions)} sessions, {reviews} of them reviews.")
    for p in plans.PASSES:
        if counts[p.name]:
            print(f"  {p.name}: {counts[p.name]} sessions, {p.model}")


def run_batch(db, args):
    print(batch.write_prompt(db, args.session))


def run_submit(db, args):
    print(batch.submit(db, args.session, args.layer))


def run_done(db, args):
    print(batch.done(db, args.session))


def run_reset(db, args):
    print(batch.reset(db, args.session))


def run_status(db, args):
    sessions = plans.load(plans.PILOT_PLAN if args.pilot else plans.PLAN)
    if args.ready:
        for session in sessions:
            if not session.done() and not plans.waiting_on(session, sessions):
                print(f"{session.id}\t{session.model}\t{','.join(session.layers)}")
        return
    states = [(session, plans.state(db, session, sessions)) for session in sessions]
    for p in plans.PASSES:
        mine = [(s, state) for s, state in states if s.pass_name == p.name]
        if not mine:
            continue
        tally = Counter(state.split(":")[0].split(" for ")[0] for _, state in mine)
        print(f"{p.name}: " + ", ".join(f"{n} {state}" for state, n in sorted(tally.items())))
        for s, state in mine:
            if args.all or state not in ("done",) and not state.startswith("waiting"):
                rates = s.folder / "rates.json"
                rated = ""
                if rates.exists():
                    rated = "  errors " + ", ".join(f"{name} {wrong}/{checked}" for name, (wrong, checked) in json.loads(rates.read_text()).items())
                print(f"  {s.id}\t{s.covers}\t{state}{rated}")


def run_replay(db, args):
    unknown = set(args.layers) - LAYERS.keys()
    if unknown:
        raise Rejected(f"no layer {', '.join(sorted(unknown))}. Layers: {', '.join(LAYERS)}")
    print(jobs.replay(db, [layer for name, layer in LAYERS.items() if name in args.layers or not args.layers]))


def parser() -> argparse.ArgumentParser:
    main = argparse.ArgumentParser(prog="python3 -m bomnerds.agent", description=__doc__)
    commands = main.add_subparsers(required=True, metavar="command")

    command = commands.add_parser("plan", help="cut every session of the run into plan.tsv, from counts in the database")
    command.add_argument("--pilot", action="store_true", help="cut the pilot's sessions into plan-pilot.tsv instead")
    command.set_defaults(run=run_plan)

    command = commands.add_parser("batch", help="write the prompt for a session: every layer it answers, or its review")
    command.add_argument("session", help="such as people-014")
    command.set_defaults(run=run_batch)

    command = commands.add_parser("submit", help="store a session's answer for one layer, or a review's fixes")
    command.add_argument("session")
    command.add_argument("layer", nargs="?", help="such as names. A review takes none")
    command.set_defaults(run=run_submit)

    command = commands.add_parser("done", help="mark a session done, once every section is stored")
    command.add_argument("session")
    command.set_defaults(run=run_done)

    command = commands.add_parser("status", help="show how far each pass of the plan is")
    command.add_argument("--pilot", action="store_true", help="the pilot plan")
    command.add_argument("--ready", action="store_true", help="list only sessions that can start now, in plan order")
    command.add_argument("--all", action="store_true", help="list every session, done and waiting ones too")
    command.set_defaults(run=run_status)

    command = commands.add_parser("reset", help="delete everything a writer session stored, so it runs again from the start")
    command.add_argument("session")
    command.set_defaults(run=run_reset)

    command = commands.add_parser("replay", help="store every stored answer again, after a script layer rebuilds a table")
    command.add_argument("layers", nargs="*")
    command.set_defaults(run=run_replay)

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

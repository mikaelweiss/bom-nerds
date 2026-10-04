"""Holds each job's answers until they settle, then stores the settled tags.

A job lives in jobs/<layer>/<scope>/, with one file per role's answer and settled.json once its tags are stored.
Settled tags are kept as agents write them, so they can be stored again after a script layer rebuilds its table.
"""

import fcntl
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from ..sources import ROOT
from .layer import PILOT, Layer, Rejected, Tag

JOBS = Path(os.environ.get("BOMNERDS_JOBS", ROOT / "jobs"))
MISSING = JOBS / "missing.jsonl"
ROLES = {"compare": ("a", "b", "decider"), "check": ("writer", "checker")}
CLI = "python3 -m bomnerds.agent"


class Job:
    def __init__(self, layer: Layer, scope: str):
        self.layer = layer
        self.scope = scope
        self.path = JOBS / layer.name / scope

    @property
    def id(self) -> str:
        return f"{self.layer.name}/{self.scope}"

    def answer(self, role: str) -> Any:
        return read(self.path / f"{role}.json")

    def settled(self) -> list[dict] | None:
        return read(self.path / "settled.json")

    def write(self, name: str, value: Any):
        self.path.mkdir(parents=True, exist_ok=True)
        temporary = self.path / f".{name}.json"
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        temporary.replace(self.path / f"{name}.json")

    def state(self, db: sqlite3.Connection) -> str:
        if self.settled() is not None:
            return "settled"
        given = {role for role in ROLES[self.layer.mode] if (self.path / f"{role}.json").exists()}
        if self.layer.mode == "check":
            return "needs checker" if "writer" in given else self.waiting(db, "needs writer")
        if {"a", "b"} <= given:
            return "needs decider"
        if given:
            return f"needs {'b' if 'a' in given else 'a'}"
        return self.waiting(db, "needs a and b")

    def waiting(self, db: sqlite3.Connection, state: str) -> str:
        reason = self.layer.ready(db, Jobs, self.scope)
        return f"waiting: {reason}" if reason else state

    @contextmanager
    def lock(self):
        self.path.mkdir(parents=True, exist_ok=True)
        with open(self.path / ".lock", "w") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            yield


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


class Jobs:
    """Lookups a layer makes into other jobs, such as the speeches a book's previous chapter left open."""

    @staticmethod
    def get(layer_name: str, scope: str) -> Job:
        from .layers import LAYERS

        return Job(LAYERS[layer_name], scope)


def find(db: sqlite3.Connection, job_id: str) -> Job:
    from .layers import LAYERS

    name, _, scope = job_id.partition("/")
    if name not in LAYERS:
        raise Rejected(f"no layer {name!r}. Layers: {', '.join(LAYERS)}")
    layer = LAYERS[name]
    if scope not in layer.scope_set(db):
        raise Rejected(f"{name} has no job {scope!r}. List them with: {CLI} jobs {name}")
    return Job(layer, scope)


def listed(db: sqlite3.Connection, layer: Layer, pilot: bool = False) -> list[Job]:
    scopes = layer.scopes(db)
    if pilot:
        chosen = set(PILOT)
        scopes = [s for s in scopes if chosen & set(layer.chapters(db, s))]
    return [Job(layer, scope) for scope in scopes]


def roles(job: Job) -> tuple[str, ...]:
    return ROLES[job.layer.mode]


def already(db: sqlite3.Connection, job: Job) -> list[Tag]:
    """Tags this job's answers leave out: the ones a script settles for it, and the ones already in the database."""
    return job.layer.fixed(db, job.scope) + job.layer.given(db, job.scope)


def agreement(db: sqlite3.Connection, job: Job) -> tuple[list[Tag], list[Tag], list[Tag]]:
    """The tags both runs gave, the tags only the first gave, and the tags only the second gave."""
    first = job.layer.parse(db, job.scope, job.answer("a"))
    second = job.layer.parse(db, job.scope, job.answer("b"))
    second_set, first_set = set(second), set(first)
    return [t for t in first if t in second_set], [t for t in first if t not in second_set], [t for t in second if t not in first_set]


def check(db: sqlite3.Connection, job: Job, role: str, answer: Any) -> list[Tag]:
    """The tags an answer from this role would add, or Rejected with every problem in it."""
    layer = job.layer
    if role not in roles(job):
        raise Rejected(f"{layer.name} jobs take the roles {', '.join(roles(job))}")
    if job.settled() is not None:
        raise Rejected(f"{job.id} is settled. An operator must reset it before it takes answers")
    reason = layer.ready(db, Jobs, job.scope)
    if reason:
        raise Rejected(f"{job.id} cannot start yet: {reason}")
    if role == "decider":
        if job.answer("a") is None or job.answer("b") is None:
            raise Rejected(f"{job.id} needs both runs before a decider")
        agreed, _, _ = agreement(db, job)
        if not isinstance(answer, list):
            raise Rejected("the answer must be a JSON array of objects")
        tags = layer.parse(db, job.scope, answer + [layer.render(db, t) for t in agreed])
        repeats(db, layer, tags)
        tags = tags[: len(tags) - len(agreed)]
    else:
        if role == "checker" and job.answer("writer") is None:
            raise Rejected(f"{job.id} needs the writer's answer before a checker")
        tags = layer.parse(db, job.scope, answer)
        repeats(db, layer, tags)
    taken = set(already(db, job))
    clashes = [layer.render(db, t) for t in tags if t in taken]
    if clashes:
        raise Rejected("these are already tagged, so leave them out:\n" + "\n".join(line(c) for c in clashes))
    return tags


def repeats(db: sqlite3.Connection, layer: Layer, tags: list[Tag]):
    seen, twice = set(), []
    for tag in tags:
        if tag in seen:
            twice.append(layer.render(db, tag))
        seen.add(tag)
    if twice:
        raise Rejected("the same fact appears twice:\n" + "\n".join(line(t) for t in twice))


def submit(db: sqlite3.Connection, job: Job, role: str, answer: Any) -> str:
    with job.lock():
        tags = check(db, job, role, answer)
        if job.answer(role) is not None:
            raise Rejected(f"{job.id} already has an answer from {role}")
        job.write(role, answer)
        if role in ("a", "b"):
            if job.answer("a") is None or job.answer("b") is None:
                return f"{job.id}: stored the answer from {role}. Waiting for the other run."
            agreed, first, second = agreement(db, job)
            if first or second:
                return f"{job.id}: both runs in. They agree on {len(agreed)} tags and differ on {len(first) + len(second)}. Needs a decider."
            settle(db, job, agreed)
            return f"{job.id}: both runs agree on all {len(agreed)} tags. Settled and stored."
        if role == "writer":
            return f"{job.id}: stored the writer's answer. Needs a checker."
        if role == "decider":
            agreed, _, _ = agreement(db, job)
            tags = agreed + tags
        settle(db, job, tags)
        return f"{job.id}: settled and stored {len(tags)} tags."


def settle(db: sqlite3.Connection, job: Job, tags: list[Tag]):
    layer = job.layer
    final = layer.fixed(db, job.scope) + tags
    with db:
        layer.store(db, job.scope, final)
    job.write("settled", [layer.render(db, t) for t in final])


def reset(db: sqlite3.Connection, job: Job) -> str:
    """Delete a job's stored tags and every answer, so it runs again from the start."""
    with job.lock():
        settled = job.settled()
        if settled is not None:
            try:
                with db:
                    job.layer.unstore(db, job.scope, job.layer.parse(db, job.scope, settled))
            except sqlite3.IntegrityError:
                raise Rejected(f"{job.id} cannot reset while later jobs' tags still point at what it stored. Reset those jobs first.")
        for path in job.path.glob("*.json"):
            path.unlink()
    return f"{job.id}: reset" + (f", {len(settled)} tags deleted" if settled else "")


def replay(db: sqlite3.Connection, layers: list[Layer]) -> str:
    """Store every settled job again, in build order. Run it after a script layer rebuilds a table jobs also write to."""
    counts = []
    for layer in sorted(layers, key=lambda layer: (layer.step, bool(layer.after))):
        # Latest first, so a job never unstores tags a later job built on.
        settled = [(job, layer.parse(db, job.scope, job.settled())) for job in listed(db, layer) if job.settled() is not None]
        with db:
            for job, tags in reversed(settled):
                layer.unstore(db, job.scope, tags)
            for job, tags in settled:
                layer.store(db, job.scope, tags)
        counts.append(f"{layer.name}: {len(settled)} jobs stored again")
    return "\n".join(counts)


# Answer fields that hold entity ids. Quotes and written text never change when an entity is renamed.
ENTITY_FIELDS = {"entity", "speaker", "through", "listeners", "subject", "object", "traveler", "from", "to", "id", "pick", "keep", "merge"}


def rename_entity(old: str, new: str) -> int:
    """Rename an entity id in every saved answer, as the database cascades it through every table. Returns files changed."""

    def swap(value, field=None):
        if isinstance(value, dict):
            return {k: swap(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [swap(v, field) for v in value]
        return new if value == old and field in ENTITY_FIELDS else value

    changed = 0
    for path in JOBS.glob("*/**/*.json"):
        value = read(path)
        renamed = swap(value)
        if renamed != value:
            path.write_text(json.dumps(renamed, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            changed += 1
    return changed


def report_missing(db: sqlite3.Connection, job: Job, report: dict) -> str:
    JOBS.mkdir(exist_ok=True)
    with open(MISSING, "a", encoding="utf-8") as out:
        fcntl.flock(out, fcntl.LOCK_EX)
        out.write(json.dumps({"job": job.id, **report}, ensure_ascii=False) + "\n")
    return f"reported {report['name']} missing. Leave its tags out of this answer. The job runs again once it is added."


def resolve_report(job_id: str, name: str):
    """Remove the reports of this name from this job, once the entity is added."""
    if not MISSING.exists():
        return
    with open(MISSING, "r+", encoding="utf-8") as reports:
        fcntl.flock(reports, fcntl.LOCK_EX)
        kept = [l for l in reports.read().splitlines() if (lambda r: (r["job"], r["name"]) != (job_id, name))(json.loads(l))]
        reports.seek(0)
        reports.truncate()
        reports.write("".join(l + "\n" for l in kept))


def missing_reports() -> list[dict]:
    return [json.loads(l) for l in MISSING.read_text(encoding="utf-8").splitlines()] if MISSING.exists() else []


def line(tag: dict) -> str:
    return json.dumps(tag, ensure_ascii=False)

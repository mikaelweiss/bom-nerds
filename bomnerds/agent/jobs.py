"""Stores each scope's answer once it passes, and the tags it settles.

A job is one layer on one scope. It lives in jobs/<layer>/<scope>/: settled.json holds every tag it stored, as agents write them,
so they can be stored again after a script layer rebuilds its table. flagged.json and unlisted.json hold what the writer was unsure of
and the names it found no entity for, which the pass's review settles.
"""

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from ..sources import ROOT
from .layer import Layer, Rejected, Tag

JOBS = Path(os.environ.get("BOMNERDS_JOBS", ROOT / "jobs"))
CLI = "python3 -m bomnerds.agent"


class Job:
    def __init__(self, layer: Layer, scope: str):
        self.layer = layer
        self.scope = scope
        self.path = JOBS / layer.name / scope

    @property
    def id(self) -> str:
        return f"{self.layer.name}/{self.scope}"

    def settled(self) -> list[dict] | None:
        if self.id in Jobs.pending:
            return Jobs.pending[self.id]
        return self.read("settled")

    def read(self, name: str) -> Any:
        return read(self.path / f"{name}.json")

    def write(self, name: str, value: Any):
        self.path.mkdir(parents=True, exist_ok=True)
        temporary = self.path / f".{name}.json"
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        temporary.replace(self.path / f"{name}.json")

    def clear(self):
        for path in self.path.glob("*.json"):
            path.unlink()


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


class Jobs:
    """Lookups a layer makes into other jobs, such as the speeches a book's previous chapter left open.

    pending holds settled answers a review stores in one transaction, so each scope reads its neighbors' answers before they are written.
    """

    pending: dict[str, list[dict]] = {}

    @staticmethod
    def get(layer_name: str, scope: str) -> Job:
        from .layers import LAYERS

        return Job(LAYERS[layer_name], scope)


def already(db: sqlite3.Connection, job: Job) -> list[Tag]:
    """Tags this job's answer leaves out: the ones a script settles for it, and the ones already in the database."""
    return job.layer.fixed(db, job.scope) + job.layer.given(db, job.scope)


def check(db: sqlite3.Connection, job: Job, items: list[dict]) -> list[Tag]:
    """The tags an answer would add, or Rejected with every problem in it."""
    layer = job.layer
    tags = layer.parse(db, job.scope, items)
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


def submit(db: sqlite3.Connection, job: Job, items: list[dict], flagged: list[str] = (), unlisted: list[dict] = ()) -> int:
    """Check an answer and store it with the tags a script settles for the scope. Returns how many tags were stored."""
    if job.settled() is not None:
        raise Rejected(f"{job.id} is already stored")
    tags = check(db, job, items)
    final = job.layer.fixed(db, job.scope) + tags
    with db:
        job.layer.store(db, job.scope, final)
    job.write("settled", [job.layer.render(db, t) for t in final])
    if flagged:
        job.write("flagged", list(flagged))
    if unlisted:
        job.write("unlisted", list(unlisted))
    return len(final)


def reset(db: sqlite3.Connection, job: Job) -> int:
    """Delete a job's stored tags and its files. Returns how many tags were deleted."""
    settled = job.settled()
    if settled is not None:
        try:
            with db:
                job.layer.unstore(db, job.scope, job.layer.parse(db, job.scope, settled))
        except sqlite3.IntegrityError:
            raise Rejected(f"{job.id} cannot reset while later layers' tags still point at what it stored. Reset those first.")
    job.clear()
    return len(settled or [])


def replay(db: sqlite3.Connection, layers: list[Layer]) -> str:
    """Store every settled job again, in build order. Run it after a script layer rebuilds a table jobs also write to."""
    counts = []
    for layer in sorted(layers, key=lambda layer: layer.step):
        # Latest first, so a job never unstores tags a later job built on.
        settled = [(job, layer.parse(db, job.scope, job.settled())) for job in (Job(layer, scope) for scope in layer.scopes(db)) if job.settled() is not None]
        with db:
            for job, tags in reversed(settled):
                layer.unstore(db, job.scope, tags)
            for job, tags in settled:
                layer.store(db, job.scope, tags)
        counts.append(f"{layer.name}: {len(settled)} jobs stored again")
    return "\n".join(counts)


# Answer fields that hold entity ids. Quotes and written text never change when an entity is renamed.
ENTITY_FIELDS = {"entity", "speaker", "through", "listeners", "subject", "object", "traveler", "from", "to", "id", "pick"}


def rename_entity(old: str, new: str) -> int:
    """Rename an entity id in every saved answer, as the database cascades it through every table. Returns files changed."""

    def swap(value, field=None):
        if isinstance(value, dict):
            return {k: swap(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [swap(v, field) for v in value]
        return new if value == old and field in ENTITY_FIELDS else value

    changed = 0
    for path in JOBS.glob("*/**/settled.json"):
        value = read(path)
        renamed = swap(value)
        if renamed != value:
            path.write_text(json.dumps(renamed, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            changed += 1
    return changed


def line(tag: dict) -> str:
    return json.dumps(tag, ensure_ascii=False)

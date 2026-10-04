"""Prints a chapter with every tag the layers have placed on it, in the form agents write."""

import json
import sqlite3

from ..passages import chapter_verses, english_edition, reference


def show(db: sqlite3.Connection, book_id: str, chapter: int, edition: str | None = None, layers: tuple[str, ...] | None = None) -> str:
    from .layers import LAYERS

    edition = edition or english_edition(db, book_id)
    lines = [f"# {reference(db, book_id, chapter)} ({edition})", ""]
    lines += [f"{verse} {text.strip()}" for verse, text in chapter_verses(db, edition, book_id, chapter)]
    for name, layer in LAYERS.items():
        if layers is not None and name not in layers:
            continue
        tags = layer.shown(db, edition, book_id, chapter)
        if tags:
            lines += ["", f"## {name}", ""]
            lines += [json.dumps(tag, ensure_ascii=False) for tag in tags]
    return "\n".join(lines)

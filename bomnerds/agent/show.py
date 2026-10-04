"""Prints a chapter with every tag the layers have placed on it, in the form agents write."""

import json
import sqlite3

from ..passages import chapter_verses, english_edition, reference


def show(db: sqlite3.Connection, book_id: str, chapter: int, edition: str | None = None, layers: tuple[str, ...] | None = None, level: int = 1) -> str:
    """The chapter under a heading of this level, each layer's tags under a heading one level down."""
    from .layers import LAYERS

    edition = edition or english_edition(db, book_id)
    lines = [f"{'#' * level} {reference(db, book_id, chapter)} ({edition})", ""]
    lines += [f"{verse} {text.strip()}" for verse, text in chapter_verses(db, edition, book_id, chapter)]
    for name, layer in LAYERS.items():
        if layers is not None and name not in layers:
            continue
        tags = layer.shown(db, edition, book_id, chapter)
        if tags:
            lines += ["", f"{'#' * (level + 1)} {name}", ""]
            lines += [compact(tag) for tag in tags]
    return "\n".join(lines)


def compact(tag: dict) -> str:
    """A tag on one line: a mention as verse, quote, and entity, which most tags are, and anything else as JSON."""
    passage = tag.get("passage")
    if set(tag) <= {"entity", "kind", "passage"} and isinstance(passage, dict) and set(passage) <= {"verse", "quote", "in"} and "verse" in passage:
        quote = f' "{passage["quote"]}"' if "quote" in passage else ""
        within = f' in "{passage["in"]}"' if "in" in passage else ""
        kind = f" ({tag['kind']})" if tag.get("kind", "names") != "names" else ""
        return f"{passage['verse']}{quote}{within} = {tag['entity']}{kind}"
    return json.dumps(tag, ensure_ascii=False)

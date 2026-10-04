"""Finds entities by name, other name, or id, with the ones already found in a book first."""

import sqlite3


def search(db: sqlite3.Connection, text: str, book_id: str | None = None, type_id: str | None = None, limit: int = 20) -> list[dict]:
    needle = text.strip().casefold()
    rows = db.execute(
        """
        select e.id, e.type_id, e.name, e.description,
            (select group_concat(n.name, '; ') from entity_name n where n.entity_id = e.id and n.name <> e.name) as other_names,
            exists (select 1 from entity_book b where b.entity_id = e.id and b.book_id = :book) as in_book,
            min(case
                when lower(e.name) = :needle or e.id = :needle then 0
                when lower(n.name) = :needle then 1
                when lower(e.name) like :needle || '%' or lower(n.name) like :needle || '%' then 2
                else 3 end) as closeness
        from entity e
        join entity_type t on t.id = e.type_id
        left join entity_name n on n.entity_id = e.id
        where (lower(e.name) like '%' || :needle || '%' or lower(n.name) like '%' || :needle || '%' or e.id like '%' || :needle || '%')
            and (:type is null or t.id = :type or t.parent_id = :type)
        group by e.id
        order by in_book desc, closeness, e.name, e.id
        limit :limit
        """,
        {"needle": needle, "book": book_id, "type": type_id, "limit": limit},
    )
    return [
        {"id": id, "type": type_id, "name": name, "other_names": other.split("; ") if other else [], "description": description, "in_book": bool(in_book)}
        for id, type_id, name, description, other, in_book, _ in rows
    ]


def format_results(results: list[dict], book_name: str | None) -> str:
    if not results:
        return "No entity matches. Try another name or title, or report it missing."
    lines = []
    for r in results:
        also = f" Also: {', '.join(r['other_names'])}." if r["other_names"] else ""
        found = f" Found in {book_name}." if r["in_book"] and book_name else ""
        lines.append(f"{r['id']} ({r['type']}) {r['name']}. {r['description']}{also}{found}")
    return "\n".join(lines)

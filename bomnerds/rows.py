import sqlite3


def row_id(db: sqlite3.Connection, table: str, name: str, column: str = "name") -> int:
    row = db.execute(f"select id from {table} where {column} = ?", (name,)).fetchone()
    if row is None:
        raise LookupError(f"no {table} has {column} {name!r}")
    return row[0]

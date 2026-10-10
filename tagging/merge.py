"""Merge duplicate entities in scripture.db.

    python3 tagging/merge.py KEEP DROP [DROP ...] [--description TEXT]

Every reference to a DROP entity moves to KEEP, then DROP is deleted. KEEP
takes DROP's TIPNR id and coordinates when it has none, and DROP's names
become KEEP's other names.
"""

import argparse
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "scripture.db"


def move_relationships(db: sqlite3.Connection, keep: int, drop: int):
    rows = db.execute(
        "select id, subject_id, relationship_kind_id, object_id from relationship where ? in (subject_id, object_id)",
        (drop,),
    ).fetchall()
    for rid, subject, kind, obj in rows:
        subject = keep if subject == drop else subject
        obj = keep if obj == drop else obj
        if subject == obj:
            db.execute("delete from relationship_evidence where relationship_id = ?", (rid,))
            db.execute("delete from date where relationship_id = ?", (rid,))
            db.execute("delete from relationship where id = ?", (rid,))
            continue
        same = db.execute(
            "select id from relationship where relationship_kind_id = ? and min(subject_id, object_id) = min(?, ?)"
            " and max(subject_id, object_id) = max(?, ?) and id <> ?",
            (kind, subject, obj, subject, obj, rid),
        ).fetchone()
        if same:
            db.execute(
                "insert or ignore into relationship_evidence (relationship_id, first_word_id, last_word_id)"
                " select ?, first_word_id, last_word_id from relationship_evidence where relationship_id = ?",
                (same[0], rid),
            )
            db.execute("delete from relationship_evidence where relationship_id = ?", (rid,))
            db.execute("update date set relationship_id = ? where relationship_id = ?", (same[0], rid))
            db.execute("delete from relationship where id = ?", (rid,))
        else:
            db.execute("update relationship set subject_id = ?, object_id = ? where id = ?", (subject, obj, rid))


def merge(db: sqlite3.Connection, keep: int, drop: int, description: str | None = None, skip_names: tuple[str, ...] = ()):
    k = db.execute("select name, tipnr, latitude, longitude from entity where id = ?", (keep,)).fetchone()
    d = db.execute("select name, tipnr, latitude, longitude from entity where id = ?", (drop,)).fetchone()
    if not k or not d or keep == drop:
        raise SystemExit(f"cannot merge {drop} into {keep}")

    if k[1] is None and d[1] is not None:
        db.execute("update entity set tipnr = null where id = ?", (drop,))
        db.execute("update entity set tipnr = ? where id = ?", (d[1], keep))
    keep_is_place = db.execute(
        "select 1 from entity e join entity_type t on t.id = e.entity_type_id left join entity_type p on p.id = t.parent_id"
        " where e.id = ? and 'Place' in (t.name, p.name)",
        (keep,),
    ).fetchone()
    if k[2] is None and d[2] is not None and keep_is_place:
        db.execute("update entity set latitude = ?, longitude = ? where id = ?", (d[2], d[3], keep))
    if description:
        db.execute("update entity set description = ? where id = ?", (description, keep))

    names = [(d[0], 0)] + db.execute("select name, is_title from entity_name where entity_id = ?", (drop,)).fetchall()
    db.execute("delete from entity_name where entity_id = ?", (drop,))
    for name, is_title in names:
        taken = db.execute(
            "select 1 from entity where id = ? and lower(name) = lower(?)"
            " union all select 1 from entity_name where entity_id = ? and lower(name) = lower(?)",
            (keep, name, keep, name),
        ).fetchone()
        if not taken and name not in skip_names:
            db.execute("insert into entity_name (entity_id, name, is_title) values (?, ?, ?)", (keep, name, is_title))

    db.execute("update or ignore mention set entity_id = ? where entity_id = ?", (keep, drop))
    db.execute("delete from mention where entity_id = ?", (drop,))

    move_relationships(db, keep, drop)

    for table in ("speech_speaker", "speech_listener"):
        db.execute(f"update or ignore {table} set entity_id = ? where entity_id = ?", (keep, drop))
        db.execute(f"delete from {table} where entity_id = ?", (drop,))
    db.execute(
        "delete from speech_speaker where entity_id = ? and speech_id in (select id from speech where through_id = ?)",
        (keep, drop),
    )
    db.execute("update speech set through_id = ? where through_id = ?", (keep, drop))
    db.execute(
        "delete from speech_speaker where entity_id = ? and speech_id in (select id from speech where through_id = ?)",
        (keep, keep),
    )

    db.execute("update journey set from_id = null where from_id in (?, ?) and to_id in (?, ?)", (keep, drop, keep, drop))
    for column in ("traveler_id", "from_id", "to_id"):
        db.execute(f"update journey set {column} = ? where {column} = ?", (keep, drop))
    db.execute("update date set entity_id = ? where entity_id = ?", (keep, drop))

    db.execute("delete from entity where id = ?", (drop,))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("keep", type=int)
    parser.add_argument("drop", type=int, nargs="+")
    parser.add_argument("--description")
    parser.add_argument("--skip-name", action="append", default=[], help="a DROP name not to keep as an other name")
    args = parser.parse_args()
    db = sqlite3.connect(DB)
    db.execute("pragma foreign_keys = on")
    with db:
        for drop in args.drop:
            merge(db, args.keep, drop, args.description, tuple(args.skip_name))
        problems = db.execute("pragma foreign_key_check").fetchall()
        if problems:
            raise SystemExit(f"foreign key problems: {problems[:5]}")


if __name__ == "__main__":
    main()

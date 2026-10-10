"""Apply staged AI annotation decisions: word senses, new senses, speech listeners, journey origins, and entity merges.

Words tagged in senses_orig_existing move onto the headword of their meaning, and headwords left unused are deleted.

    python scripts/apply_ai_pass.py scripture.db decisions/ai-pass

Every decision is checked against the database first, so a run can be repeated safely.
"""

import json
import os
import sqlite3
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from project_to_originals import KJV, Projector  # noqa: E402

SENSE_FILES = (
    "senses_hebrew_a",
    "senses_hebrew_b",
    "senses_hebrew_proverbs",
    "senses_greek",
    "senses_orig_existing",
    "senses_en_even",
    "senses_en_odd",
)
NEW_MEANING_FILES = ("new_meanings_orig", "new_meanings_en")
REHOME_FILES = ("senses_orig_existing",)
LISTENER_FILES = ("listeners", "listeners_review")


def read_decisions(directory, name, report):
    path = os.path.join(directory, name + ".jsonl")
    if not os.path.exists(path):
        report[f"{name}: file missing"] += 1
        return
    for line in open(path, encoding="utf-8"):
        if not line.strip():
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            report[f"{name}: unreadable line"] += 1


def edition_of(db, word):
    return db.execute(
        "select c.edition_id from word w join verse v on v.id = w.verse_id join chapter c on c.id = v.chapter_id "
        "where w.id = ?",
        (word,),
    ).fetchone()[0]


def entity_exists(db, entity):
    return db.execute("select 1 from entity where id = ?", (entity,)).fetchone() is not None


def tag_word(db, word, meaning):
    return db.execute(
        "update word set meaning_id = ? where id = ? and meaning_id is null "
        "and headword_id = (select headword_id from meaning where id = ?)",
        (meaning, word, meaning),
    ).rowcount


def apply_senses(db, directory, report):
    for name in SENSE_FILES:
        for pick in read_decisions(directory, name, report):
            word = db.execute("select headword_id, meaning_id from word where id = ?", (pick["word_id"],)).fetchone()
            meaning = db.execute("select headword_id from meaning where id = ?", (pick["meaning_id"],)).fetchone()
            if word is None or meaning is None:
                report["senses: rejected"] += 1
            elif word[1] is not None:
                report["senses: already tagged"] += 1
            elif word[0] == meaning[0]:
                tag_word(db, pick["word_id"], pick["meaning_id"])
                report["senses: tagged"] += 1
            elif name in REHOME_FILES:
                db.execute(
                    "update word set headword_id = ?, meaning_id = ? where id = ?",
                    (meaning[0], pick["meaning_id"], pick["word_id"]),
                )
                report["senses: moved to the meaning's headword and tagged"] += 1
            else:
                report["senses: rejected"] += 1


def delete_unused_headwords(db, report):
    report["headwords: unused deleted"] += db.execute(
        "delete from headword where not exists (select 1 from word where headword_id = headword.id) "
        "and not exists (select 1 from meaning where headword_id = headword.id)"
    ).rowcount


def apply_new_meanings(db, directory, report):
    for name in NEW_MEANING_FILES:
        for sense in read_decisions(directory, name, report):
            headword = sense["headword_id"]
            if not db.execute("select 1 from headword where id = ?", (headword,)).fetchone():
                report["new senses: rejected"] += 1
                continue
            existing = db.execute(
                "select id from meaning where headword_id = ? and gloss = ? and definition is ?",
                (headword, sense["gloss"], sense["definition"]),
            ).fetchone()
            if existing:
                meaning = existing[0]
                report["new senses: already there"] += 1
            else:
                number = db.execute(
                    "select coalesce(max(number), 0) + 1 from meaning where headword_id = ?", (headword,)
                ).fetchone()[0]
                meaning = db.execute(
                    "insert into meaning (headword_id, number, gloss, definition) values (?, ?, ?, ?)",
                    (headword, number, sense["gloss"], sense["definition"]),
                ).lastrowid
                report["new senses: added"] += 1
            for word in sense["word_ids"]:
                report["new senses: words tagged" if tag_word(db, word, meaning) else "new senses: words skipped"] += 1


def projected_speech(db, projector, speech):
    first, last = db.execute("select first_word_id, last_word_id from speech where id = ?", (speech,)).fetchone()
    if edition_of(db, first) != KJV:
        return None
    span = projector.project(first, last)
    if span is None:
        return None
    row = db.execute("select id from speech where first_word_id = ? and last_word_id = ?", span).fetchone()
    return row and row[0]


def add_listener(db, speech, entity):
    """Insert a listener unless it is a speaker or the messenger of the speech."""
    if db.execute(
        "select 1 from speech_speaker where speech_id = ? and entity_id = ? "
        "union select 1 from speech where id = ? and through_id = ?",
        (speech, entity, speech, entity),
    ).fetchone():
        return "skipped as speaker or messenger"
    added = db.execute("insert or ignore into speech_listener values (?, ?)", (speech, entity)).rowcount
    return "added" if added else "already there"


def apply_listeners(db, directory, projector, keeper_of, report):
    for name in LISTENER_FILES:
        for decision in read_decisions(directory, name, report):
            speech = decision["speech_id"]
            if not db.execute("select 1 from speech where id = ?", (speech,)).fetchone():
                report["listeners: unknown speech"] += 1
                continue
            copy = projected_speech(db, projector, speech)
            for entity in dict.fromkeys(keeper_of.get(e, e) for e in decision["entity_ids"]):
                if not entity_exists(db, entity):
                    report["listeners: unknown entity"] += 1
                    continue
                report[f"listeners: {add_listener(db, speech, entity)}"] += 1
                if copy:
                    report[f"listeners on originals: {add_listener(db, copy, entity)}"] += 1


def apply_origins(db, directory, projector, keeper_of, report):
    for decision in read_decisions(directory, "origins", report):
        journey = db.execute(
            "select traveler_id, from_id, to_id, first_word_id, last_word_id from journey where id = ?",
            (decision["journey_id"],),
        ).fetchone()
        origin = keeper_of.get(decision["from_id"], decision["from_id"])
        if journey is None or not entity_exists(db, origin) or origin == journey[2]:
            report["origins: rejected"] += 1
            continue
        traveler, current, destination, first, last = journey
        if current is not None:
            report["origins: already set"] += 1
        else:
            db.execute("update journey set from_id = ? where id = ?", (origin, decision["journey_id"]))
            report["origins: set"] += 1
        if edition_of(db, first) != KJV:
            continue
        span = projector.project(first, last)
        if span is None:
            continue
        report["origins on originals: set"] += db.execute(
            "update journey set from_id = ? where traveler_id = ? and to_id = ? and first_word_id = ? "
            "and last_word_id = ? and from_id is null",
            (origin, traveler, destination, *span),
        ).rowcount


def repoint_relationships(db, merged, keeper, report):
    for relationship, subject, kind, obj in db.execute(
        "select id, subject_id, relationship_kind_id, object_id from relationship where ? in (subject_id, object_id)",
        (merged,),
    ).fetchall():
        subject = keeper if subject == merged else subject
        obj = keeper if obj == merged else obj
        if subject == obj:
            db.execute("delete from relationship where id = ?", (relationship,))
            report["merges: self-relationships dropped"] += 1
            continue
        survivor = db.execute(
            "select id from relationship where relationship_kind_id = ? and id <> ? "
            "and min(subject_id, object_id) = ? and max(subject_id, object_id) = ?",
            (kind, relationship, min(subject, obj), max(subject, obj)),
        ).fetchone()
        if survivor:
            db.execute(
                "insert or ignore into relationship_evidence select ?, first_word_id, last_word_id "
                "from relationship_evidence where relationship_id = ?",
                (survivor[0], relationship),
            )
            db.execute("update date set relationship_id = ? where relationship_id = ?", (survivor[0], relationship))
            db.execute("delete from relationship where id = ?", (relationship,))
            report["merges: duplicate relationships folded"] += 1
        else:
            db.execute("update relationship set subject_id = ?, object_id = ? where id = ?", (subject, obj, relationship))


def repoint_speeches(db, merged, keeper):
    db.execute(
        "delete from speech_speaker where entity_id = ? and speech_id in "
        "(select speech_id from speech_speaker where entity_id = ?)",
        (merged, keeper),
    )
    db.execute("update speech_speaker set entity_id = ? where entity_id = ?", (keeper, merged))
    db.execute(
        "update speech set through_id = null where through_id in (?, ?) "
        "and id in (select speech_id from speech_speaker where entity_id = ?)",
        (merged, keeper, keeper),
    )
    db.execute("update speech set through_id = ? where through_id = ?", (keeper, merged))
    db.execute(
        "delete from speech_listener where entity_id = ? and speech_id in "
        "(select speech_id from speech_listener where entity_id = ? "
        "union select speech_id from speech_speaker where entity_id = ? "
        "union select id from speech where through_id = ?)",
        (merged, keeper, keeper, keeper),
    )
    db.execute("update speech_listener set entity_id = ? where entity_id = ?", (keeper, merged))


def repoint_names(db, merged, keeper):
    keeper_name = db.execute("select name from entity where id = ?", (keeper,)).fetchone()[0]
    merged_name = db.execute("select name from entity where id = ?", (merged,)).fetchone()[0]
    db.execute(
        "insert or ignore into entity_name (entity_id, name, is_title) select ?, name, is_title "
        "from entity_name where entity_id = ? and name <> ?",
        (keeper, merged, keeper_name),
    )
    db.execute("delete from entity_name where entity_id = ?", (merged,))
    if merged_name != keeper_name:
        db.execute("insert or ignore into entity_name (entity_id, name) values (?, ?)", (keeper, merged_name))


def copy_place_details(db, merged, keeper, report):
    keeper_row = db.execute("select tipnr, latitude from entity where id = ?", (keeper,)).fetchone()
    tipnr, latitude, longitude = db.execute(
        "select tipnr, latitude, longitude from entity where id = ?", (merged,)
    ).fetchone()
    if keeper_row[1] is None and latitude is not None:
        is_place = db.execute(
            "select 1 from entity e join entity_type t on t.id = e.entity_type_id "
            "left join entity_type p on p.id = t.parent_id where e.id = ? and 'Place' in (t.name, p.name)",
            (keeper,),
        ).fetchone()
        if is_place:
            db.execute("update entity set latitude = ?, longitude = ? where id = ?", (latitude, longitude, keeper))
            report["merges: coordinates copied"] += 1
        else:
            report["merges: coordinates dropped, keeper not a place"] += 1
    if keeper_row[0] is None and tipnr is not None:
        db.execute("update entity set tipnr = null where id = ?", (merged,))
        db.execute("update entity set tipnr = ? where id = ?", (tipnr, keeper))
        report["merges: tipnr moved"] += 1


def merge(db, merged, keeper, report):
    db.execute(
        "delete from mention where entity_id = ? and exists (select 1 from mention k where k.entity_id = ? "
        "and k.mention_kind_id = mention.mention_kind_id and k.first_word_id = mention.first_word_id "
        "and k.last_word_id = mention.last_word_id)",
        (merged, keeper),
    )
    db.execute("update mention set entity_id = ? where entity_id = ?", (keeper, merged))
    repoint_speeches(db, merged, keeper)
    repoint_relationships(db, merged, keeper, report)
    db.execute(
        "update journey set traveler_id = iif(traveler_id = :m, :k, traveler_id), to_id = iif(to_id = :m, :k, to_id), "
        "from_id = iif(iif(from_id = :m, :k, from_id) = iif(to_id = :m, :k, to_id), null, iif(from_id = :m, :k, from_id)) "
        "where :m in (traveler_id, from_id, to_id)",
        {"m": merged, "k": keeper},
    )
    db.execute("update date set entity_id = ? where entity_id = ?", (keeper, merged))
    repoint_names(db, merged, keeper)
    copy_place_details(db, merged, keeper, report)
    db.execute("delete from entity where id = ?", (merged,))
    report["merges: entities merged"] += 1


def read_merges(directory, report):
    """Map each merged entity to its final keeper, following chains of merges."""
    keeper_of = {}
    for decision in read_decisions(directory, "merges", report):
        for merged in decision["merge_ids"]:
            keeper_of[merged] = decision["keep_id"]
    final = {}
    for merged in keeper_of:
        entity, seen = merged, set()
        while entity in keeper_of and entity not in seen:
            seen.add(entity)
            entity = keeper_of[entity]
        final[merged] = entity
    return final


def apply_merges(db, keeper_of, report):
    for merged, keeper in keeper_of.items():
        if keeper == merged or not entity_exists(db, keeper):
            report["merges: rejected"] += 1
        elif not entity_exists(db, merged):
            report["merges: already merged"] += 1
        else:
            merge(db, merged, keeper, report)


def main(path, directory):
    db = sqlite3.connect(path, isolation_level=None)
    db.execute("pragma foreign_keys = on")
    projector = Projector(db)
    report = Counter()
    db.execute("begin")
    apply_senses(db, directory, report)
    apply_new_meanings(db, directory, report)
    delete_unused_headwords(db, report)
    keeper_of = read_merges(directory, report)
    apply_listeners(db, directory, projector, keeper_of, report)
    apply_origins(db, directory, projector, keeper_of, report)
    apply_merges(db, keeper_of, report)
    problems = db.execute("pragma foreign_key_check").fetchall()
    if problems:
        db.execute("rollback")
        sys.exit(f"foreign key problems, nothing applied: {problems[:10]}")
    db.execute("commit")
    for key, n in sorted(report.items()):
        print(f"{key}: {n}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])

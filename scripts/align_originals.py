"""Match KJV words to Hebrew and Greek words with eflomal, seeded by the existing matches.

Run with a Python that has eflomal installed:
    python align_originals.py scripture.db WORKDIR [--evaluate]

--evaluate holds out a tenth of the verses, aligns without their matches, and reports
how often the aligner recovers them. Without it, new matches are written to word_match.
"""

import os
import random
import sqlite3
import sys
from collections import Counter, defaultdict

import eflomal

KJV = 1
ORIGINALS = {2: "hebrew", 3: "greek"}
PRIOR_WEIGHT = 5.0


def load_words(db, edition):
    rows = db.execute(
        "select w.id, w.verse_id, w.supplied, coalesce(h.strongs, 'h' || h.id, lower(w.text)), lower(h.text) "
        "from word w join verse v on v.id = w.verse_id join chapter c on c.id = v.chapter_id "
        "left join headword h on h.id = w.headword_id where c.edition_id = ? order by w.sequence",
        (edition,),
    )
    verses = defaultdict(list)
    for word, verse, supplied, strongs, lemma in rows:
        if supplied:
            continue
        key = lemma if edition == KJV else strongs
        verses[verse].append((word, (key or "?").replace(" ", "_")))
    return verses


def verse_units(db, original):
    """Group KJV and original verses that share matches, so versification differences line up."""
    counts = Counter()
    for kjv_verse, original_verse in db.execute(
        "select a.verse_id, b.verse_id from word_match m join word a on a.id = m.word_id "
        "join word b on b.id = m.other_word_id where a.verse_id in (select v.id from verse v join chapter c "
        "on c.id = v.chapter_id where c.edition_id = ?) and b.verse_id in (select v.id from verse v "
        "join chapter c on c.id = v.chapter_id where c.edition_id = ?)",
        (KJV, original),
    ):
        counts[kjv_verse, original_verse] += 1
    totals = Counter()
    for (kjv_verse, _), n in counts.items():
        totals[kjv_verse] += n

    parent = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for (kjv_verse, original_verse), n in counts.items():
        if n >= max(2, 0.2 * totals[kjv_verse]):
            parent[find(("k", kjv_verse))] = find(("o", original_verse))

    groups = defaultdict(lambda: ([], []))
    for node in list(parent):
        side, verse = node
        groups[find(node)][0 if side == "k" else 1].append(verse)
    units = []
    for kjv_list, original_list in groups.values():
        if kjv_list and original_list and len(kjv_list) <= 6 and len(original_list) <= 6:
            units.append((sorted(kjv_list), sorted(original_list)))
    return units


def run(db, original, workdir, evaluate):
    kjv_verses = load_words(db, KJV)
    original_verses = load_words(db, original)
    units = verse_units(db, original)

    existing = set(db.execute("select word_id, other_word_id from word_match"))
    held_out = set()
    if evaluate:
        rng = random.Random(1)
        held_out = {i for i in range(len(units)) if rng.random() < 0.1}

    sentences = []
    for i, (kjv_list, original_list) in enumerate(units):
        english = [t for v in kjv_list for t in kjv_verses[v]]
        foreign = [t for v in original_list for t in original_verses[v]]
        sentences.append((english, foreign))

    priors = Counter()
    for i, (english, foreign) in enumerate(sentences):
        if i in held_out:
            continue
        for word, key in english:
            for other, other_key in foreign:
                if (min(word, other), max(word, other)) in existing:
                    priors[other_key, key] += 1

    name = ORIGINALS[original]
    src_path = os.path.join(workdir, f"{name}.src")
    trg_path = os.path.join(workdir, f"{name}.trg")
    priors_path = os.path.join(workdir, f"{name}.priors")
    fwd_path = os.path.join(workdir, f"{name}.fwd")
    rev_path = os.path.join(workdir, f"{name}.rev")
    with open(src_path, "w") as src, open(trg_path, "w") as trg:
        for english, foreign in sentences:
            print(" ".join(k for _, k in foreign), file=src)
            print(" ".join(k for _, k in english), file=trg)
    with open(priors_path, "w") as f:
        for (src, trg), n in priors.items():
            print(f"LEX\t{src}\t{trg}\t{n * PRIOR_WEIGHT:g}", file=f)

    aligner = eflomal.Aligner()
    with open(src_path) as src, open(trg_path) as trg, open(priors_path) as pri:
        aligner.align(src, trg, links_filename_fwd=fwd_path, links_filename_rev=rev_path, priors_input=pri)

    proposed = []
    with open(fwd_path) as fwd, open(rev_path) as rev:
        for i, (f_line, r_line, (english, foreign)) in enumerate(zip(fwd, rev, sentences)):
            links = set(f_line.split()) & set(r_line.split())
            for link in links:
                s, t = map(int, link.split("-"))
                proposed.append((i, english[t][0], foreign[s][0]))

    if evaluate:
        gold = defaultdict(set)
        for i, english, foreign in ((i, *sentences[i]) for i in held_out):
            ids = {w for w, _ in foreign}
            for word, _ in english:
                for other in ids:
                    if (min(word, other), max(word, other)) in existing:
                        gold[word].add(other)
        judged = correct = 0
        for i, word, other in proposed:
            if i in held_out and word in gold:
                judged += 1
                correct += other in gold[word]
        recovered = sum(1 for i, w, o in proposed if i in held_out and o in gold.get(w, ()))
        total_gold = sum(len(v) for v in gold.values())
        print(f"{name}: precision {correct / judged:.3f} on {judged} judged links, "
              f"recall {recovered / total_gold:.3f} of {total_gold} held-out matches")
        return

    matched = set()
    for a, b in existing:
        matched.add(a)
        matched.add(b)
    added = 0
    for _, word, other in proposed:
        pair = (min(word, other), max(word, other))
        if pair in existing or (word in matched and other in matched):
            continue
        db.execute("insert or ignore into word_match (word_id, other_word_id) values (?, ?)", pair)
        added += 1
    db.commit()
    print(f"{name}: {len(units)} verse groups, {added} matches added")


def main():
    path, workdir = sys.argv[1], sys.argv[2]
    evaluate = "--evaluate" in sys.argv
    db = sqlite3.connect(path)
    for original in ORIGINALS:
        run(db, original, workdir, evaluate)


if __name__ == "__main__":
    main()

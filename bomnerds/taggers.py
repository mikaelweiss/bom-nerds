"""Runs spaCy, Stanza, and MorphAdorner over every English sentence, on our own words, and caches what each says about each word.

Each cache line is one sentence: [[word id, lemma, part of speech, head word id, dependency], ...].
spaCy and Stanza give universal parts of speech. MorphAdorner gives NUPOS tags and no parse.
"""

import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from .sentences import ENGLISH
from .sources import ROOT, fetch

CACHE = ROOT / "cache"
TAGGERS = ("spacy", "stanza", "morphadorner")
POSSESSIVE = re.compile(r"(.+?)(['’]s)$")


def sentences(db: sqlite3.Connection) -> list[list[tuple[int, str, str, str]]]:
    """Every English sentence as (word id, before, text, after) in reading order."""
    words = {}
    for id, before, text, after in db.execute(
        f"select id, before, text, after from word where edition_id in ({','.join('?' * len(ENGLISH))})", ENGLISH
    ):
        words[id] = (id, before, text, after)
    spans = db.execute(
        f"select s.first_word_id, s.last_word_id from sentence s join word w on w.id = s.first_word_id where w.edition_id in ({','.join('?' * len(ENGLISH))}) order by s.first_word_id",
        ENGLISH,
    )
    return [[words[id] for id in range(first, last + 1)] for first, last in spans]


def tokens(sentence) -> tuple[list[str], list[int]]:
    """Split possessives so taggers see "Lord" and "'s", and remember which word each token came from."""
    found, owners = [], []
    for index, (_, _, text, _) in enumerate(sentence):
        possessive = POSSESSIVE.match(text)
        parts = [possessive.group(1), possessive.group(2)] if possessive else [text]
        found.extend(parts)
        owners.extend([index] * len(parts))
    return found, owners


def to_words(sentence, owners, analyses) -> list[list]:
    """Keep each word's first token, and point heads at the words that own them."""
    result, seen = [], set()
    for token_index, (lemma, pos, head, dep) in enumerate(analyses):
        owner = owners[token_index]
        if owner in seen:
            continue
        seen.add(owner)
        head_id = sentence[owners[head]][0] if head is not None and owners[head] != owner else None
        result.append([sentence[owner][0], lemma, pos, head_id, dep])
    return result


def run_spacy(batch):
    import spacy
    from spacy.tokens import Doc

    nlp = spacy.load("en_core_web_trf")
    docs = []
    for sentence in batch:
        words, _ = tokens(sentence)
        docs.append(Doc(nlp.vocab, words=words, sent_starts=[True] + [False] * (len(words) - 1)))
    for sentence, doc in zip(batch, nlp.pipe(docs, batch_size=32)):
        _, owners = tokens(sentence)
        yield to_words(sentence, owners, [(t.lemma_, t.pos_, None if t.head.i == t.i else t.head.i, t.dep_) for t in doc])


def run_stanza(batch):
    import stanza
    import torch

    device = "mps" if torch.backends.mps.is_available() else None
    nlp = stanza.Pipeline("en", processors="tokenize,pos,lemma,depparse", package="default_accurate", tokenize_pretokenized=True, verbose=False, device=device)
    for start in range(0, len(batch), 200):
        chunk = batch[start:start + 200]
        doc = nlp([tokens(s)[0] for s in chunk])
        for sentence, parsed in zip(chunk, doc.sentences):
            _, owners = tokens(sentence)
            yield to_words(sentence, owners, [(w.lemma, w.upos, w.head - 1 if w.head else None, w.deprel) for w in parsed.words])
        # The GPU keeps every batch's buffers until told to let go, and grows until the system kills the run.
        del doc
        if device == "mps":
            torch.mps.empty_cache()


def run_morphadorner(batch):
    home = fetch("morphadorner-2.0.1.zip").parent / "morphadorner"
    if not home.exists():
        subprocess.run(["unzip", "-q", str(fetch("morphadorner-2.0.1.zip")), "-d", str(home)], check=True)
    with tempfile.TemporaryDirectory() as folder:
        source, output = Path(folder) / "in", Path(folder) / "out"
        source.mkdir()
        output.mkdir()
        lines = ["".join(b + t + a for _, b, t, a in s).replace("\n", " ") for s in batch]
        for number, start in enumerate(range(0, len(lines), 2000)):
            (source / f"{number:04}.txt").write_text("\n".join(lines[start:start + 2000]) + "\n", encoding="utf-8")
        data = home / "data"
        subprocess.run(
            ["java", "-Xmx6g", "-Xss2m", "-cp", f"{home}/bin:{home}/dist/*:{home}/lib/*", "edu.northwestern.at.morphadorner.MorphAdorner",
             "-p", str(home / "emeplaintext.properties"), "-l", str(data / "emelexicon.lex"), "-t", str(data / "emetransmat.mat"),
             "-u", str(data / "emesuffixlexicon.lex"), "-a", str(data / "ememergedspellingpairs.tab"), "-s", str(data / "standardspellings.txt"),
             "-w", str(data / "spellingsbywordclass.txt"), "-o", str(output), *sorted(str(p) for p in source.glob("*.txt"))],
            check=True, cwd=home, stdout=subprocess.DEVNULL,
        )
        adorned = []
        for number in range(len(list(source.glob("*.txt")))):
            path = next(output.glob(f"{number:04}*"))
            adorned.extend(line.split("\t") for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    yield from align_morphadorner(batch, lines, adorned)


def align_morphadorner(batch, lines, adorned):
    """MorphAdorner tokenizes on its own, so give each word the token that covers exactly its characters."""
    position = 0
    for sentence, line in zip(batch, lines):
        starts = {}
        offset = 0
        for id, before, text, after in sentence:
            offset += len(before)
            starts[offset] = (id, text)
            offset += len(text) + len(after)
        result = []
        cursor = 0
        while position < len(adorned):
            token, _, pos, _, lemma = adorned[position][:5]
            found = line.find(token, cursor)
            position += 1
            if found < 0:
                continue
            cursor = found + len(token)
            word = starts.get(found)
            if word and word[1] == token:
                result.append([word[0], lemma, pos, None, None])
            if cursor >= len(line.rstrip()):
                break
        yield result


def clear(db: sqlite3.Connection):
    pass


def run(db: sqlite3.Connection):
    for name in TAGGERS:
        tag(name, db)


def tag(name: str, db: sqlite3.Connection):
    """Tag every sentence the cache lacks. The cache survives rebuilds, because a full run takes hours."""
    CACHE.mkdir(exist_ok=True)
    path = CACHE / f"{name}.jsonl"
    done = complete_lines(path)
    every = sentences(db)
    with open(path, encoding="utf-8") if path.exists() else open(os.devnull) as cached:
        for line, sentence in zip(cached, every):
            cached = json.loads(line)
            if cached and not sentence[0][0] <= cached[0][0] <= cached[-1][0] <= sentence[-1][0]:
                sys.exit(f"{path} was made from different sentences. Delete it to tag again.")
    batch = every[done:]
    if not batch:
        return
    tagger = {"spacy": run_spacy, "stanza": run_stanza, "morphadorner": run_morphadorner}[name]
    with open(path, "a", encoding="utf-8") as out:
        for count, result in enumerate(tagger(batch), done + 1):
            out.write(json.dumps(result, ensure_ascii=False) + "\n")
            if count % 200 == 0:
                out.flush()
            if count % 1000 == 0:
                print(f"{name}: {count} sentences", flush=True)


def complete_lines(path: Path) -> int:
    """Count the finished lines, cutting off a last line a stopped run left half written."""
    if not path.exists():
        return 0
    data = path.read_bytes()
    finished = data[:data.rfind(b"\n") + 1]
    if len(finished) != len(data):
        path.write_bytes(finished)
    return finished.count(b"\n")


if __name__ == "__main__":
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    from .text import DATABASE

    tag(sys.argv[1], sqlite3.connect(DATABASE))

import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from .sources import ROOT, fetch
from .text import WORDS, english_editions, marks

CACHE = ROOT / "cache"
TAGGERS = ("spacy", "stanza", "morphadorner")
POSSESSIVE = re.compile(r"(.+?)(['’]s)$")


def sentences(db: sqlite3.Connection) -> list[list[tuple[int, str, str, str]]]:
    english = english_editions(db)
    words = list(db.execute(
        f"select w.sequence, w.id, w.before, w.text, w.after from {WORDS} where c.edition_id in ({marks(english)}) order by w.sequence", english
    ))
    index = {word[0]: i for i, word in enumerate(words)}
    spans = db.execute(
        f"select w.sequence, l.sequence from sentence s join word l on l.id = s.last_word_id, {WORDS} "
        f"where w.id = s.first_word_id and c.edition_id in ({marks(english)}) order by w.sequence",
        english,
    )
    return [[word[1:] for word in words[index[first]:index[last] + 1]] for first, last in spans]


def tokens(sentence) -> tuple[list[str], list[int]]:
    found, owners = [], []
    for index, (_, _, text, _) in enumerate(sentence):
        possessive = POSSESSIVE.match(text)
        parts = [possessive.group(1), possessive.group(2)] if possessive else [text]
        found.extend(parts)
        owners.extend([index] * len(parts))
    return found, owners


def to_words(sentence, owners, analyses) -> list[list]:
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
    CACHE.mkdir(exist_ok=True)
    path = CACHE / f"{name}.jsonl"
    done = complete_lines(path)
    every = sentences(db)
    with open(path, encoding="utf-8") if path.exists() else open(os.devnull) as cached:
        for line, sentence in zip(cached, every):
            cached = json.loads(line)
            if not {word[0] for word in cached} <= {word[0] for word in sentence}:
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

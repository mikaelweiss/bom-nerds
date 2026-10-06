#!/usr/bin/env python3
import argparse
import json
import re
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import tag

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"
QUESTION_BUDGET = 40_000
STATE_BUDGET = 24_000

SINGULAR = {"he", "him", "his", "himself", "she", "her", "hers", "herself", "it", "its", "itself", "i", "me", "my", "mine", "myself",
            "thou", "thee", "thy", "thine", "thyself", "who", "whom", "whose", "which"}
PLURAL = {"they", "them", "their", "theirs", "themselves", "we", "us", "our", "ours", "ourselves", "ye", "you", "your", "yours",
          "yourselves", "these", "those"}
NOUNS = {"father", "mother", "son", "sons", "daughter", "daughters", "brother", "brothers", "brethren", "sister", "sisters",
         "wife", "wives", "husband", "children", "king", "kings", "queen", "prince", "princes", "priest", "priests", "prophet",
         "prophets", "people", "servant", "servants", "parents", "family", "household", "rulers", "judges", "enemies"}
GROUP_WORDS = PLURAL | {"sons", "daughters", "brothers", "brethren", "sisters", "wives", "children", "kings", "princes", "priests",
                        "prophets", "people", "servants", "parents", "family", "household", "rulers", "judges", "enemies"}


def tokens(value) -> int:
    return len(json.dumps(value)) // 4


def ask(state, questions: dict) -> tuple[dict, dict]:
    key = subprocess.run(["pass", "typesafe-ai-api-key"], capture_output=True, text=True, check=True).stdout.splitlines()[0]
    body = json.dumps({"model": MODEL, "state": state, "questions": questions}).encode()
    for attempt in range(6):
        request = urllib.request.Request(ENDPOINT, body, {"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                result = json.loads(response.read())
                return result["answers"], result["usage"]
        except urllib.error.HTTPError as error:
            detail = error.read().decode()
            if error.code in (429, 500, 502, 503, 504) and attempt < 5:
                time.sleep(float(error.headers.get("retry-after") or 2 ** attempt))
                continue
            sys.exit(f"TypeSafe error {error.code}: {detail}")
    sys.exit("TypeSafe kept failing")


def ask_all(state, questions: dict) -> tuple[dict, dict]:
    """Asks every question over one state, split into as few requests as the context budget allows."""
    batches, batch, size = [], {}, 0
    for qid, question in questions.items():
        cost = tokens(question)
        if batch and size + cost > QUESTION_BUDGET:
            batches.append(batch)
            batch, size = {}, 0
        batch[qid] = question
        size += cost
    if batch:
        batches.append(batch)
    answers, usage = {}, {"input_tokens": 0, "output_tokens": 0, "requests": 0}
    with ThreadPoolExecutor(8) as pool:
        for got, used in pool.map(lambda b: ask(state, b), batches):
            answers.update(got)
            usage["input_tokens"] += used.get("input_tokens", 0)
            usage["output_tokens"] += used.get("output_tokens", 0)
            usage["requests"] += 1
    return answers, usage


def verse_text(p: tag.Passage, c: int, v: int, mark: tuple[int, int] | None = None) -> str:
    out = []
    for i, (_, text, before, after) in enumerate(p.words[(c, v)]):
        if mark and i == mark[0]:
            text = "[[" + text
        if mark and i == mark[1]:
            text = text + "]]"
        out.append(f"{before}{text}{after}")
    return "".join(out).strip()


def describe(db: sqlite3.Connection, ref: str, new: dict) -> str:
    if ref in new:
        t, name, description = new[ref]
        return f"{name} ({description})"
    name, description = db.execute("select name, description from entity where id = ?", (int(ref[1:]),)).fetchone()
    return f"{name} ({description})"


def judge(db: sqlite3.Connection, p: tag.Passage) -> tuple[str, dict, dict]:
    panel = json.loads((tag.PANEL / tag.key_path(p.label).stem).with_suffix(".json").read_text())
    key_text = tag.key_path(p.label).read_text()
    structure = [line for line in key_text.splitlines() if line.startswith("E ")] + panel["definitions"]
    named = tag.lists(db)
    kinds = {v: k for k, v in named["kind"].items()}
    modes = {v: k for k, v in named["mode"].items()}
    systems = {v: k for k, v in named["system"].items()}
    questions = {}
    for item in panel["items"]:
        a = tag.parse(db, p, "\n".join(structure + [item["line"]]))
        new = {k: v for k, v in a.entities.items() if k.startswith("+")}
        d = lambda ref: describe(db, ref, new)
        span = lambda first, last: tag.span_text(p, first, last)
        if a.mentions:
            first, last, e, kind = next(iter(a.mentions))
            text = (f"In {span(first, last)}, do the quoted words refer to {d(e)}?" if kind == 1 else
                    f"Is the passage {span(first, last)} about {d(e)}, so that a reader looking up {d(e).split(' (')[0]} should find it?")
        elif a.relationships:
            (s, k, o), spans = next(iter(a.relationships.items()))
            text = f"Does the passage state that {d(s)} is {kinds[k]} {d(o)}? The cited evidence is " + "; ".join(span(*x) for x in spans) + "."
        elif a.speeches:
            speaker, mode, listeners, first, last, through = a.speeches[0]
            text = (f"Are exactly the words {span(first, last)} the {modes[mode]} words of {d(speaker)}"
                    + (f", spoken to {', '.join(d(x) for x in listeners)}" if listeners else "")
                    + (f", delivered through {d(through)}" if through else "") + "?")
        elif a.journeys:
            traveler, start, end, days, first, last = a.journeys[0]
            text = (f"Do the words {span(first, last)} tell of {d(traveler)} traveling" + (f" from {d(start)}" if start else "")
                    + f" to {d(end)}" + (f" in {days:g} days" if days else "") + "?")
        elif a.dates:
            where, system, start, end, _ = a.dates[0]
            target = d(where) if isinstance(where, str) else span(*where)
            text = f"Is {target} dated from {tag.ymd(*start)} to {tag.ymd(*end)} in the counting system {systems[system]}?"
        else:
            continue
        questions[str(item["n"])] = {"type": "noul", "instructions": text,
                                     "criteria": {"true": "The tag is correct under `rules` and belongs in the passage's tags.",
                                                  "false": "The tag is wrong, or the rules say to leave it out."}}
    state = {"rules": tag.RULES.read_text(), "passage": [f"{c}:{v} {verse_text(p, c, v)}" for _, c, v in p.verses]}
    answers, usage = ask_all(state, questions)
    probabilities = {n: answers[n]["noul"] for n in questions}
    verdicts = "\n".join(f"{n} {'yes' if probabilities[n] >= 0.5 else 'no'}" for n in questions) + "\n"
    return verdicts, probabilities, usage


DEFINITIONS = {
    "Jesus Christ": "Jehovah, the premortal and mortal Christ, the Son. The LORD and Jehovah refer to him unless the passage points to the Father.",
    "God the Father": "Elohim, the Father of Jesus Christ. The LORD, Lord, or God is the Father where the passage shows him as the Father of Christ: "
                      "he speaks to the Son, begets, anoints, or sets up the Son as king, seats him at his right hand, or sends the Messiah. God alone is usually the Father.",
    "Holy Ghost": "The Spirit, the third member of the Godhead.",
}
POSSESSIVES = {"my", "thy", "thine", "his", "her", "our", "your", "their", "mine"}
DIVINE = {"LORD", "GOD", "JAH", "JEHOVAH", "Jehovah", "Lord", "God"}


def spans(p: tag.Passage, names: set[str], main: set[str]) -> list[tuple[int, int, int, str]]:
    """Every name, pronoun, and person noun phrase in the passage, as (verse index, first word, last word, kind)."""
    lower = {n.lower() for n in names if n not in main or " " in n}
    longest = max((len(n.split()) for n in names), default=1)
    found = []
    for index, (_, c, v) in enumerate(p.verses):
        words = [re.sub(r"[^\w'’-]", "", w[1]) for w in p.words[(c, v)]]
        bare = [w.lower().removesuffix("’s").removesuffix("'s") for w in words]
        i = 0
        while i < len(words):
            for n in range(min(longest, len(words) - i), 0, -1):
                phrase = " ".join(words[i:i + n])
                if phrase in names and phrase[:1].isupper() or phrase in DIVINE or phrase.lower() in lower:
                    first = i - 1 if phrase.lower() in lower and i and bare[i - 1] in POSSESSIVES | {"ye"} else i
                    if first < i and bare[first] != "ye":
                        found.append((index, first, first, "group" if bare[first] in GROUP_WORDS else "one"))
                    found.append((index, first, i + n - 1, "group" if bare[i + n - 1] in GROUP_WORDS else "name"))
                    i += n
                    break
            else:
                if bare[i] in SINGULAR | PLURAL:
                    found.append((index, i, i, "group" if bare[i] in GROUP_WORDS else "one"))
                elif bare[i] in NOUNS and words[i].islower() or bare[i] == "son":
                    first = i - 1 if i and bare[i - 1] in POSSESSIVES | {"ye"} else i
                    last = i
                    if i + 2 < len(words) and bare[i + 1] == "of":
                        last = i + 3 if bare[i + 2] == "the" and i + 3 < len(words) else i + 2
                    if first < i and bare[first] != "ye":
                        found.append((index, first, first, "one" if bare[first] not in GROUP_WORDS else "group"))
                    found.append((index, first, last, "group" if bare[i] in GROUP_WORDS else "one"))
                    i = last
                i += 1
    return found


def tag_mentions(db: sqlite3.Connection, p: tag.Passage, window: int = 3) -> tuple[str, list[dict], dict]:
    key = tag.parse(db, p, tag.key_path(p.label).read_text()) if tag.key_path(p.label).exists() else tag.Answer()
    new = {ref: e for ref, e in key.entities.items() if ref.startswith("+") and not re.match(r"\+r\d+\.", ref)}
    pool = tag.candidates(db, p, tag.current(db, p))
    names = {}
    for i in pool:
        for n, in db.execute("select name from entity where id = ? union select name from entity_name where entity_id = ?", (i, i)):
            names.setdefault(n, set()).add(f"#{i}")
    for ref, (_, name, _) in new.items():
        names.setdefault(name, set()).add(ref)
    for ref, name, _ in key.names:
        names.setdefault(name, set()).add(ref)
    main = {n for n, in db.execute("select name from entity")} | {e[1] for e in new.values()}
    found = spans(p, set(names), main)
    godhead = [f"#{i}" for i, in db.execute(f"select id from entity where name in ({','.join('?' * len(tag.GODHEAD))})", tag.GODHEAD)]
    label = lambda ref: f"{(new[ref][1] if ref in new else db.execute('select name from entity where id = ?', (int(ref[1:]),)).fetchone()[0])} {ref}"
    lines, details = [], []
    usage = {"input_tokens": 0, "output_tokens": 0, "requests": 0}
    for index, (_, c, v) in enumerate(p.verses):
        nearby = set(godhead) | set(new)
        for j in range(max(0, index - window), min(len(p.verses), index + window + 1)):
            text = " " + " ".join(re.sub(r"[^\w'’-]", "", w[1]) for w in p.words[p.verses[j][1:]]) + " "
            nearby |= {ref for n, refs in names.items() if f" {n} " in text or n not in main and f" {n.lower()} " in text.lower() for ref in refs}
        options = sorted(nearby, key=label)[:254]
        context = [f"{p.verses[j][1]}:{p.verses[j][2]} {verse_text(p, *p.verses[j][1:])}"
                   for j in range(max(0, index - window), min(len(p.verses), index + window + 1))]
        entity_list = [f"{label(ref)}: {describe(db, ref, new)}" for ref in options]
        state = {"rules": tag.RULES.read_text(), "context": context, "entities": entity_list}
        questions = {}
        here = [s for s in found if s[0] == index]
        for n, (_, a, b, kind) in enumerate(here):
            sentence = f"{c}:{v} {verse_text(p, c, v, (a, b))}"
            questions[f"{n}"] = {"type": "choice", "instructions": {
                "sentence": sentence,
                "question": "Which entity in `entities` do the words in [[double brackets]] in `sentence` refer to, read in `context` and under `rules`?"},
                "criteria": {**{label(ref): DEFINITIONS.get(label(ref).rsplit(" ", 1)[0]) for ref in options},
                             "none": "The words refer to no specific entity, or to one not in `entities`."}}
            if kind == "group":
                for ref in options:
                    questions[f"{n}|{ref}"] = {"type": "noul", "instructions": {
                        "sentence": sentence,
                        "question": f"Read in `context`, are the people or things that the words in [[double brackets]] in `sentence` refer to made up of, or do they include, {label(ref)}?"}}
        if not questions:
            continue
        answers, used = ask_all(state, questions)
        for k in usage:
            usage[k] += used[k]
        for n, (_, a, b, kind) in enumerate(here):
            first, last = p.words[(c, v)][a][0], p.words[(c, v)][b][0]
            choice = answers[f"{n}"]
            chosen = [] if choice["choice"] == "none" else [choice["choice"].rsplit(" ", 1)[1]]
            if kind == "group":
                members = [ref for ref in options if answers[f"{n}|{ref}"]["noul"] >= 0.5]
                chosen = members or chosen
            for ref in chosen:
                lines.append(f"M {tag.span_text(p, first, last)} {ref}")
            details.append({"span": tag.span_text(p, first, last), "kind": kind, "chosen": chosen, "confidence": choice["confidence"],
                            "top": sorted(choice["probabilities"].items(), key=lambda x: -x[1])[:3]})
    definitions = [tag.entity_definition(ref, e, tag.lists(db)) for ref, e in new.items()]
    return "\n".join(definitions + lines) + "\n", details, usage


def main():
    parser = argparse.ArgumentParser(description="Use TypeSafe's Jev to judge disputed tags and to tag mentions.")
    parser.add_argument("--db", type=Path, default=tag.DATABASE)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("judge", help="judge the passage's disputed tags").add_argument("passage")
    commands.add_parser("mentions", help="tag every name, pronoun, and person noun in the passage").add_argument("passage")
    args = parser.parse_args()
    db = sqlite3.connect(args.db)
    p = tag.passage(db, args.passage)
    stem = tag.key_path(p.label).stem
    started = time.monotonic()
    if args.command == "judge":
        verdicts, probabilities, usage = judge(db, p)
        out = (tag.PANEL / stem).with_suffix(".jev.verdicts.txt")
        out.write_text(verdicts)
        out.with_suffix(".json").write_text(json.dumps(probabilities, indent=1))
        print(f"{out} ({time.monotonic() - started:.0f}s, {usage})")
    else:
        answer, details, usage = tag_mentions(db, p)
        tag.record(db, p, "jev:mentions", answer, usage, time.monotonic() - started)
        (tag.RUNS / f"jev-mentions-{stem}.json").write_text(json.dumps(details, indent=1))


if __name__ == "__main__":
    main()

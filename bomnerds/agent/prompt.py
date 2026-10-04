"""The text an agent reads to do one job in one role."""

import sqlite3

from .jobs import CLI, Job, Jobs, agreement, already, line

POINTING = """## Pointing at text

Point at words by verse and quote. Copy the quote exactly from the verse. The CLI finds the words, so never count them.
Write verse references the way people do: `1 Nephi 3:7`, `D&C 76:22`. A passage takes one of these shapes:

{ "verse": "1 Nephi 3:7", "quote": "Nephi" }                  words inside one verse
{ "verse": "1 Nephi 3:7", "quote": "I", "in": "I will go" }   words that appear more than once in the verse: `in` is longer words that appear once and hold the quote once
{ "verse": "1 Nephi 3:7" }                                    a whole verse
{ "from": "Alma 32:21", "to": "Alma 32:43" }                  whole verses
{ "from": "Mosiah 2:9", "to": "Mosiah 5:15", "starts": "My brethren", "ends": "Amen" }   starting and ending partway through verses
{ "chapter": "Alma 32" }                                      a whole chapter

"starts" and "ends" take "starts_in" and "ends_in" the way "quote" takes "in", when their words appear more than once in the verse."""

ROLE = {
    "a": "Answer on your own. Another agent answers the same job separately, and only the tags you both give are stored without review.",
    "b": "Answer on your own. Another agent answers the same job separately, and only the tags you both give are stored without review.",
    "writer": "Write the answer. An agent from another model family checks it against the scripture and corrects it.",
    "decider": (
        "Two agents answered this job on their own. The tags under Agreed are stored as they are. "
        "They differ on the tags under each run below. Check each against the text and the instructions. "
        "Answer with every tag to store besides the agreed ones: keep a tag from either run, correct it, or leave it out. "
        "Your answer is checked together with the agreed tags, so a problem's item number past the end of your answer points at an agreed tag."
    ),
    "checker": (
        "Another agent wrote the answer under Writer's answer. Check every item against the scripture and the instructions: "
        "fix what is wrong, remove what does not belong, and add what is missing. Answer with the whole corrected list."
    ),
}


def prompt(db: sqlite3.Connection, job: Job, role: str) -> str:
    layer = job.layer
    sections = [
        f"# Job {job.id}, role {role}",
        layer.instructions.strip(),
        ROLE[role],
        *([POINTING] if layer.points else []),
        answering(job, role),
    ]
    taken = layer.already_shown(db, already(db, job))
    if taken:
        sections.append("## Already tagged\n\nThese are settled. Leave them out of your answer.\n\n" + "\n".join(line(t) for t in taken))
    if role == "decider":
        agreed, first, second = agreement(db, job)
        sections.append("## Agreed\n\n" + ("\n".join(line(layer.render(db, t)) for t in agreed) or "Nothing."))
        sections.append("## Only the first run\n\n" + ("\n".join(line(layer.render(db, t)) for t in first) or "Nothing."))
        sections.append("## Only the second run\n\n" + ("\n".join(line(layer.render(db, t)) for t in second) or "Nothing."))
    if role == "checker":
        written = layer.parse(db, job.scope, job.answer("writer"))
        sections.append("## Writer's answer\n\n" + "\n".join(line(layer.render(db, t)) for t in written))
    sections.append("## Context\n\n" + layer.context(db, Jobs, job.scope))
    return "\n\n".join(sections) + "\n"


def answering(job: Job, role: str) -> str:
    text = f"""## Answering

Run every command from the repository root. Write your answer as a JSON array to a file, then:

{CLI} check {job.id} --role {role} answer.json    checks it and lists every problem, changing nothing
{CLI} submit {job.id} --role {role} answer.json   stores it, once check passes"""
    if not job.layer.points:
        return text
    return text + f"""

Look things up as you work:

{CLI} show "1 Nephi 3"                    a chapter with every tag placed on it so far
{CLI} search "Nephi" --book "1 Nephi"     entities whose names match, the book's own first
{CLI} missing {job.id} --name "Zoram" --type person --description "Servant of Laban who joins Nephi." --verse "1 Nephi 4:35"
                                          reports an entity the list lacks. Leave its tags out of your answer"""

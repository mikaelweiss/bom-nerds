"""Give a headword and part of speech to every English word the taggers left bare."""

import sqlite3
import sys
from collections import Counter, defaultdict

# Forms with no tagged occurrence anywhere: archaic, compound, borrowed, or Hebrew letters.
UNSEEN = {
    "brasen": ("brasen", "Adjective"), "twined": ("twine", "Verb"), "intreated": ("intreat", "Verb"),
    "proceedings": ("proceeding", "Noun"), "king-men": ("king-man", "Noun"), "astonied": ("astony", "Verb"),
    "forgat": ("forget", "Verb"), "shorn": ("shear", "Verb"), "mr": ("Mr", "Noun"), "graffed": ("graff", "Verb"),
    "ax": ("ax", "Noun"), "stablished": ("stablish", "Verb"), "people’s": ("people", "Noun"),
    "calledst": ("call", "Verb"), "wading": ("wade", "Verb"), "us-ward": ("us-ward", "Adverb"),
    "pourtrayed": ("pourtray", "Verb"), "outstretched": ("outstretched", "Adjective"), "lothed": ("lothe", "Verb"),
    "lien": ("lie", "Verb"), "forgettest": ("forget", "Verb"), "forbare": ("forbear", "Verb"),
    "desiredst": ("desire", "Verb"), "whited": ("white", "Verb"), "unnoticed": ("unnoticed", "Adjective"),
    "task-masters": ("task-master", "Noun"), "stoning": ("stone", "Verb"), "stammering": ("stammer", "Verb"),
    "shewedst": ("shew", "Verb"), "seraphim": ("seraph", "Noun"), "selfwilled": ("selfwilled", "Adjective"),
    "sabachthani": ("sabachthani", "Verb"), "receivedst": ("receive", "Verb"), "ravin": ("ravin", "Noun"),
    "plaistered": ("plaister", "Verb"), "pilled": ("pill", "Verb"), "onti": ("onti", "Noun"), "oiled": ("oil", "Verb"),
    "melting": ("melt", "Verb"), "lovedst": ("love", "Verb"), "lefthanded": ("lefthanded", "Adjective"),
    "lama": ("lama", "Adverb"), "forsookest": ("forsake", "Verb"), "etc": ("etc", "Adverb"), "blest": ("bless", "Verb"),
    "all-searching": ("all-searching", "Adjective"), "youward": ("youward", "Adverb"), "wove": ("weave", "Verb"),
    "workmen’s": ("workman", "Noun"), "wine-presses": ("wine-press", "Noun"), "vowedst": ("vow", "Verb"),
    "ungirded": ("ungird", "Verb"), "thee-ward": ("thee-ward", "Adverb"), "terrifiest": ("terrify", "Verb"),
    "ten’s": ("ten", "Numeral"), "sweetsmelling": ("sweetsmelling", "Adjective"), "summum": ("summum", "Adjective"),
    "succored": ("succor", "Verb"), "subduedst": ("subdue", "Verb"), "strowed": ("strow", "Verb"),
    "strake": ("strike", "Verb"), "sixtyfold": ("sixtyfold", "Adverb"), "satisfiest": ("satisfy", "Verb"),
    "rue": ("rue", "Noun"), "repairer": ("repairer", "Noun"), "refusedst": ("refuse", "Verb"),
    "rattling": ("rattle", "Verb"), "pruning-hooks": ("pruning-hook", "Noun"), "propria": ("propria", "Adjective"),
    "pricking": ("pricking", "Adjective"), "pransing": ("pranse", "Verb"), "plow-shares": ("plow-share", "Noun"),
    "pining": ("pine", "Verb"), "partakest": ("partake", "Verb"), "overpowering": ("overpower", "Verb"),
    "neighing": ("neighing", "Noun"), "maul": ("maul", "Noun"), "marishes": ("marish", "Noun"), "magna": ("magna", "Adjective"),
    "layedst": ("lay", "Verb"), "languishing": ("languish", "Verb"), "laidst": ("lay", "Verb"),
    "judgment-seats": ("judgment-seat", "Noun"), "jesuites": ("Jesuite", "Proper noun"), "jah-oh-eh": ("Jah-oh-eh", "Proper noun"),
    "ites": ("ite", "Noun"), "intreaties": ("intreaty", "Noun"), "gushing": ("gush", "Verb"),
    "graveclothes": ("graveclothes", "Noun"), "gendered": ("gender", "Verb"), "galilaean": ("Galilaean", "Proper noun"),
    "foundest": ("find", "Verb"), "foresworn": ("forswear", "Verb"), "followedst": ("follow", "Verb"),
    "fetcht": ("fetch", "Verb"), "executedst": ("execute", "Verb"), "ephraimite": ("Ephraimite", "Proper noun"),
    "enish-go-on-dosh": ("Enish-go-on-dosh", "Proper noun"), "ear-rings": ("ear-ring", "Noun"), "dissolvest": ("dissolve", "Verb"),
    "dismaying": ("dismaying", "Noun"), "deseret": ("deseret", "Noun"), "deeded": ("deed", "Verb"), "cumi": ("cumi", "Verb"),
    "crisping": ("crisping", "Adjective"), "cor": ("cor", "Noun"), "charta": ("charta", "Noun"), "can't": ("can", "Verb"),
    "bonum": ("bonum", "Noun"), "anise": ("anise", "Noun"), "adieu": ("adieu", "Interjection"), "abhorring": ("abhorring", "Noun"),
    "3d": ("3d", "Numeral"),
}
HEBREW_LETTERS = set("אבגדהוזחטיכלמנסעפצקרשת")


def main(path):
    db = sqlite3.connect(path)
    pos_id = dict(db.execute("select name, id from part_of_speech"))
    english = db.execute("select id from language where iso_code = 'en'").fetchone()[0]
    english_editions = {e for (e,) in db.execute("select id from edition where language_id = ?", (english,))}

    rows = db.execute(
        "select w.id, w.verse_id, w.position, w.text, w.headword_id, w.part_of_speech_id, c.edition_id "
        "from word w join verse v on v.id = w.verse_id join chapter c on c.id = v.chapter_id order by w.sequence"
    ).fetchall()
    rows = [r for r in rows if r[6] in english_editions]

    by_form = defaultdict(Counter)
    by_form_next = defaultdict(Counter)
    for i, (_, verse, _, text, headword, pos, _) in enumerate(rows):
        if headword is None:
            continue
        form = text.lower()
        by_form[form][(headword, pos)] += 1
        if i + 1 < len(rows) and rows[i + 1][1] == verse:
            by_form_next[form, rows[i + 1][3].lower()][(headword, pos)] += 1

    headword_id = {t: i for i, t in db.execute("select id, text from headword where language_id = ? and strongs is null", (english,))}

    def headword_for(text):
        if text not in headword_id:
            headword_id[text] = db.execute(
                "insert into headword (language_id, text) values (?, ?)", (english, text)
            ).lastrowid
        return headword_id[text]

    filled = Counter()
    for i, (word, verse, _, text, headword, _, _) in enumerate(rows):
        if headword is not None:
            continue
        form = text.lower()
        following = rows[i + 1][3].lower() if i + 1 < len(rows) and rows[i + 1][1] == verse else None
        context = by_form_next.get((form, following))
        if context and sum(context.values()) >= 3:
            choice, how = context.most_common(1)[0][0], "context"
        elif form in by_form:
            choice, how = by_form[form].most_common(1)[0][0], "form"
        elif form in UNSEEN:
            lemma, pos = UNSEEN[form]
            choice, how = (headword_for(lemma), pos_id[pos]), "table"
        elif text in HEBREW_LETTERS:
            choice, how = (headword_for(text), pos_id["Noun"]), "letter"
        else:
            raise SystemExit(f"no headword rule for {text!r}")
        db.execute("update word set headword_id = ?, part_of_speech_id = ? where id = ?", (*choice, word))
        filled[how] += 1

    db.commit()
    print(dict(filled))


if __name__ == "__main__":
    main(sys.argv[1])

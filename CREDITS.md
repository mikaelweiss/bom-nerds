# Credits

The dataset is licensed under [CC BY 4.0](LICENSE-DATA.txt). The code is licensed under [Apache 2.0](LICENSE.md).

The dataset is built from the sources below. Each is reshaped into this project's schema: split into words, matched to other editions, and tagged. Anyone sharing the dataset must keep these credits.

| Source | License | Attribution |
|---|---|---|
| [bcbooks/scriptures-json](https://github.com/bcbooks/scriptures-json): Book of Mormon, Doctrine and Covenants, and Pearl of Great Price text | Public domain | None required. Thanks to bcbooks. |
| [eBible.org eng-kjv2006](https://ebible.org/kjv/): King James Version text with Strong's numbers | Public domain, except in the United Kingdom, where the Crown holds printing rights | None required. Thanks to eBible.org. |
| [MACULA Hebrew](https://github.com/Clear-Bible/macula-hebrew/) © 2022-2024 Biblica, Inc. | CC BY 4.0 | "MACULA Hebrew Linguistic Datasets, available at https://github.com/Clear-Bible/macula-hebrew/" |
| Westminster Leningrad Codex, from the Groves Center, through MACULA Hebrew | Public domain | None required. |
| Westminster Hebrew Syntax © 1991-2018 The J. Alan Groves Center for Advanced Biblical Research, through MACULA Hebrew | CC BY 4.0 | "Westminster Hebrew Syntax, The J. Alan Groves Center for Advanced Biblical Research" |
| [Open Scriptures Hebrew Bible](https://hb.openscriptures.org) morphology, through MACULA Hebrew | CC BY 4.0 | "Open Scriptures Hebrew Bible, https://hb.openscriptures.org" |
| [MACULA Greek](https://github.com/Clear-Bible/macula-greek/) © 2022-2024 Biblica, Inc. | CC BY 4.0 | "MACULA Greek Linguistic Datasets, available at https://github.com/Clear-Bible/macula-greek/" |
| [SBL Greek New Testament](https://github.com/LogosBible/SBLGNT) © 2010 Society of Biblical Literature and Logos Bible Software, through MACULA Greek | CC BY 4.0 | "SBL Greek New Testament, © 2010 Society of Biblical Literature and Logos Bible Software" |
| Cherith Glosses for the Hebrew Old Testament © 2022 and for the Greek New Testament © 2023, by Andi Wu, Cherith Analytics, through MACULA | CC BY 4.0 | "Cherith Glosses, by Andi Wu, Cherith Analytics" |
| [STEPBible TIPNR and TVTMS](https://github.com/STEPBible/STEPBible-Data), Tyndale House, Cambridge | CC BY 4.0 | "STEP Bible", linked to [www.STEPBible.org](https://www.stepbible.org) |
| [OpenBible.info](https://www.openbible.info) cross-references and Bible geocoding data | CC BY 4.0 | "OpenBible.info", linked to [www.openbible.info](https://www.openbible.info) |

MACULA's United Bible Societies columns (`domain`, `ln`, `sdbh`, `lexdomain`, `coredomain`, `contextualdomain`) are used with permission rather than under CC BY, so the dataset leaves them out.

English headwords, parts of speech, and parses are produced with [spaCy](https://spacy.io) (MIT), [Stanza](https://stanfordnlp.github.io/stanza/) (Apache 2.0), and [MorphAdorner](https://morphadorner.northwestern.edu) (NCSA open source license).

# Tagging status

## Done

- Book of Mormon, Doctrine and Covenants, and Pearl of Great Price: every chapter tagged by Opus with the `chapter-tagger` agent, and duplicate entities merged.
- Bible: open datasets imported (see CREDITS.md), and 940 of 1,190 chapters tagged by Opus on top of them.

## Left

1. Tag the 250 Bible chapters below with the `chapter-tagger` agent:
   - 1 Chronicles 10-20
   - 1 Corinthians 1-5
   - 1 John 1-5
   - 1 Kings 1
   - 2 John 1
   - 2 Samuel 15-24
   - 3 John 1
   - Esther 1-10
   - Exodus 16-29
   - Ezekiel 19-25
   - Haggai 1-2
   - Isaiah 53-66
   - Jeremiah 1-5
   - Job 1-10
   - Joel 4
   - Jude 1
   - Judges 4-8
   - Luke 14-19
   - Nehemiah 10-13
   - Proverbs 1-8
   - Psalms 72-150
   - Revelation 1-22
   - Romans 5-16
   - Zechariah 1-14
   - Zephaniah 2-3
2. Merge the duplicate entities the parallel taggers created. Entities above #11167 were created during the Bible pass.
3. Fix known errors:
   - Jeremiah 27:1 names Zedekiah where the text says Jehoiakim.
   - Hori is described as a people.
   - Generic titles such as "father" and "my people" are stored as other names.

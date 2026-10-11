#!/usr/bin/env python3
# Packs the AI agent transcripts added since the last release into
# conversations.zip, redacts secrets, and writes the cumulative byte offsets
# to conversations-manifest.json so the next release picks up where this one
# stopped.
# Usage: conversations.py <repo root> <dist dir>
import json
import os
import re
import subprocess
import sys
import zipfile
from collections import Counter
from pathlib import Path

REPO = 'mikaelweiss/standard-works-corpus'
MANIFEST = 'conversations-manifest.json'
# Agents file transcripts under the folder they ran in, and the repo was built in this folder first.
LEGACY_ROOTS = [Path.home() / 'code/bom-nerds']

SECRET_PATTERNS = {name: re.compile(pattern, re.S) for name, pattern in {
    'anthropic key': r'\bsk-ant-[A-Za-z0-9_-]{20,}',
    'openai key': r'\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}',
    'github token': r'\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}|\bgithub_pat_[A-Za-z0-9_]{40,}',
    'aws key': r'\bAKIA[0-9A-Z]{16}',
    'google key': r'\bAIza[0-9A-Za-z_-]{35}',
    'slack token': r'\bxox[abpr]-[A-Za-z0-9-]{10,}',
    'private key': r'-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----',
    'bearer token': r'\b[Bb]earer [A-Za-z0-9._-]{20,}',
    'jwt': r'\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+',
}.items()}


def slug(path):
    return re.sub('[^A-Za-z0-9]', '-', str(path))


def transcript_dirs(root):
    claude = Path.home() / '.claude/projects'
    cursor = Path.home() / '.cursor/projects'
    for r in dict.fromkeys([root, *LEGACY_ROOTS]):
        name = slug(r)
        if claude.is_dir():
            for d in sorted(claude.iterdir()):
                if d.name == name or d.name.startswith(name + '--'):
                    yield f'claude-code/{d.name}', d
        d = cursor / name.lstrip('-') / 'agent-transcripts'
        if d.is_dir():
            yield f'cursor-agent/{d.parent.name}', d


def transcript_files(root):
    for prefix, d in transcript_dirs(root):
        for path in sorted(d.rglob('*')):
            if path.is_file() and not path.is_symlink():
                yield f'{prefix}/{path.relative_to(d)}', path


def previous_manifest():
    tags = subprocess.run(
        ['gh', 'api', '--paginate', f'repos/{REPO}/releases',
         '--jq', f'.[] | select(any(.assets[]; .name == "{MANIFEST}")) | .tag_name'],
        capture_output=True, text=True, check=True).stdout.split()
    if not tags:
        return {}
    data = subprocess.run(
        ['gh', 'release', 'download', tags[0], '--repo', REPO, '--pattern', MANIFEST, '--output', '-'],
        capture_output=True, check=True).stdout
    return json.loads(data)


def known_secrets():
    values = [v for k, v in os.environ.items()
              if re.search('KEY|TOKEN|SECRET|PASSWORD', k) and len(v) >= 12
              and not v.startswith('/') and not re.search(r'\s', v)]
    # jev reads this key from pass, so a transcript of a jev run could hold it.
    try:
        typesafe = subprocess.run(['pass', 'show', 'typesafe-ai-api-key'],
                                  capture_output=True, text=True).stdout.split('\n')[0].strip()
    except FileNotFoundError:
        typesafe = ''
    return [v for v in [*values, typesafe] if v]


def new_bytes(path, seen):
    data = path.read_bytes()
    if len(data) < seen:
        seen = 0
    if path.suffix == '.jsonl':
        end = max(data.rfind(b'\n') + 1, seen)
        return data[seen:end], end
    if len(data) == seen:
        return b'', seen
    return data, len(data)


def redact(text, secrets, counts):
    for value in secrets:
        if value in text:
            counts['known secret'] += text.count(value)
            text = text.replace(value, '[REDACTED]')
    for name, pattern in SECRET_PATTERNS.items():
        text, n = pattern.subn('[REDACTED]', text)
        counts[name] += n
    return text


def main():
    root, dist = Path(sys.argv[1]).resolve(), Path(sys.argv[2])
    seen = previous_manifest()
    secrets = known_secrets()
    manifest, counts, added = dict(seen), Counter(), 0
    archive = dist / 'conversations.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, path in transcript_files(root):
            chunk, manifest[name] = new_bytes(path, seen.get(name, 0))
            if chunk:
                text = redact(chunk.decode('utf-8', 'surrogateescape'), secrets, counts)
                z.writestr(name, text.encode('utf-8', 'surrogateescape'))
                added += 1
    if not added:
        archive.unlink()
    (dist / MANIFEST).write_text(json.dumps(manifest, indent=1, sort_keys=True) + '\n')
    redacted = ', '.join(f'{n} {name}' for name, n in counts.items() if n) or 'nothing'
    print(f'conversations: {added} new or extended files, redacted {redacted}')


if __name__ == '__main__':
    main()

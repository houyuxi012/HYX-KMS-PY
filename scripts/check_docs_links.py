#!/usr/bin/env python3
"""Reject broken local Markdown links in product documentation."""
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r'(?<!!)\[[^]]*\]\(([^)]+)\)')


def link_targets(path):
    in_fence = False
    for line in path.read_text(encoding='utf-8').splitlines():
        if line.lstrip().startswith(('```', '~~~')):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for match in LINK.finditer(line):
            yield match.group(1).strip().split(' ', 1)[0].strip('<>')


def audit():
    documents = [
        ROOT / 'README.md',
        ROOT / 'CHANGELOG.md',
        ROOT / 'SECURITY.md',
        *sorted((ROOT / 'docs').glob('*.md')),
    ]
    errors = []
    for document in documents:
        for target in link_targets(document):
            parts = urlsplit(target)
            if parts.scheme or parts.netloc or target.startswith('#') or not unquote(parts.path):
                continue
            destination = (document.parent / unquote(parts.path)).resolve()
            try:
                destination.relative_to(ROOT)
            except ValueError:
                errors.append(f'{document.relative_to(ROOT)}: link escapes repository: {target}')
                continue
            if not destination.exists():
                errors.append(f'{document.relative_to(ROOT)}: missing local target: {target}')
    return errors


def main():
    errors = audit()
    if errors:
        print('\n'.join(errors), file=sys.stderr)
        return 1
    print('Local Markdown links are valid.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

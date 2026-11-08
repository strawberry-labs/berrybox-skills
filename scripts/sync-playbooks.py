#!/usr/bin/env python3
"""Refresh the bundled BerryBox Playbooks from the live site.

Reads <site>/llms.txt and saves every playbook page it lists as Markdown:
  https://berrybox.io/playbooks.md         -> skills/faster-ci/references/playbooks.md
  https://berrybox.io/playbooks/<path>.md  -> skills/faster-ci/references/playbooks/<path>.md
Pages the site no longer lists are deleted. Warns when the baseline script
embedded in baseline.md differs from skills/faster-ci/scripts/ci_baseline.py.

usage: python3 scripts/sync-playbooks.py [--site https://berrybox.io]
"""
import argparse
import re
import sys
import urllib.request
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent / "skills" / "faster-ci"
REFS = SKILL / "references"


def get(url):
    request = urllib.request.Request(url, headers={"User-Agent": "berrybox-skills-sync"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


def main():
    parser = argparse.ArgumentParser(description="Refresh the bundled BerryBox Playbooks.")
    parser.add_argument("--site", default="https://berrybox.io", help="origin to fetch from")
    site = parser.parse_args().site.rstrip("/")

    # llms.txt always links the canonical berrybox.io URLs; fetch them from --site.
    paths = sorted(set(re.findall(r"https://berrybox\.io/(playbooks(?:/[a-z0-9-]+)*)\.md\b", get(f"{site}/llms.txt"))))
    if "playbooks" not in paths:
        sys.exit(f"{site}/llms.txt does not link playbooks.md")

    saved = set()
    for path in paths:
        target = REFS / f"{path}.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(get(f"{site}/{path}.md"), encoding="utf-8")
        saved.add(target)
    for old in sorted((REFS / "playbooks").rglob("*.md")):
        if old not in saved:
            old.unlink()
            print(f"removed {old.relative_to(SKILL)}")
    for folder in sorted((REFS / "playbooks").glob("*/"), reverse=True):
        if not any(folder.iterdir()):
            folder.rmdir()
    print(f"saved {len(saved)} pages from {site}")

    baseline = (REFS / "playbooks" / "baseline.md").read_text(encoding="utf-8")
    embedded = re.search(r"```python\n(.*?)```", baseline, re.S)
    script = (SKILL / "scripts" / "ci_baseline.py").read_text(encoding="utf-8")
    if not embedded or embedded.group(1).strip() != script.strip():
        print("warning: the script in baseline.md differs from scripts/ci_baseline.py", file=sys.stderr)


if __name__ == "__main__":
    main()

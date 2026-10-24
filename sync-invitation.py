#!/usr/bin/env python3
"""Keep the complete gallery invitations aligned, without changing the wording."""
import argparse
import html
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def replace_once(text, pattern, replacement):
    result, count = re.subn(pattern, lambda _: replacement, text, flags=re.S)
    if count != 1:
        raise ValueError(f"expected one invitation block, found {count}: {pattern}")
    return result


def aligned_files(source):
    page = (ROOT / "index.html").read_text()
    # Comments cannot contain '--'; entities preserve the words without
    # letting handwritten arrows terminate the HTML comment prematurely.
    comment = html.escape(source, quote=False).replace("--", "&#45;&#45;")
    page = replace_once(page,
        r"<!-- SHARED INVITATION START\n.*?\nSHARED INVITATION END -->",
        "<!-- SHARED INVITATION START\n" + comment + "\nSHARED INVITATION END -->")
    page = replace_once(page, r'<pre class="agentWall">.*?</pre>',
                        '<pre class="agentWall">' + html.escape(source) + '</pre>')
    introduction = re.search(r"^> (.+(?:\n> .+)*)", source, flags=re.M)
    if introduction:
        lead = introduction.group(1).replace("\n> ", " ")
        page = replace_once(page, r'<p class="agentLead">.*?</p>',
                            '<p class="agentLead">' + html.escape(lead) + '</p>')
    readme = (ROOT / "README.md").read_text()
    readme = replace_once(readme,
        r"<!-- SHARED INVITATION START -->\n.*?\n<!-- SHARED INVITATION END -->",
        "<!-- SHARED INVITATION START -->\n" + source +
        "\n<!-- SHARED INVITATION END -->")
    return {ROOT / "index.html": page, ROOT / "README.md": readme}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    source = (ROOT / "llms.txt").read_text()
    stale = []
    for path, expected in aligned_files(source).items():
        if path.read_text() != expected:
            stale.append(path.name)
            if not args.check:
                path.write_text(expected)
    if args.check and stale:
        print("Invitations differ: " + ", ".join(stale))
        return 1
    print("Invitations aligned: llms.txt, page source, visible agent invitation, README.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

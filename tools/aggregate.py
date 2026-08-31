#!/usr/bin/env python3
"""Builds the combined plugin list from each plugin's own repo.json.

Every plugin repository already publishes a repo.json that works on its own. This walks that
list, fetches each one, and concatenates them into a single file. Nothing is rewritten on the way
through: each plugin repository stays the one place its version, description and download links
are edited, and this is purely derived from them.

The rule that matters is what happens when a fetch fails. A plugin dropped from the combined list
disappears from everyone's plugin installer, which looks exactly like it having been pulled. So a
source that cannot be read keeps whatever it contributed last time, and the run reports it rather
than quietly shipping a shorter list.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import urllib.error
import urllib.request

# Fields Dalamud needs to show and install a plugin. An entry missing any of these is broken in a
# way that is easier to see here than in the plugin installer.
REQUIRED = (
    "Author",
    "Name",
    "InternalName",
    "AssemblyVersion",
    "DownloadLinkInstall",
    "DownloadLinkUpdate",
    "DownloadLinkTesting",
)

RAW = "https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}"


class SourceError(Exception):
    """A source that could not be read or did not look like a plugin list."""


def fetch(url: str, timeout: int = 30) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "xivplugins-aggregator"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8")


def read_source(source: dict, offline: pathlib.Path | None) -> list[dict]:
    """One source's entries, validated."""
    name = f"{source['owner']}/{source['repo']}"

    if offline is not None:
        candidate = offline / f"{source['repo']}.json"
        if not candidate.exists():
            raise SourceError(f"{name}: no fixture at {candidate}")
        raw = candidate.read_text()
    else:
        url = RAW.format(
            owner=source["owner"],
            repo=source["repo"],
            branch=source.get("branch", "main"),
            path=source.get("path", "repo.json"),
        )
        try:
            raw = fetch(url)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            raise SourceError(f"{name}: could not be fetched ({exc})") from exc

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SourceError(f"{name}: is not readable JSON ({exc})") from exc

    if not isinstance(parsed, list) or not parsed:
        raise SourceError(f"{name}: repo.json should be a non-empty array of plugins")

    for entry in parsed:
        if not isinstance(entry, dict):
            raise SourceError(f"{name}: contains something that is not a plugin entry")
        missing = [field for field in REQUIRED if not entry.get(field)]
        if missing:
            raise SourceError(f"{name}: entry is missing {', '.join(missing)}")

    return parsed


def merge(sources: list[dict], previous: list[dict], offline: pathlib.Path | None):
    """The combined list, plus what went wrong.

    Sources are kept in the order they are listed, so the plugin installer shows them in an order
    somebody chose rather than whichever repository answered first.
    """
    combined: list[dict] = []
    seen: dict[str, str] = {}
    problems: list[str] = []

    for source in sources:
        label = f"{source['owner']}/{source['repo']}"

        try:
            entries = read_source(source, offline)
        except SourceError as exc:
            # Fall back to what this source gave us last time rather than dropping its plugins.
            kept = [entry for entry in previous if entry.get("_source") == label]
            if kept:
                problems.append(f"{exc} — kept the previous entry")
                combined.extend(kept)
            else:
                problems.append(f"{exc} — and there is nothing previous to fall back on")
            continue

        for entry in entries:
            internal = entry["InternalName"]
            if internal in seen:
                # Two plugins claiming one internal name is not something to paper over: the
                # installer would treat them as the same plugin.
                problems.append(
                    f"{label}: '{internal}' is already provided by {seen[internal]}, so it was skipped")
                continue

            seen[internal] = label
            entry = dict(entry)
            entry["_source"] = label
            combined.append(entry)

    return combined, problems


def publish(combined: list[dict]) -> list[dict]:
    """Strips the bookkeeping this script adds before the file is written."""
    return [{k: v for k, v in entry.items() if not k.startswith("_")} for entry in combined]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", default="sources.json")
    parser.add_argument("--output", default="repo.json")
    parser.add_argument("--state", default=".aggregate-state.json",
                        help="Remembers which source each plugin came from, for the fallback.")
    parser.add_argument("--offline-dir", default=None,
                        help="Read sources from this folder instead of the network. For tests.")
    parser.add_argument("--check", action="store_true",
                        help="Report what would change without writing anything.")
    args = parser.parse_args()

    offline = pathlib.Path(args.offline_dir) if args.offline_dir else None
    sources = json.loads(pathlib.Path(args.sources).read_text())["sources"]

    state_path = pathlib.Path(args.state)
    previous = json.loads(state_path.read_text()) if state_path.exists() else []

    combined, problems = merge(sources, previous, offline)

    for problem in problems:
        print(f"warning: {problem}", file=sys.stderr)

    if not combined:
        # Publishing an empty list would empty the plugin installer for everyone who uses it.
        print("error: nothing could be read from any source; leaving the existing list alone",
              file=sys.stderr)
        return 1

    output = pathlib.Path(args.output)
    rendered = json.dumps(publish(combined), indent=2, ensure_ascii=False) + "\n"
    unchanged = output.exists() and output.read_text() == rendered

    print(f"{len(combined)} plugin(s): {', '.join(e['InternalName'] for e in combined)}")

    if args.check:
        print("unchanged" if unchanged else "would be updated")
        return 0

    if not unchanged:
        output.write_text(rendered)
        print(f"wrote {output}")
    else:
        print("no change")

    state_path.write_text(json.dumps(combined, indent=2, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

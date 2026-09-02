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


def verify_release(entry: dict, timeout: int = 60) -> str | None:
    """
    Checks the version this list advertises against the archive it points at.

    The version in the list and the version inside the download have to agree. When they do not,
    the installer is told one thing and handed another, and the install fails outright — which is
    what happens if this list ever goes stale while a plugin carries on releasing.

    Returns a description of the problem, or None if the two match.
    """
    name = entry["InternalName"]
    url = entry["DownloadLinkInstall"]

    try:
        request = urllib.request.Request(url, headers={"User-Agent": "xivplugins-aggregator"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except Exception as exc:  # noqa: BLE001 - any failure here is the same kind of problem
        return f"{name}: the download link could not be fetched ({exc})"

    try:
        import io
        import zipfile

        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            names = archive.namelist()
            manifest_name = f"{name}.json"

            if manifest_name not in names:
                return f"{name}: the archive has no {manifest_name} at its root (found {names})"
            if f"{name}.dll" not in names:
                return f"{name}: the archive has no {name}.dll at its root"

            manifest = json.loads(archive.read(manifest_name).decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        return f"{name}: the archive could not be read ({exc})"

    built = manifest.get("AssemblyVersion")
    listed = entry["AssemblyVersion"]

    if built != listed:
        return (f"{name}: this list says {listed} but the archive contains {built}. "
                f"Anyone installing it is told one version and handed another, and the install fails.")

    return None


def Audit(entries: list[dict]) -> int:
    """Reports every entry whose download does not contain what it claims."""
    broken = [problem for entry in entries if (problem := verify_release(entry)) is not None]

    for problem in broken:
        print(f"error: {problem}", file=sys.stderr)

    if broken:
        return 1

    print(f"verified {len(entries)} download(s) against the versions advertised")
    return 0


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
    parser.add_argument("--verify", action="store_true",
                        help="Also confirm each download really contains the version being advertised.")
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

    # Verified before anything is written, not after.
    #
    # This used to read `Audit(publish(combined))` at the end, which published the list and then
    # checked it. The run went red, which looked like the check working -- but the broken list was
    # already on the branch and already being served to every installer pointed at it. A safety net
    # that catches you after you have hit the floor is decoration.
    if args.verify and Audit(publish(combined)) != 0:
        print("nothing written: the list would advertise a download that does not match",
              file=sys.stderr)
        return 1

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

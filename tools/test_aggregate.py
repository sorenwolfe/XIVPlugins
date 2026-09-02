#!/usr/bin/env python3
"""Checks for the aggregator.

The one that matters is the fallback. If a source cannot be read and its plugin quietly vanishes
from the combined list, it disappears from everyone's plugin installer and looks exactly like the
plugin having been pulled. Everything else here is bookkeeping by comparison.
"""

import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from aggregate import SourceError, merge, publish, read_source  # noqa: E402

failures = 0


def check(name, ok, detail=""):
    global failures
    print(("PASS  " if ok else "FAIL  ") + name + (f"  — {detail}" if detail else ""))
    if not ok:
        failures += 1


def entry(internal, version="1.0.0.0", name=None):
    return {
        "Author": "SorenWolfe",
        "Name": name or internal,
        "InternalName": internal,
        "AssemblyVersion": version,
        "DownloadLinkInstall": f"https://example/{internal}.zip",
        "DownloadLinkUpdate": f"https://example/{internal}.zip",
        "DownloadLinkTesting": f"https://example/{internal}.zip",
    }


def sources(*repos):
    return [{"owner": "sorenwolfe", "repo": repo} for repo in repos]


with tempfile.TemporaryDirectory() as tmp:
    fixtures = pathlib.Path(tmp)
    (fixtures / "RaidPlan.json").write_text(json.dumps([entry("RaidPlan", "0.4.1.0")]))
    (fixtures / "Foxtrot.json").write_text(json.dumps([entry("Foxtrot", "0.1.0.0")]))

    combined, problems = merge(sources("RaidPlan", "Foxtrot"), [], fixtures)
    check("both plugins come through", len(combined) == 2, str(len(combined)))
    check("nothing is reported wrong", not problems, "; ".join(problems))
    check("they keep the order they are listed in",
          [e["InternalName"] for e in combined] == ["RaidPlan", "Foxtrot"])
    check("each entry's own version is passed through untouched",
          combined[0]["AssemblyVersion"] == "0.4.1.0" and combined[1]["AssemblyVersion"] == "0.1.0.0")

    published = publish(combined)
    check("bookkeeping is stripped before publishing",
          all(not any(k.startswith("_") for k in e) for e in published))
    check("but is kept internally for the fallback",
          all("_source" in e for e in combined))

    # Updating one plugin must leave the other's version exactly as it was — the whole point of
    # keeping them in separate repositories.
    (fixtures / "Foxtrot.json").write_text(json.dumps([entry("Foxtrot", "0.2.0.0")]))
    after, _ = merge(sources("RaidPlan", "Foxtrot"), combined, fixtures)
    check("updating one plugin bumps only that one",
          after[0]["AssemblyVersion"] == "0.4.1.0" and after[1]["AssemblyVersion"] == "0.2.0.0",
          f"{after[0]['AssemblyVersion']} / {after[1]['AssemblyVersion']}")

    # The rule this whole thing is arranged around.
    (fixtures / "Foxtrot.json").unlink()
    degraded, problems = merge(sources("RaidPlan", "Foxtrot"), after, fixtures)
    check("a source that cannot be read does not lose its plugin",
          [e["InternalName"] for e in degraded] == ["RaidPlan", "Foxtrot"],
          str([e["InternalName"] for e in degraded]))
    kept_entry = next((e for e in degraded if e["InternalName"] == "Foxtrot"), None)
    check("the kept entry is the last good one",
          kept_entry is not None and kept_entry["AssemblyVersion"] == "0.2.0.0",
          "missing entirely" if kept_entry is None else kept_entry["AssemblyVersion"])
    check("and the failure is reported rather than swallowed",
          any("Foxtrot" in p and "kept the previous" in p for p in problems),
          "; ".join(problems))

    # A brand new source that fails on its first run has nothing to fall back on, and must say so
    # rather than pretending it published something.
    fresh, problems = merge(sources("RaidPlan", "Foxtrot"), [], fixtures)
    check("a new source that fails is left out, loudly",
          [e["InternalName"] for e in fresh] == ["RaidPlan"] and
          any("nothing previous" in p for p in problems),
          "; ".join(problems))

    # Two plugins claiming one internal name would be treated as the same plugin by the installer.
    (fixtures / "Foxtrot.json").write_text(json.dumps([entry("RaidPlan", "9.9.9.9", name="Impostor")]))
    clash, problems = merge(sources("RaidPlan", "Foxtrot"), [], fixtures)
    check("a duplicate internal name is refused, not merged",
          len(clash) == 1 and clash and clash[0]["AssemblyVersion"] == "0.4.1.0",
          str([(e["InternalName"], e["AssemblyVersion"]) for e in clash]))
    check("and the clash is reported",
          any("already provided by" in p for p in problems), "; ".join(problems))

    # Malformed sources are rejected at the door, where the error is legible.
    (fixtures / "Broken.json").write_text("{ not json")
    try:
        read_source({"owner": "x", "repo": "Broken"}, fixtures)
        check("unreadable JSON is rejected", False)
    except SourceError as exc:
        check("unreadable JSON is rejected", "not readable JSON" in str(exc), str(exc))

    (fixtures / "Empty.json").write_text("[]")
    try:
        read_source({"owner": "x", "repo": "Empty"}, fixtures)
        check("an empty list is rejected", False)
    except SourceError as exc:
        check("an empty list is rejected", "non-empty array" in str(exc), str(exc))

    (fixtures / "Object.json").write_text('{"InternalName": "Nope"}')
    try:
        read_source({"owner": "x", "repo": "Object"}, fixtures)
        check("a bare object is rejected", False)
    except SourceError as exc:
        check("a bare object is rejected", "non-empty array" in str(exc), str(exc))

    partial = entry("Partial")
    del partial["DownloadLinkUpdate"]
    (fixtures / "Partial.json").write_text(json.dumps([partial]))
    try:
        read_source({"owner": "x", "repo": "Partial"}, fixtures)
        check("an entry missing a required field is rejected", False)
    except SourceError as exc:
        check("an entry missing a required field is rejected",
              "DownloadLinkUpdate" in str(exc), str(exc))

    blank = entry("Blank")
    blank["AssemblyVersion"] = ""
    (fixtures / "Blank.json").write_text(json.dumps([blank]))
    try:
        read_source({"owner": "x", "repo": "Blank"}, fixtures)
        check("an empty required field counts as missing", False)
    except SourceError as exc:
        check("an empty required field counts as missing",
              "AssemblyVersion" in str(exc), str(exc))

    # One repository is allowed to publish more than one plugin.
    (fixtures / "Pair.json").write_text(json.dumps([entry("One"), entry("Two")]))
    both, problems = merge(sources("Pair"), [], fixtures)
    check("a source may carry several plugins", len(both) == 2 and not problems)

# A broken list must never reach the branch. This used to publish and then verify: the run went
# red, which looked like the check working, while the bad list was already being served.
source = pathlib.Path("tools/aggregate.py").read_text()

# find, not index: a missing marker means the guard is gone, which is a failing check rather than
# a crashed test. A harness that raises when the defect appears looks broken rather than useful.
verify_at = source.find("if args.verify and Audit(")
write_at = source.find("output.write_text(rendered)")

check("verification happens before anything is written",
      verify_at >= 0 and write_at >= 0 and verify_at < write_at,
      "publishing first means the check reports damage rather than preventing it")
check("a failed verification writes nothing",
      verify_at >= 0 and write_at >= 0 and "return 1" in source[verify_at:write_at],
      source[verify_at:write_at].strip()[:120] if verify_at >= 0 else "the guard is missing")
check("the old publish-then-verify form is gone",
      "Audit(publish(combined)) if args.verify" not in source)

print("ALL CHECKS PASSED" if not failures else f"{failures} CHECK(S) FAILED")
sys.exit(1 if failures else 0)

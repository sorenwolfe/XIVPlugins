# SorenWolfe's FFXIV plugins

One repository link that serves all of my Dalamud plugins. Add it once and everything here shows
up in your plugin list — including anything I release later.

```
https://raw.githubusercontent.com/sorenwolfe/XIVPlugins/main/repo.json
```

In game: `/xlplugins` → **Settings** → **Experimental** → paste that into **Custom Plugin
Repositories** → **+** → **Save and Close**.

---

## What's here

| Plugin | What it does | Repository |
|---|---|---|
| **RaidPlan** | Build and call raid strategies in game — slide-by-slide arena diagrams, cooldown assignments, spoken calls, and live party positions drawn over the plan. | [sorenwolfe/RaidPlan](https://github.com/sorenwolfe/RaidPlan) |
| **Foxtrot** | Hear an orchestrion roll before you go and earn it. Right-click a roll, or browse and search every track in the game. | [sorenwolfe/Foxtrot](https://github.com/sorenwolfe/Foxtrot) |

---

## What this repository actually is

**No plugin code lives here.** Each plugin has its own repository, its own issues, its own
releases and its own version. This repository holds one generated file — `repo.json` — that lists
them all together, so players paste one link instead of one per plugin.

`repo.json` is rebuilt automatically from each plugin's own `repo.json`. Nothing here is edited by
hand, and nothing is rewritten on the way through: each plugin repository stays the single place
its version, description and download links are set.

That means **releasing one plugin never touches another**. Dalamud offers an update by comparing
the installed `AssemblyVersion` against the one in the list; a plugin whose version has not moved
is not offered an update, whatever else changed around it.

### Adding a plugin

Add a line to `sources.json`:

```json
{ "owner": "sorenwolfe", "repo": "NewPlugin", "branch": "main", "path": "repo.json" }
```

Push it. The list rebuilds on the next run and the plugin appears for everyone who has the link.
Nothing else in this repository needs touching.

### How the rebuild runs

- **Hourly**, so a release is picked up without anyone doing anything.
- **On demand** from the Actions tab, for when you have just released and don't want to wait.
- **On a `plugin-released` dispatch**, if you later add a step to a plugin's release workflow to
  poke this one.

The aggregator's own tests run before it is allowed to publish anything.

### The rule it is built around

If a plugin's repository can't be read — a GitHub blip, a bad edit, a renamed branch — that
plugin's **previous entry is kept** rather than dropped, and the run reports it. A plugin that
vanishes from the list vanishes from everyone's plugin installer, which looks exactly like it
having been pulled. Being briefly out of date is a much smaller problem than appearing to be gone.

If *nothing* can be read, the run fails and leaves the existing list alone rather than publishing
an empty one.

### Running it yourself

```
python3 tools/test_aggregate.py     # the rules
python3 tools/aggregate.py --check  # what would change, without writing
python3 tools/aggregate.py          # rebuild repo.json
```

---

## Each plugin also works on its own

Every plugin repository publishes a working `repo.json` of its own, so this one is a convenience
rather than a dependency. Anyone who already has an individual plugin's link keeps working exactly
as before, and doesn't have to change anything.

---

## Licence

The plugins are AGPL-3.0-or-later, each in its own repository. The scripts here are the same.

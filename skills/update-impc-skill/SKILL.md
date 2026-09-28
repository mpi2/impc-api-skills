---
name: update-impc-skill
metadata:
  version: "1.0.0"
description: Update an installed skill from mpi2/impc-api-skills after its local metadata.version has been found to differ from the main-branch version. Invoke only for a confirmed version mismatch; routine version checks belong to the calling skill.
---

# Update IMPC Skill

Invoke only after the calling skill has compared its local `metadata.version`
with its `SKILL.md` on GitHub `main` and found a mismatch. Matching versions or
an unsuccessful check do not trigger this skill.

Update only the requested installed skill. The latest published version is
its directory under `skills/` on the `mpi2/impc-api-skills` GitHub `main` branch.
This updater must be installed alongside skills that invoke it.

Ensure `uv` is available on `PATH` (use the `uv` skill if needed). Run the
bundled standard-library script with absolute paths:

```bash
uv run --script <updater-directory>/scripts/update_skill.py --install-dir <target-installed-skill-directory>
```

Locate the target from the
loaded skill's `SKILL.md`; do not target a development checkout or guess a
client's installation directory. Resolve an installation symlink to its real
installed directory first.

The script reads the target's `name` and `metadata.version`, compares numeric
`MAJOR.MINOR.PATCH` versions, and replaces the whole skill directory only when
a newer version exists. It validates the download before replacement and
prints the previous installation's backup path, preserving local edits there.
It does not downgrade newer local versions. Both copies must have a version.

After updating, re-read the target's installed `SKILL.md` before resuming its
workflow. Return the skill name, version actually used, check outcome, and
backup path when applicable. The calling skill records the version and outcome
in its output README. If used directly, report these details to the user;
no separate README is needed.

If the check or update fails, report the error and do not claim the installation
is current. When invoked by another skill, let it continue with its installed
copy if available and disclose that freshness could not be verified. Do not
retry indefinitely. Updating this updater uses the same command with its own
installation directory as the target; do not invoke this skill recursively.

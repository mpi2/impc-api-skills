#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Check or update one installed IMPC skill from GitHub main."""

import argparse
import io
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from urllib.request import urlopen

SOURCE = "https://codeload.github.com/mpi2/impc-api-skills/zip/refs/heads/main"
PREFIX = "impc-api-skills-main/skills/"


def metadata(directory):
    path = directory / "SKILL.md"
    frontmatter = path.read_text(encoding="utf-8").split("---", 2)
    match = re.search(r'^  version: "(\d+\.\d+\.\d+)"$', frontmatter[1], re.M) if len(frontmatter) == 3 else None
    if not match:
        raise ValueError(f"Missing or invalid metadata.version in {path}")
    name = re.search(r'^name: ([a-z0-9]+(?:-[a-z0-9]+)*)$', frontmatter[1], re.M)
    if not name:
        raise ValueError(f"Missing or invalid name in {path}")
    return name[1], tuple(map(int, match[1].split(".")))


def update(archive, target, check=False):
    if target.is_symlink():
        raise ValueError("Use the real installation directory, not a symlink")
    name, installed = metadata(target)
    prefix = f"{PREFIX}{name}/"
    # Stage outside the installation so failed downloads/extraction never change it.
    with tempfile.TemporaryDirectory() as temporary:
        staged = Path(temporary) / name
        staged.mkdir()
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            for item in bundle.infolist():
                if not item.filename.startswith(prefix) or item.is_dir():
                    continue
                relative = Path(item.filename[len(prefix):])
                if relative.is_absolute() or ".." in relative.parts or "\\" in str(relative):
                    raise ValueError("Unsafe archive path")
                if (item.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError("Archive contains a symlink")
                destination = staged / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(bundle.read(item))
        upstream_name, latest = metadata(staged)
        if upstream_name != name:
            raise ValueError("Upstream skill name does not match the installation")
        result = {"skill": name, "installed": ".".join(map(str, installed)), "latest": ".".join(map(str, latest)), "source": SOURCE}
        if installed >= latest or check:
            return dict(result, status="update available" if installed < latest else "current or newer")
        target.parent.mkdir(parents=True, exist_ok=True)
        # Keep the previous installation (including local edits) for recovery.
        with tempfile.TemporaryDirectory(dir=target.parent, prefix=f".{name}-stage-") as sibling:
            replacement = Path(sibling) / name
            shutil.copytree(staged, replacement)
            backup = None
            if target.exists():
                backup = Path(tempfile.mkdtemp(dir=target.parent, prefix=f".{name}-backup-")) / name
                target.rename(backup)
            try:
                replacement.rename(target)
            except OSError:
                if backup is not None:
                    backup.rename(target)
                raise
        return dict(result, status="updated", backup=str(backup) if backup else None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install-dir", required=True, type=Path, help="Exact installed skill directory")
    parser.add_argument("--check", action="store_true", help="Report versions without updating")
    args = parser.parse_args()
    try:
        with urlopen(SOURCE, timeout=30) as response:
            archive = response.read()
        print(update(archive, args.install_dir.absolute(), args.check))
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        print(f"Skill update/check failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

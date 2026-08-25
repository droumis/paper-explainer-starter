#!/usr/bin/env python
"""Tests for scaffolding and asset syncing across several papers.

The case that matters is a paper that improves a shared file. Syncing must not
overwrite it, because that improvement is the thing the starter wants fed back
upstream, and losing it is silent.

Run:  pixi run --manifest-path template/pixi.toml python tests/test_papers.py
"""

import importlib.util
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "template" / "scripts"))

spec = importlib.util.spec_from_file_location(
    "papers", ROOT / "template" / "scripts" / "papers.py")
papers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(papers)


def check(name, condition, detail=""):
    mark = "ok  " if condition else "FAIL"
    print(f"  {mark} {name}" + (f"  ({detail})" if detail and not condition else ""))
    return bool(condition)


def build_repo(root: Path):
    """A minimal repo: a template with one shared css and one shared lib file."""
    css = root / "template" / "docs" / "assets" / "css"
    lib = root / "template" / "docs" / "assets" / "js" / "lib"
    css.mkdir(parents=True)
    lib.mkdir(parents=True)
    (css / "custom.css").write_text("/* v1 */\n")
    (lib / "stats.js").write_text("// v1\n")
    (root / "template" / "docs" / "assets" / "js" / "diagrams.js").write_text("// paper\n")
    (root / "template" / "docs" / "index.md").write_text("# x\n")
    (root / "template" / "mkdocs.yml").write_text("site_name: x\n")
    (root / "template" / "figures.toml").write_text("# none\n")
    (root / "PAPER.md").write_text("# brief\n")
    papers.ROOT = root
    papers.TEMPLATE = root / "template"


def stats_of(project: Path) -> str:
    return (project / "docs/assets/js/lib/stats.js").read_text()


def main():
    passed = []

    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        build_repo(root)
        cwd = Path.cwd()
        try:
            import os
            os.chdir(root)

            papers.cmd_new(["paper-one"])
            one = root / "paper-one"
            passed.append(check("new-paper writes the shared assets",
                                stats_of(one) == "// v1\n"))
            passed.append(check("new-paper records what it wrote",
                                (one / papers.SYNC_RECORD).exists()))

            # A pristine copy must take the upstream improvement.
            (root / "template/docs/assets/js/lib/stats.js").write_text("// v2\n")
            skipped = papers.sync_project(one)
            passed.append(check("a pristine copy is updated",
                                stats_of(one) == "// v2\n" and not skipped,
                                f"got {stats_of(one)!r}, skipped={skipped}"))

            # A paper that improved the file keeps it.
            (one / "docs/assets/js/lib/stats.js").write_text("// v2 plus fitLDA\n")
            (root / "template/docs/assets/js/lib/stats.js").write_text("// v3\n")
            skipped = papers.sync_project(one)
            passed.append(check("a locally improved file is not overwritten",
                                stats_of(one) == "// v2 plus fitLDA\n",
                                f"got {stats_of(one)!r}"))
            passed.append(check("and the skip is reported",
                                any("stats.js" in s for s in skipped),
                                f"skipped={skipped}"))
            passed.append(check("while its unmodified siblings still update",
                                (one / "docs/assets/css/custom.css").read_text()
                                == "/* v1 */\n"))

            # --force is the escape hatch, and must be explicit.
            skipped = papers.sync_project(one, force=True)
            passed.append(check("--force overwrites",
                                stats_of(one) == "// v3\n" and not skipped,
                                f"got {stats_of(one)!r}"))

            # A paper with no record predates the mechanism, so its copy cannot be
            # told apart from an improvement. Conservative: leave it.
            two = root / "paper-two"
            papers.cmd_new(["paper-two"])
            (two / papers.SYNC_RECORD).unlink()
            (two / "docs/assets/js/lib/stats.js").write_text("// unknown\n")
            skipped = papers.sync_project(two)
            passed.append(check("an unrecorded difference is left alone",
                                stats_of(two) == "// unknown\n"
                                and any("stats.js" in s for s in skipped),
                                f"got {stats_of(two)!r}, skipped={skipped}"))

            # diagrams.js is the paper's own work and is never shared.
            (two / "docs/assets/js/diagrams.js").write_text("// mine\n")
            papers.sync_project(two, force=True)
            passed.append(check("diagrams.js is never synced",
                                (two / "docs/assets/js/diagrams.js").read_text()
                                == "// mine\n"))

            # A paper that is its own git repo manages its own machinery, and a
            # sweep over every paper must not write into it.
            (two / ".git").mkdir()
            (two / "docs/assets/js/lib/stats.js").write_text("// theirs\n")
            (two / papers.SYNC_RECORD).unlink(missing_ok=True)
            papers.cmd_sync_assets([])
            passed.append(check("a paper that is its own repo is skipped entirely",
                                stats_of(two) == "// theirs\n"
                                and not (two / papers.SYNC_RECORD).exists(),
                                f"got {stats_of(two)!r}"))
            (two / ".git").rmdir()

            # Scaffolding into a directory holding the PDF is the normal start.
            three = root / "paper-three"
            three.mkdir()
            (three / "paper.pdf").write_text("%PDF\n")
            papers.cmd_new(["paper-three"])
            passed.append(check("new-paper scaffolds around an existing PDF",
                                (three / "mkdocs.yml").exists()
                                and (three / "paper.pdf").exists()))
            try:
                papers.cmd_new(["paper-three"])
                passed.append(check("new-paper refuses to overwrite a paper", False,
                                    "no SystemExit"))
            except SystemExit as exc:
                passed.append(check("new-paper refuses to overwrite a paper",
                                    "Refusing to overwrite" in str(exc), str(exc)))
        finally:
            os.chdir(cwd)

    print(f"\n{sum(passed)}/{len(passed)} checks passed")
    return 0 if all(passed) else 1


if __name__ == "__main__":
    raise SystemExit(main())

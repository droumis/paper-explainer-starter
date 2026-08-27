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
    # scripts/ is what marks template/ as the scaffold source rather than a paper.
    (root / "template" / "scripts").mkdir()
    (root / "template" / "scripts" / "papers.py").write_text("# machinery\n")
    (root / "template" / "pixi.toml").write_text("[project]\nname = 'x'\n")
    (root / "template" / "pixi.lock").write_text("# lock\n")
    (root / "template" / ".gitignore").write_text(".pixi/\nsite/\ndist/\n")
    # The starter's own, carrying the marker init looks for.
    (root / ".gitignore").write_text(
        "# template/ is the source of truth\n"
        "/docs/\n/scripts\n/mkdocs.yml\n/pixi.toml\n/pixi.lock\n")
    (root / "PAPER.md").write_text("# brief\n")
    point_at(root)


def point_at(root: Path):
    """Aim the module at a repo that build_repo already created."""
    papers.ROOT = root
    papers.TEMPLATE = root / "template"


def stats_of(project: Path) -> str:
    return (project / "docs/assets/js/lib/stats.js").read_text()


def check_workflow_shell(check) -> list:
    """Every `run:` block must be valid bash once the paper list is substituted.

    The list is interpolated into the shell verbatim, so a multi-line value turns
    `for p in ${{ ... }}` into a syntax error. That shipped, and it only showed up
    in a repo with more than one paper, because one paper is one line.
    """
    import re
    import subprocess
    import yaml

    passed = []
    for wf in sorted((ROOT / "template" / ".github" / "workflows").glob("*.yml")):
        spec = yaml.safe_load(wf.read_text())
        for job in spec.get("jobs", {}).values():
            for step in job.get("steps", []):
                script = step.get("run")
                if not script:
                    continue
                # Two papers, which is what breaks a newline-separated list.
                filled = re.sub(r"\$\{\{[^}]*\}\}", "paper-a paper-b", script)
                r = subprocess.run(["bash", "-n"], input=filled,
                                   capture_output=True, text=True)
                passed.append(check(
                    f"{wf.name}: `{step.get('name', 'run')}` is valid shell",
                    r.returncode == 0, r.stderr.strip()))

        # The consumer check above cannot see the bug that shipped: substituting a
        # value of its own choosing hides the fact that the producer emitted a
        # multi-line one. So check the producer. Any output that a `for ... in`
        # interpolates has to be written on a single line.
        text = wf.read_text()
        looped = set(re.findall(
            r"for\s+\w+\s+in\s+\$\{\{\s*steps\.\w+\.outputs\.(\w+)", text))
        heredoc = set(re.findall(r'echo\s+"(\w+)<<', text))
        both = sorted(looped & heredoc)
        passed.append(check(
            f"{wf.name}: outputs used in a for loop are single-line",
            not both, f"multi-line and looped over: {both}"))
    return passed


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
            # A mono root's entry points are pixi.toml, pixi.lock and the
            # scripts symlink, and init creates all three. Inheriting the
            # starter's .gitignore, which anchors exactly those paths, produced a
            # repo that could not be built from a clone and a CI failure on a
            # missing manifest. Both layouts must end up with a .gitignore that
            # does not hide what init just wrote.
            for layout in ([], ["--mono"]):
                label = "--mono" if layout else "one paper"
                with tempfile.TemporaryDirectory() as d2:
                    fresh = Path(d2)
                    build_repo(fresh)
                    papers.cmd_init(layout)
                    text = (fresh / ".gitignore").read_text()
                    hidden = [f for f in ("pixi.toml", "pixi.lock", "scripts")
                              if f"/{f}" in text]
                    passed.append(check(
                        f"init ({label}) leaves the entry points trackable",
                        not hidden, f"still ignored: {hidden}"))
                    passed.append(check(
                        f"init ({label}) still ignores build output",
                        "site/" in text and "dist/" in text))
                point_at(root)  # later checks operate on the outer repo again

            # A CI fix upstream is useless if it cannot reach a repo that
            # already has a copy of the workflow, which is what init installs.
            with tempfile.TemporaryDirectory() as d5:
                fresh = Path(d5)
                build_repo(fresh)
                wf = fresh / "template" / papers.SITE_WORKFLOW
                wf.parent.mkdir(parents=True)
                wf.write_text("name: CI\n# v2\n")
                papers.cmd_init(["--mono"])
                (fresh / papers.SITE_WORKFLOW).write_text("name: CI\n# v1\n")
                papers.cmd_update([])
                passed.append(check(
                    "update refreshes a stale installed CI workflow",
                    (fresh / papers.SITE_WORKFLOW).read_text() == "name: CI\n# v2\n",
                    (fresh / papers.SITE_WORKFLOW).read_text()))
            point_at(root)

            # An existing mono root predates that fix, so update repairs it. The
            # starter itself must be left alone: there, the anchors are correct.
            with tempfile.TemporaryDirectory() as d3:
                fresh = Path(d3)
                build_repo(fresh)
                papers.cmd_init(["--mono"])
                (fresh / ".gitignore").write_text(
                    "# template/ is the source of truth\n/pixi.toml\n/scripts\n")
                # A paper directory, written directly: cmd_new resolves against
                # the working directory, and this check is about ROOT.
                (fresh / "paper-a").mkdir()
                (fresh / "paper-a" / "mkdocs.yml").write_text("site_name: a\n")
                papers.cmd_update([])
                passed.append(check(
                    "update repairs a root that still ignores its entry points",
                    "/pixi.toml" not in (fresh / ".gitignore").read_text(),
                    (fresh / ".gitignore").read_text()))
            with tempfile.TemporaryDirectory() as d4:
                fresh = Path(d4)
                build_repo(fresh)  # no paper directories: this is the starter
                keep = (fresh / ".gitignore").read_text()
                papers.cmd_update([])
                passed.append(check(
                    "update leaves the starter's own .gitignore alone",
                    (fresh / ".gitignore").read_text() == keep))
            point_at(root)
        finally:
            os.chdir(cwd)

    passed += check_workflow_shell(check)

    print(f"\n{sum(passed)}/{len(passed)} checks passed")
    return 0 if all(passed) else 1


if __name__ == "__main__":
    raise SystemExit(main())

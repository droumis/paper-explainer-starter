#!/usr/bin/env python
"""Manage one or more paper projects in this repo. Paper-agnostic.

    pixi run --manifest-path template/pixi.toml init [--mono]
                                       one-time bootstrap of a fresh clone
    pixi run update                    after a git pull, refresh the copies
    pixi run papers                    list the projects and their state
    pixi run new-paper <name>          scaffold a project from template/
    pixi run sync-assets [name]        refresh the shared css/js from template/
    pixi run serve [name]              mkdocs serve for one project
    pixi run build [name]              mkdocs build for one project

`init` exists because copying the template by hand drops its dotfiles: a project
that inherits the starter's own `.gitignore` has its `docs/`, `scripts/` and
`mkdocs.yml` ignored, so nothing can be committed and the omission is invisible
until someone tries.

`serve` and `build` exist as wrappers so that every command takes the project
the same way, rather than mkdocs needing `-f <name>/mkdocs.yml` while the Python
tools take a directory.

Assets are copied, not symlinked, because mkdocs walks `docs/` without following
symlinked directories, so a symlinked asset tree silently ships nothing.
`sync-assets` is how a shared fix in template/ reaches projects that already
exist. It never touches `diagrams.js`, which is per paper.
"""

import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from project import (  # noqa: E402
    FIGURES_FILE,
    candidate_projects,
    load_figures,
    looks_like_project,
    resolve_project,
)

MACHINERY = Path(__file__).parent.parent      # the directory holding scripts/
if MACHINERY.name == "template":
    # Running as template/scripts/papers.py, which is how `init` is invoked
    # before the repo root has a manifest of its own.
    ROOT, TEMPLATE = MACHINERY.parent, MACHINERY
else:
    # An instantiated project, or a multi-paper root where scripts is a symlink
    # into template/. Path resolution deliberately does not follow the symlink.
    ROOT, TEMPLATE = MACHINERY, MACHINERY / "template"

# Paper-agnostic files that template/ owns and every project only borrows.
SHARED_ASSETS = ("docs/assets/css", "docs/assets/js/lib")


def require_template():
    if not (TEMPLATE / "docs").is_dir():
        raise SystemExit(
            f"No template/ directory at {ROOT}. Scaffolding needs the starter's "
            "template, so run this from a repo cloned from the starter."
        )


# Instantiated into a single-paper project root. `.pixi` is an environment, not
# template content, and pycache is noise.
INIT_SKIP = {".pixi", "__pycache__", ".gitignore", ".github"}
# What a multi-paper root takes from the template. Everything from mkdocs.yml
# downwards belongs to a paper, not to the root.
MONO_FILES = ("pixi.toml", "pixi.lock")


# The starter's own .gitignore hides an instantiated project's docs/, scripts/
# and mkdocs.yml, because in the starter those paths are generated. A clone keeps
# that file, so init has to replace it, and this marker identifies it without
# clobbering a .gitignore somebody wrote.
STARTER_GITIGNORE_MARK = "instantiated project files"
# The starter's own workflow tests the template and the machinery. A papers repo
# wants the one that checks prose, crops, the build and the site per paper.
STARTER_CI_MARK = "CI for the starter itself"
CI_PATH = ".github/workflows/ci.yml"


def install_replacing_starter(rel: str, marker: str, label: str):
    """Install a template file, replacing the starter's version of it.

    A clone arrives with the starter's `.gitignore` and workflow, both of which
    are wrong for a project and neither of which announces that. Replace them
    when the marker identifies them as the starter's, and never touch a file
    somebody wrote.
    """
    src, dest = TEMPLATE / rel, ROOT / rel
    if not src.exists():
        return
    if dest.exists():
        if marker in dest.read_text():
            dest.write_text(src.read_text())
            print(f"  replaced {rel} ({label})")
        else:
            print(f"  kept {rel} (not the starter's)")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    print(f"  wrote {rel}")


def copy_into(src: Path, dest: Path) -> bool:
    """Copy one file or tree, never overwriting. True if it was written."""
    if dest.exists():
        print(f"  kept {dest.name} (already here)")
        return False
    if src.is_dir():
        shutil.copytree(src, dest)
    else:
        shutil.copy2(src, dest)
    print(f"  wrote {dest.name}")
    return True


def cmd_init(args):
    """Bootstrap a fresh clone into one of the two layouts.

    Writes to the repo root rather than the working directory, because this runs
    through `--manifest-path template/pixi.toml` before the root has a manifest
    of its own, and pixi runs tasks from the manifest's directory.
    """
    require_template()
    mono = "--mono" in args
    print(f"initialising {ROOT} for "
          + ("several papers" if mono else "one paper"))
    install_replacing_starter(".gitignore", STARTER_GITIGNORE_MARK,
                              "the starter's hid this project's own files")
    install_replacing_starter(CI_PATH, STARTER_CI_MARK,
                              "the starter's tests the template, not a site")
    if mono:
        for name in MONO_FILES:
            src = TEMPLATE / name
            if src.exists():
                copy_into(src, ROOT / name)
        link = ROOT / "scripts"
        if link.exists() or link.is_symlink():
            print("  kept scripts (already here)")
        else:
            # Relative, so it survives the repo being moved or checked out
            # elsewhere, and one copy of the machinery serves every paper.
            link.symlink_to(Path("template/scripts"))
            print("  linked scripts -> template/scripts")
        print("\nNext: `pixi install`, then `pixi run new-paper <name>`.")
        return

    for src in sorted(TEMPLATE.iterdir()):
        if src.name in INIT_SKIP:
            continue
        copy_into(src, ROOT / src.name)
    print("\nNext: `pixi install`, put the paper's PDF here, fill in PAPER.md.")


def cmd_update(args):
    """Push a pulled machinery change out to where the copies live.

    A repo that adds papers on top of this one gets machinery updates by pulling,
    which lands them in `template/`. Three kinds of copy do not update
    themselves: the root manifest, the scripts of a single-paper project, and the
    shared css/js inside each paper's `docs/`. Run this after a pull.
    """
    require_template()
    print(f"refreshing machinery in {ROOT} from template/")
    for name in MONO_FILES:
        src = TEMPLATE / name
        if src.exists() and (ROOT / name).exists():
            shutil.copy2(src, ROOT / name)
            print(f"  {name}")
    scripts = ROOT / "scripts"
    if scripts.is_dir() and not scripts.is_symlink():
        # A single-paper project owns a copy. A multi-paper root symlinks
        # template/scripts and needs nothing.
        for f in sorted((TEMPLATE / "scripts").glob("*.py")):
            shutil.copy2(f, scripts / f.name)
            print(f"  scripts/{f.name}")
    install_replacing_starter(".gitignore", STARTER_GITIGNORE_MARK,
                              "the starter's hid this project's own files")
    install_replacing_starter(CI_PATH, STARTER_CI_MARK,
                              "the starter's tests the template, not a site")
    cmd_sync_assets([])


def cmd_list(args):
    cwd = Path.cwd()
    projects = [cwd] if looks_like_project(cwd) else candidate_projects(cwd)
    if not projects:
        print("No paper projects here. Scaffold one with `pixi run new-paper <name>`.")
        return
    print(f"{'paper':28s} {'pdf':5s} {'crops':6s} pages")
    for p in projects:
        pdfs = [q for q in p.glob("*.pdf") if not q.name.startswith(".")]
        try:
            crops = len(load_figures(p))
        except SystemExit:
            crops = 0
        pages = len(list((p / "docs").glob("*.md"))) if (p / "docs").is_dir() else 0
        print(f"{p.name:28s} {'yes' if pdfs else 'no':5s} {crops:<6d} {pages}")


def cmd_new(args):
    require_template()
    if not args:
        raise SystemExit("Usage: pixi run new-paper <name>")
    name = args[0]
    dest = Path.cwd() / name
    # Scaffolding into a directory that already holds the PDF is the normal way
    # to start, so an existing directory is fine as long as nothing would be
    # overwritten.
    clashes = [p for p in ("docs", "mkdocs.yml", FIGURES_FILE, "PAPER.md")
               if (dest / p).exists()]
    if clashes:
        raise SystemExit(
            f"{name} already has {', '.join(clashes)}. Refusing to overwrite.\n"
            f"Work in {name} as it is, or move it aside first."
        )
    dest.mkdir(parents=True, exist_ok=True)

    shutil.copytree(TEMPLATE / "docs", dest / "docs")
    shutil.copy2(TEMPLATE / "mkdocs.yml", dest / "mkdocs.yml")
    shutil.copy2(TEMPLATE / FIGURES_FILE, dest / FIGURES_FILE)
    brief = ROOT / "PAPER.md"
    if brief.exists():
        shutil.copy2(brief, dest / "PAPER.md")

    print(f"scaffolded {name}/")
    for f in sorted(p.relative_to(dest) for p in dest.rglob("*") if p.is_file()):
        print(f"  {f}")
    print(f"\nNext: put the paper's PDF in {name}/, fill in {name}/PAPER.md, "
          f"then `pixi run probe {name} --suggest`.")


def leading_name(args):
    """Split `args` into a leading project name and the rest.

    Deliberately first-token-only, because the rest is handed to mkdocs and its
    own flags take values that must never be read as a directory name.
    """
    if args and not args[0].startswith("-"):
        return args[0], args[1:]
    return None, list(args)


def cmd_sync_assets(args):
    require_template()
    name, _ = leading_name(args)
    targets = [resolve_project(name)] if name else candidate_projects(Path.cwd())
    if not targets:
        raise SystemExit("No paper projects here.")
    for project in targets:
        for rel in SHARED_ASSETS:
            src, dst = TEMPLATE / rel, project / rel
            if not src.is_dir():
                continue
            dst.mkdir(parents=True, exist_ok=True)
            for f in sorted(src.iterdir()):
                if f.is_file():
                    shutil.copy2(f, dst / f.name)
                    print(f"  {project.name}/{rel}/{f.name}")
    print("Shared assets synced. diagrams.js is per paper and was not touched.")


def cmd_mkdocs(verb, args):
    name, rest = leading_name(args)
    project = resolve_project(name)
    cfg = project / "mkdocs.yml"
    if not cfg.exists():
        raise SystemExit(f"No mkdocs.yml in {project}.")
    argv = ["mkdocs", verb, "-f", str(cfg), *rest]
    print(f"$ {' '.join(argv)}")
    # exec rather than subprocess: mkdocs serve is long-lived and interactive,
    # and its exit status is the task's exit status.
    os.execvp(argv[0], argv)


def main():
    if not sys.argv[1:]:
        raise SystemExit(__doc__)
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "init":
        cmd_init(args)
    elif cmd == "update":
        cmd_update(args)
    elif cmd == "list":
        cmd_list(args)
    elif cmd == "new":
        cmd_new(args)
    elif cmd == "sync-assets":
        cmd_sync_assets(args)
    elif cmd in ("serve", "build"):
        cmd_mkdocs(cmd, args)
    else:
        raise SystemExit(f"Unknown command {cmd!r}.\n{__doc__}")


if __name__ == "__main__":
    main()

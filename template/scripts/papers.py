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
    pixi run index [--serve] [--port N] build every paper into dist/ behind one
                                       landing page, and optionally serve it

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

import hashlib
import json
import os
import re
import shutil
import subprocess
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
# Records the template content last written into a paper, so a local improvement
# to a shared file is never mistaken for a stale copy and overwritten. A dotfile,
# which mkdocs leaves out of the built site.
SYNC_RECORD = "docs/assets/.synced.json"


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
STARTER_GITIGNORE_MARK = "template/ is the source of truth"
# The site workflow keeps its own filename rather than replacing this repo's
# ci.yml, so a papers repo that pulls machinery updates never has to merge it.
SITE_WORKFLOW = ".github/workflows/site.yml"


def install_gitignore():
    """Give a single-paper project a .gitignore that does not hide it.

    A clone arrives with the starter's, which anchors docs/, scripts/, mkdocs.yml
    and figures.toml at the root because there they are generated. In an
    instantiated project those are the project, so nothing could be committed and
    nothing said why. A multi-paper root keeps the starter's file, where those
    anchors are correct and each paper's own docs/ is tracked.
    """
    src, dest = TEMPLATE / ".gitignore", ROOT / ".gitignore"
    if not src.exists():
        return
    if dest.exists():
        if STARTER_GITIGNORE_MARK in dest.read_text():
            dest.write_text(src.read_text())
            print("  replaced .gitignore (the starter's hid this project's own files)")
        else:
            print("  kept .gitignore (not the starter's)")
        return
    shutil.copy2(src, dest)
    print("  wrote .gitignore")


def install_site_workflow():
    src = TEMPLATE / SITE_WORKFLOW
    dest = ROOT / SITE_WORKFLOW
    if not src.exists() or dest.exists():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    print(f"  wrote {SITE_WORKFLOW}")


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
    install_site_workflow()
    if not mono:
        # A multi-paper root keeps the starter's .gitignore, where the root-level
        # anchors are correct and each paper's own docs/ is still tracked.
        install_gitignore()
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
        install_gitignore()
    install_site_workflow()
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
    # Record the shared assets just written, so a later sync can tell a pristine
    # copy from one this paper improved.
    write_record(dest, {
        f"{rel}/{f.name}": digest(f)
        for rel in SHARED_ASSETS if (TEMPLATE / rel).is_dir()
        for f in (TEMPLATE / rel).iterdir() if f.is_file()
    })

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


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_record(project: Path) -> dict:
    path = project / SYNC_RECORD
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}


def write_record(project: Path, record: dict):
    path = project / SYNC_RECORD
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")


def self_managed(project: Path) -> bool:
    """True for a paper directory that is its own git repo.

    Such a directory arrived as a standalone project and carries its own copy of
    the machinery, so the shared assets here are not authoritative for it. Writing
    into it would overwrite work the repo it belongs to is tracking.
    """
    return (project / ".git").exists()


def sync_project(project: Path, force: bool = False) -> list[str]:
    """Copy the shared assets into one paper, keeping its own edits.

    A paper may improve a shared file, and that improvement belongs upstream, not
    in the bin. The record says which template content was last written here, so a
    destination matching it is a pristine older copy and safe to replace, while
    anything else was edited locally and is left alone with a warning.
    """
    record = read_record(project)
    skipped = []
    for rel in SHARED_ASSETS:
        src_dir = TEMPLATE / rel
        if not src_dir.is_dir():
            continue
        (project / rel).mkdir(parents=True, exist_ok=True)
        for src in sorted(src_dir.iterdir()):
            if not src.is_file():
                continue
            key = f"{rel}/{src.name}"
            dest = project / rel / src.name
            src_hash = digest(src)
            if dest.exists():
                dest_hash = digest(dest)
                if dest_hash == src_hash:
                    record[key] = src_hash
                    continue
                if not force and record.get(key) not in (None, dest_hash):
                    skipped.append(f"{project.name}/{key}")
                    continue
                if not force and key not in record:
                    # No record at all: this paper predates the record, so its
                    # copy cannot be told apart from a local improvement.
                    skipped.append(f"{project.name}/{key}")
                    continue
            shutil.copy2(src, dest)
            record[key] = src_hash
            print(f"  {project.name}/{key}")
    write_record(project, record)
    return skipped


def cmd_sync_assets(args):
    require_template()
    force = "--force" in args
    name, _ = leading_name([a for a in args if a != "--force"])
    targets = [resolve_project(name)] if name else candidate_projects(Path.cwd())
    if not targets:
        raise SystemExit("No paper projects here.")
    skipped = []
    for project in targets:
        if self_managed(project) and not name:
            print(f"  skipping {project.name}, which is its own git repo")
            continue
        skipped += sync_project(project, force=force)
    print("Shared assets synced. diagrams.js is per paper and was not touched.")
    if skipped:
        print("\nLeft alone because they differ from what was last synced here:")
        for s in skipped:
            print(f"  {s}")
        print("Reconcile by hand, ideally by sending the improvement upstream. "
              "`--force` overwrites.")


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
    elif cmd == "index":
        cmd_index(args)
    elif cmd in ("serve", "build"):
        cmd_mkdocs(cmd, args)
    else:
        raise SystemExit(f"Unknown command {cmd!r}.\n{__doc__}")


# ------------------------------------------------------------
# One landing page over every paper's built site
# ------------------------------------------------------------

INDEX_DIR = "dist"


def site_title(project: Path) -> str:
    """The site_name from a project's mkdocs.yml, for the landing page."""
    cfg = project / "mkdocs.yml"
    if cfg.exists():
        m = re.search(r'^site_name:\s*["\']?(.+?)["\']?\s*$', cfg.read_text(), re.M)
        if m:
            return m.group(1).strip()
    return project.name


def cmd_index(args):
    """Build every paper and gather the results under one landing page.

    Each paper is built by its own mkdocs.yml and copied whole into dist/<name>/,
    so nothing about a paper's site or content changes: this only collects output.
    It works because the template sets `site_url: ""`, which makes mkdocs emit
    relative asset paths, so a built site runs from any subdirectory.

    A nav-merging plugin was the alternative and was rejected: every paper has its
    own diagrams.js and its own nav, and merging would mean editing each paper to
    suit the index.
    """
    projects = [p for p in candidate_projects(Path.cwd()) if (p / "mkdocs.yml").exists()]
    if not projects:
        raise SystemExit("No paper projects here.")
    dist = Path.cwd() / INDEX_DIR
    dist.mkdir(exist_ok=True)

    entries = []
    for project in projects:
        print(f"building {project.name}")
        if subprocess.run(["mkdocs", "build", "-q", "-f",
                           str(project / "mkdocs.yml")]).returncode != 0:
            raise SystemExit(f"{project.name} failed to build; index not written.")
        src = project / "site"
        if not src.is_dir():
            raise SystemExit(f"{project.name} built no site/ directory.")
        dest = dist / project.name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest)
        try:
            crops = len(load_figures(project))
        except SystemExit:
            crops = 0
        entries.append({
            "name": project.name,
            "title": site_title(project),
            "pages": len(list((project / "docs").glob("*.md"))),
            "crops": crops,
        })

    (dist / "index.html").write_text(render_index(entries))
    print(f"\nwrote {dist / 'index.html'} covering {len(entries)} papers")

    if "--serve" in args:
        port = args[args.index("--port") + 1] if "--port" in args else "8000"
        print(f"serving at http://127.0.0.1:{port}/")
        os.execvp(sys.executable,
                  [sys.executable, "-m", "http.server", port, "-d", str(dist)])
    print(f"serve it with:  pixi run index --serve")


INDEX_CSS = """
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         max-width: 46rem; margin: 4rem auto; padding: 0 1.5rem; line-height: 1.6;
         color: #23272b; background: #fff; }
  h1 { font-size: 1.6rem; margin-bottom: 0.2rem; }
  p.lede { color: #666; margin-top: 0; }
  ul { list-style: none; padding: 0; margin-top: 2rem; }
  li { padding: 0.9rem 0; border-top: 1px solid #e7e7e7; }
  li:last-child { border-bottom: 1px solid #e7e7e7; }
  a { text-decoration: none; color: inherit; }
  a:hover .title { text-decoration: underline; }
  .title { font-size: 1.1rem; font-weight: 600; }
  .dir { font-family: ui-monospace, monospace; font-size: 0.8rem; color: #999;
         margin-left: 0.6rem; }
  .meta { font-size: 0.85rem; color: #888; }
  footer { margin-top: 3rem; font-size: 0.85rem; color: #999; }
"""


def render_index(entries) -> str:
    """A dependency-free landing page. Deliberately plain: it is a doorway."""
    rows = []
    for e in entries:
        rows.append(
            '      <li>\n'
            f'        <a href="{e["name"]}/index.html">'
            f'<span class="title">{e["title"]}</span>'
            f'<span class="dir">{e["name"]}</span></a><br>\n'
            f'        <span class="meta">{e["pages"]} pages &middot; '
            f'{e["crops"]} figure crops</span>\n'
            '      </li>'
        )
    return (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<title>Paper explainers</title>\n<style>' + INDEX_CSS + '</style>\n'
        '</head>\n<body>\n  <h1>Paper explainers</h1>\n'
        '  <p class="lede">One interactive site per paper. Each is built by its own\n'
        '  mkdocs configuration and copied here unchanged.</p>\n  <ul>\n'
        + "\n".join(rows) +
        '\n  </ul>\n  <footer>Regenerate with <code>pixi run index</code>. To change a\n'
        '  paper, edit its own directory and rebuild this index.</footer>\n'
        '</body>\n</html>\n'
    )


if __name__ == "__main__":
    main()

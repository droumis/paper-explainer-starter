"""Locate one paper project and load its crop boxes. Paper-agnostic.

Two layouts are supported, and every script resolves them the same way so the
commands read identically in both:

  one paper per repo        the project is the working directory
  several papers in one     the project is a named subdirectory,
                            e.g. `pixi run probe andermann-2011`

A project directory holds the paper's PDF, `figures.toml`, `mkdocs.yml`, `docs/`
and `PAPER.md`. Everything else, this module included, is shared machinery.

Crop boxes live in the project's `figures.toml` rather than in a Python file,
because in a multi-paper repo the extraction script is shared and per-paper
state cannot live inside it.
"""

from dataclasses import dataclass, field
from pathlib import Path

import fitz

try:
    import tomllib
except ModuleNotFoundError:                     # pragma: no cover, py<3.11
    import tomli as tomllib

FIGURES_FILE = "figures.toml"

# What marks a directory as a paper project. `mkdocs.yml` is the reliable one:
# it exists from the moment the project is scaffolded, before any PDF or crop
# box does.
PROJECT_MARKERS = ("mkdocs.yml", FIGURES_FILE)


def looks_like_project(path: Path) -> bool:
    return any((path / m).exists() for m in PROJECT_MARKERS)


def is_scaffold_source(path: Path) -> bool:
    """True for the starter's own `template/`, which is not a paper.

    It carries a mkdocs.yml and a figures.toml so that a project can be copied
    out of it, which makes it indistinguishable from a paper by markers alone.
    """
    return path.name == "template" and (path / "scripts").is_dir()


def candidate_projects(root: Path) -> list[Path]:
    """Paper projects one level below `root`, in sorted order."""
    return sorted(
        p for p in root.iterdir()
        if p.is_dir() and not p.name.startswith(".")
        and looks_like_project(p) and not is_scaffold_source(p)
    )


def resolve_project(name: str | None = None, cwd: Path | None = None) -> Path:
    """Return the paper project directory to operate on.

    `name` wins when given. Otherwise the working directory is used if it is
    itself a project, and failing that a single project directory below it. An
    ambiguous choice is an error listing the candidates, because guessing which
    paper the user meant is how the wrong site gets rebuilt.
    """
    cwd = (cwd or Path.cwd()).resolve()

    if name:
        path = (cwd / name).resolve() if not Path(name).is_absolute() else Path(name)
        if not path.is_dir():
            raise SystemExit(f"No such directory: {name}")
        if is_scaffold_source(path):
            raise SystemExit(
                "template/ is the scaffold every paper is copied out of, not a "
                "paper. Run `pixi run new-paper <name>` and work in that."
            )
        if not looks_like_project(path):
            raise SystemExit(
                f"{name} does not look like a paper project: expected one of "
                f"{', '.join(PROJECT_MARKERS)} inside it.\n"
                f"Run `pixi run new-paper {name}` to scaffold it."
            )
        return path

    if looks_like_project(cwd):
        return cwd

    found = candidate_projects(cwd)
    if len(found) == 1:
        return found[0]
    if not found:
        raise SystemExit(
            f"No paper project found in {cwd}.\n"
            "Run this from a project directory, name one as the first argument, "
            "or scaffold one with `pixi run new-paper <name>`."
        )
    names = " ".join(p.name for p in found)
    raise SystemExit(
        f"Several paper projects in {cwd} ({names}).\n"
        "Name the one you mean as the first argument, e.g. "
        f"`pixi run probe {found[0].name}`."
    )


def split_project_arg(argv: list[str],
                      value_flags: tuple[str, ...] = ()) -> tuple[str | None, list[str]]:
    """Peel the project name out of `argv`, returning it and the other args.

    The name is the first bare token, wherever it sits, because pixi appends
    user arguments after any flags the task already carries: `pixi run
    verify-figures andermann-2011` arrives as `--verify andermann-2011`.

    `value_flags` names the flags that consume the next token, so `--page 10`
    never mistakes `10` for a directory.
    """
    rest: list[str] = []
    name = None
    skip = False
    for token in argv:
        if skip:
            rest.append(token)
            skip = False
            continue
        if token.startswith("-"):
            rest.append(token)
            skip = token in value_flags
            continue
        if name is None:
            name = token
        else:
            rest.append(token)
    return name, rest


def load_figures(project: Path,
                 qualities: dict[str, int] | None = None,
                 ) -> dict[str, tuple[int, fitz.Rect]]:
    """Read `figures.toml` into {name: (page_index, Rect)}.

    Pass `qualities` to also collect each crop's optional WebP quality, which is
    absent for the lossless default.

    Every malformed entry is reported at once, with the file and key named, so
    filling this in is one edit-and-rerun cycle rather than several.
    """
    path = project / FIGURES_FILE
    if not path.exists():
        raise SystemExit(
            f"No {FIGURES_FILE} in {project}.\n"
            f"Copy the one from template/{FIGURES_FILE}, then fill it in from "
            "`pixi run probe --suggest`."
        )
    try:
        data = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as exc:
        raise SystemExit(f"{path}: {exc}") from None

    unknown = sorted(set(data) - {"figures"})
    if unknown:
        raise SystemExit(
            f"{path}: unexpected top-level key(s) {', '.join(unknown)}. "
            "Crops go under [figures.<name>]."
        )

    figures: dict[str, tuple[int, fitz.Rect]] = {}
    qualities = {} if qualities is None else qualities
    problems: list[str] = []
    for name, entry in (data.get("figures") or {}).items():
        if not isinstance(entry, dict):
            problems.append(f"{name}: expected a table, e.g. [figures.{name}]")
            continue
        bad = []
        extra = sorted(set(entry) - {"page", "box", "quality"})
        if extra:
            bad.append(f"{name}: unexpected key(s) {', '.join(extra)}")
        # The markdown scanner in extract_figures matches figures/<name>.png on
        # lowercase, digits and underscores, so a name outside that set would be
        # generated and then reported as unreferenced.
        if not name.replace("_", "").isalnum() or not name.islower():
            bad.append(f"{name}: name must be lowercase letters, digits "
                       "and underscores")
        page = entry.get("page")
        if not isinstance(page, int) or isinstance(page, bool) or page < 0:
            bad.append(f"{name}: page must be a 0-based page index")
        box = entry.get("box")
        if (not isinstance(box, list) or len(box) != 4
                or not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                           for v in box)):
            bad.append(f"{name}: box must be [x0, y0, x1, y1] in points")
        elif box[2] <= box[0] or box[3] <= box[1]:
            bad.append(f"{name}: box is empty or inverted ({box})")
        quality = entry.get("quality")
        if quality is not None and (not isinstance(quality, int)
                                    or isinstance(quality, bool)
                                    or not 1 <= quality <= 100):
            bad.append(f"{name}: quality must be an integer from 1 to 100, or "
                       "absent for lossless")
        problems.extend(bad)
        if not bad:
            figures[name] = (page, fitz.Rect(*box))
            if quality is not None:
                qualities[name] = quality

    if problems:
        raise SystemExit(f"{path} is malformed:\n  " + "\n  ".join(problems))
    return figures


@dataclass(frozen=True)
class Paper:
    """One paper project: where its PDF, crops and docs live."""

    root: Path
    pdf: Path | None
    figures: dict[str, tuple[int, fitz.Rect]]
    # Per-crop WebP quality. A crop absent from here is written lossless, which
    # is the default because these are data figures: hairlines, small axis text
    # and faint points are exactly what lossy compression damages.
    qualities: dict[str, int] = field(default_factory=dict)

    @property
    def docs(self) -> Path:
        return self.root / "docs"

    @property
    def figure_dir(self) -> Path:
        return self.docs / "assets" / "img" / "figures"

    @property
    def pages_dir(self) -> Path:
        return self.figure_dir / "pages"

    @classmethod
    def load(cls, project: Path, *, need_pdf: bool = True,
             need_figures: bool = True) -> "Paper":
        """Load a project, resolving only what the caller needs.

        `--check-refs` compares crop names against the markdown and never opens
        the PDF, so it must not fail on a repo where the paper is not
        redistributable and the PDF is absent.
        """
        from pdf_geometry import find_pdf

        qualities: dict[str, int] = {}
        figures = load_figures(project, qualities) if need_figures else {}
        return cls(
            root=project,
            pdf=find_pdf(project) if need_pdf else None,
            figures=figures,
            qualities=qualities,
        )

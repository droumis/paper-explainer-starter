#!/usr/bin/env python
"""Crop figures out of a paper PDF, refusing to write bad crops.

Crop boxes live in the project's `figures.toml`, not in this file, because one
copy of this script serves every paper in a multi-paper repo. Fill that file in
from `pixi run probe --suggest`, then run `pixi run extract-figures`.

Usage:
    pixi run verify-figures [paper]        checks only, writes nothing
    pixi run extract-figures [paper]       verify, then write the crops
    pixi run check-refs [paper]            crops and markdown agree both ways
    pixi run extract-figures [paper] --pages   full-page renders

`paper` is the project directory, needed only when the repo holds several.

Three checks gate every write, and they exist because each corresponds to a
class of bug that otherwise ships silently:

  verify_crops         no caption or body prose inside a crop
  verify_coverage      no figure content clipped, and none stranded between
                       two crops on the same page
  verify_panel_labels  every panel label lands inside some crop

Confirm the checks actually bite before trusting them: temporarily set a box to
something obviously wrong (a whole page, say) and watch all three complain.
"""

import re
import sys
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).parent))
from pdf_geometry import (  # noqa: E402
    figure_graphics,
    panel_labels,
    prose_words,
)
from project import (  # noqa: E402
    Paper,
    resolve_project,
    split_project_arg,
)

DPI = 250
ZOOM = DPI / 72

# Cap the delivered width of a cropped figure. The site renders these in a
# container roughly 720 px wide, so a 250-DPI crop of a full-width journal
# figure ships several times more pixels than it can display. Wide crops are
# rendered at a lower zoom rather than resampled, which keeps text sharp.
MAX_FIGURE_WIDTH = 1400

# Slack before a graphic straddling a crop edge counts as clipped.
CLIP_TOLERANCE = 2.0
# Minimum size for a graphic to count as real content when looking for material
# stranded between two crops. Below this, stray rules raise false alarms.
MIN_STRANDED_SIZE = 4.0


def by_page(figures):
    grouped = {}
    for name, (page_idx, rect) in figures.items():
        grouped.setdefault(page_idx, []).append((name, rect))
    return grouped


def verify_crops(paper):
    """No crop may contain caption or body prose."""
    doc = fitz.open(str(paper.pdf))
    problems = []
    for name, (page_idx, rect) in paper.figures.items():
        page = doc[page_idx]
        intruders = [t for wrect, t in prose_words(page) if rect.intersects(wrect)]
        if intruders:
            problems.append(f"{name}: {len(intruders)} prose word(s) inside crop: "
                            f"{' '.join(intruders[:8])!r}")
    doc.close()
    if problems:
        print("FAILED: crop boxes overlap prose text")
        for p in problems:
            print(f"  {p}")
        return False
    print(f"  all {len(paper.figures)} crop boxes clear of caption and body text")
    return True


def verify_coverage(paper):
    """No crop may slice through figure content, and none may be stranded.

    Two ways content is lost. A crop cuts through a graphic, or a graphic falls
    entirely between two crops on the same page so it intersects neither.
    Splitting a figure into per-page crops creates exactly those gaps.
    """
    doc = fitz.open(str(paper.pdf))
    problems = []
    for page_idx, crops in by_page(paper.figures).items():
        page = doc[page_idx]
        graphics = list(figure_graphics(page))
        for name, rect in crops:
            worst = None
            for grect in graphics:
                if not rect.intersects(grect):
                    continue
                overhang = max(rect.x0 - grect.x0, rect.y0 - grect.y0,
                               grect.x1 - rect.x1, grect.y1 - rect.y1)
                if overhang > CLIP_TOLERANCE and (worst is None or overhang > worst[0]):
                    worst = (overhang, grect)
            if worst:
                overhang, grect = worst
                problems.append(
                    f"{name}: crop clips figure content by {overhang:.1f}pt "
                    f"(graphic [{grect.x0:.0f},{grect.y0:.0f},{grect.x1:.0f},{grect.y1:.0f}])")

        prose = [wrect for wrect, _ in prose_words(page)]
        for grect in graphics:
            if grect.width < MIN_STRANDED_SIZE and grect.height < MIN_STRANDED_SIZE:
                continue
            if any(rect.intersects(grect) for _, rect in crops):
                continue
            if any(grect.intersects(p) for p in prose):
                continue                  # decoration inside prose, not a panel
            problems.append(
                f"page {page_idx}: figure content at "
                f"[{grect.x0:.0f},{grect.y0:.0f},{grect.x1:.0f},{grect.y1:.0f}] "
                f"falls in no crop box")
    doc.close()
    if problems:
        print("FAILED: crop boxes clip or strand figure content")
        for p in problems:
            print(f"  {p}")
        return False
    print(f"  all {len(paper.figures)} crop boxes contain their figure content")
    return True


def verify_panel_labels(paper):
    """Every panel label must land inside some crop for its page.

    Direct guard against the worst failure mode: a caption describing a panel
    the reader cannot see.
    """
    doc = fitz.open(str(paper.pdf))
    problems = []
    for page_idx, crops in by_page(paper.figures).items():
        page = doc[page_idx]
        for rect, letter in panel_labels(page):
            if not any(crop.contains(rect) for _, crop in crops):
                problems.append(f"page {page_idx}: panel label {letter!r} at "
                                f"[{rect.x0:.0f},{rect.y0:.0f}] is in no crop box")
    doc.close()
    if problems:
        print("FAILED: panel labels fall outside every crop box")
        for p in problems:
            print(f"  {p}")
        return False
    print("  every panel label is inside a crop box")
    return True


# Both `--verify` and the write path gate on this one list, so they can never
# disagree about what "verified" means. Add new checks here.
CHECKS = (verify_crops, verify_coverage, verify_panel_labels)


def verify_all(paper):
    # An empty figures.toml makes every check vacuously true, so `--verify`
    # would report success on a project where no figures have been defined yet.
    # In CI that is a green build on unfinished work, so treat it as a failure.
    if not paper.figures:
        print(f"FAILED: no crops defined in {paper.root / 'figures.toml'}, "
              "so there is nothing to verify.")
        print("  Run `pixi run probe --suggest` to get candidate crop boxes.")
        return False
    # A list, not a generator, so every check runs and reports rather than
    # short-circuiting at the first failure.
    return all([check(paper) for check in CHECKS])


def crop_figures(paper):
    if not verify_all(paper):
        raise SystemExit("Refusing to write figures with bad crop boxes.")

    paper.figure_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(str(paper.pdf))
    for name, (page_idx, rect) in paper.figures.items():
        page = doc[page_idx]
        zoom = min(ZOOM, MAX_FIGURE_WIDTH / rect.width)
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=rect)
        out_path = paper.figure_dir / f"{name}.png"
        pix.save(str(out_path))
        kb = out_path.stat().st_size / 1024
        print(f"  {name}.png ({pix.width}x{pix.height}, {kb:.0f} KB)")
    doc.close()


def render_all_pages(paper, zoom=2.0):
    """Full-page renders, for identifying which page holds which figure."""
    paper.pages_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(str(paper.pdf))
    for i, page in enumerate(doc):
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        pix.save(str(paper.pages_dir / f"page_{i:02d}.png"))
    print(f"  wrote {len(doc)} page renders to {paper.pages_dir}")
    doc.close()


def check_references(paper):
    """Cross-check figures against the markdown, in both directions.

    The second direction catches stale orphans: if a key is renamed but the
    markdown is not updated, the page keeps rendering an old file that
    re-running extraction never regenerates, so fixing a crop box appears to do
    nothing at all.
    """
    md = "\n".join(p.read_text() for p in paper.docs.glob("*.md"))
    ok = True
    for name in paper.figures:
        if f"{name}.png" not in md:
            print(f"  generated but unreferenced: {name}.png")
            ok = False
    for ref in sorted(set(re.findall(r"figures/([a-z0-9_]+)\.png", md))):
        if not (paper.figure_dir / f"{ref}.png").exists():
            print(f"  referenced but missing: {ref}.png")
            ok = False
    if ok:
        print("  figure references resolve in both directions")
    return ok


def main(argv=None):
    name, args = split_project_arg(sys.argv[1:] if argv is None else argv)
    project = resolve_project(name)
    if project != Path.cwd():
        print(f"paper: {project.name}")

    if "--check-refs" in args:
        paper = Paper.load(project, need_pdf=False)
        raise SystemExit(0 if check_references(paper) else 1)

    paper = Paper.load(project, need_figures="--pages" not in args)
    print(f"PDF: {paper.pdf.name}")
    if "--pages" in args:
        render_all_pages(paper)
    elif "--verify" in args:
        raise SystemExit(0 if verify_all(paper) else 1)
    else:
        crop_figures(paper)


if __name__ == "__main__":
    main()

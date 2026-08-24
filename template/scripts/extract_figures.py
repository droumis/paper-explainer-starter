#!/usr/bin/env python
"""Crop figures out of the paper PDF, refusing to write bad crops.

Fill in FIGURES below, then run `pixi run extract-figures`. Use
`pixi run probe --suggest` to get candidate boxes rather than guessing.

Three checks gate every write, and they exist because each corresponds to a
class of bug that otherwise ships silently:

  verify_crops         no caption or body prose inside a crop
  verify_coverage      no figure content clipped, and none stranded between
                       two crops on the same page
  verify_panel_labels  every panel label lands inside some crop

Confirm the checks actually bite before trusting them: temporarily set a box to
something obviously wrong (a whole page, say) and watch all three complain.
"""

import sys
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).parent))
from pdf_geometry import (  # noqa: E402
    figure_graphics,
    find_pdf,
    panel_labels,
    prose_words,
)

ROOT = Path(__file__).parent.parent
PDF_PATH = find_pdf(ROOT)
OUT_DIR = ROOT / "docs" / "assets" / "img" / "figures"
PAGES_DIR = OUT_DIR / "pages"

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


# ---------------------------------------------------------------------------
# FIGURES: one entry per crop, keyed by the filename used in docs/*.md.
#
# Page indices are 0-based PyMuPDF indices and do NOT match the paper's printed
# page numbers. Get them from `pixi run probe`.
#
# ONE CROP PER CLAIM. If a figure's panels serve different site pages, split it
# into several entries so each page's caption describes exactly what is visible.
# Naming a crop after its panels (fig6ab_..., fig6c_..., fig6de_...) keeps that
# honest.
# ---------------------------------------------------------------------------
FIGURES: dict[str, tuple[int, fitz.Rect]] = {
    # "fig1_task": (2, fitz.Rect(56, 98, 297, 307)),
}


def verify_crops():
    """No crop may contain caption or body prose."""
    doc = fitz.open(str(PDF_PATH))
    problems = []
    for name, (page_idx, rect) in FIGURES.items():
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
    print(f"  all {len(FIGURES)} crop boxes clear of caption and body text")
    return True


def verify_coverage():
    """No crop may slice through figure content, and none may be stranded.

    Two ways content is lost. A crop cuts through a graphic, or a graphic falls
    entirely between two crops on the same page so it intersects neither.
    Splitting a figure into per-page crops creates exactly those gaps.
    """
    doc = fitz.open(str(PDF_PATH))
    by_page = {}
    for name, (page_idx, rect) in FIGURES.items():
        by_page.setdefault(page_idx, []).append((name, rect))

    problems = []
    for page_idx, crops in by_page.items():
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
    print(f"  all {len(FIGURES)} crop boxes contain their figure content")
    return True


def verify_panel_labels():
    """Every panel label must land inside some crop for its page.

    Direct guard against the worst failure mode: a caption describing a panel
    the reader cannot see.
    """
    doc = fitz.open(str(PDF_PATH))
    by_page = {}
    for name, (page_idx, rect) in FIGURES.items():
        by_page.setdefault(page_idx, []).append((name, rect))

    problems = []
    for page_idx, crops in by_page.items():
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


def verify_all():
    # A list, not a generator, so every check runs and reports rather than
    # short-circuiting at the first failure.
    return all([check() for check in CHECKS])


def crop_figures():
    if not FIGURES:
        raise SystemExit(
            "FIGURES is empty. Run `pixi run probe --suggest` to get candidate\n"
            "boxes, paste them in, then re-run this."
        )
    if not verify_all():
        raise SystemExit("Refusing to write figures with bad crop boxes.")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(str(PDF_PATH))
    for name, (page_idx, rect) in FIGURES.items():
        page = doc[page_idx]
        zoom = min(ZOOM, MAX_FIGURE_WIDTH / rect.width)
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=rect)
        out_path = OUT_DIR / f"{name}.png"
        pix.save(str(out_path))
        kb = out_path.stat().st_size / 1024
        print(f"  {name}.png ({pix.width}x{pix.height}, {kb:.0f} KB)")
    doc.close()


def render_all_pages(zoom=2.0):
    """Full-page renders, for identifying which page holds which figure."""
    PAGES_DIR.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(str(PDF_PATH))
    for i, page in enumerate(doc):
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        pix.save(str(PAGES_DIR / f"page_{i:02d}.png"))
    print(f"  wrote {len(doc)} page renders to {PAGES_DIR}")
    doc.close()


def check_references(docs_dir=None):
    """Cross-check figures against the markdown, in both directions.

    The second direction catches stale orphans: if a key is renamed but the
    markdown is not updated, the page keeps rendering an old file that
    re-running extraction never regenerates, so fixing a crop box appears to do
    nothing at all.
    """
    docs_dir = docs_dir or (ROOT / "docs")
    md = "\n".join(p.read_text() for p in docs_dir.glob("*.md"))
    ok = True
    for name in FIGURES:
        if f"{name}.png" not in md:
            print(f"  generated but unreferenced: {name}.png")
            ok = False
    import re
    for ref in sorted(set(re.findall(r"figures/([a-z0-9_]+)\.png", md))):
        if not (OUT_DIR / f"{ref}.png").exists():
            print(f"  referenced but missing: {ref}.png")
            ok = False
    if ok:
        print("  figure references resolve in both directions")
    return ok


if __name__ == "__main__":
    args = sys.argv[1:]
    print(f"PDF: {PDF_PATH.name}")
    if "--pages" in args:
        render_all_pages()
    elif "--verify" in args:
        raise SystemExit(0 if verify_all() else 1)
    elif "--check-refs" in args:
        raise SystemExit(0 if check_references() else 1)
    else:
        crop_figures()

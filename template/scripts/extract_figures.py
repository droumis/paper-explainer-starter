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
  verify_coverage      no figure graphic clipped, and none stranded between
                       two crops on the same page
  verify_figure_text   same, for the figure's own text: axis labels, tick
                       labels and orientation markers
  verify_panel_labels  every panel label lands inside some crop

Confirm the checks actually bite before trusting them: temporarily set a box to
something obviously wrong (a whole page, say) and watch them complain.
"""

import io
import re
import sys
from pathlib import Path

import fitz
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from pdf_geometry import (  # noqa: E402
    figure_graphics,
    figure_text,
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

# Crops are written as WebP. Lossless WebP is about 60% of the equivalent PNG at
# identical pixels, and a per-figure `quality` in figures.toml turns on lossy
# compression for photographic panels, where it saves far more.
FIGURE_EXT = "webp"

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
        graphics = list(figure_graphics(page, paper.header_y, paper.footer_y))
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


def verify_figure_text(paper):
    """No crop may slice through the figure's own text, or strand it.

    `verify_coverage` looks at drawings and images, so an axis label, a tick
    label or an anatomical orientation marker can be sliced in half without any
    check objecting. The rendered crop then shows half a word, which no amount
    of caption care can repair.

    Scoped to text intersecting the union of a page's crops, so section headings
    and running heads elsewhere on the page raise no false alarms.
    """
    doc = fitz.open(str(paper.pdf))
    problems = []
    for page_idx, crops in by_page(paper.figures).items():
        page = doc[page_idx]
        union = fitz.Rect(crops[0][1])
        for _, rect in crops[1:]:
            union |= rect

        for wrect, text in figure_text(page, paper.header_y, paper.footer_y):
            if not wrect.intersects(union):
                continue                  # elsewhere on the page, not our business
            hits = [(name, rect) for name, rect in crops if rect.intersects(wrect)]
            if not hits:
                problems.append(
                    f"page {page_idx}: figure text {text!r} at "
                    f"[{wrect.x0:.0f},{wrect.y0:.0f}] falls between crops")
                continue
            for name, rect in hits:
                overhang = max(rect.x0 - wrect.x0, rect.y0 - wrect.y0,
                               wrect.x1 - rect.x1, wrect.y1 - rect.y1)
                if overhang > CLIP_TOLERANCE:
                    problems.append(
                        f"{name}: crop slices figure text {text!r} at "
                        f"[{wrect.x0:.0f},{wrect.y0:.0f}] by {overhang:.1f}pt")
    doc.close()
    if problems:
        print("FAILED: crop boxes slice or strand the figure's own text")
        for p in problems:
            print(f"  {p}")
        return False
    print("  no crop slices or strands the figure's own text")
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
CHECKS = (verify_crops, verify_coverage, verify_figure_text,
          verify_panel_labels)


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


def write_crop(pix, out_path, quality=None):
    """Write one crop as WebP, lossless unless a quality is given.

    Lossless is the default because a figure crop is data: hairlines, small axis
    text and faint scatter points are what lossy compression damages first, and a
    reader cannot tell an artefact from a measurement. It still lands around 60%
    of the equivalent PNG.

    Set `quality` per figure in figures.toml for a photographic panel, where the
    saving is far larger: a histology or wide-field image at quality 90 is
    roughly a sixth of the PNG with no visible difference at display size.
    """
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    if quality is None:
        img.save(out_path, format="WEBP", lossless=True, method=6)
    else:
        img.save(out_path, format="WEBP", quality=quality, method=6)


def crop_figures(paper):
    if not verify_all(paper):
        raise SystemExit("Refusing to write figures with bad crop boxes.")

    paper.figure_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(str(paper.pdf))
    for name, (page_idx, rect) in paper.figures.items():
        page = doc[page_idx]
        zoom = min(ZOOM, MAX_FIGURE_WIDTH / rect.width)
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=rect)
        quality = paper.qualities.get(name)
        out_path = paper.figure_dir / f"{name}.{FIGURE_EXT}"
        write_crop(pix, out_path, quality)
        kb = out_path.stat().st_size / 1024
        how = "lossless" if quality is None else f"quality {quality}"
        print(f"  {out_path.name} ({pix.width}x{pix.height}, {kb:.0f} KB, {how})")
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
    # Both extensions are accepted, so a site written before crops became WebP
    # keeps verifying until it is converted.
    for name in paper.figures:
        if not any(f"{name}.{ext}" in md for ext in ("webp", "png")):
            print(f"  generated but unreferenced: {name}.{FIGURE_EXT}")
            ok = False
    for ref, ext in sorted(set(re.findall(r"figures/([a-z0-9_]+)\.(webp|png)", md))):
        if not (paper.figure_dir / f"{ref}.{ext}").exists():
            print(f"  referenced but missing: {ref}.{ext}")
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

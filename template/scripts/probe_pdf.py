#!/usr/bin/env python
"""Report a PDF's structure so figure crop boxes can be derived, not guessed.

Run this BEFORE writing any crop boxes. Deriving boxes from the document's own
geometry is the difference between figures that are tight and correct and
figures that include the journal logo, bleed into the text column, and cut off
the panels your captions describe.

Usage:
    pixi run probe                      # page inventory: which pages have figures
    pixi run probe --page 10            # everything about one page
    pixi run probe --suggest            # proposed crop boxes for every figure page
    pixi run probe --render 10          # write a PNG of one page to inspect
    pixi run probe --render-all         # write PNGs of every page

Typical workflow:
    1. `--suggest` to get candidate boxes and the panel labels on each page.
    2. Paste the boxes into FIGURES in extract_figures.py, splitting any page
       whose panels serve different site pages.
    3. `pixi run extract-figures --verify` until all checks pass.
"""

import sys
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).parent))
from pdf_geometry import (  # noqa: E402
    caption_blocks,
    content_bbox,
    figure_graphics,
    find_pdf,
    panel_labels,
    prose_words,
    suggest_crop,
)

ROOT = Path(__file__).parent.parent
OUT_DIR = ROOT / "docs" / "assets" / "img" / "figures" / "pages"


def fmt(r):
    return f"[{r.x0:6.1f},{r.y0:6.1f},{r.x1:6.1f},{r.y1:6.1f}]"


def inventory(doc):
    """Which pages carry figures, and where are their panels."""
    print(f"{len(doc)} pages, page size {doc[0].rect.width:.0f} x {doc[0].rect.height:.0f} pt\n")
    print("page  graphics  panels                caption starts with")
    print("-" * 78)
    for i, page in enumerate(doc):
        gfx = list(figure_graphics(page))
        labels = [t for _, t in panel_labels(page)]
        caps = [t for _, t in caption_blocks(page)]
        if not gfx and not caps:
            continue
        cap = caps[0][:34] if caps else ""
        print(f"{i:4d}  {len(gfx):8d}  {''.join(sorted(set(labels))):20s}  {cap}")
    print("\nPage indices above are 0-based and do NOT match the paper's printed")
    print("page numbers. Always use these indices in FIGURES.")


def detail(doc, idx):
    page = doc[idx]
    print(f"=== page {idx}  ({page.rect.width:.0f} x {page.rect.height:.0f} pt) ===\n")

    print("PANEL LABELS (use these to decide where one figure ends):")
    for rect, letter in sorted(panel_labels(page), key=lambda t: (t[0].y0, t[0].x0)):
        print(f"  {letter}  at {fmt(rect)}")

    print("\nCAPTIONS / TABLE BLOCKS:")
    for rect, text in caption_blocks(page):
        print(f"  {fmt(rect)}  {text}")

    print("\nPROSE EXTENT (crop boxes must not overlap these):")
    words = list(prose_words(page))
    if words:
        xs = [r.x0 for r, _ in words] + [r.x1 for r, _ in words]
        ys = [r.y0 for r, _ in words] + [r.y1 for r, _ in words]
        print(f"  {len(words)} prose words spanning x {min(xs):.0f}..{max(xs):.0f}, "
              f"y {min(ys):.0f}..{max(ys):.0f}")
        # column structure matters: two-column pages often indent around figures
        left = [r for r, _ in words if r.x0 < page.rect.width / 2]
        right = [r for r, _ in words if r.x0 >= page.rect.width / 2]
        if left and right:
            print(f"  left column  x from {min(r.x0 for r in left):.0f}")
            print(f"  right column x from {min(r.x0 for r in right):.0f}"
                  "   <- if this is indented, a wide figure sits beside it")
    else:
        print("  none")

    box = content_bbox(page)
    print(f"\nFIGURE GRAPHICS UNION: {fmt(box) if box else 'none'}")
    print(f"  ({len(list(figure_graphics(page)))} elements, clip-aware)")

    s, notes = suggest_crop(page)
    print(f"\nSUGGESTED CROP (whole page): {fmt(s) if s else 'none'}")
    for n in notes:
        print(f"  ! {n}")
    print("  Verify before trusting it. If the page holds several figures, or")
    print("  panels that belong on different site pages, split it by hand using")
    print("  the panel label positions above.")


def suggest_all(doc):
    print("Candidate crop boxes. Split any page whose panels serve different")
    print("site pages, then paste into FIGURES in extract_figures.py.\n")
    for i, page in enumerate(doc):
        if not list(figure_graphics(page)):
            continue
        s, notes = suggest_crop(page)
        if not s:
            continue
        labels = "".join(sorted({t for _, t in panel_labels(page)}))
        print(f'    # page {i}: panels {labels or "(none detected)"}')
        for n in notes:
            print(f'    #   ! {n}')
        print(f'    "figN_name": ({i}, fitz.Rect('
              f'{s.x0:.0f}, {s.y0:.0f}, {s.x1:.0f}, {s.y1:.0f})),')


def render(doc, idx, zoom=2.0):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    page = doc[idx]
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    out = OUT_DIR / f"page_{idx:02d}.png"
    pix.save(str(out))
    print(f"  wrote {out}  ({pix.width}x{pix.height})")


def main():
    pdf = find_pdf(ROOT)
    print(f"PDF: {pdf.name}\n")
    doc = fitz.open(str(pdf))

    args = sys.argv[1:]
    if "--page" in args:
        detail(doc, int(args[args.index("--page") + 1]))
    elif "--suggest" in args:
        suggest_all(doc)
    elif "--render" in args:
        render(doc, int(args[args.index("--render") + 1]))
    elif "--render-all" in args:
        for i in range(len(doc)):
            render(doc, i)
    else:
        inventory(doc)
    doc.close()


if __name__ == "__main__":
    main()

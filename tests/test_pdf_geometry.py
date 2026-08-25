#!/usr/bin/env python
"""Tests for the figure-geometry machinery, against a synthetic PDF.

No real paper needed: `build_fixture()` fabricates a page laid out like a
journal figure page, including the three things that make naive geometry wrong.
Every assertion here corresponds to a bug that shipped in a real site.

Run:  pixi run test-python
"""

import sys
from pathlib import Path

import fitz

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "template" / "scripts"))

import pdf_geometry as G  # noqa: E402

PAGE_W, PAGE_H = 603, 783

# Fixture layout, in points. A two-column page: a figure occupying the upper
# area, a caption below it, and a body column on the right that is indented to
# make room for the figure.
FIG_BOX = fitz.Rect(60, 110, 380, 420)
PANEL_A = (66, 116)
PANEL_B = (66, 280)
CAPTION_Y = 440
BODY_X = 400          # right column, indented clear of the figure

# The clipped band: filled CLIP_FILL_W wide, clipped to CLIP_VISIBLE_W.
CLIP_X0 = 200
CLIP_BAND_BOTTOM = 400
CLIP_BAND_H = 50
CLIP_VISIBLE_W = 160          # clip stops the fill here
CLIP_FILL_W = 360             # the fill's own width, reaching into the body


def build_fixture(path: Path):
    doc = fitz.open()
    page = doc.new_page(width=PAGE_W, height=PAGE_H)

    # Running header and footer, which must be ignored as figure content.
    page.insert_text((60, 40), "JOURNAL NAME  Vol 1", fontsize=8)
    page.insert_text((60, 770), "114  Neuron 90, 113-127", fontsize=8)

    # Figure content: a filled rect, an axis line (zero height), a tick (zero
    # width), and an embedded-style shape.
    page.draw_rect(fitz.Rect(90, 140, 240, 260), color=(0, 0, 0), fill=(0.8, 0.85, 1))
    page.draw_line(fitz.Point(90, 300), fitz.Point(300, 300))          # zero height
    page.draw_line(fitz.Point(120, 300), fitz.Point(120, 340))         # zero width
    page.draw_rect(fitz.Rect(260, 150, 370, 410), color=(0, 0, 0))

    # A genuinely clipped path: the fill spans x 200..560, reaching into the body
    # column, but the clip stops it at x=360. Naive geometry reports the fill's
    # own rect and concludes the figure covers the text column. Nothing in the
    # PyMuPDF drawing API emits a clip, so write the operators directly.
    # PDF space is bottom-up, so y_pdf = PAGE_H - y_top.
    y_pdf = PAGE_H - CLIP_BAND_BOTTOM
    ops = (f"\nq {CLIP_X0} {y_pdf} {CLIP_VISIBLE_W} {CLIP_BAND_H} re W n\n"
           f"1 0.94 0 rg {CLIP_X0} {y_pdf} {CLIP_FILL_W} {CLIP_BAND_H} re f\nQ\n")
    xref = page.get_contents()[0]
    doc.update_stream(xref, doc.xref_stream(xref) + ops.encode())

    # Panel labels: single capitals, part of the figure.
    page.insert_text(PANEL_A, "A", fontsize=11)
    page.insert_text(PANEL_B, "B", fontsize=11)

    # An anatomical orientation marker, which looks exactly like a panel label.
    page.insert_text((330, 170), "M", fontsize=8)

    # Caption: prose, must never end up inside a crop.
    caption = ("Figure 1. A synthetic figure used for testing. (A) The upper "
               "panel shows nothing in particular. (B) The lower panel likewise "
               "shows nothing, but it does so at greater length so that this "
               "block is unambiguously prose rather than a label.")
    page.insert_textbox(fitz.Rect(60, CAPTION_Y, 380, CAPTION_Y + 90), caption,
                        fontsize=8)

    # Body column, indented to the right of the figure.
    body = ("This paragraph exists to occupy the right hand column with enough "
            "words that the block is classified as prose. It is indented so "
            "that a wide figure can sit beside it, which is exactly the layout "
            "that makes text block bounding boxes unreliable.")
    page.insert_textbox(fitz.Rect(BODY_X, 110, 550, 420), body, fontsize=8)

    doc.save(str(path))
    doc.close()


# ---------------------------------------------------------------------------

def check(name, condition, detail=""):
    mark = "ok  " if condition else "FAIL"
    print(f"  {mark} {name}" + (f"  ({detail})" if detail and not condition else ""))
    return bool(condition)


def main():
    tmp = ROOT / "tests" / "_fixture.pdf"
    build_fixture(tmp)
    doc = fitz.open(str(tmp))
    page = doc[0]
    passed = []

    print("prose detection")
    words = list(G.prose_words(page))
    texts = {t for _, t in words}
    passed.append(check("finds caption words", "Figure" in texts))
    passed.append(check("finds body column words", "indented" in texts))
    label_rects = [r for r, t in G.panel_labels(page) if t == "A"]
    prose_rects = [r for r, _ in words]
    passed.append(check(
        "the panel label A is not classified as prose",
        label_rects and not any(label_rects[0].intersects(pr) for pr in prose_rects),
        "note: 'A' also appears as a caption word, so this must be positional"))

    print("\npanel labels")
    labels = {t for _, t in G.panel_labels(page)}
    passed.append(check("finds A and B", {"A", "B"} <= labels, f"got {labels}"))
    passed.append(check("also finds the orientation marker M, a known false "
                        "positive", "M" in labels))

    print("\nfigure graphics")
    gfx = list(G.figure_graphics(page))
    passed.append(check("finds some graphics", len(gfx) > 0, f"got {len(gfx)}"))
    passed.append(check("ignores the running header",
                        all(r.y1 >= G.HEADER_Y for r in gfx)))
    passed.append(check("ignores the footer",
                        all(r.y0 <= G.FOOTER_Y for r in gfx)))
    zero_h = [r for r in gfx if abs(r.y1 - r.y0 - G.DEGENERATE_PAD) < 1e-6]
    passed.append(check("keeps the zero-height axis line, padded",
                        len(zero_h) > 0))
    passed.append(check("padded degenerate rects are non-empty for intersects()",
                        all(not r.is_empty for r in gfx)))
    band = [r for r in gfx if abs(r.y0 - (CLIP_BAND_BOTTOM - CLIP_BAND_H)) < 2
            and r.x0 <= CLIP_X0 + 1]
    clipped_ok = band and max(r.x1 for r in band) <= CLIP_X0 + CLIP_VISIBLE_W + 1
    passed.append(check(
        "a clipped path is reported at its VISIBLE width, not its fill width",
        clipped_ok,
        f"expected x1<={CLIP_X0 + CLIP_VISIBLE_W}, got "
        f"{max((r.x1 for r in band), default=None)}"))
    passed.append(check("no graphic reaches the body column",
                        all(r.x1 <= BODY_X for r in gfx),
                        f"max x1={max(r.x1 for r in gfx):.0f}"))

    print("\ncrop suggestion")
    box, notes = G.suggest_crop(page)
    passed.append(check("proposes a box", box is not None))
    if box:
        passed.append(check("box includes panel label A",
                            box.x0 <= PANEL_A[0] and box.y0 <= PANEL_A[1],
                            f"box={box}"))
        overlaps = [t for r, t in words if box.intersects(r)]
        passed.append(check("box excludes all prose", not overlaps,
                            f"swallowed {overlaps[:3]}"))

    doc.close()

    # ---- the three checks, driven through extract_figures
    print("\ncrop checks (via extract_figures)")
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "ef", ROOT / "template" / "scripts" / "extract_figures.py")
    ef = importlib.util.module_from_spec(spec)
    # extract_figures resolves the PDF at import time, so point it at the fixture
    sys.argv = ["ef"]
    orig_find = G.find_pdf
    G.find_pdf = lambda root: tmp
    try:
        spec.loader.exec_module(ef)
    finally:
        G.find_pdf = orig_find
    ef.PDF_PATH = tmp

    import io
    import contextlib

    def run(figs):
        ef.FIGURES = figs
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            result = ef.verify_all()
        return result, buf.getvalue()

    # Assert the end-to-end property that matters: a box produced by
    # suggest_crop must satisfy all three checks. On a real paper the first
    # version of suggest_crop failed the panel-label check on every page, which
    # is exactly the regression this guards.
    ok, out = run({"fig": (0, box)})
    passed.append(check("a box from suggest_crop passes all three", ok,
                        out.strip().splitlines()[-1] if not ok else ""))

    ok, out = run({"fig": (0, fitz.Rect(56, 106, 560, 520))})
    passed.append(check("a box containing prose is rejected",
                        not ok and "prose" in out))

    ok, out = run({"fig": (0, fitz.Rect(56, 106, 384, 250))})
    passed.append(check("a box clipping content is rejected",
                        not ok and ("clip" in out or "falls in no crop" in out)))

    ok, out = run({"fig": (0, fitz.Rect(56, 200, 384, 424))})
    passed.append(check("a box omitting a panel label is rejected",
                        not ok and "panel label" in out))

    ok, out = run({"top": (0, fitz.Rect(56, 106, 384, 200)),
                   "bot": (0, fitz.Rect(56, 320, 384, 424))})
    passed.append(check("content stranded between two crops is rejected",
                        not ok and "falls in no crop" in out))

    ok, out = run({})
    passed.append(check("an empty FIGURES is rejected, not vacuously passed",
                        not ok and "empty" in out))

    tmp.unlink(missing_ok=True)
    print(f"\n{sum(passed)}/{len(passed)} checks passed")
    return 0 if all(passed) else 1


if __name__ == "__main__":
    raise SystemExit(main())

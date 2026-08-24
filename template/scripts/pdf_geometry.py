"""Derive figure geometry from a PDF's own structure.

Paper-agnostic. Every function here answers a question you would otherwise
answer by squinting at a page render, which is how bad crop boxes get shipped.

Three traps this module exists to handle, all of which produce silently wrong
answers if you use PyMuPDF naively:

1. **Clipped paths report unclipped geometry.** A shape clipped to a figure can
   claim a rectangle reaching deep into the caption column. `figure_graphics`
   tracks the clip stack and intersects each path with its active scissor.

2. **Block bounding boxes overclaim.** In two-column layouts the body column is
   often indented around a wide figure, so a block bbox covers territory that
   contains no glyphs. `prose_words` tests individual words instead.

3. **Zero-thickness rects are invisible to intersection tests.**
   `fitz.Rect.intersects()` returns False for any empty rect, so every axis
   line, rule and tick mark would be exempt from geometric checks. They are
   padded rather than dropped.
"""

from pathlib import Path

import fitz

# A text block counts as prose (caption or body copy) only if it has at least
# this many words AND is wider than PROSE_MIN_WIDTH. The width test excludes
# rotated axis labels, which are narrow, word-rich, and part of the figure.
PROSE_WORD_COUNT = 12
PROSE_MIN_WIDTH = 60.0

# Zero-thickness rects (axis lines, rules, ticks) are real figure content, but
# intersection tests ignore empty rects. Give each degenerate axis this much
# extent so the geometry behaves.
DEGENERATE_PAD = 0.5

# Content above/below these page offsets is running header or footer.
HEADER_Y = 95.0
FOOTER_Y = 745.0

# A drawing wider than this fraction of the page is a background or a full-width
# rule, not figure content.
MAX_CONTENT_WIDTH_FRAC = 0.85


def find_pdf(root: Path) -> Path:
    """Return the single PDF in `root`, or raise with a useful message.

    The starter deliberately does not hardcode a filename: drop any PDF in the
    project root and the tooling finds it.
    """
    pdfs = sorted(p for p in root.glob("*.pdf") if not p.name.startswith("."))
    if not pdfs:
        raise SystemExit(
            f"No PDF found in {root}. Drop the paper's PDF in the project root."
        )
    if len(pdfs) > 1:
        names = ", ".join(p.name for p in pdfs)
        raise SystemExit(
            f"Found several PDFs in {root} ({names}). Keep one, or set PDF_PATH "
            "explicitly in scripts/extract_figures.py."
        )
    return pdfs[0]


def prose_words(page):
    """Yield (rect, text) for every word belonging to a prose text block."""
    prose_blocks = set()
    for block in page.get_text("blocks"):
        x0, _, x1, _, text, block_no = block[0], block[1], block[2], block[3], block[4], block[5]
        if len(text.split()) >= PROSE_WORD_COUNT and (x1 - x0) >= PROSE_MIN_WIDTH:
            prose_blocks.add(block_no)
    for word in page.get_text("words"):
        x0, y0, x1, y1, text, block_no = word[0], word[1], word[2], word[3], word[4], word[5]
        if block_no in prose_blocks:
            yield fitz.Rect(x0, y0, x1, y1), text


def figure_graphics(page):
    """Yield rects of drawings and images that are plausibly figure content."""
    page_width = page.rect.width
    clip_stack = []
    for item in page.get_drawings(extended=True):
        level = item.get("level", 0)
        while clip_stack and clip_stack[-1][0] >= level:
            clip_stack.pop()
        if item["type"] == "clip":
            scissor = item.get("scissor")
            if scissor is not None:
                clip_stack.append((level, fitz.Rect(scissor)))
            continue
        rect = item.get("rect")
        if rect is None:
            continue
        rect = fitz.Rect(rect)
        for _, scissor in clip_stack:
            rect.intersect(scissor)
        if rect.width <= 0 and rect.height <= 0:
            continue                      # a single point protects nothing
        if rect.width <= 0:
            rect.x1 += DEGENERATE_PAD
        if rect.height <= 0:
            rect.y1 += DEGENERATE_PAD
        if rect.width > MAX_CONTENT_WIDTH_FRAC * page_width:
            continue
        if rect.y1 < HEADER_Y or rect.y0 > FOOTER_Y:
            continue
        yield rect
    for info in page.get_image_info():
        yield fitz.Rect(*info["bbox"])


def panel_labels(page):
    """Yield (rect, letter) for each single-capital-letter panel label.

    Letters sitting inside prose are skipped, so a sentence starting with "A"
    is not mistaken for a panel marker.
    """
    prose = [r for r, _ in prose_words(page)]
    for word in page.get_text("words"):
        x0, y0, x1, y1, text = word[0], word[1], word[2], word[3], word[4]
        if len(text) != 1 or not text.isupper() or not text.isalpha():
            continue
        rect = fitz.Rect(x0, y0, x1, y1)
        if any(rect.intersects(p) for p in prose):
            continue
        yield rect, text


def caption_blocks(page):
    """Yield (rect, first words) for blocks that look like figure captions."""
    for block in page.get_text("blocks"):
        text = " ".join(block[4].split())
        if not text:
            continue
        low = text.lower()
        if low.startswith("figure") or low.startswith("fig.") or low.startswith("table"):
            yield fitz.Rect(block[0], block[1], block[2], block[3]), text[:90]


def content_bbox(page):
    """Union of figure graphics on a page, or None if there are none."""
    rects = list(figure_graphics(page))
    if not rects:
        return None
    box = fitz.Rect(rects[0])
    for r in rects[1:]:
        box |= r
    return box


def suggest_crop(page, y0=None, y1=None, pad=3.0):
    """Propose a crop box for a page, optionally limited to a vertical band.

    Unions the figure graphics AND the panel labels, because a panel letter is
    text rather than a drawing and a crop that omits it will fail the
    panel-label check.

    Then pulls the box back from prose, but only where doing so cannot cut a
    graphic. If a caption word genuinely sits inside the graphics' own extent
    the box is left alone and a conflict is reported, since silently shrinking
    there is how content ends up stranded outside every crop.

    Returns (rect, notes). The rect is a starting point for a human to confirm,
    never an answer.
    """
    lo = y0 if y0 is not None else 0.0
    hi = y1 if y1 is not None else page.rect.height

    parts = [r for r in figure_graphics(page) if r.y0 >= lo - 1 and r.y1 <= hi + 1]
    parts += [r for r, _ in panel_labels(page) if r.y0 >= lo - 1 and r.y1 <= hi + 1]
    if not parts:
        return None, []

    content = fitz.Rect(parts[0])
    for r in parts[1:]:
        content |= r

    box = fitz.Rect(content)
    box.x0 -= pad
    box.y0 -= pad
    box.x1 += pad
    box.y1 += pad

    notes = []
    for wrect, text in prose_words(page):
        if not box.intersects(wrect):
            continue
        # Only trim on a side where the prose lies clear of the actual content.
        if wrect.y0 >= content.y1:
            box.y1 = min(box.y1, wrect.y0 - 2)
        elif wrect.y1 <= content.y0:
            box.y0 = max(box.y0, wrect.y1 + 2)
        elif wrect.x0 >= content.x1:
            box.x1 = min(box.x1, wrect.x0 - 2)
        elif wrect.x1 <= content.x0:
            box.x0 = max(box.x0, wrect.x1 + 2)
        else:
            notes.append(
                f"prose {text!r} at [{wrect.x0:.0f},{wrect.y0:.0f}] sits inside the "
                f"figure's own extent; split this page by hand")

    if box.width <= 20 or box.height <= 20:
        return None, notes
    return box, sorted(set(notes))

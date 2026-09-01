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

# A text block counts as prose (caption or body copy) only if it holds at least
# this many word-like tokens AND is wider than PROSE_MIN_WIDTH. The width test
# excludes rotated axis labels, which are narrow, word-rich, and part of the
# figure.
PROSE_WORD_COUNT = 12
PROSE_MIN_WIDTH = 60.0

# Only tokens this long, and alphabetic once punctuation is stripped, count
# towards PROSE_WORD_COUNT. Without this, a row of short axis tick labels
# spanning a wide figure ("V1 AL PM" repeated per subpanel, or a row of numeric
# ticks) is one wide block of many "words" and gets classified as prose, which
# then rejects every crop box that correctly includes those labels.
PROSE_MIN_WORD_LEN = 3
_PUNCTUATION = "()[].,;:!?\"'`-\u2013\u2014"

# PyMuPDF span flag bit for bold. Only `get_text("dict")` reports font weight;
# `get_text("words")` does not, which is why panel_labels needs both.
BOLD_FLAG = 1 << 4

# Zero-thickness rects (axis lines, rules, ticks) are real figure content, but
# intersection tests ignore empty rects. Give each degenerate axis this much
# extent so the geometry behaves.
DEGENERATE_PAD = 0.5

# Content above/below these page offsets is running header or footer.
#
# These are defaults, not truths about paper layout. A journal that starts its
# figures higher than HEADER_Y makes the top of every figure invisible to the
# geometry: panel letters, panel titles and legend keys are silently discarded,
# so `verify_coverage` and `verify_figure_text` cannot see a crop that cuts them
# off. Nature runs figures from about y=48 and needs HEADER_Y nearer 45.
#
# Override per paper in figures.toml, which threads the values through every
# check:
#
#     [page]
#     header_y = 45
#
HEADER_Y = 95.0
FOOTER_Y = 745.0

# A drawing wider than this fraction of the page is a background or a full-width
# rule, not figure content.
MAX_CONTENT_WIDTH_FRAC = 0.85

# The same problem rotated: journals draw a hairline down the page edge or
# between columns, and it runs the full text height. Height alone cannot
# disqualify a drawing, because a page-filling figure legitimately has tall
# elements, so this applies only to rules thin enough to carry no content. Left
# in, such a rule intersects no sensible crop box and `verify_coverage` reports
# it as figure content stranded outside every crop, on every page of the paper.
MAX_RULE_HEIGHT_FRAC = 0.85
MAX_RULE_THICKNESS = 2.0


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


def word_like(text):
    """Count tokens that only running prose plausibly contains.

    Axis tick labels are short ("V1", "PM", "0.32", "24"), so counting raw
    whitespace-separated tokens makes a row of them look like a sentence.
    """
    count = 0
    for token in text.split():
        stripped = token.strip(_PUNCTUATION)
        if len(stripped) >= PROSE_MIN_WORD_LEN and stripped.isalpha():
            count += 1
    return count


def prose_words(page):
    """Yield (rect, text) for every word belonging to a prose text block."""
    prose_blocks = set()
    for block in page.get_text("blocks"):
        x0, _, x1, _, text, block_no = block[0], block[1], block[2], block[3], block[4], block[5]
        if word_like(text) >= PROSE_WORD_COUNT and (x1 - x0) >= PROSE_MIN_WIDTH:
            prose_blocks.add(block_no)
    for word in page.get_text("words"):
        x0, y0, x1, y1, text, block_no = word[0], word[1], word[2], word[3], word[4], word[5]
        if block_no in prose_blocks:
            yield fitz.Rect(x0, y0, x1, y1), text


def subpath_rects(item):
    """Yield a rect per drawn segment of one drawing, not one for the group.

    `page.get_drawings()` returns one entry per path, and a single path can hold
    many unconnected segments: a journal figure often draws every axis line of
    every panel as one path object. Its reported `rect` is then the union of
    those segments, a box spanning the whole figure that is mostly empty. Used
    as figure content it makes panels impossible to crop apart, because one
    phantom rect straddles every boundary at once.

    Falls back to the whole bounding rect when an entry reports no segments. That
    fallback must never be reached by a transparency `group`: PyMuPDF populates
    `items` only for non-group entries, so a group would fall through and
    reinstate exactly the phantom union this function exists to remove. One real
    case unioned 24 separately reported child drawings into a single 233 x 127 pt
    rect. `figure_graphics` therefore skips groups outright, since their children
    are reported independently.
    """
    segments = item.get("items") or ()
    if not segments:
        rect = item.get("rect")
        if rect is not None:
            yield fitz.Rect(rect)
        return
    for seg in segments:
        op, args = seg[0], seg[1:]
        if op == "re":
            yield fitz.Rect(args[0])
        elif op == "qu":
            yield fitz.Quad(args[0]).rect
        else:
            # "l" is two points, "c" is four control points. A curve's control
            # hull contains the curve, so its bounding box is a safe superset.
            points = [p for p in args if isinstance(p, fitz.Point)]
            if not points:
                continue
            # Built from coordinates rather than by unioning per-point rects,
            # because `Rect.__or__` ignores an empty operand: a rect grown from
            # single points stays a point, so every straight segment on the page
            # would vanish and the coverage checks would silently pass.
            yield fitz.Rect(min(p.x for p in points), min(p.y for p in points),
                            max(p.x for p in points), max(p.y for p in points))


def figure_graphics(page, header_y=None, footer_y=None):
    """Yield rects of drawings and images that are plausibly figure content."""
    header_y = HEADER_Y if header_y is None else header_y
    footer_y = FOOTER_Y if footer_y is None else footer_y
    page_width = page.rect.width
    page_height = page.rect.height
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
        # A transparency group carries no `items`, and its children are reported
        # separately, so honouring it would re-add one rect spanning every child.
        # Skipped for the same reason as a clip.
        if item["type"] == "group":
            continue
        if item.get("rect") is None:
            continue
        for rect in subpath_rects(item):
            rect = fitz.Rect(rect)
            # Clamp per axis rather than calling `Rect.intersect`, for two
            # reasons. `intersect` is documented as a no-op on an empty rect, and
            # a horizontal or vertical segment is empty in one dimension, so it
            # would escape its scissor entirely. And padding before intersecting
            # pushes a segment sitting exactly on the scissor's far edge past it,
            # after which the intersection collapses and the segment is lost:
            # real 13.7 pt axis lines disappeared that way. Clamp first, pad
            # after, and both problems go away.
            for _, scissor in clip_stack:
                rect.x0 = max(rect.x0, scissor.x0)
                rect.y0 = max(rect.y0, scissor.y0)
                rect.x1 = min(rect.x1, scissor.x1)
                rect.y1 = min(rect.y1, scissor.y1)
            if rect.x1 < rect.x0 or rect.y1 < rect.y0:
                continue                  # wholly outside its clip
            if rect.x1 == rect.x0 and rect.y1 == rect.y0:
                continue                  # a single point protects nothing
            if rect.x1 == rect.x0:
                rect.x1 += DEGENERATE_PAD
            if rect.y1 == rect.y0:
                rect.y1 += DEGENERATE_PAD
            if rect.width > MAX_CONTENT_WIDTH_FRAC * page_width:
                continue
            if (rect.width <= MAX_RULE_THICKNESS
                    and rect.height > MAX_RULE_HEIGHT_FRAC * page_height):
                continue
            if rect.y1 < header_y or rect.y0 > footer_y:
                continue
            yield rect
    for info in page.get_image_info():
        yield fitz.Rect(*info["bbox"])


def figure_text(page, header_y=None, footer_y=None):
    """Yield (rect, text) for the figure's own text: axis and panel labels.

    Everything inside the body bands that is not part of a prose block. Shared by
    the crop suggester and the figure-text check so the two cannot disagree about
    what counts as a label.

    A word merely intersecting the bands counts here, matching the figure-text
    check. `suggest_crop` wants the stricter rule and calls
    `figure_text_contained`, because a running head straddling the boundary would
    otherwise drag a suggested box up out of the figure.
    """
    header_y = HEADER_Y if header_y is None else header_y
    footer_y = FOOTER_Y if footer_y is None else footer_y
    prose = [r for r, _ in prose_words(page)]
    for word in page.get_text("words"):
        rect = fitz.Rect(word[:4])
        if rect.y1 < header_y or rect.y0 > footer_y:
            continue
        if any(rect.intersects(p) for p in prose):
            continue
        yield rect, word[4]


def figure_text_contained(page, header_y=None, footer_y=None):
    """`figure_text`, but only words lying wholly inside the body bands."""
    header_y = HEADER_Y if header_y is None else header_y
    footer_y = FOOTER_Y if footer_y is None else footer_y
    for rect, text in figure_text(page, header_y, footer_y):
        if rect.y0 >= header_y and rect.y1 <= footer_y:
            yield rect, text


def panel_labels(page):
    """Yield (rect, letter) for each single-letter panel label.

    Two passes, because the two cases need different evidence.

    Uppercase letters are taken at any font weight, which is what single-column
    and two-column journals do. Lowercase letters are taken only when **bold**,
    because Nature-style journals set panels as bold lowercase and plain
    lowercase single letters are everywhere on a figure page: the English
    article "a", axis units, and italic maths variables. Boldness is the only
    thing separating a panel marker from an article, so a naive `islower()`
    would report a panel "a" on essentially every page of every paper.

    Letters sitting inside prose are skipped, so a sentence starting with "A" is
    not mistaken for a panel marker, and neither is the bold letter that opens
    each clause of a Nature caption.
    """
    prose = [r for r, _ in prose_words(page)]

    def outside_prose(rect):
        return not any(rect.intersects(p) for p in prose)

    # Uppercase, from words. Unchanged behaviour: word extraction carries no
    # font information, and every paper that passed before must still pass.
    for word in page.get_text("words"):
        x0, y0, x1, y1, text = word[0], word[1], word[2], word[3], word[4]
        if len(text) != 1 or not text.isupper() or not text.isalpha():
            continue
        rect = fitz.Rect(x0, y0, x1, y1)
        if outside_prose(rect):
            yield rect, text

    # Lowercase, from spans, which is the only extraction that reports weight.
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", ()):
            for span in line.get("spans", ()):
                text = span["text"].strip()
                if len(text) != 1 or not text.isalpha() or not text.islower():
                    continue
                if not span["flags"] & BOLD_FLAG:
                    continue
                rect = fitz.Rect(span["bbox"])
                if outside_prose(rect):
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


def content_bbox(page, header_y=None, footer_y=None):
    """Union of figure graphics on a page, or None if there are none."""
    rects = list(figure_graphics(page, header_y, footer_y))
    if not rects:
        return None
    box = fitz.Rect(rects[0])
    for r in rects[1:]:
        box |= r
    return box


def suggest_crop(page, y0=None, y1=None, pad=3.0, header_y=None, footer_y=None):
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

    parts = [r for r in figure_graphics(page, header_y, footer_y)
             if r.y0 >= lo - 1 and r.y1 <= hi + 1]
    parts += [r for r, _ in panel_labels(page) if r.y0 >= lo - 1 and r.y1 <= hi + 1]
    if not parts:
        return None, []

    content = fitz.Rect(parts[0])
    for r in parts[1:]:
        content |= r

    # Grow to swallow whole any figure text the box already touches: axis
    # labels, tick labels, orientation markers. Only text that already
    # intersects counts, so a section heading elsewhere on the page cannot drag
    # the box into the body column. Growing can touch new words, so iterate to
    # a fixed point under a cap.
    # The strict containment rule, matching the behaviour this function had before
    # the bands became per-paper: a word straddling a band boundary must not drag
    # the suggested box out of the figure.
    labels = [r for r, _ in figure_text_contained(page, header_y, footer_y)]
    for _ in range(8):
        grown = fitz.Rect(content)
        for wrect in labels:
            if content.intersects(wrect):
                grown |= wrect
        if grown == content:
            break
        content = grown

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

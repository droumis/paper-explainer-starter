#!/usr/bin/env python
"""Tests for the figure-geometry machinery, against a synthetic PDF.

No real paper needed: `build_fixture()` fabricates a page laid out like a
journal figure page, including the three things that make naive geometry wrong.
Every assertion here corresponds to a bug that shipped in a real site.

Run:  pixi run --manifest-path template/pixi.toml python tests/test_pdf_geometry.py
"""

import sys
from pathlib import Path

import fitz

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "template" / "scripts"))

import pdf_geometry as G  # noqa: E402
import project as P  # noqa: E402

PAGE_W, PAGE_H = 603, 783

# Fixture layout, in points. A two-column page: a figure occupying the upper
# area, a caption below it, and a body column on the right that is indented to
# make room for the figure.
FIG_BOX = fitz.Rect(60, 110, 380, 420)
PANEL_A = (66, 116)
PANEL_B = (66, 280)
PANEL_BOLD_LOWER = (200, 116)   # a bold lowercase panel letter, Nature style
PLAIN_LOWER = (250, 170)        # a plain lowercase letter, not a panel
CAPTION_Y = 440
BODY_X = 400          # right column, indented clear of the figure

# The clipped band: filled CLIP_FILL_W wide, clipped to CLIP_VISIBLE_W.
CLIP_X0 = 200
CLIP_BAND_BOTTOM = 400
CLIP_BAND_H = 50
CLIP_VISIBLE_W = 160          # clip stops the fill here
CLIP_FILL_W = 360             # the fill's own width, reaching into the body

# A row of short axis tick labels, the width of the figure. Thirteen
# whitespace-separated tokens, so a naive word count classifies the row as prose
# and then rejects every crop that correctly contains it. It also extends past
# the drawings' own right edge, so a crop derived from graphics alone cuts it.
TICKS = "V1 AL PM LM RL A1 S1 M2 AM LI POR PPC MM"
TICKS_X0 = 95.0
TICKS_BASELINE = 405.0

# One more label, straddling the right edge of the drawings at x=370. A box
# derived from graphics alone cuts it in half, so it exercises both the growth
# step in suggest_crop and the figure-text check.
EDGE_LABEL = "RSPd"
EDGE_X0 = 360.0

# The page-edge hairline rule, left of everything else on the page.
PAGE_RULE_X = 34.0

# A clipped path whose second segment lies wholly OUTSIDE the clip, to the left of
# it. Intersecting that segment yields an inverted rect rather than an empty one,
# which reads as real content at coordinates that appear nowhere on the page.
# Kept clear of the body column so it tests only the inversion.
OUTSIDE_SEG_X = (120.0, 170.0)
OUTSIDE_SEG_Y = CLIP_BAND_BOTTOM - CLIP_BAND_H / 2

# A zero-thickness segment lying exactly ON its clip's far edge. Padding before
# clipping pushes it past the scissor, the intersection then collapses, and the
# segment is lost. Real 13.7 pt axis lines disappeared this way, so the clip has
# to be applied by clamping and the padding has to come after.
EDGE_SEG_X = CLIP_X0 + CLIP_VISIBLE_W          # exactly scissor.x1
EDGE_SEG_Y = (CLIP_BAND_BOTTOM - CLIP_BAND_H + 8, CLIP_BAND_BOTTOM - 8)

# Stand-in for a transparency group entry: PyMuPDF reports no `items` for one, so
# `subpath_rects` falls back to the whole bounding rect. That is why
# `figure_graphics` has to skip groups outright rather than rely on the fallback.
GROUP_LIKE = {"type": "group", "rect": fitz.Rect(96, 150, 232, 250), "level": 0}

# Two axis lines belonging to different panels, drawn as ONE path. The path's
# reported rect spans both, so it covers GROUP_GAP_X, where there is no ink.
# Journals really do emit figures this way, and the phantom rect straddles every
# panel boundary at once, which makes a figure impossible to split by panel.
GROUP_Y = 275.0
GROUP_LEFT = (95.0, 150.0)
GROUP_RIGHT = (300.0, 360.0)
GROUP_GAP_X = 225.0


def build_fixture(path: Path):
    doc = fitz.open()
    page = doc.new_page(width=PAGE_W, height=PAGE_H)

    # Running header and footer, which must be ignored as figure content.
    page.insert_text((60, 40), "JOURNAL NAME  Vol 1", fontsize=8)
    page.insert_text((60, 770), "114  Neuron 90, 113-127", fontsize=8)

    # A hairline rule down the page edge, running the full text height. Journals
    # draw these on every page, figure pages included. Counted as figure
    # content it sits in no crop box, so `verify_coverage` reports stranded
    # content that no crop can legitimately capture.
    page.draw_line(fitz.Point(PAGE_RULE_X, 28), fitz.Point(PAGE_RULE_X, PAGE_H - 40))

    # Figure content: a filled rect, an axis line (zero height), a tick (zero
    # width), and an embedded-style shape.
    page.draw_rect(fitz.Rect(90, 140, 240, 260), color=(0, 0, 0), fill=(0.8, 0.85, 1))
    page.draw_line(fitz.Point(90, 300), fitz.Point(300, 300))          # zero height
    page.draw_line(fitz.Point(120, 300), fitz.Point(120, 340))         # zero width
    page.draw_rect(fitz.Rect(260, 150, 370, 410), color=(0, 0, 0))

    # Two panels' axis lines committed as a single path, so PyMuPDF reports one
    # rect spanning the gap between them.
    shape = page.new_shape()
    shape.draw_line(fitz.Point(GROUP_LEFT[0], GROUP_Y),
                    fitz.Point(GROUP_LEFT[1], GROUP_Y))
    shape.draw_line(fitz.Point(GROUP_RIGHT[0], GROUP_Y),
                    fitz.Point(GROUP_RIGHT[1], GROUP_Y))
    shape.finish(color=(0, 0, 0), width=0.5)
    shape.commit()

    # A genuinely clipped path: the fill spans x 200..560, reaching into the body
    # column, but the clip stops it at x=360. Naive geometry reports the fill's
    # own rect and concludes the figure covers the text column. Nothing in the
    # PyMuPDF drawing API emits a clip, so write the operators directly.
    # PDF space is bottom-up, so y_pdf = PAGE_H - y_top.
    # The same clip also carries a two-segment stroked path whose second segment
    # is entirely outside the scissor, which is what produces an inverted rect.
    y_pdf = PAGE_H - CLIP_BAND_BOTTOM
    seg_y = PAGE_H - OUTSIDE_SEG_Y
    e0, e1 = PAGE_H - EDGE_SEG_Y[0], PAGE_H - EDGE_SEG_Y[1]
    ops = (f"\nq {CLIP_X0} {y_pdf} {CLIP_VISIBLE_W} {CLIP_BAND_H} re W n\n"
           f"1 0.94 0 rg {CLIP_X0} {y_pdf} {CLIP_FILL_W} {CLIP_BAND_H} re f\n"
           f"0 0 0 RG 0.5 w {CLIP_X0 + 10} {seg_y} m {CLIP_X0 + 60} {seg_y} l\n"
           f"{OUTSIDE_SEG_X[0]} {seg_y} m {OUTSIDE_SEG_X[1]} {seg_y} l S\n"
           # A vertical segment sitting exactly on the scissor's right edge.
           f"{EDGE_SEG_X} {e0} m {EDGE_SEG_X} {e1} l S\nQ\n")
    xref = page.get_contents()[0]
    doc.update_stream(xref, doc.xref_stream(xref) + ops.encode())

    # A transparency group would belong here, but emitting one needs an ExtGState
    # resource that this fixture has no clean way to add, and a half-written one
    # produces MuPDF syntax errors rather than a `group` entry. The group guard is
    # covered instead by `check_subpath_fallback` below plus verification against
    # real papers, which do contain groups.

    # Panel labels: single capitals, part of the figure.
    page.insert_text(PANEL_A, "A", fontsize=11)
    page.insert_text(PANEL_B, "B", fontsize=11)

    # A Nature-style panel label: bold lowercase. Invisible to any check that
    # only matches capitals, which is how a caption came to describe a panel
    # that had been cropped off.
    page.insert_text(PANEL_BOLD_LOWER, "d", fontsize=11, fontname="Helvetica-Bold")

    # A plain lowercase single letter inside the figure, standing in for an axis
    # unit or an italic maths variable. Accepting lowercase without requiring
    # bold would report this as a panel and demand a crop contain it.
    page.insert_text(PLAIN_LOWER, "q", fontsize=7)

    # An anatomical orientation marker, which looks exactly like a panel label.
    page.insert_text((330, 170), "M", fontsize=8)

    # Axis tick labels: figure content that is text, not drawing.
    page.insert_text((TICKS_X0, TICKS_BASELINE), TICKS, fontsize=7)
    page.insert_text((EDGE_X0, TICKS_BASELINE), EDGE_LABEL, fontsize=7)

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


def expect_exit(fn, *needles):
    """Run `fn`, expecting SystemExit whose message mentions every needle."""
    try:
        fn()
    except SystemExit as exc:
        msg = str(exc)
        return all(n in msg for n in needles), msg
    return False, "no SystemExit raised"


def check_project_module():
    """figures.toml parsing and project resolution.

    These exist because both replaced something that used to be impossible to
    get wrong: crop boxes were Python, so a typo was a syntax error, and the
    project was wherever the script lived. Data files and a search need checks.
    """
    import tempfile

    passed = []
    print("\nfigures.toml")
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d) / "paper"
        proj.mkdir()
        (proj / "mkdocs.yml").write_text("site_name: x\n")

        ok, msg = expect_exit(lambda: P.load_figures(proj), "figures.toml")
        passed.append(check("a missing figures.toml names the file it wants", ok, msg))

        (proj / "figures.toml").write_text("# nothing yet\n")
        passed.append(check("a comment-only file loads as no crops",
                            P.load_figures(proj) == {}))

        (proj / "figures.toml").write_text(
            "[figures.fig1_task]\npage = 2\nbox = [56, 98, 297, 307]\n")
        figs = P.load_figures(proj)
        passed.append(check("a valid entry becomes (page, Rect)",
                            figs == {"fig1_task": (2, fitz.Rect(56, 98, 297, 307))},
                            f"got {figs}"))

        (proj / "figures.toml").write_text(
            "[figures.fig1]\npage = -1\nbox = [56, 98, 297, 307]\n")
        ok, msg = expect_exit(lambda: P.load_figures(proj), "page")
        passed.append(check("a negative page index is rejected", ok, msg))

        (proj / "figures.toml").write_text(
            "[figures.fig1]\npage = 2\nbox = [297, 307, 56, 98]\n")
        ok, msg = expect_exit(lambda: P.load_figures(proj), "inverted")
        passed.append(check("an inverted box is rejected", ok, msg))

        (proj / "figures.toml").write_text(
            "[figures.fig1]\npage = 2\nbox = [1, 2, 3]\n")
        ok, msg = expect_exit(lambda: P.load_figures(proj), "x0, y0, x1, y1")
        passed.append(check("a three-number box is rejected", ok, msg))

        # A name outside [a-z0-9_] would be written and then reported as
        # unreferenced, because that is the class the markdown scanner matches.
        (proj / "figures.toml").write_text(
            "[figures.Fig1]\npage = 2\nbox = [56, 98, 297, 307]\n")
        ok, msg = expect_exit(lambda: P.load_figures(proj), "lowercase")
        passed.append(check("an uppercase crop name is rejected", ok, msg))

        (proj / "figures.toml").write_text(
            "[figures.fig1]\npage = 2\nbox = [56, 98, 297, 307]\nzoom = 3\n")
        ok, msg = expect_exit(lambda: P.load_figures(proj), "unexpected key")
        passed.append(check("an unknown key is rejected rather than ignored",
                            ok, msg))

        # Optional lossy quality for photographic panels.
        (proj / "figures.toml").write_text(
            "[figures.fig1]\npage = 2\nbox = [56, 98, 297, 307]\nquality = 90\n")
        q = {}
        P.load_figures(proj, q)
        passed.append(check("a quality is collected for the crop that sets it",
                            q == {"fig1": 90}, f"got {q}"))
        (proj / "figures.toml").write_text(
            "[figures.fig1]\npage = 2\nbox = [56, 98, 297, 307]\nquality = 0\n")
        ok, msg = expect_exit(lambda: P.load_figures(proj), "1 to 100")
        passed.append(check("a quality outside 1 to 100 is rejected", ok, msg))

        # The optional [page] band overrides. These gate every geometry check, so
        # a value that silently disables them is worse than a rejected one.
        good = "[page]\nheader_y = 45\n[figures.f]\npage = 2\nbox = [1, 2, 3, 4]\n"
        (proj / "figures.toml").write_text(good)
        passed.append(check("a valid [page] header_y is read",
                            P.load_bands(proj) == {"header_y": 45.0},
                            f"got {P.load_bands(proj)}"))
        passed.append(check("[page] does not make load_figures reject the file",
                            set(P.load_figures(proj)) == {"f"}))

        for bad_value, label in (("nan", "nan"), ("inf", "inf"), ("-5", "negative"),
                                 ("0", "zero"), ("10000", "off the page"),
                                 ('"45"', "a string")):
            (proj / "figures.toml").write_text(f"[page]\nheader_y = {bad_value}\n")
            ok_f, msg_f = expect_exit(lambda: P.load_figures(proj), "header_y")
            ok_b, msg_b = expect_exit(lambda: P.load_bands(proj), "header_y")
            passed.append(check(
                f"[page] header_y = {label} is rejected by both loaders",
                ok_f and ok_b,
                f"load_figures: {msg_f} / load_bands: {msg_b}; a band outside the "
                "page makes every geometry check pass having examined nothing"))

        (proj / "figures.toml").write_text("[page]\nheaderY = 45\n")
        ok_f, msg_f = expect_exit(lambda: P.load_figures(proj), "headerY")
        ok_b, msg_b = expect_exit(lambda: P.load_bands(proj), "headerY")
        passed.append(check("a misspelled [page] key is rejected by both loaders",
                            ok_f and ok_b,
                            f"load_figures: {msg_f} / load_bands: {msg_b}; the probe "
                            "reads load_bands only, and would use the wrong band"))

        (proj / "figures.toml").write_text("[page]\nheader_y = 45\nbroken =\n")
        ok_b, msg_b = expect_exit(lambda: P.load_bands(proj), "figures.toml")
        passed.append(check("load_bands reports malformed TOML instead of "
                            "defaulting silently", ok_b, msg_b))

        # Every bad entry at once, so filling this in is one edit-and-rerun.
        (proj / "figures.toml").write_text(
            "[figures.a]\npage = 2\nbox = [1, 2]\n"
            "[figures.b]\npage = 2\nbox = [9, 9, 1, 1]\n")
        ok, msg = expect_exit(lambda: P.load_figures(proj), "a:", "b:")
        passed.append(check("both malformed entries are reported together",
                            ok, msg))

    print("\nproject resolution")
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        one = root / "paper-one"
        one.mkdir()
        (one / "mkdocs.yml").write_text("site_name: one\n")

        passed.append(check("a project directory resolves to itself",
                            P.resolve_project(None, cwd=one) == one.resolve()))
        passed.append(check("a lone project below the cwd is found without naming it",
                            P.resolve_project(None, cwd=root) == one.resolve()))
        passed.append(check("a named project resolves",
                            P.resolve_project("paper-one", cwd=root) == one.resolve()))

        two = root / "paper-two"
        two.mkdir()
        (two / "mkdocs.yml").write_text("site_name: two\n")
        ok, msg = expect_exit(lambda: P.resolve_project(None, cwd=root),
                              "paper-one", "paper-two")
        passed.append(check("two projects force the choice instead of guessing",
                            ok, msg))

        # The scaffold source carries a mkdocs.yml and a figures.toml so a
        # project can be copied out of it, which made it a phantom third paper.
        scaffold = root / "template"
        (scaffold / "scripts").mkdir(parents=True)
        (scaffold / "mkdocs.yml").write_text("site_name: t\n")
        found = [p.name for p in P.candidate_projects(root)]
        passed.append(check("template/ is not counted as a paper",
                            found == ["paper-one", "paper-two"], f"got {found}"))
        ok, msg = expect_exit(lambda: P.resolve_project("template", cwd=root),
                              "scaffold")
        passed.append(check("naming template/ is refused", ok, msg))

        (root / "notes").mkdir()
        ok, msg = expect_exit(lambda: P.resolve_project("notes", cwd=root),
                              "new-paper")
        passed.append(check("a directory that is not a project says how to make one",
                            ok, msg))
        ok, msg = expect_exit(lambda: P.resolve_project("nope", cwd=root),
                              "No such directory")
        passed.append(check("a missing directory is reported plainly", ok, msg))

    print("\nargument splitting")
    cases = [
        (["andermann"], (), "andermann", []),
        (["--verify", "andermann"], (), "andermann", ["--verify"]),
        (["--suggest"], (), None, ["--suggest"]),
        (["--page", "10"], ("--page",), None, ["--page", "10"]),
        (["--page", "10", "andermann"], ("--page",), "andermann", ["--page", "10"]),
        (["--port", "8001"], ("--port",), None, ["--port", "8001"]),
    ]
    for argv, value_flags, want_name, want_rest in cases:
        got = P.split_project_arg(argv, value_flags)
        passed.append(check(f"{argv} -> {want_name!r}", got == (want_name, want_rest),
                            f"got {got}"))
    return passed


def check_link_classifier():
    """The link classifier in check_site, whose path arithmetic decides whether
    a link is checkable at all.

    A link that climbs above the served project root is how a link into a
    sibling paper is written. Those resolve only in the combined `index` build,
    so calling them broken would make the check unusable in a multi-paper repo,
    and calling them internal would report a false 404 on every one.
    """
    import check_site as C

    print("\nlink classification")
    cases = [
        ("/one/", "../two/", ("internal", "/two/", "")),
        ("/one/", "#heading", ("internal", "/one/", "heading")),
        ("/one/", "../assets/img/f.webp", ("internal", "/assets/img/f.webp", "")),
        ("/", "two/", ("internal", "/two/", "")),
        ("/a/b/", "../c/", ("internal", "/a/c/", "")),
        ("/a/b/", "../../d/", ("internal", "/d/", "")),
        # Escaping the project root: unverifiable from a single-project serve.
        ("/one/", "../../other-paper/", ("escapes", "../../other-paper/", "")),
        ("/one/", "../../other/p/#frag", ("escapes", "../../other/p/", "frag")),
        ("/", "../other/", ("escapes", "../other/", "")),
        ("/a/b/", "../../../e/", ("escapes", "../../../e/", "")),
        # Other schemes are none of this check's business.
        ("/one/", "https://example.com", ("skip", None, None)),
        ("/one/", "mailto:a@b.c", ("skip", None, None)),
        ("/one/", "javascript:void(0)", ("skip", None, None)),
    ]
    passed = []
    for slug, href, want in cases:
        got = C.classify_link(slug, href)
        passed.append(check(f"{slug} + {href} -> {want[0]}", got == want,
                            f"got {got}, expected {want}"))
    return passed


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

    tick_tokens = set(TICKS.split())
    passed.append(check(
        "a row of short axis tick labels is not classified as prose",
        not (texts & tick_tokens),
        f"leaked {sorted(texts & tick_tokens)[:4]}; a crop containing the axis "
        "would then be rejected"))

    print("\npanel labels")
    labels = {t for _, t in G.panel_labels(page)}
    passed.append(check("finds A and B", {"A", "B"} <= labels, f"got {labels}"))
    passed.append(check("also finds the orientation marker M, a known false "
                        "positive", "M" in labels))
    passed.append(check(
        "finds the bold lowercase panel label d",
        "d" in labels,
        f"got {labels}; Nature-style journals set panels as bold lowercase, so "
        "matching capitals only makes every such paper's panels invisible"))
    passed.append(check(
        "does not treat a plain lowercase letter as a panel label",
        "q" not in labels,
        f"got {labels}; requiring bold is the only thing separating a panel "
        "marker from the article 'a' and from axis units"))
    lower_rects = [r for r, t in G.panel_labels(page) if t == "d"]
    passed.append(check(
        "the bold lowercase label is positioned where it was drawn",
        lower_rects and abs(lower_rects[0].x0 - PANEL_BOLD_LOWER[0]) < 2,
        f"got {[(round(r.x0), round(r.y0)) for r in lower_rects]}, "
        f"expected near {PANEL_BOLD_LOWER}"))

    print("\nfigure graphics")
    gfx = list(G.figure_graphics(page))
    passed.append(check("finds some graphics", len(gfx) > 0, f"got {len(gfx)}"))
    passed.append(check("ignores the running header",
                        all(r.y1 >= G.HEADER_Y for r in gfx)))
    passed.append(check("ignores the footer",
                        all(r.y0 <= G.FOOTER_Y for r in gfx)))
    passed.append(check(
        "ignores the full-height page rule",
        not any(r.x1 <= PAGE_RULE_X + 1 for r in gfx),
        "a page-edge hairline counted as figure content is stranded outside "
        "every crop box, on every page"))
    passed.append(check(
        "but keeps a tall element that is not a hairline",
        any(r.height > 200 for r in gfx),
        "the height filter must not disqualify real panels"))
    # Why groups must be skipped rather than handled by the fallback: an entry
    # with no `items` yields its whole bounding rect, and for a group that rect is
    # the union over every child, each of which is reported separately anyway.
    fallback = list(G.subpath_rects(GROUP_LIKE))
    passed.append(check(
        "an entry with no segments falls back to its whole bounding rect",
        fallback == [GROUP_LIKE["rect"]],
        f"got {fallback}; this is why figure_graphics skips type == 'group'"))

    gap = fitz.Point(GROUP_GAP_X, GROUP_Y)
    passed.append(check(
        "a multi-segment path is reported per segment, not as one union rect",
        not any(r.contains(gap) for r in gfx),
        "a path holding two panels' axis lines claims the empty space between "
        "them, which straddles every panel boundary and blocks splitting"))
    edge = [r for r in gfx
            if abs(r.x0 - EDGE_SEG_X) < 1 and r.y0 <= EDGE_SEG_Y[0] + 1
            and r.y1 >= EDGE_SEG_Y[1] - 1]
    passed.append(check(
        "a degenerate segment lying on its clip's far edge survives",
        bool(edge),
        "padding before clipping pushes such a segment past the scissor, the "
        "intersection then collapses, and a real axis line vanishes; clamp to "
        "the clip first and pad afterwards"))

    gone = fitz.Point(sum(OUTSIDE_SEG_X) / 2, OUTSIDE_SEG_Y)
    passed.append(check(
        "a segment clipped entirely away is dropped, not inverted",
        all(r.x1 >= r.x0 and r.y1 >= r.y0 for r in gfx)
        and not any(r.contains(gone) for r in gfx),
        "intersecting a segment that lies outside its clip gives x1 < x0, and "
        "Rect.width reports the absolute difference, so it survives every size "
        "filter and is reported as stranded content at impossible coordinates"))
    passed.append(check(
        "both segments of that path survive",
        any(abs(r.x1 - GROUP_LEFT[1]) < 1 for r in gfx)
        and any(abs(r.x0 - GROUP_RIGHT[0]) < 1 for r in gfx),
        "per-segment rects must not be dropped; Rect.__or__ ignores empty "
        "operands, so unioning point rects silently loses every line"))
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
        # The label straddles the drawings' right edge, so a box unioned from
        # graphics alone would slice it. Growth has to swallow it whole.
        edge = [r for r, t in
                ((fitz.Rect(w[:4]), w[4]) for w in page.get_text("words"))
                if t == EDGE_LABEL]
        passed.append(check(
            "box grows to contain a label straddling the drawings' edge",
            edge and box.contains(edge[0]),
            f"box.x1={box.x1:.0f}, label ends at "
            f"{edge[0].x1:.0f}" if edge else "label missing"))

    doc.close()

    # ---- the three checks, driven through extract_figures
    print("\ncrop checks (via extract_figures)")
    import extract_figures as ef  # noqa: E402
    import io
    import contextlib

    def run(figs):
        paper = P.Paper(root=ROOT / "tests", pdf=tmp, figures=figs)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            result = ef.verify_all(paper)
        return result, buf.getvalue()

    # Assert the end-to-end property that matters: a box produced by
    # suggest_crop must satisfy every check. On a real paper the first
    # version of suggest_crop failed the panel-label check on every page, which
    # is exactly the regression this guards.
    ok, out = run({"fig": (0, box)})
    passed.append(check("a box from suggest_crop passes every check", ok,
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
    passed.append(check("an empty figures.toml is rejected, not vacuously passed",
                        not ok and "nothing to verify" in out))

    # The figure's own text, which the drawing-based checks cannot see. A crop
    # that stops at the drawings' edge cuts the straddling label in half, and the
    # rendered figure then shows half a word.
    ok, out = run({"fig": (0, fitz.Rect(56, 106, 372, 424))})
    passed.append(check("a crop slicing an axis label is rejected",
                        not ok and "slices figure text" in out,
                        out.strip().splitlines()[-1] if out else ""))
    ok, out = run({"top": (0, fitz.Rect(56, 106, 384, 396)),
                   "bot": (0, fitz.Rect(56, 409, 384, 424))})
    passed.append(check("figure text stranded between two crops is rejected",
                        not ok and "falls between crops" in out,
                        out.strip().splitlines()[-1] if out else ""))

    # ---- crops are written as WebP, lossless unless a quality says otherwise
    print("\nwriting crops")
    import tempfile as _tempfile
    with _tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        (proj / "docs").mkdir()
        doc = fitz.open(str(tmp))
        page = doc[0]
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=box)
        lossless = proj / "a.webp"
        lossy = proj / "b.webp"
        ef.write_crop(pix, lossless)
        ef.write_crop(pix, lossy, quality=80)
        doc.close()
        head = lossless.read_bytes()[:12]
        passed.append(check("writes a real WebP file",
                            head[:4] == b"RIFF" and head[8:12] == b"WEBP",
                            f"header {head!r}"))
        passed.append(check("a quality setting changes the encoding",
                            lossless.read_bytes() != lossy.read_bytes()))
        # On flat vector art lossy is often LARGER than lossless, which is why
        # lossless is the default and quality is opt-in per figure. The saving
        # appears on photographic content, so check it where it exists.
        import random
        from PIL import Image as _Image
        rng = random.Random(0)
        noise = _Image.new("RGB", (240, 240))
        noise.putdata([(rng.randrange(256), rng.randrange(256), rng.randrange(256))
                       for _ in range(240 * 240)])
        a, b = proj / "n1.webp", proj / "n2.webp"
        noise.save(a, format="WEBP", lossless=True, method=6)
        noise.save(b, format="WEBP", quality=80, method=6)
        passed.append(check("on photographic content, quality 80 beats lossless",
                            b.stat().st_size < a.stat().st_size,
                            f"lossless {a.stat().st_size}, q80 {b.stat().st_size}"))

    passed.extend(check_project_module())
    passed.extend(check_link_classifier())

    tmp.unlink(missing_ok=True)
    print(f"\n{sum(passed)}/{len(passed)} checks passed")
    return 0 if all(passed) else 1


if __name__ == "__main__":
    raise SystemExit(main())

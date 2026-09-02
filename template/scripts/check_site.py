#!/usr/bin/env python
"""Verify the built site in a real browser. Paper-agnostic.

Discovers pages from mkdocs.yml, then for each page:
  - opens every collapsed <details>, since Playwright cannot drive a hidden
    control and optional depth usually lives behind a disclosure
  - checks every diagram container actually rendered something
  - checks every label sits inside its own viewBox and clear of other labels, at
    the low, middle and high setting of every slider
  - checks each viewBox is the size its diagram actually draws, since the height
    lives in the markup and the layout maths lives in the JS, and the two drift
  - exercises every button, slider and select it can find
  - re-checks for non-finite SVG geometry, which is how a scale computed from
    empty data silently destroys a panel
  - counts genuinely broken images, distinguishing them from lazy images that
    simply have not loaded yet
  - follows every internal link and heading anchor, because a reworded heading
    silently breaks every link to it and the build reports success
  - reports console errors

Usage:
    pixi run serve                 # in another terminal
    pixi run check-site
    pixi run check-site --shots     # also save a screenshot per page

Add the project directory as the first argument when the repo holds several
papers: `pixi run check-site andermann-2011`.

Why a browser and not a unit test: every failure this catches is a rendering
failure that a build step reports as success.
"""

import re
import sys
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).parent))
from project import resolve_project, split_project_arg  # noqa: E402

DEFAULT_PORT = 8000

# Layout thresholds. A diagram may legitimately leave some blank space, so only
# flag a viewBox that is mostly empty: that is the signature of the markup and
# the JS layout constants having drifted apart.
MIN_VIEWBOX_FILL = 0.80
# Slack in viewBox units before a label counts as outside the box.
LABEL_PAD = 1.0
# Two labels overlap meaningfully once the intersection covers this much of the
# smaller one. Below this, descenders and kerning raise false alarms.
LABEL_OVERLAP_FRAC = 0.22
# Control settings to test the layout at. Labels move with the data. Sliders go
# to their low, middle and high value; a select takes its first, middle and last
# option, so a diagram with a three-way mode select is checked in all three.
LAYOUT_MODES = ("mid", "min", "max")
# How long to wait for an image that has not settled. Past this it is reported as
# pending rather than awaited, because awaiting it never returns.
IMAGE_SETTLE_MS = 3000

# A lazy image that has not loaded is not broken. Only zero intrinsic width
# after loading settles counts as a real failure.
#
# Two traps here, both of which cost a long debugging session. A single jump to
# the bottom of the page can skip an image entirely, leaving it lazy and pending;
# and a pending image fires neither `load` nor `error`, so awaiting it never
# returns. `page.evaluate` takes no timeout, so that hangs the whole run with no
# output and looks like a browser problem. Scroll in steps to trigger loading,
# then race every straggler against a timer.
COUNT_BROKEN_IMAGES = """
    async (waitMs) => {
      const step = Math.max(200, Math.floor(window.innerHeight * 0.8));
      for (let y = 0; y < document.body.scrollHeight; y += step) {
        window.scrollTo(0, y);
        await new Promise(r => setTimeout(r, 60));
      }
      window.scrollTo(0, 0);
      const imgs = [...document.querySelectorAll('img')];
      const settled = await Promise.all(imgs.map(i => i.complete
        ? Promise.resolve(true)
        : Promise.race([
            new Promise(r => {
              i.addEventListener('load', () => r(true));
              i.addEventListener('error', () => r(true));
            }),
            new Promise(r => setTimeout(() => r(false), waitMs)),
          ])));
      return {
        broken: imgs.filter((i, n) => settled[n] && i.naturalWidth === 0).length,
        pending: imgs.filter((i, n) => !settled[n])
                     .map(i => i.getAttribute('src')).slice(0, 3),
      };
    }
"""

SCAN_BAD_GEOMETRY = """
    () => {
      const attrs = ['x','y','x1','y1','x2','y2','width','height','cx','cy','r','d','transform'];
      const bad = [];
      document.querySelectorAll('svg *').forEach(el => {
        for (const a of attrs) {
          const v = el.getAttribute(a);
          if (v !== null && /NaN|Infinity/.test(v)) bad.push(el.tagName + '.' + a);
        }
      });
      return bad;
    }
"""

EXERCISE_CONTROLS = """
    async () => {
      const log = [];
      for (const d of document.querySelectorAll('details')) { d.open = true; }
      await new Promise(r => setTimeout(r, 200));
      for (const c of document.querySelectorAll('.vis-container')) {
        for (const el of c.querySelectorAll('input[type=range]')) {
          const lo = +el.min || 0, hi = +el.max || 100;
          for (const v of [lo, (lo + hi) / 2, hi]) {
            el.value = v; el.dispatchEvent(new Event('input', {bubbles: true}));
          }
          log.push('slider ' + (el.id || '?'));
        }
        for (const el of c.querySelectorAll('select')) {
          for (const o of el.options) {
            el.value = o.value; el.dispatchEvent(new Event('change', {bubbles: true}));
          }
          log.push('select ' + (el.id || '?'));
        }
        for (const el of c.querySelectorAll('button')) {
          for (let i = 0; i < 3; i++) el.click();
          log.push('button ' + (el.id || '?'));
        }
      }
      await new Promise(r => setTimeout(r, 400));
      return log;
    }
"""

# Two silent layout failures, neither of which a build step or a screenshot
# glance reliably catches.
#
# A label positioned from a data domain can land outside the viewBox, where it is
# simply invisible, or on top of another label, where both become unreadable.
# Both depend on control settings, so this runs at several settings.
#
# Separately, the viewBox lives in the markdown and the layout coordinates live
# in the JS. Change one and forget the other and the diagram either loses its
# bottom edge or ships a slab of blank space. Comparing the drawn content's
# extent against the declared viewBox catches both directions.
CHECK_LAYOUT = """
    async (opts) => {
      const { mode, minFill, pad, overlapFrac } = opts;
      document.querySelectorAll('details').forEach(d => { d.open = true; });
      for (const c of document.querySelectorAll('.vis-container')) {
        for (const el of c.querySelectorAll('input[type=range]')) {
          const lo = +el.min || 0, hi = +el.max || 100;
          el.value = mode === 'min' ? lo : mode === 'max' ? hi : (lo + hi) / 2;
          el.dispatchEvent(new Event('input', { bubbles: true }));
        }
        // A select changes the layout as much as a slider does, and a diagram
        // whose modes add or move labels is only checked in the mode that
        // happens to be selected by default unless the options are swept too.
        for (const el of c.querySelectorAll('select')) {
          const opts = [...el.options];
          if (!opts.length) continue;
          const pick = mode === 'min' ? 0
            : mode === 'max' ? opts.length - 1
            : Math.floor((opts.length - 1) / 2);
          el.value = opts[pick].value;
          el.dispatchEvent(new Event('change', { bubbles: true }));
        }
      }
      await new Promise(r => setTimeout(r, 350));

      const out = [];
      for (const c of document.querySelectorAll('.vis-container')) {
        const svg = c.querySelector('svg');
        if (!svg || !svg.viewBox || !svg.viewBox.baseVal) continue;
        const vb = svg.viewBox.baseVal;
        if (!vb.width || !vb.height) continue;
        const sr = svg.getBoundingClientRect();
        if (!sr.width || !sr.height) continue;
        const kx = sr.width / vb.width, ky = sr.height / vb.height;
        const toVB = (r) => ({
          left: (r.left - sr.left) / kx, right: (r.right - sr.left) / kx,
          top: (r.top - sr.top) / ky, bottom: (r.bottom - sr.top) / ky,
        });

        const escaped = [];
        const texts = [...svg.querySelectorAll('text')]
          .filter(t => (t.textContent || '').trim());
        for (const t of texts) {
          const raw = t.getBoundingClientRect();
          if (!raw.width) continue;
          const b = toVB(raw);
          if (b.left < -pad || b.right > vb.width + pad ||
              b.top < -pad || b.bottom > vb.height + pad) {
            escaped.push(t.textContent.trim().slice(0, 30));
          }
        }

        const overlaps = [];
        const boxes = texts.map(t => [t, t.getBoundingClientRect()])
          .filter(b => b[1].width > 0);
        for (let i = 0; i < boxes.length; i++) {
          for (let j = i + 1; j < boxes.length; j++) {
            const a = boxes[i][1], b = boxes[j][1];
            const ix = Math.min(a.right, b.right) - Math.max(a.left, b.left);
            const iy = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
            if (ix <= 3 || iy <= 3) continue;
            const smaller = Math.min(a.width * a.height, b.width * b.height);
            if (smaller > 0 && (ix * iy) / smaller > overlapFrac) {
              overlaps.push(boxes[i][0].textContent.trim().slice(0, 22) + ' / ' +
                            boxes[j][0].textContent.trim().slice(0, 22));
            }
          }
        }

        // Extent actually drawn, from every rendered child.
        let lo = Infinity, hi = -Infinity;
        for (const el of svg.querySelectorAll('*')) {
          if (el.tagName === 'defs' || el.closest('defs')) continue;
          let raw;
          try { raw = el.getBoundingClientRect(); } catch (e) { continue; }
          if (!raw.width && !raw.height) continue;
          const b = toVB(raw);
          if (!isFinite(b.top) || !isFinite(b.bottom)) continue;
          lo = Math.min(lo, b.top);
          hi = Math.max(hi, b.bottom);
        }
        const fill = isFinite(hi) ? (hi - Math.max(0, lo)) / vb.height : 1;
        out.push({
          id: c.id, vbH: Math.round(vb.height),
          drawn: isFinite(hi) ? Math.round(hi) : null,
          fill: Math.round(fill * 100) / 100,
          slack: fill < minFill, escaped, overlaps: overlaps.slice(0, 4),
        });
      }
      return out;
    }
"""


COLLECT_LINKS = """
() => Array.from(document.querySelectorAll('a[href]'), a => a.getAttribute('href'))
"""

# Anything mkdocs-material can legitimately point at that is not a page of this
# project: other schemes, and the theme's own generated navigation.
_SKIP_SCHEMES = ("http://", "https://", "mailto:", "tel:", "javascript:", "data:")


def classify_link(slug, href):
    """Sort one href into ('skip'|'internal'|'escapes', path, fragment).

    `escapes` means the link climbs above the served project root, which is how
    a link into a sibling paper is written. Those resolve only in the combined
    `pixi run index` build, so a single-project run cannot check them and must
    not fail them either. Distinguishing the two cases is the whole reason this
    is not simply "every link must return 200".
    """
    if not href or href.startswith(_SKIP_SCHEMES):
        return "skip", None, None
    if href.startswith("#"):
        return "internal", slug, href[1:]

    path, _, frag = href.partition("#")
    if not path:
        return "internal", slug, frag

    # Depth of the page doing the linking. "/a/" is depth 1, "/" is depth 0.
    depth = len([p for p in slug.split("/") if p])
    ups = 0
    for part in path.split("/"):
        if part == "..":
            ups += 1
        elif part not in ("", "."):
            break
    if ups > depth:
        return "escapes", path, frag

    base = slug if slug.endswith("/") else slug.rsplit("/", 1)[0] + "/"
    parts = [p for p in base.split("/") if p]
    for part in path.split("/"):
        if part == "..":
            if parts:
                parts.pop()
        elif part not in ("", "."):
            parts.append(part)
    resolved = "/" + "/".join(parts)
    if path.endswith("/") and not resolved.endswith("/"):
        resolved += "/"
    return "internal", resolved, frag


_ID_RE = re.compile(r'\bid="([^"]+)"')


def page_anchors(ctx, base, path, cache):
    """Element ids on one served page, fetched once and cached.

    Returns None when the page itself cannot be fetched, so the caller can
    report a broken path rather than a missing anchor.
    """
    if path in cache:
        return cache[path]
    try:
        resp = ctx.request.get(f"{base}{path}")
        ids = set(_ID_RE.findall(resp.text())) if resp.status < 400 else None
    except PlaywrightError:
        ids = None
    cache[path] = ids
    return ids


RENDERED_CONTAINERS = """
    () => [...document.querySelectorAll('.vis-container')].map(c => {
      const svg = c.querySelector('svg');
      return { id: c.id, nodes: svg ? svg.querySelectorAll('*').length : -1 };
    })
"""


def site_name(project):
    """The site_name declared in mkdocs.yml, used to confirm identity."""
    m = re.search(r'^site_name:\s*["\']?(.+?)["\']?\s*$',
                  (project / "mkdocs.yml").read_text(), re.M)
    return m.group(1).strip() if m else None


def confirm_right_site(page, base, project):
    """Refuse to check a server that is not this project.

    Ports get reused. A stale `mkdocs serve` from another project will answer on
    8000 and every page of this site will 404, which looks like a site bug and
    is not one. In a repo holding several papers that is the normal case rather
    than an accident, so fail loudly.
    """
    expected = site_name(project)
    title = page.title()
    if expected and expected.lower() not in (title or "").lower():
        raise SystemExit(
            f"{base} is serving '{title}', but {project.name}/mkdocs.yml "
            f"declares '{expected}'.\nAnother site is on that port. Run "
            f"`pixi run serve {project.name}`, or pass --port N."
        )


def page_slugs(project):
    """Page URLs, from mkdocs.yml nav if present.

    Commented-out nav lines are skipped. The template ships its future pages
    commented out, so counting them would report every unwritten page as a 404
    on a freshly scaffolded project.
    """
    cfg = (project / "mkdocs.yml").read_text()
    nav = re.search(r"^nav:\s*$(.*?)(?=^\S)", cfg, re.M | re.S)
    slugs = ["/"]
    if nav:
        live = "\n".join(line for line in nav.group(1).splitlines()
                         if not line.lstrip().startswith("#"))
        for m in re.finditer(r":\s*([\w./-]+\.md)\s*$", live, re.M):
            f = m.group(1)
            if f == "index.md":
                continue
            slugs.append("/" + f[:-3] + "/")
    return slugs


def main():
    name, args = split_project_arg(sys.argv[1:], ("--port",))
    project = resolve_project(name)
    shots = "--shots" in args
    port = DEFAULT_PORT
    if "--port" in args:
        port = int(args[args.index("--port") + 1])
    base = f"http://127.0.0.1:{port}"
    out = project / "screenshots"
    if shots:
        out.mkdir(exist_ok=True)
    slugs = page_slugs(project)
    failures = 0
    anchor_cache = {}
    cross_project = set()

    with sync_playwright() as p:
        browser = p.chromium.launch()
        for slug in slugs:
            # A fresh context per page, so console errors cannot be inherited
            # from an earlier page and reported against this one.
            ctx = browser.new_context(viewport={"width": 1280, "height": 900})
            page = ctx.new_page()
            errors = []
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: errors.append(str(e)))

            try:
                resp = page.goto(f"{base}{slug}", wait_until="load")
            except PlaywrightError as exc:
                # Nothing listening is the common case, and a Playwright stack
                # trace hides which of the two commands was forgotten.
                ctx.close()
                browser.close()
                raise SystemExit(
                    f"Cannot reach {base}{slug}: {str(exc).splitlines()[0]}\n"
                    f"Start the site first with `pixi run serve {project.name}`, "
                    "or pass --port N if it is on another port."
                ) from None
            if slug == "/":
                confirm_right_site(page, base, project)
            if resp and resp.status >= 400:
                failures += 1
                print(f"FAIL {slug:24s} HTTP {resp.status}")
                ctx.close()
                continue
            page.wait_for_timeout(900)

            containers = page.evaluate(RENDERED_CONTAINERS)
            empty = [c["id"] for c in containers if c["nodes"] <= 0]
            images = page.evaluate(COUNT_BROKEN_IMAGES, IMAGE_SETTLE_MS)
            broken, pending = images["broken"], images["pending"]

            layout = []
            for mode in LAYOUT_MODES:
                for d in page.evaluate(CHECK_LAYOUT, {
                    "mode": mode, "minFill": MIN_VIEWBOX_FILL,
                    "pad": LABEL_PAD, "overlapFrac": LABEL_OVERLAP_FRAC,
                }):
                    if d["escaped"]:
                        layout.append(f"{d['id']} [{mode}] label outside viewBox: "
                                      f"{d['escaped'][0]!r}")
                    if d["overlaps"]:
                        layout.append(f"{d['id']} [{mode}] labels overlap: "
                                      f"{d['overlaps'][0]}")
                    # Only report slack once, since it does not vary with controls
                    # in any interesting way and would otherwise triple.
                    if d["slack"] and mode == LAYOUT_MODES[0]:
                        layout.append(
                            f"{d['id']} draws to y={d['drawn']} of a "
                            f"{d['vbH']} viewBox ({int(d['fill'] * 100)}% used); "
                            f"the markup height and the JS layout have drifted")

            links = []
            for href in page.evaluate(COLLECT_LINKS):
                kind, path, frag = classify_link(slug, href)
                if kind == "skip":
                    continue
                if kind == "escapes":
                    cross_project.add(href)
                    continue
                ids = page_anchors(ctx, base, path, anchor_cache)
                if ids is None:
                    links.append(f"dead link {href!r} -> {path} does not load")
                elif frag and frag not in ids:
                    links.append(f"dead anchor {href!r} -> #{frag} is not on {path}")

            page.evaluate(EXERCISE_CONTROLS)
            bad = page.evaluate(SCAN_BAD_GEOMETRY)

            if shots:
                shot = slug.strip("/").replace("/", "_") or "index"
                page.screenshot(path=str(out / f"{shot}.png"), full_page=True)

            status = []
            if broken:
                status.append(f"{broken} broken images")
            if pending:
                # Not a failure: a lazy image can stay pending on a tall page.
                # Worth saying, because it is the one thing this check did not
                # manage to inspect.
                print(f"     {slug} images still pending: {', '.join(pending)}")
            if empty:
                status.append(f"empty diagrams: {','.join(empty)}")
            if bad:
                status.append(f"{len(bad)} non-finite geometry ({bad[0]})")
            if layout:
                status.append(f"{len(layout)} layout problems")
            if links:
                status.append(f"{len(links)} link problems")
            if errors:
                status.append(f"{len(errors)} console errors: {errors[0][:70]}")

            if status:
                failures += 1
                print(f"FAIL {slug:24s} {'; '.join(status)}")
                for problem in layout + links:
                    print(f"       {problem}")
            else:
                print(f"ok   {slug:24s} {len(containers)} diagrams, no errors")
            ctx.close()
        browser.close()

    print()
    if cross_project:
        # Not a failure. These climb above this project's root, so they resolve
        # only in the combined `pixi run index` build. Naming them is the point:
        # otherwise a link into a sibling paper is checked by nothing at all.
        print(f"{len(cross_project)} links leave this project and were not "
              f"checked here:")
        for href in sorted(cross_project):
            print(f"     {href}")
        print("     Verify these against `pixi run index`, which builds the "
              "sibling projects beside each other.")
        print()
    if failures:
        print(f"{failures} of {len(slugs)} pages have problems.")
        raise SystemExit(1)
    print(f"All {len(slugs)} pages clean on {base}.")


if __name__ == "__main__":
    main()

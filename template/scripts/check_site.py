#!/usr/bin/env python
"""Verify the built site in a real browser. Paper-agnostic.

Discovers pages from mkdocs.yml, then for each page:
  - opens every collapsed <details>, since Playwright cannot drive a hidden
    control and optional depth usually lives behind a disclosure
  - checks every diagram container actually rendered something
  - exercises every button, slider and select it can find
  - re-checks for non-finite SVG geometry, which is how a scale computed from
    empty data silently destroys a panel
  - counts genuinely broken images, distinguishing them from lazy images that
    simply have not loaded yet
  - reports console errors

Usage:
    pixi run serve                 # in another terminal
    pixi run check-site
    pixi run check-site --shots     # also save a screenshot per page

Why a browser and not a unit test: every failure this catches is a rendering
failure that a build step reports as success.
"""

import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).parent.parent
OUT = ROOT / "screenshots"
DEFAULT_PORT = 8000

# A lazy image that has not loaded is not broken. Only zero intrinsic width
# after loading settles counts as a real failure.
COUNT_BROKEN_IMAGES = """
    async () => {
      window.scrollTo(0, document.body.scrollHeight);
      await new Promise(r => setTimeout(r, 400));
      window.scrollTo(0, 0);
      const imgs = [...document.querySelectorAll('img')];
      await Promise.all(imgs.map(i => i.complete ? null : new Promise(r => {
        i.addEventListener('load', r); i.addEventListener('error', r);
      })));
      return imgs.filter(i => i.naturalWidth === 0).length;
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

RENDERED_CONTAINERS = """
    () => [...document.querySelectorAll('.vis-container')].map(c => {
      const svg = c.querySelector('svg');
      return { id: c.id, nodes: svg ? svg.querySelectorAll('*').length : -1 };
    })
"""


def site_name():
    """The site_name declared in mkdocs.yml, used to confirm identity."""
    m = re.search(r'^site_name:\s*["\']?(.+?)["\']?\s*$',
                  (ROOT / "mkdocs.yml").read_text(), re.M)
    return m.group(1).strip() if m else None


def confirm_right_site(page, base):
    """Refuse to check a server that is not this project.

    Ports get reused. A stale `mkdocs serve` from another project will answer on
    8000 and every page of this site will 404, which looks like a site bug and
    is not one. Fail loudly instead.
    """
    expected = site_name()
    title = page.title()
    if expected and expected.lower() not in (title or "").lower():
        raise SystemExit(
            f"{base} is serving '{title}', but mkdocs.yml declares "
            f"'{expected}'.\nAnother project is probably on that port. Run "
            f"`pixi run serve` for THIS project, or pass --port N."
        )


def page_slugs():
    """Page URLs, from mkdocs.yml nav if present."""
    cfg = (ROOT / "mkdocs.yml").read_text()
    nav = re.search(r"^nav:\s*$(.*?)(?=^\S)", cfg, re.M | re.S)
    slugs = ["/"]
    if nav:
        for m in re.finditer(r":\s*([\w./-]+\.md)\s*$", nav.group(1), re.M):
            f = m.group(1)
            if f == "index.md":
                continue
            slugs.append("/" + f[:-3] + "/")
    return slugs


def main():
    shots = "--shots" in sys.argv
    port = DEFAULT_PORT
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    base = f"http://127.0.0.1:{port}"
    if shots:
        OUT.mkdir(exist_ok=True)
    slugs = page_slugs()
    failures = 0

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

            resp = page.goto(f"{base}{slug}", wait_until="load")
            if slug == "/":
                confirm_right_site(page, base)
            if resp and resp.status >= 400:
                failures += 1
                print(f"FAIL {slug:24s} HTTP {resp.status}")
                ctx.close()
                continue
            page.wait_for_timeout(900)

            containers = page.evaluate(RENDERED_CONTAINERS)
            empty = [c["id"] for c in containers if c["nodes"] <= 0]
            broken = page.evaluate(COUNT_BROKEN_IMAGES)
            page.evaluate(EXERCISE_CONTROLS)
            bad = page.evaluate(SCAN_BAD_GEOMETRY)

            if shots:
                name = slug.strip("/").replace("/", "_") or "index"
                page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)

            status = []
            if broken:
                status.append(f"{broken} broken images")
            if empty:
                status.append(f"empty diagrams: {','.join(empty)}")
            if bad:
                status.append(f"{len(bad)} non-finite geometry ({bad[0]})")
            if errors:
                status.append(f"{len(errors)} console errors: {errors[0][:70]}")

            if status:
                failures += 1
                print(f"FAIL {slug:24s} {'; '.join(status)}")
            else:
                print(f"ok   {slug:24s} {len(containers)} diagrams, no errors")
            ctx.close()
        browser.close()

    print()
    if failures:
        print(f"{failures} of {len(slugs)} pages have problems.")
        raise SystemExit(1)
    print(f"All {len(slugs)} pages clean on {base}.")


if __name__ == "__main__":
    main()

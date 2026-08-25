# AGENTS.md

## What you are building

An mkdocs site that explains one research paper to the audience named in
`PAPER.md`, using interactive D3 diagrams. The paper's PDF is in the project
root.

## Before anything else

1. **Read `PAPER.md` in full.** It is the brief. If a required field is empty
   (audience, the one thing, emphasise, skip), ask rather than guess. Scope
   creep is the main failure mode of this project type, and `PAPER.md` is the
   only thing holding it back.
2. **Load the `paper-explainer` skill** in `skills/paper-explainer/SKILL.md`. It
   carries the accumulated lessons: figure geometry, diagram honesty, how to
   explain a statistical method, how to budget depth. Follow it.
3. **Copy `template/` into the project root** if it has not been copied yet:
   `pixi.toml`, `mkdocs.yml`, `scripts/`, `docs/`. Then `pixi install`.
4. **Read the paper.** Not just the abstract and figures: the methods, and the
   supplemental methods, which is where the details that make claims correct
   actually live.

## Build order

Do these in order. Each step depends on the previous one being right.

### 1. Understand the paper's geometry

```bash
pixi run probe                 # which pages hold figures, and their panels
pixi run probe --page N        # detail for one page
pixi run probe --suggest       # candidate crop boxes
```

Page indices are 0-based and do not match printed page numbers.

### 2. Extract the figures

Fill in `FIGURES` in `scripts/extract_figures.py` from the probe output, then:

```bash
pixi run verify-figures        # must pass before writing anything
pixi run extract-figures
```

Split any figure whose panels belong on different site pages. Do not hand-tune
boxes without re-running the checks. Confirm the checks bite by temporarily
setting a box to a whole page and watching all three complain.

### 3. Plan the pages

Write the nav in `mkdocs.yml` and a one-line purpose for each page. Check the
plan against `PAPER.md`'s emphasise and skip lists before writing prose.

If the pipeline page is on, settle its endpoint here. Use `PAPER.md`'s
**Pipeline target** if it names one; if it is blank, pick the paper's central
multi-stage result, and tell the user which figure or panel you chose before
building the page. Every stage on the page has to be on the path to that
endpoint.

### 4. Write pages one at a time

For each page: prose first, then the figures it needs, then the diagrams. Keep
narrative pages under about 800 words. Put optional depth behind `???`
disclosures rather than letting a page sprawl.

### 5. Build the diagrams

Follow the conventions at the top of `docs/assets/js/diagrams.js`. Use
`lib/stats.js` for anything statistical rather than writing a second copy.

### 6. Verify

```bash
pixi run build                 # no warnings
pixi run check-refs            # figures referenced and generated both ways
pixi run serve                 # then, in another terminal:
pixi run check-site            # browser check of every page
```

`check-site` opens disclosures, exercises every control, and scans for
non-finite geometry. It must be clean.

### 7. Audit

Run an accuracy pass over every claim against the PDF, and a writing pass
against the no-ai-slop rules. `/audit-accuracy` fans this out across
sub-agents. Do this before declaring done, not after the user asks.

### 8. Keep CI green

`template/.github/workflows/ci.yml` was copied in with the rest of the template.
It checks the prose conventions, the figure crops and their references, a
warning-free build, and the site in a browser. Run those checks locally before
declaring done rather than discovering them in CI.

If you change the shipped machinery in `scripts/` or
`docs/assets/js/lib/stats.js`, the starter repo's own tests cover it:
`tests/test_pdf_geometry.py` and `tests/test_stats.cjs`. Fixes that are not
paper-specific belong upstream in the starter, with a test.

## Rules that are not negotiable

Repeated from `PAPER.md` because they are the ones most often broken:

- **Every number traces to the paper**, supplemental methods included.
- **No invented numbers in diagrams.** Real values, or an explicitly labelled
  schematic with no numeric axis.
- **A "fit" button must actually fit.** `lib/stats.js` does real maximum
  likelihood; use it. Displaying the generating parameters as though they were
  estimated is the single most tempting shortcut here and it destroys the point
  of the demonstration.
- **Captions describe exactly the visible panels.**
- **Correlational analyses get correlational language.**
- **When a fit fails, show nothing.** Non-converged coefficients are not
  results.

## Writing

Follow the no-ai-slop rules. In particular, for this project type:

- **Em dashes: use none.** Commas, colons, periods, parentheses instead.
- No mid-sentence colons.
- No "not just X but Y" contrasts. State Y.
- No reader guidance: "note that", "the key point is", "it's worth noting".
- No schematic sitting next to the real figure it schematises. Delete it and
  link.
- Do not introduce a quantity by naming it. If the site invents a symbol, say
  what problem it solves and where its formula comes from.

## When you finish a page

Check it against its siblings by word count. If one page is three times longer
than the rest, the depth needs demoting behind a disclosure, not keeping.

## Feeding lessons back

`skills/paper-explainer/SKILL.md` is meant to accumulate. When you hit a
pitfall, find a better approach, or discover a convention worth keeping, update
the skill so the next paper benefits. Do the same for the generic machinery in
`template/scripts/` and `template/docs/assets/js/lib/`: a fix that is not
paper-specific belongs there, not in this project's copy.

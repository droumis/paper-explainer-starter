# Paper explainer starter

Turn a research paper PDF into an interactive mkdocs site.

## Use it
0. **Make a new directory and go into it**
1. **Get the starter.** Click "Use this template" on GitHub, or:

   ```bash
   git clone git@github.com:droumis/paper-explainer-starter.git my-paper-site
   cd my-paper-site && rm -rf .git && git init
   ```

2. **Put the PDF in that folder.** `cp ~/Downloads/some-paper.pdf .`

3. **Open the folder in your coding agent and run `/build-site`.** If it does not
   do slash commands, say "follow AGENTS.md" instead.

The command reads the PDF and drafts the brief from it, then asks you the few
things the paper cannot settle: who is reading, the one sentence they should
remember, what to skip. After that it derives the figure crops, writes the pages,
builds the diagrams, and checks the result in a browser. `pixi run serve` shows
the site at `http://localhost:8000`.

### Steering it

`PAPER.md` is where those answers get recorded, and the steering wheel
afterwards. Edit it and run `/build-site` again to rebuild with a different
audience, a different emphasis, or a different pipeline endpoint. Filling it in
before you start also works, and then the command has nothing to ask.

To skip the questions, run `/build-site auto`, or set **Decide for me** to `yes`
in `PAPER.md`. The agent then picks the audience, the one sentence, the emphasis
and the skip list from the paper, marks each choice in `PAPER.md`, and lists them
when it finishes. That is the fastest path and the one most likely to aim at the
wrong reader, so expect to correct a field and rebuild.

## What you get

- an mkdocs-material site with interactive D3 diagrams
- figure crops taken from the PDF, checked so they cannot include caption text
  or cut off panels the captions describe
- real in-browser model fitting where the paper fits a model, rather than
  animations that display a stored answer
- optionally, a page carrying one simulated dataset from raw data through to
  reconstructions of the paper's figure panels, and a companion notebook

## What is in here

| Path | Purpose |
|---|---|
| `PAPER.md` | The brief. **The one file that steers the build.** Blank fields get drafted from the PDF and confirmed with you. |
| `AGENTS.md` | Instructions the agent follows. |
| `skills/paper-explainer/SKILL.md` | Accumulated lessons: figure geometry, diagram honesty, explaining a method, budgeting depth. |
| `template/` | Working machinery, copied into the project root. Not reinvented per paper. |
| `.kilo/command/` | `/build-site` and `/audit-accuracy`. |

### The machinery

`template/scripts/`

- `pdf_geometry.py` derives figure geometry from the PDF's own structure. Handles
  the three traps that otherwise produce silently wrong crops: clipped paths
  reporting unclipped bounds, text block boxes overclaiming in two-column
  layouts, and zero-thickness rects being invisible to intersection tests.
- `probe_pdf.py` reports that geometry so crop boxes can be derived instead of
  guessed. Run it first.
- `extract_figures.py` crops figures and **refuses to write bad ones**. Three
  checks: no prose inside a crop, no content clipped or stranded between crops,
  every panel label inside some crop.
- `check_site.py` drives the built site in a browser: opens disclosures,
  exercises every control, scans for non-finite SVG geometry, counts genuinely
  broken images, reports console errors.

`template/docs/assets/js/lib/stats.js` is paper-agnostic statistics: seeded RNG,
Poisson sampling, a linear solver, a Poisson GLM fitted by IRLS with an optional
per-iteration trace, and repeated-split cross-validation against a shuffled
baseline. It exists so a diagram can do real estimation rather than revealing
the parameters it generated its own data from.

## Tests and CI

```bash
node tests/test_stats.cjs                                       # 39 checks
pixi run --manifest-path template/pixi.toml \
  python tests/test_pdf_geometry.py                             # 21 checks
```

`tests/test_pdf_geometry.py` fabricates a synthetic journal page containing the
three things that make naive PDF geometry wrong, so it needs no real paper:

- a path whose fill reaches into the text column but is **clipped** to the figure
- a **two-column layout** where the body text is indented around the figure
- **zero-thickness** axis lines and tick marks

It then asserts that a box produced by `suggest_crop` passes all three crop
checks, and that boxes which swallow prose, clip content, strand content between
crops, or omit a panel label are each rejected.

`tests/test_stats.cjs` checks the statistics: that the RNG is reproducible and
uniform, that Poisson samples have variance equal to their mean, that the solver
pivots and reports singular matrices, that the GLM recovers known coefficients
and refuses underdetermined fits, that `w = mu` and `z = eta + (y-mu)/mu` hold in
the trace, and that estimation error falls as 1/sqrt(n).

It deliberately does **not** assert that the log-likelihood rises every pass. An
undamped Newton step can overshoot from a cold start, so it sometimes dips. A
site claiming the score "rose" each pass is wrong a few percent of the time.

### Two workflows

`.github/workflows/ci.yml` covers this repo: syntax, both test suites, and a
proof that `cp -r template/* .` yields a project that builds with no warnings.
It also fails if the template ever ships paper-specific state such as filled-in
crop boxes or a committed PDF.

`template/.github/workflows/ci.yml` is copied into each paper project. It checks
syntax, the prose conventions (no em dashes, no "not just X but Y"), the figure
crops and their references, a warning-free build, and then drives the built site
in a real browser.

## Requirements

[pixi](https://pixi.sh). Everything else is declared in `template/pixi.toml`.

## Why the checks

Every check corresponds to something that shipped broken in an earlier build of
one of these sites:

- a figure caption describing panels D and E while the crop cut them off
- a cross-validation animation reporting correlations from `sin(fold * 0.7)`
- a "Fit" button that plotted the generating weights labelled "fitted"
- red meaning "positive" in one diagram and "negative" in another on one page
- a bar chart whose scale went `NaN` when a subsample produced no usable data
- a stale figure file that re-running extraction never regenerated, so fixing
  the crop box appeared to do nothing

A build that succeeds is not a site that works.

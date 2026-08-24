# Paper explainer starter

Turn a research paper PDF into an interactive mkdocs site.

## Use it

```bash
# 1. new project from this starter
git clone <this-repo> my-paper-site && cd my-paper-site
rm -rf .git && git init

# 2. drop the paper in
cp ~/Downloads/some-paper.pdf .

# 3. say what you want
$EDITOR PAPER.md

# 4. open the folder in your editor and tell the agent:
#      "Follow AGENTS.md"
```

The agent reads `PAPER.md`, copies `template/` into place, works out the figure
geometry from the PDF, and builds the site. `PAPER.md` is the steering wheel:
fill in what to emphasise and what to skip, and it will respect both.

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
| `PAPER.md` | The brief. **This is the file you edit.** |
| `AGENTS.md` | Instructions the agent follows. |
| `skills/paper-explainer/SKILL.md` | Accumulated lessons: figure geometry, diagram honesty, explaining a method, budgeting depth. |
| `template/` | Working machinery, copied into the project root. Not reinvented per paper. |
| `.kilo/command/` | Slash commands for the build and the accuracy audit. |

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

# Paper explainer starter

Turn a research paper PDF into an interactive mkdocs site.

## Use it

You have a PDF somewhere on your machine. Paste this to your coding agent, with
your own path in place of the example:

```text
Clone https://github.com/droumis/paper-explainer-starter into a new directory
named after the paper, replace the starter's git history with a fresh one, and
copy ~/Downloads/some-paper.pdf into it. Then read that project's AGENTS.md and
build the explainer site.
```

The agent reads the PDF and drafts the brief from it, then asks you the few things
the paper cannot settle: who is reading, the one sentence they should remember,
what to skip. After that it derives the figure crops, writes the pages, builds the
diagrams, and checks the result in a browser. `pixi run serve` shows the site at
`http://localhost:8000`.

Reopen the new directory as its own project afterwards, so `/build-site` and
`/audit-accuracy` load, and rebuilds are one command.

### Or set it up by hand

0. **Make an empty directory for the site and `cd` into it.** Name it whatever
   you like. This becomes the project, one directory per paper.

1. **Get the starter into it.**

   ```bash
   git clone https://github.com/droumis/paper-explainer-starter.git .
   rm -rf .git && git init          # your own history, not the starter's
   ```

   Or click "Use this template" on GitHub and clone your copy the same way.

2. **Put the machinery in place and the PDF next to it.**

   ```bash
   pixi run --manifest-path template/pixi.toml init
   cp ~/Downloads/some-paper.pdf .
   ```

   The filename does not matter; the tooling reads whichever PDF is in the
   project root, and complains if there are two.

3. **Open the directory in your coding agent and run `/build-site`.** If it does
   not do slash commands, say "follow AGENTS.md" instead.

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

### Several papers in one repo

Cloning the starter per paper gives you N copies of the machinery to keep in
step, and N environments. For a directory of papers, keep one repo instead:

```bash
git clone https://github.com/droumis/paper-explainer-starter.git ~/src/papers
cd ~/src/papers
pixi run --manifest-path template/pixi.toml init --mono
pixi install
pixi run new-paper andermann-2011     # scaffolds the directory
```

Keep the clone's history rather than running `git init`. The papers repo is then a
fork of this one: machinery arrives by pulling, and your own commits only ever add
paper directories.

```bash
git pull origin main       # machinery updates
pixi run update            # push them into the root manifest and each paper's shared assets
```

`init --mono` puts `pixi.toml` at the root and links `scripts` to
`template/scripts`, so there is one copy of the machinery for every paper. Those
two are ignored by `.gitignore`, because they are local instantiation rather than
content, which is what keeps every pull a clean fast-forward.

Sending a lesson back upstream, once you hit one while writing a paper:

```bash
git fetch origin
git checkout -b better-crop-check origin/main   # a branch with no paper commits
git cherry-pick <the commit touching template/, skills/ or tests/>
git push origin better-crop-check
```

Then drop that paper's PDF in `andermann-2011/`, and name the paper in any
command: `pixi run probe andermann-2011 --suggest`, `pixi run serve
andermann-2011`. The argument is optional while only one paper exists, and
required once there are two, because guessing which paper you meant is how the
wrong site gets rebuilt. `pixi run papers` lists them with their state.

Each paper directory holds its own PDF, `PAPER.md`, `figures.toml`, `mkdocs.yml`
and `docs/`, and builds its own independent site. `pixi run sync-assets` pushes a
shared CSS or `stats.js` improvement from `template/` into papers that already
exist, leaving each paper's `diagrams.js` alone. A shared file that a paper has
edited is reported and skipped rather than overwritten, since that edit is
usually a lesson that belongs upstream.

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
| `template/` | Working machinery, copied into the project root, or shared by every paper in a multi-paper repo. Not reinvented per paper. |
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
- `project.py` decides which paper a command acts on, and loads that paper's
  `figures.toml`. Every malformed crop entry is reported at once, with the key
  named, rather than one per run.
- `papers.py` scaffolds a paper, syncs the shared assets into existing papers,
  and wraps `mkdocs serve`/`build` so the project is named the same way for every
  command.

`template/docs/assets/js/lib/stats.js` is paper-agnostic statistics: seeded RNG,
Poisson sampling, a linear solver, a Poisson GLM fitted by IRLS with an optional
per-iteration trace, and repeated-split cross-validation against a shuffled
baseline. It exists so a diagram can do real estimation rather than revealing
the parameters it generated its own data from.

## Tests and CI

```bash
node tests/test_stats.cjs                                       # 39 checks
pixi run --manifest-path template/pixi.toml \
  python tests/test_pdf_geometry.py                             # 44 checks
pixi run --manifest-path template/pixi.toml \
  python tests/test_papers.py                                   # 11 checks
```

`tests/test_papers.py` covers scaffolding and asset syncing, and its central case
is a paper that improves a shared file: syncing must leave that copy alone and say
so, because the improvement is what belongs upstream and losing it is silent.

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

`template/.github/workflows/site.yml` is installed by `init`, under that name so
it never collides with this repo's own `ci.yml` and a pull stays clean. The
starter's `ci.yml` comes along with the clone and keeps testing the machinery;
delete it if you would rather not run that. `site.yml` checks
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

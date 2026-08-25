---
name: paper-explainer
description: Build an interactive mkdocs site that explains a research paper. Use when turning a paper PDF into a teaching site with D3 diagrams, extracted figure crops, and in-browser model fitting.
---

# Paper Explainer

Build a site that makes one paper's context, methods, results and significance
understandable to a stated audience, using interactive diagrams.

## The machinery already exists

**Do not reimplement any of this.** It is in `template/` and it is
paper-agnostic. Rebuilding it from the descriptions below will reproduce bugs
that took a long time to find.

| File | What it does |
|---|---|
| `scripts/pdf_geometry.py` | Derives figure geometry from the PDF's structure, handling clipped paths, overclaiming text blocks, and zero-thickness rects |
| `scripts/probe_pdf.py` | Reports that geometry; `--suggest` proposes crop boxes. **Run first.** |
| `scripts/extract_figures.py` | Crops figures, refusing to write bad ones. Three checks. |
| `scripts/check_site.py` | Drives the built site in a browser and fails on rendering problems |
| `docs/assets/js/lib/stats.js` | Seeded RNG, Poisson sampling, linear solver, Poisson GLM by IRLS with trace, cross-validation |
| `docs/assets/css/{distill,custom}.css` | Diagram, figure, caption and control styling |

The sections below explain the judgement calls the machinery cannot make for
you: what to crop, what to plot, how much depth to give, and how to write it.

## Principles

- **Visual first.** Every concept gets a diagram before prose. Use screenshots from the actual paper figures as anchors, but generate new explanatory diagrams (D3.js, SVG, or Python-rendered) that build intuition step by step.
- **Synthetic before real.** For complex analyses (GLMs, statistical tests, decoding), construct a simplified synthetic example the reader works through before showing the paper's actual results. This makes the logic graspable before the data is overwhelming.
- **Concise pages.** Each page covers one conceptual unit. Short paragraphs, no filler. Every sentence earns its place.
- **Interactivity where it teaches.** Interactive diagrams (sliders, step-through animations, hover annotations) for concepts where parameter manipulation builds intuition. Static figures for results that are better absorbed at a glance.
- **No AI slop.** All prose must pass the no-ai-slop skill checks. Concrete language, active voice, no throat-clearing, no importance puffery.

## Tech stack

- **Environment**: pixi (pixi.toml at repo root)
- **Site generator**: mkdocs with mkdocs-material theme
- **Interactivity**: D3.js v7 for inline interactive diagrams, MathJax for equations
- **Figures**: PyMuPDF (fitz) to extract/crop figures from paper PDF; Pillow for processing
- **Style**: Custom CSS inspired by Distill.pub — clean typography, card-style vis containers, margin notes on wide screens, callout boxes for insights and analogies

## Repo structure

```
├── pixi.toml
├── mkdocs.yml
├── docs/
│   ├── index.md
│   ├── background.md          # Domain context for naive readers
│   ├── experiment.md          # What was done
│   ├── [method-pages].md      # One per key method/analysis
│   ├── synthesis.md           # Big picture, significance
│   └── assets/
│       ├── css/
│       │   ├── custom.css     # Layout overrides
│       │   └── distill.css    # Vis containers, callouts, margin notes
│       ├── js/
│       │   └── diagrams.js    # All D3 interactive code
│       └── img/
│           ├── figures/       # Cropped from paper PDF
│           └── diagrams/      # Generated explanatory diagrams
├── scripts/
│   └── extract_figures.py     # PDF figure extraction
└── paper.pdf                  # Source paper (or symlink)
```

## pixi.toml dependencies

Include at minimum:
- mkdocs
- mkdocs-material
- pymdownx-extensions (via mkdocs-material)
- pymupdf (for figure extraction)
- pillow
- numpy, matplotlib (for generating static diagrams if needed)
- playwright (pypi, for screenshot verification)

## Page writing process

1. Read the relevant section of the paper thoroughly.
2. Identify the 1–3 core concepts the page must convey.
3. Decide which concepts need interactive treatment vs. static figures.
4. Write the page: lead with a one-sentence framing, use figures/diagrams inline with text, close with what the reader now understands.
5. Run the no-ai-slop check on the draft. Fix violations.
6. For interactive sections: write the D3 code in `diagrams.js`, reference the container div from markdown.

**Narrative continuity:** If a page opens by referencing material from a prior page ("the correlations from the previous section..."), verify that material actually exists where you claim. Read the site in order before finalizing — transitions between pages should be seamless.

**Experimental paradigms:** Explain the trial-by-trial structure, not just the high-level goal. A naive reader needs to know: where does the animal start, what does it see/hear, what decision does it make, what makes a trial correct, and what reward does it get. One-sentence summaries are insufficient for paradigms the reader hasn't encountered before.

## Interactive diagram guidelines

- Each diagram lives in a `.vis-container` div with an SVG and optional `.vis-controls` div.
- Diagrams should be self-contained: all data generated in JS, no external fetches.
- Use consistent color variables from the CSS.
- Provide controls (sliders, step buttons) that let the reader manipulate the key parameter.
- Annotate directly on the diagram (labels, arrows) rather than relying on surrounding text.

### Never display invented numbers

A diagram that reports `r = 0.15 + sin(fold * 0.7) * 0.05` or "6.4% improvement" from a hand-tuned formula is showing the reader fabricated data, and it sits on the page next to real statistics from the paper. Either plot the paper's actual values, or make the diagram unmistakably qualitative: drop the numeric axis entirely, label it "(schematic)", and say so in the prose. A schematic curve should also be smooth — added `sin()` wiggle imitates measurement noise and implies data that does not exist.

The subtlest version of this: a **"fit" button that reveals the answer key**. If a synthetic demo generates data from known parameters and then displays those same parameters labeled "fitted", it has skipped the one step it exists to teach. Implement the estimator for real — for a Poisson GLM, iteratively reweighted least squares plus a small Gaussian-elimination solver is about 60 lines and runs instantly in a browser. Then show recovered against true side by side, so the reader sees that estimates are close but not exact.

Real estimation also unlocks teaching that fake estimation cannot:

- **Sample size.** Expose an n slider. The error in recovered parameters falls as 1/√n, so quadrupling the data halves the error — state the scaling law rather than specific numbers, which are seed-dependent.
- **Failure.** Let the reader drive the model into non-convergence (more parameters than observations). If the paper discarded non-converging fits, the reader can now reproduce that exclusion.
- **When a fit fails, show nothing.** A diverged fit's coefficients are meaningless; plotting them as estimates is the invented-numbers problem again. Draw the true values only and say why the estimates are absent.

Also check that synthetic data stays physiologically plausible as controls change. With a log link, adding predictors multiplies the predicted rate, so ten unshrunk weights can produce "17 spikes in 200 ms" and contradict prose that says a window holds one or two. Scale generating weights by the predictor count to hold total drive roughly constant.

### Cut interactives that do not teach

Interactivity has to earn its place. Two patterns to delete on sight:

- **Controls that only recolor.** A "next fold" button that swaps one rectangle from "Train" to "Test" conveys less than the numbered list of steps beside it.
- **Redundant explorers.** If an equation breakdown and a concept diagram already cover the mechanism, a third slider widget on the same idea adds confusion, not depth. Keep the prose bullets, which usually carry the real content, and remove the widget.

When you do cut one, remove the container div, the init function, and its dispatcher line, then grep for every related element ID to confirm nothing dangles. Verify parity afterward: the set of dispatched init calls, the set of defined init functions, and the set of `.vis-container` IDs across all pages should match exactly.

**Check the Playwright verification script too.** It drives diagrams by element ID, so deleting a widget leaves it waiting on an element that will never appear. Playwright then hangs for its full timeout and aborts, skipping every check below that point — so the site quietly loses coverage while the script still looks like it merely "failed at the end". Any diagram removal must be paired with a run of that script.

### Sanity-check multi-panel plots

If one slider changes a panel it logically should not, the reader will notice and lose trust. A common cause: each panel holds the other variable fixed at a nonzero value, so the other coefficient enters as an additive offset in a log-link exponent and rescales both curves. Either hold the other variable at zero, show a single panel, or state the held-fixed value on the plot.

Check axis labels actually render where intended. In D3, setting `x`/`y` attributes **and** a `transform` on the same `<text>` applies the attributes in the transformed frame, so a rotated axis label given both can land in the middle of the plot area instead of beside the axis. Use the transform alone.

## Figure extraction

Use PyMuPDF to render pages at high DPI, then crop to specific figure bounding boxes. Store cropped figures in `docs/assets/img/figures/` with descriptive names like `fig3_swr_modulation.png`.

**Critical: verify page indices visually.** PDF page indices do not reliably match paper page numbers. The extraction script should support a `--pages` mode that renders every page as a full-width PNG so you can visually confirm which page contains each figure before setting crop coordinates. Never guess page indices from paper page numbers alone — full-page figures, supplementary materials, and multi-column layouts can shift everything.

Extraction script modes:
- `--pages`: Render all pages for visual identification
- `--embedded`: Extract all embedded images (useful for quick batch capture)
- `--verify`: Run the crop-box checks below without writing files
- Default: Verify, then crop using (page_idx, Rect) coordinates

### Start with the probe, and expect to iterate

`pixi run probe` first, always. Three things it reliably surfaces that would
otherwise waste hours:

- **Which pages hold figures**, with their panel letters. Page indices are
  0-based and do not match printed page numbers.
- **Whether the PDF contains more than one article.** Downloaded PDFs often
  bundle unrelated material; the inventory makes that obvious immediately.
- **Whether a page's prose sits inside the figure's own extent**, which means
  the page cannot be cropped as one box and must be split by panel.

`--suggest` proposes boxes from the geometry, but treat them as a first draft.
On a real paper the suggestions failed the panel-label check on every page,
because panel letters are *text* and the suggestion unioned only *graphics*.
Both are now unioned, but the general lesson holds: run `--verify` and expect
the checks to reject the first attempt. A suggestion that passes all three
checks on the first try is the exception.

### Anatomical direction markers look exactly like panel labels

In any paper with anatomical maps, single capitals marking anterior, posterior,
medial and lateral are indistinguishable from panel labels by shape. They sit
inside the figure so they do not usually cause false failures, but if the
panel-label check complains about a letter you cannot find as a panel, check
whether it is an orientation marker before moving a crop box to accommodate it.

### Derive crop boxes from PDF geometry, not from eyeballing renders

Eyeballing page renders produces boxes that are wrong in ways nobody notices until a reader complains. Get the coordinates from the PDF itself:

- **Panel positions** come from `page.get_text("blocks")`. Panel labels are short blocks containing a single capital letter; they mark where each panel row starts.
- **Prose boundaries** come from the same call. The caption block begins with "Figure N." and body columns are the large blocks. A crop must stop short of both.
- **Graphic extents** come from `page.get_drawings()` plus `page.get_image_info()`.

Two traps make naive extents wrong:

1. **Clipped paths report unclipped geometry.** A shape clipped to the figure can claim a rect reaching deep into the caption column. Use `page.get_drawings(extended=True)`, track the clip stack by `level`, and intersect each path rect with the active `scissor`.
2. **Block bounding boxes overclaim.** In two-column layouts the body column is often indented around a wide figure, so a block bbox covers territory containing no glyphs. Test individual words from `page.get_text("words")`, filtered to the word-rich blocks, instead of block rects.

Also exclude the page-background rect, the running header/footer, and full-width rules before unioning extents, and skip narrow word-rich blocks — those are rotated axis labels, which are figure content, not prose.

### The extraction script is already self-checking

`scripts/extract_figures.py` gates every write on three checks. Do not weaken
them, and do add to `CHECKS` if you find a fourth class of bad crop:

- **No prose inside the crop.** Catches journal logos, caption text, bled-in
  body columns.
- **No content clipped or stranded.** Catches truncated panels, and content
  falling in the gap between two crops of the same page.
- **Every panel label inside some crop.** Direct guard against a caption
  describing a panel the reader cannot see.

Confirm the checks bite before trusting them: set a box to a whole page
temporarily and watch all three complain. A check you have never seen fail is a
check you cannot rely on.

### One crop per claim

Crop to the panels a given page actually discusses, and write the caption to match. When a paper figure's panels serve different pages, split it into several crops (`fig6ab_pair_correlations`, `fig6c_theta_vs_swr`, `fig6de_glm`) rather than showing the whole figure everywhere and describing only part of it. Captions should name every panel that is visible, and only panels that are visible. Pull the wording from the real caption text (`page.get_text("text", clip=caption_rect)`) so reported statistics and colors match the paper.

### Check references in both directions

After extraction, cross-check that every image referenced in `docs/*.md` exists **and** that every generated image is referenced. The second direction catches stale orphans: if the script's output key is renamed but the markdown is not updated, the page keeps rendering an old file that re-running extraction never regenerates, so fixing the crop box appears to do nothing.

Then verify with Playwright that all `<img>` tags load across all pages. Image paths in markdown pages served as `/pagename/index.html` resolve relative to that subdirectory — use `../assets/img/...` not `assets/img/...`.

### Keep the delivered image size near the displayed size

A 250-DPI crop of a full-width journal figure is several thousand pixels wide against a content column of roughly 720 px, so pages can ship megabytes they cannot display. Cap the render zoom per crop rather than resampling afterward, which keeps text in the figure sharp:

```python
zoom = min(ZOOM, MAX_FIGURE_WIDTH / rect.width)   # MAX_FIGURE_WIDTH ~1400
pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=rect)
```

Add `loading="lazy"` to every figure below the first on a page. If you do, fix any broken-image check that treats `!img.complete` as broken — for a lazy image that simply has not loaded yet, that is a false positive. Scroll the page to trigger the loads, await each image, then count only `naturalWidth === 0`.

**Inspecting figures without blowing up context:** high-DPI crops are multi-megabyte PNGs, and reading several at once can exceed the provider's attachment limit and force a context compaction. Downscale to roughly 500 px and save as JPEG before reading, and crop to the region in question rather than loading whole pages. Note that element screenshots of a live page can capture the theme's sticky header over the image — inspect the PNG on disk when checking a crop.

## Explaining a statistical method

Naming a method is not explaining it. A page that presents an equation, defines its symbols, and reports the results can still leave a reader unable to say what the method *is*. Audit any method page against this list:

- **What the model assumes about the data.** If the outcome is counts, name the Poisson distribution and say the property that makes it apt — its variance equals its mean, so spread grows with the average. Do not leave a symbol like λ standing unexplained; state explicitly that it is a rate, that it can be fractional, and that observed counts vary around it. Rate-versus-realization is a real conceptual hurdle, and rounding λ to "≈ 1 spike" in a diagram quietly erases it.
- **Why not the simpler method.** "Why not ordinary linear regression?" earns its own section. Give every reason, not just the obvious one: counts cannot go negative, they are discrete and small, *and* their variability grows with their mean.
- **What the name means.** Unpack jargon literally. For a GLM, "generalized" means ordinary regression extended to outcomes that are not continuous and normal, and the generalization is exactly three choices: a distribution, a linear predictor, and a link function. Structure the page around those three.
- **How parameters are estimated.** This is the most commonly omitted piece. State the principle (maximum likelihood: pick parameters making the observed data most probable), then that there is no closed-form solution as in least squares, so fitting is iterative, and that iteration can fail to converge. If the paper excluded non-converging fits, that detail is now meaningful rather than trivia.
- **Never introduce a quantity by naming it.** "Fold the miss into a working response $z$" tells the reader nothing; it restates the formula in words. Any intermediate quantity an algorithm invents needs three things: what problem its existence solves, where its formula comes from, and why it moves the estimate. For IRLS the answer is that $\beta$ is linear in the log-rate $\eta$ but $\eta$ is never observed, so the algorithm manufactures an estimate of it: $z = \eta + (y-\mu)/\mu$ is the current log-rate plus the miss converted from counts into log-units by the derivative $d\mu/d\eta = \mu$. Regressing $z$ on the predictors is then ordinary weighted least squares, because $\eta$ *is* linear in $\beta$. Deriving the conversion factor from the derivative is what makes the formula stop looking arbitrary.
- **Show the approximation, and let it explain the loop.** Linearised updates are exact only in the limit, and that gap is usually the clearest reason an algorithm iterates. Plot the nonlinear curve, the tangent at the current guess, and where each one reaches the observed value: the invented target sits where the *tangent* arrives, the true per-observation answer where the *curve* does. Give the reader a slider on the current guess so they watch the gap collapse (0.90, 0.22, 0.02, then nothing). This doubles as a picture of quadratic convergence.
- **Say what a single-case diagram cannot show.** A per-observation picture invites the inference that each observation gets its own parameters. State plainly that one shared parameter set is fitted against all the targets at once and individual cases get outvoted.
- **Use degenerate cases as teaching moments.** A zero count has no exact target because $\log 0$ is undefined, and the update reduces to $\eta - 1$ regardless of the guess. Reachable edge cases like this are worth a control setting rather than a caveat.
- **How to interpret a coefficient's magnitude, not just its sign.** With a log link, $e^\beta$ is a multiplicative rate ratio: β = 0.3 means +35% per unit, β = −0.3 means −26%, β = 0.69 means doubling. A small table of β against $e^\beta$ conveys this faster than prose. Never write that "the sign is the whole story."
- **Every validation quantity, defined.** If a figure axis reads "percent improvement over shuffled," the page must say what error measure improved and what the shuffle scrambled. Read the supplemental methods for these; they are rarely in the main text.

**Get validation procedures from the methods section, not from convention.** It is easy to describe a familiar textbook procedure the authors did not use. One paper's "cross-validation" turned out to be 5000 repeated random 90/10 splits, not 10-fold — which also falsified the natural-sounding claim that "every event is predicted exactly once by a model that never saw it." Quote the methods text into your notes before writing the section.

**Distinguish what the analysis shows from what it suggests.** A regression on simultaneous activity is correlational. Watch for "drives," "causes," and "influences" leaking into prose, headings, and figure captions. Say "predicts" instead, and if the paper ran the model in the reverse direction, mention it — that alone shows the direction is a modeling choice. Put the genuine directional evidence (timing, anatomy, perturbation) in a callout that separates it from the model's own contribution.

### Budget the depth, and put the optional part behind a disclosure

Method pages grow by accretion. Each reader question gets answered with another section, and nothing ever gets removed, so the page silently becomes three times longer than its siblings with the algorithm's internals outweighing the paper's findings. Check the balance numerically rather than by feel: count prose words per section, and compare the page against the others in the site.

The fix is not to delete the depth but to demote it. With `pymdownx.details`, a `???` block keeps the main line short while leaving the full treatment one click away:

```markdown
??? note "How the search actually works, step by step"

    Indented content, including `<div>` diagrams, renders normally.
```

D3 diagrams work inside a collapsed `<details>` as long as nothing measures the DOM. Code that reads `clientWidth` or `getBoundingClientRect()` will get zeros; use an explicit `viewBox` and fixed coordinates instead. Note that a Playwright check cannot click a control inside a closed disclosure, so any verification script must open the `summary` first.

Decide what belongs on the main line by asking what the reader needs in order to understand *the paper*. For an optimization routine that is usually three sentences: what it optimizes, that it is iterative, and that it can fail if the paper excluded non-converging cases. Derivations, per-iteration anatomy, and convergence rates are genuine depth but they are optional depth.

### Prune duplicated explanation

Accretion also produces redundancy that is invisible while writing. Recurring forms worth grepping for:

- A **table and a bullet list** saying the same thing. Keep whichever carries the extra nuance and fold the rest into one sentence.
- An **overview section that pre-argues the case** the next section makes at length. Let the overview name the structure and stop.
- **Navigation instructions** ("try the button now, then read on"). Cut them; readers can see the button.
- A **schematic sitting next to the real figure it schematizes.** Once a page shows the paper's actual panel, or another page computes it for real, a fake-axis version of the same trend is strictly worse. Delete it and link instead.

Removing a diagram means removing its init function, its dispatcher line, and any reference in the verification script. Grep for the element IDs afterward.

Method pages still run longer than the ~800-word guideline for narrative pages. Keep them navigable with short subsections so the sidebar table of contents carries the structure, and make sure each heading names a real stage rather than wrapping unrelated children.

## Bridge raw data to the paper's figures

A method page can explain a technique correctly and still leave the reader unable to say how the paper's figure was produced. The common failure is **two disconnected islands**: a synthetic toy that begins from an already-assembled data matrix, and the published figure shown as a finished artifact. Nothing carries data across the middle.

### Name the endpoint before building any stage

The page needs one destination: a specific figure panel or result it reconstructs. `PAPER.md`'s **Pipeline target** field is where the user names it. Honour it literally, including which panels of a multi-panel figure are in scope. When it is blank, choose the paper's central multi-stage result yourself and tell the user which one before writing the page, because this choice determines every stage that follows.

The endpoint is the scoping tool for this page, which otherwise grows without limit. Once it is fixed, each candidate stage gets one question: does the endpoint depend on it? Preprocessing the target panel never touches, and analyses branching off elsewhere in the paper, get a sentence and a link rather than a diagram. A stage the endpoint needs but that is dull to depict still has to appear, at least as a stated array shape, otherwise the chain has a hole.

Audit the chain explicitly, stage by stage, and look for the joints nobody depicts:

- **Raw measurement → the numbers in the array.** This is the most-skipped stage and usually the most valuable. For spike data it is "align to each event, count within a window." Show a raster with a draggable analysis window, tally the spikes inside it, and have those integers visibly become one row of the matrix. Grey out what falls outside the window so the reader sees what the analysis discards.
- **Array shapes, stated.** Give the dimensions of every array and say what one row is. Also say the *scoping*: if the model is fit per session and per target neuron, say so, because a reader told the dataset has 536 and 312 neurons will otherwise assume one enormous fit. Scoping is what makes the paper's ensemble sizes intelligible.
- **The repetition that builds the figure.** A striking network diagram is often just one fit repeated per target neuron, with the coefficient vectors drawn as edges. If you show one fit and then the network, state that the network *is* the stacked fits — otherwise it looks like a separate analysis.
- **The sweep that builds the summary panel.** Bar charts of performance versus some parameter are a loop around the whole pipeline. Once the estimator runs in the browser, compute these rather than drawing them.
- **A closing diagram of the whole chain.** A short ASCII or SVG flow from raw data to the target panel gives the reader somewhere to orient.

Then place the reconstruction beside the real panel, and add an explicit **"where this simplification departs from the paper"** list: scale, number of resampling repeats, how significance is approximated, and the fact that ground truth exists only because you generated it.

**Be candid when the toy flatters the method.** If spikes are drawn from exactly the process the model assumes, the model has an advantage no real dataset offers, and reconstructed effect sizes will beat the paper's. Say so and give both ranges, rather than letting a reader conclude the real result was weak.

### Make each stage consume the previous stage's output

The pipeline must be real, not merely depicted. If the design matrix is regenerated from the generative parameters instead of being *counted from the spike times shown in the raster*, the page only looks like a pipeline. Order the simulation so that counting is the source of truth: place spikes, count them in windows to build X, then push those counts through the true weights to produce the response, and place the response's spikes back into the raster. Verify by asserting that the tally rendered next to each raster row equals the matrix cell it fills.

Watch for invariants that break when a control changes scale. Event windows must not overlap, so session duration has to grow with event count rather than staying fixed — otherwise raising an "events" slider silently makes windows overlap and double-count spikes. Assert the invariant across the full slider range.

Finally, check that recovery is actually reliable at the default settings before writing prose that claims it is. Measuring sign-recovery accuracy across sample sizes is a few lines in Node and will tell you whether "the fit recovers the pattern" is true, or true only at the top of the slider. If accuracy at the default is 90%, write "mostly" and make the imperfection a teaching point about needing more data.

## Interactive equations

Every equation should have an interactive breakdown where the reader can click/hover on individual components to see:
1. What that symbol represents in plain language
2. A visual connection to the diagram (highlight the corresponding neuron, edge, or data)
3. A concrete numeric example showing how that component contributes to the final result

Use a `.formula-interactive` div with `data-part` attributes on clickable spans. Color-code each component type consistently (outputs in purple, inputs in green, parameters in orange). Show the full computation with real numbers in a side panel so the reader sees the equation in action, not just in the abstract.

## Maze/track diagrams

When drawing behavioral apparatus (tracks, mazes), verify the shape against the actual paper figure. Common pitfalls:
- W-track: three parallel vertical arms connected by horizontal base segments (not a Y or inverted-T)
- Y-maze: single stem splitting into two arms at an angle
- Linear track: single corridor with reward wells at each end

Always label reward wells, home locations, and directional arrows showing the animal's path.

## Repo setup

pixi.toml tasks:
```toml
[tasks]
serve = "mkdocs serve"
build = "mkdocs build"
extract-figures = "python scripts/extract_figures.py"
```

.gitignore should include:
```
site/
__pycache__/
*.pyc
.DS_Store
.env
*.pdf
screenshots/
docs/assets/img/figures/pages/
.claude/
```

The `pages/` directory (full-page renders for figure verification) and `screenshots/` (Playwright verification) are development artifacts — don't commit them.

## Git workflow

- Make commits at logical boundaries: project setup, each page, each interactive diagram.
- Commit messages: short imperative, no fluff, no co-author attribution.
- Don't bundle unrelated changes.

### Confirm you are checking the right site

`check_site.py` compares the served page title against `site_name` in
`mkdocs.yml` and aborts if they disagree. This exists because a stale
`mkdocs serve` from another project answering on port 8000 makes every page of
the current project 404, which reads as a catastrophic site bug and is nothing
of the kind. Use `--port N` when running more than one project at once.

## Quality checks before done

- [ ] `pixi run mkdocs serve` renders without errors
- [ ] Every page has at least one figure or interactive diagram
- [ ] No narrative page exceeds ~800 words of prose (method pages may run longer if well-sectioned)
- [ ] Every method page names its distribution, its link, how parameters are estimated, and how coefficient magnitude is read
- [ ] Validation procedures match the supplemental methods, not textbook convention
- [ ] Correlational analyses are not described with causal verbs
- [ ] All interactive diagrams respond to controls (verify with Playwright clicks/screenshots)
- [ ] Zero broken images (check with Playwright across all pages)
- [ ] Zero console errors on every page, checked in a **fresh browser context** after exercising every control across its full range (accumulated-history console queries will keep reporting errors you already fixed, and `NaN` geometry from a scale computed off empty data is the usual culprit)
- [ ] The chain from raw measurement to each figure panel is depicted, with no stage handed numbers it should have derived
- [ ] Reconstructions sit beside the real panel, with a stated list of simplifications
- [ ] `extract-figures` self-checks pass, and fail when given deliberately bad boxes
- [ ] No figure is referenced but missing, and none is generated but unreferenced
- [ ] Every figure caption names exactly the panels visible in that crop
- [ ] No diagram displays a number that was invented rather than measured
- [ ] Init dispatcher, init definitions, and `.vis-container` IDs all match
- [ ] Writing passes no-ai-slop checks
- [ ] Synthetic examples precede real results for complex analyses
- [ ] Every equation has an interactive breakdown connecting symbols to visuals
- [ ] Maze/track diagrams match the actual paper figures
- [ ] A general undergrad can follow page 1 through the final page without external references

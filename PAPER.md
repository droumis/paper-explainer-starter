# Paper brief

**Edit this file, then tell the agent to follow AGENTS.md.** Everything here
steers what gets built. Leave a field blank to accept the default.

The agent must read this before writing anything, and must ask rather than guess
if a required field is empty.

---

## The paper

- **PDF**: (drop it in the project root; the tooling finds it automatically)
- **Citation**:
- **DOI**:
- **Open access?**: (affects whether figure crops can be published)

## Audience

- **Who is reading**: e.g. undergraduates with no background in the field
- **Assume they know**: e.g. nothing beyond high-school biology and algebra
- **Do not assume they know**: e.g. any statistics, any neuroanatomy

## The one thing

If a reader remembers a single sentence from this site, it should be:

>

## Emphasise

Sections, analyses, or figures that deserve the most depth. Be specific: name
figures and panels.

-

## Skip or keep brief

Anything the site should not spend words on. This is as important as the
emphasis list, because these projects fail by trying to cover everything.

-

## Terms to always define on first use

-

## Interactive diagrams

Ideas for what would genuinely help. Leave blank to let the agent propose a set
and check with you first.

-

## Figures

- **Must appear**:
- **Do not use**:
- **Split by panel**: figures whose panels belong on different pages

## Page plan

Leave blank for the default arc, which is: landing, background, methods,
results, synthesis. Override if the paper wants a different shape.

-

## Optional extras

- **Companion notebook**: `no`
  Set to `yes` for a Jupyter notebook that reproduces the site's own
  simulations end to end (generate synthetic data, build the design matrix,
  fit, redraw the reconstructed panels). It must reproduce *the site's*
  simulation, not claim to reproduce the paper's analysis, because the paper's
  raw data is not here.

- **Pipeline page**: `yes`
  A page carrying one simulated dataset from raw measurements through to
  reconstructions of the paper's figure panels. Worth it when the paper's
  central result comes from a multi-stage analysis.

## Constraints

- **Tone**:
- **Length ceiling per page**: 800 words of prose for narrative pages; method
  pages may run longer if the optional depth sits behind `???` disclosures
- **Anything to avoid**:

---

## Non-negotiables

These hold regardless of what is written above. They are not style preferences;
each one corresponds to a way these sites have actually gone wrong.

1. **Every number traces to the paper.** Including the supplemental methods.
   Watch for per-day versus per-session counts, which epoch a measure came
   from, and statistics attached to the wrong test.
2. **No invented numbers in diagrams.** Plot real values, or drop the numeric
   axis and label it a schematic in both the diagram and the prose.
3. **A "fit" button must actually fit.** Never display the parameters used to
   generate synthetic data as though they were estimated from it.
4. **Captions describe exactly the panels visible in the crop.** No more, no
   fewer.
5. **Correlational analyses get correlational language.** "Predicts", not
   "drives", unless the paper establishes direction by other means.
6. **State what the simplification leaves out** wherever the site reconstructs
   a result.

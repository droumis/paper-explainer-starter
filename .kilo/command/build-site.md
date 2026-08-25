---
description: Build the explainer site from the paper PDF, following AGENTS.md
---

Read `PAPER.md` and `AGENTS.md` in full, and load the `paper-explainer` skill
from `skills/paper-explainer/SKILL.md`.

Where `PAPER.md` is blank, do not hand the empty form back to me. Read the PDF
first, draft the fields the paper can settle, and ask me about the ones it
cannot: who is reading, the one sentence they should remember, what to skip, and
the pipeline endpoint if that page is on. Ask as concrete options with your
recommendation first, not as open questions. Write my answers into `PAPER.md`
before building, so the file records what the site was built from.

Skip the questions entirely if `$ARGUMENTS` contains `auto`, or if **Decide for
me** in `PAPER.md` is `yes`. Then answer every blank field yourself from the
paper, write each answer into `PAPER.md` marked `(agent's choice)`, and build
without stopping. Choose a general-audience reading of the paper's own headline
claim, and keep the emphasis to the two or three figures that claim rests on.
List every field you chose in your final report so I can correct one and rerun.

Then work through the build order in `AGENTS.md`, starting with `pixi run probe`
to derive the figure geometry. Do not write prose before the figure crops verify
clean.

Report what you plan for the page structure before writing the pages. Finish with
the verification chain in `AGENTS.md`, then tell me what to run to view the site.

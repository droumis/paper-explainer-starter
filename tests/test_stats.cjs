#!/usr/bin/env node
/**
 * Tests for template/docs/assets/js/lib/stats.js.
 *
 * The library exists so a diagram can do REAL estimation rather than displaying
 * the parameters it generated its own data from. These tests are what make that
 * claim checkable.
 *
 * Run:  node tests/test_stats.cjs
 */

const fs = require("fs");
const path = require("path");

const LIB = path.join(__dirname, "..", "template", "docs", "assets", "js", "lib", "stats.js");
const code = fs.readFileSync(LIB, "utf8");
const M = new Function(
  code + "\n return {makeRNG, poissonSample, solveLinear, fitPoissonGLM," +
         " crossValidatedImprovement, pickSubset, logFactorial," +
         " fitLeastSquares, fitLDA," +
         " BETA_POS, BETA_NEG, BETA_ZERO};"
)();

let passed = 0, failed = 0;
function check(name, cond, detail = "") {
  if (cond) { passed++; console.log(`  ok   ${name}`); }
  else { failed++; console.log(`  FAIL ${name}${detail ? "  (" + detail + ")" : ""}`); }
}

// ---------------------------------------------------------------- no globals
console.log("packaging");
check("does not reference d3", !/\bd3\./.test(code));
check("exports the coefficient sign colours",
  M.BETA_POS && M.BETA_NEG && M.BETA_POS !== M.BETA_NEG);

// ---------------------------------------------------------------------- RNG
console.log("\nseeded RNG");
{
  const a = M.makeRNG(42), b = M.makeRNG(42), c = M.makeRNG(43);
  const seqA = [0, 0, 0, 0, 0].map(() => a());
  const seqB = [0, 0, 0, 0, 0].map(() => b());
  const seqC = [0, 0, 0, 0, 0].map(() => c());
  check("same seed gives the same sequence", seqA.join() === seqB.join());
  check("different seed gives a different sequence", seqA.join() !== seqC.join());
  check("stays in [0,1)", seqA.every(v => v >= 0 && v < 1));
  const r = M.makeRNG(7);
  let sum = 0;
  for (let i = 0; i < 200000; i++) sum += r();
  check("mean is near 0.5", Math.abs(sum / 200000 - 0.5) < 0.01,
    (sum / 200000).toFixed(4));
}

// ------------------------------------------------------------------- Poisson
console.log("\nPoisson sampling");
{
  const r = M.makeRNG(11);
  for (const lam of [0.3, 1, 5]) {
    const n = 60000;
    let s = 0, s2 = 0;
    for (let i = 0; i < n; i++) { const k = M.poissonSample(lam, r); s += k; s2 += k * k; }
    const mean = s / n, varr = s2 / n - mean * mean;
    check(`lambda=${lam}: mean matches`, Math.abs(mean - lam) < 0.05 * Math.max(1, lam),
      mean.toFixed(3));
    // The property that motivates using a Poisson GLM at all.
    check(`lambda=${lam}: variance equals the mean`,
      Math.abs(varr - lam) < 0.08 * Math.max(1, lam), varr.toFixed(3));
  }
  const r2 = M.makeRNG(5);
  let allInt = true;
  for (let i = 0; i < 1000; i++) {
    const k = M.poissonSample(2, r2);
    if (!Number.isInteger(k) || k < 0) allInt = false;
  }
  check("returns non-negative integers", allInt);
}

// -------------------------------------------------------------- linear solver
console.log("\nlinear solver");
{
  // 2x + y = 5 ; x + 3y = 10  ->  x = 1, y = 3
  const b = M.solveLinear([[2, 1], [1, 3]], [5, 10]);
  check("solves a 2x2 system", Math.abs(b[0] - 1) < 1e-9 && Math.abs(b[1] - 3) < 1e-9,
    JSON.stringify(b));
  check("returns null for a singular matrix",
    M.solveLinear([[1, 2], [2, 4]], [3, 6]) === null);
  // Requires pivoting: a zero in the first pivot position.
  const p = M.solveLinear([[0, 1], [1, 0]], [2, 3]);
  check("pivots when the leading entry is zero",
    p && Math.abs(p[0] - 3) < 1e-9 && Math.abs(p[1] - 2) < 1e-9, JSON.stringify(p));
}

// ------------------------------------------------------------------ log gamma
console.log("\nlogFactorial");
check("log 0! = 0", Math.abs(M.logFactorial(0)) < 1e-12);
check("log 5! = log 120", Math.abs(M.logFactorial(5) - Math.log(120)) < 1e-9);

// ----------------------------------------------------------------- GLM fitting
console.log("\nPoisson GLM by IRLS");
const TRUE = [-0.5, 0.4, -0.3, 0.05, 0.35];
function makeData(n, seed) {
  const r = M.makeRNG(seed), X = [], y = [];
  for (let i = 0; i < n; i++) {
    const row = [0, 0, 0, 0].map(() => Math.floor(r() * 4));
    let eta = TRUE[0];
    row.forEach((x, j) => { eta += TRUE[j + 1] * x; });
    X.push(row);
    y.push(M.poissonSample(Math.exp(eta), r));
  }
  return { X, y };
}
{
  const { X, y } = makeData(4000, 7);
  const f = M.fitPoissonGLM(X, y);
  check("converges", f.converged, `reason=${f.reason}`);
  const err = Math.max(...f.beta.map((v, j) => Math.abs(v - TRUE[j])));
  check("recovers the true coefficients", err < 0.05, `max error ${err.toFixed(4)}`);

  // Error must fall with sample size, roughly as 1/sqrt(n). This is a claim
  // about the EXPECTED error, so it has to be averaged over seeds: the max
  // error from a single draw is far too noisy to compare across n.
  const SEEDS = 20;
  const errs = [250, 1000, 4000].map(n => {
    let tot = 0;
    for (let s = 0; s < SEEDS; s++) {
      const d = makeData(n, 1000 + s * 37);
      const g = M.fitPoissonGLM(d.X, d.y);
      tot += Math.max(...g.beta.map((v, j) => Math.abs(v - TRUE[j])));
    }
    return tot / SEEDS;
  });
  check("mean error decreases with n",
    errs[1] < errs[0] && errs[2] < errs[1],
    errs.map(e => e.toFixed(4)).join(" -> "));
  // Quadrupling n should roughly halve the error. Allow a wide band; the point
  // is the scaling law, not a precise constant.
  const ratio = errs[0] / errs[2];
  check("error roughly quarters when n grows 16x (1/sqrt(n))",
    ratio > 2.5 && ratio < 6, `ratio ${ratio.toFixed(2)}`);

  const tiny = makeData(4, 3);
  const t = M.fitPoissonGLM(tiny.X, tiny.y);
  check("refuses an underdetermined fit", !t.converged, `reason=${t.reason}`);
  check("reports no data for an empty design",
    M.fitPoissonGLM([], []).reason === "nodata");
}

// ---------------------------------------------------------------------- trace
console.log("\nIRLS trace");
{
  const { X, y } = makeData(300, 21);
  const f = M.fitPoissonGLM(X, y, { trace: true });
  const last = f.trace[f.trace.length - 1];
  check("records one entry per pass", f.trace.length === f.iterations);
  check("per-observation arrays are full length",
    ["eta", "mu", "resid", "weight", "z"].every(k => last[k].length === 300));
  // The two identities the teaching diagrams depend on.
  check("weight equals mu (Poisson log link)",
    last.weight.every((w, i) => Math.abs(w - last.mu[i]) < 1e-12));
  check("z equals eta + (y - mu)/mu",
    last.z.every((z, i) => Math.abs(z - (last.eta[i] + last.resid[i] / last.mu[i])) < 1e-9));
  check("mu equals exp(eta)",
    last.mu.every((m, i) => Math.abs(m - Math.exp(last.eta[i])) < 1e-9));
  check("delta shrinks monotonically",
    f.trace.every((s, i) => i === 0 || s.delta <= f.trace[i - 1].delta + 1e-12));
  check("no trace unless asked", M.fitPoissonGLM(X, y).trace === null);

  // Deliberately NOT asserted: that logLik increases every pass. An undamped
  // Newton step can overshoot from a cold start, so it does dip sometimes. A
  // site that claims the score "rose" each pass is wrong a few percent of the
  // time. Assert only the endpoint improves on the start.
  check("log-likelihood improves overall",
    last.logLik > f.trace[0].logLik,
    `${f.trace[0].logLik.toFixed(2)} -> ${last.logLik.toFixed(2)}`);
}

// ------------------------------------------------------------ cross-validation
console.log("\ncross-validation against a shuffled baseline");
{
  const { X, y } = makeData(600, 31);
  const cv = M.crossValidatedImprovement(X, y, 40, M.makeRNG(5));
  check("reports a positive improvement on real structure",
    cv && cv.improvement > 0, cv ? cv.improvement.toFixed(1) + "%" : "null");
  check("real error is below shuffled error", cv && cv.real < cv.shuffled);

  // Predictors carrying no information must not beat the shuffle by much.
  const rj = M.makeRNG(77);
  const Xnoise = X.map(() => [0, 0, 0, 0].map(() => Math.floor(rj() * 4)));
  const cvn = M.crossValidatedImprovement(Xnoise, y, 40, M.makeRNG(5));
  check("uninformative predictors give little improvement",
    cvn === null || cvn.improvement < 8,
    cvn ? cvn.improvement.toFixed(1) + "%" : "null");
  check("returns null rather than a non-finite number",
    M.crossValidatedImprovement([[1]], [0], 5, M.makeRNG(1)) === null ||
    isFinite(M.crossValidatedImprovement([[1]], [0], 5, M.makeRNG(1)).improvement));
}

// -------------------------------------------------------------------- subsets
console.log("\npickSubset");
{
  const r = M.makeRNG(5);
  const counts = new Array(6).fill(0);
  for (let i = 0; i < 12000; i++) {
    const s = M.pickSubset(6, 3, r);
    if (s.length !== 3 || new Set(s).size !== 3) { counts[0] = -1; break; }
    s.forEach(j => counts[j]++);
  }
  check("returns k distinct indices", counts[0] > 0);
  const spread = (Math.max(...counts) - Math.min(...counts)) / 6000;
  check("selects uniformly", spread < 0.05, `spread ${(spread * 100).toFixed(1)}%`);
  check("k = n returns everything",
    M.pickSubset(4, 4, r).sort().join() === "0,1,2,3");
}

// ------------------------------------------------------- nonlinear least squares
console.log("\nfitLeastSquares");
{
  // A Gaussian tuning curve, the shape a speed or frequency tuning fit takes.
  const truth = [8, 20, 6, 1];          // peak, centre, width, baseline
  const gauss = (p, x) =>
    p[3] + p[0] * Math.exp(-0.5 * Math.pow((x - p[1]) / p[2], 2));
  const rng = M.makeRNG(7);
  const xs = [];
  for (let x = 2; x <= 40; x += 1) xs.push(x);
  const clean = xs.map(x => gauss(truth, x));
  const noisy = clean.map(v => v + (rng() - 0.5) * 0.4);

  const exact = M.fitLeastSquares(gauss, [3, 12, 12, 0], xs, clean);
  check("converges on noiseless data", exact.converged, exact.reason || "");
  const err = Math.max(...truth.map((t, j) => Math.abs(exact.params[j] - t) / Math.abs(t)));
  check("recovers the generating parameters", err < 0.02,
    `worst relative error ${(err * 100).toFixed(2)}%`);

  const fit = M.fitLeastSquares(gauss, [3, 12, 12, 0], xs, noisy);
  check("converges from a cold start on noisy data", fit.converged, fit.reason || "");
  check("centre is recovered within a tenth of the width",
    Math.abs(fit.params[1] - truth[1]) < truth[2] / 10,
    `got ${fit.params[1].toFixed(2)} for ${truth[1]}`);
  check("residual sum of squares falls below the starting value",
    fit.rss < M.fitLeastSquares(gauss, [3, 12, 12, 0], xs, noisy, { maxIter: 0 }).rss);

  // The guards that keep a Fit button from drawing nonsense.
  const under = M.fitLeastSquares(gauss, [3, 12, 12, 0], [1, 2], [1, 2]);
  check("refuses a fit with fewer points than parameters",
    !under.converged && under.reason === "underdetermined", under.reason);
  const empty = M.fitLeastSquares(gauss, [3, 12, 12, 0], [], []);
  check("refuses an empty dataset", !empty.converged && empty.reason === "nodata");
  const bad = M.fitLeastSquares(() => NaN, [1], xs, clean);
  check("reports a model that returns non-finite values",
    !bad.converged, bad.reason);

  // Bounds keep the search out of regions where the model is undefined.
  const bounded = M.fitLeastSquares(gauss, [3, 12, 12, 0], xs, noisy,
    { bounds: [null, null, [4, 8], null] });
  check("respects a bound on a parameter",
    bounded.params[2] >= 4 - 1e-9 && bounded.params[2] <= 8 + 1e-9,
    `width ${bounded.params[2].toFixed(2)}`);
}

// ----------------------------------------------------------------------- LDA
console.log("\nfitLDA");
{
  const rng = M.makeRNG(11);
  const gauss2 = (cx, cy) => [cx + (rng() - 0.5) * 2, cy + (rng() - 0.5) * 2];
  const A = [], B = [];
  for (let i = 0; i < 60; i++) { A.push(gauss2(0, 0)); B.push(gauss2(4, 4)); }
  const lda = M.fitLDA(A, B);
  check("separates two well-spaced clouds", lda && lda.accuracy > 0.95,
    lda ? lda.accuracy.toFixed(2) : "null");
  check("assigns class A to the positive side",
    lda.projectedA.filter(v => v > 0).length > lda.projectedA.length * 0.9);
  check("the boundary sits between the class means",
    lda.meanA.every((v, j) => Math.abs(v - 0) < 0.5) &&
    lda.meanB.every((v, j) => Math.abs(v - 4) < 0.5));

  // Identical clouds cannot be separated, and resubstitution accuracy must not
  // pretend otherwise.
  const C = [], D = [];
  for (let i = 0; i < 60; i++) { C.push(gauss2(0, 0)); D.push(gauss2(0, 0)); }
  const chance = M.fitLDA(C, D);
  check("scores near chance on inseparable clouds",
    chance === null || Math.abs(chance.accuracy - 0.5) < 0.15,
    chance ? chance.accuracy.toFixed(2) : "null");

  check("returns null for a class with one member",
    M.fitLDA([[0, 0]], B) === null);
  check("returns null when the points are collinear",
    M.fitLDA([[0, 0], [1, 1], [2, 2]], [[3, 3], [4, 4], [5, 5]]) === null);
}

console.log(`\n${passed}/${passed + failed} checks passed`);
process.exit(failed ? 1 : 0);

// ============================================================
// stats.js  -- generic statistics for in-browser model fitting
//
// Nothing here is specific to any paper. Load it before diagrams.js:
//
//   extra_javascript:
//     - assets/js/lib/stats.js
//     - assets/js/diagrams.js
//
// Exists so a diagram can do REAL estimation instead of displaying the
// parameters it generated its own data from. A "Fit" button that reveals the
// answer key teaches nothing, and is the single most common way these pages go
// wrong.
// ============================================================

// Sign colours for GLM coefficients, matching the legend of the paper's
// Figure 6D: magenta for significant positive, dark green for significant
// negative. Defined once because these previously disagreed between diagrams on
// the same page, where red meant "positive" in one and "negative" in another.
// Deliberately not the CA1 teal or PFC purple, which denote brain regions.
const BETA_POS = "#c0158f";
const BETA_NEG = "#1b6b4a";
const BETA_ZERO = "#c9c9c9";

// xorshift32. Seeded so a given control setting is reproducible, but reseedable
// so "new data" genuinely resamples.
function makeRNG(s) {
  let state = (s >>> 0) || 1;
  return function () {
    state ^= state << 13; state >>>= 0;
    state ^= state >>> 17;
    state ^= state << 5; state >>>= 0;
    return state / 4294967296;
  };
}

// Draw from Poisson(lambda) by inverting the CDF. Fine for the small lambdas
// here; the loop cap only guards against pathological input.
function poissonSample(lambda, rng) {
  const u = rng();
  let count = 0, p = Math.exp(-lambda), cdf = p;
  while (cdf < u && count < 200) {
    count++;
    p *= lambda / count;
    cdf += p;
  }
  return count;
}

// Solve A b = c by Gaussian elimination with partial pivoting. Returns null if
// the matrix is singular, which is how an unidentifiable model (too few SWRs
// for the number of predictors) shows up.
function solveLinear(A, c) {
  const n = c.length;
  const M = A.map((row, i) => [...row, c[i]]);
  for (let col = 0; col < n; col++) {
    let pivot = col;
    for (let r = col + 1; r < n; r++) {
      if (Math.abs(M[r][col]) > Math.abs(M[pivot][col])) pivot = r;
    }
    if (Math.abs(M[pivot][col]) < 1e-10) return null;
    [M[col], M[pivot]] = [M[pivot], M[col]];
    for (let r = col + 1; r < n; r++) {
      const f = M[r][col] / M[col][col];
      for (let k = col; k <= n; k++) M[r][k] -= f * M[col][k];
    }
  }
  const b = new Array(n).fill(0);
  for (let r = n - 1; r >= 0; r--) {
    let s = M[r][n];
    for (let k = r + 1; k < n; k++) s -= M[r][k] * b[k];
    b[r] = s / M[r][r];
  }
  return b;
}

/**
 * Fit a Poisson GLM with a log link by iteratively reweighted least squares,
 * which is how maximum likelihood is actually computed for a GLM.
 *
 * Each pass: predict mu = exp(X b), form the working response
 * z = eta + (y - mu)/mu and weights W = mu, then solve the weighted normal
 * equations (X' W X) b = X' W z. Repeat until b stops moving.
 *
 * Returns the coefficients plus whether it converged, so callers can refuse to
 * display coefficients from a fit that never settled.
 */
// log(n!) for the Poisson log-likelihood, memoized. Only ever called on small
// spike counts here.
const LOG_FACT = [0];
function logFactorial(n) {
  for (let i = LOG_FACT.length; i <= n; i++) LOG_FACT[i] = LOG_FACT[i - 1] + Math.log(i);
  return LOG_FACT[n];
}

function fitPoissonGLM(X, y, opts = {}) {
  const maxIter = opts.maxIter === undefined ? 50 : opts.maxIter;
  const tol = opts.tol === undefined ? 1e-8 : opts.tol;
  // Recording every pass costs memory proportional to iterations x observations,
  // so it is opt-in and only used by the small teaching diagrams.
  const trace = opts.trace ? [] : null;

  const n = X.length;
  if (!n) return { beta: [], converged: false, iterations: 0, reason: "nodata", trace };
  const p = X[0].length + 1;               // +1 for the intercept
  const design = X.map(row => [1, ...row]);
  let b = new Array(p).fill(0);

  for (let iter = 1; iter <= maxIter; iter++) {
    const A = Array.from({ length: p }, () => new Array(p).fill(0));
    const c = new Array(p).fill(0);
    const step = trace
      ? { iter, betaBefore: [...b], eta: [], mu: [], resid: [], weight: [], z: [], logLik: 0 }
      : null;

    for (let i = 0; i < n; i++) {
      const xi = design[i];
      let eta = 0;
      for (let j = 0; j < p; j++) eta += xi[j] * b[j];
      eta = Math.max(-30, Math.min(30, eta));   // keep exp() finite
      const mu = Math.exp(eta);
      const z = eta + (y[i] - mu) / mu;         // working response
      if (step) {
        step.eta.push(eta);
        step.mu.push(mu);
        step.resid.push(y[i] - mu);
        step.weight.push(mu);                   // Poisson log link: W = mu
        step.z.push(z);
        step.logLik += y[i] * Math.log(mu) - mu - logFactorial(y[i]);
      }
      for (let j = 0; j < p; j++) {
        c[j] += mu * xi[j] * z;
        for (let k = j; k < p; k++) A[j][k] += mu * xi[j] * xi[k];
      }
    }
    for (let j = 0; j < p; j++) {
      for (let k = 0; k < j; k++) A[j][k] = A[k][j];   // mirror
    }

    const next = solveLinear(A, c);
    if (!next || next.some(v => !isFinite(v))) {
      return { beta: b, converged: false, iterations: iter, reason: "singular", trace };
    }
    const delta = Math.max(...next.map((v, j) => Math.abs(v - b[j])));
    if (step) {
      step.betaAfter = [...next];
      step.delta = delta;
      trace.push(step);
    }
    b = next;
    if (delta < tol) {
      return { beta: b, converged: true, iterations: iter, reason: null, trace };
    }
  }
  return { beta: b, converged: false, iterations: maxIter, reason: "maxiter", trace };
}

/**
 * Predict held-out spike counts and score the model the way the paper did:
 * fit on a random 90%, predict the remaining 10%, and take the mean absolute
 * difference from the actual counts. The shuffled baseline re-scores the same
 * predictions against a scrambled assignment of which SWR each belongs to.
 *
 * Returns percent improvement of real error over shuffled error, averaged over
 * `repeats` random splits. The paper used 5000; callers here use fewer to stay
 * responsive in a browser and say so on the page.
 */
function crossValidatedImprovement(X, y, repeats, rng) {
  const n = X.length;
  const nTest = Math.max(1, Math.round(n * 0.1));
  let realTotal = 0, shuffledTotal = 0, usable = 0;

  for (let rep = 0; rep < repeats; rep++) {
    const order = [];
    for (let i = 0; i < n; i++) order.push(i);
    for (let i = n - 1; i > 0; i--) {                 // Fisher-Yates
      const j = Math.floor(rng() * (i + 1));
      [order[i], order[j]] = [order[j], order[i]];
    }
    const testIdx = order.slice(0, nTest);
    const trainIdx = order.slice(nTest);
    const fit = fitPoissonGLM(trainIdx.map(i => X[i]), trainIdx.map(i => y[i]));
    if (!fit.converged) continue;

    const predicted = testIdx.map(i => {
      let eta = fit.beta[0];
      for (let j = 0; j < X[i].length; j++) eta += fit.beta[j + 1] * X[i][j];
      return Math.exp(Math.max(-30, Math.min(30, eta)));
    });
    const actual = testIdx.map(i => y[i]);

    let realErr = 0;
    for (let i = 0; i < actual.length; i++) realErr += Math.abs(predicted[i] - actual[i]);
    realErr /= actual.length;

    // Shuffle which SWR each prediction belongs to
    const shuffled = [...predicted];
    for (let i = shuffled.length - 1; i > 0; i--) {
      const j = Math.floor(rng() * (i + 1));
      [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
    }
    let shufErr = 0;
    for (let i = 0; i < actual.length; i++) shufErr += Math.abs(shuffled[i] - actual[i]);
    shufErr /= actual.length;

    realTotal += realErr;
    shuffledTotal += shufErr;
    usable++;
  }

  if (!usable) return null;
  const real = realTotal / usable;
  const shuffled = shuffledTotal / usable;
  // A vanishing shuffled error would make the ratio explode; treat it as
  // unusable rather than emitting a huge or non-finite improvement.
  if (!(shuffled > 1e-9)) return null;
  const improvement = (shuffled - real) / shuffled * 100;
  if (!isFinite(improvement)) return null;
  return { improvement, real, shuffled, usable };
}


/**
 * Pick `k` distinct indices out of `n`, unbiased (Fisher-Yates prefix).
 * Used for subsampling predictors when sweeping ensemble size.
 */
function pickSubset(n, k, rng) {
  const idx = [];
  for (let i = 0; i < n; i++) idx.push(i);
  for (let i = 0; i < k; i++) {
    const j = i + Math.floor(rng() * (n - i));
    [idx[i], idx[j]] = [idx[j], idx[i]];
  }
  return idx.slice(0, k);
}

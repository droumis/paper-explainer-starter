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
 * Fit an arbitrary nonlinear model by least squares, using Gauss-Newton with
 * Levenberg-Marquardt damping and a numeric Jacobian.
 *
 * For papers whose model is not a GLM. A Gaussian tuning surface, a saturating
 * contrast response, a power law: any `predict(params, x) -> number`. The
 * Jacobian is taken by central differences, so callers supply no derivatives.
 *
 * Damping matters. Undamped Gauss-Newton diverges readily from a cold start on
 * a model with a curved parameter space, and a diagram whose Fit button
 * sometimes explodes is worse than no Fit button. Each pass tries a step; if
 * the residual sum of squares fails to fall, lambda rises and the step is
 * retried, which is what makes convergence dependable enough to put behind a
 * slider.
 *
 * `bounds` is an optional array of [lo, hi] per parameter, clamped after each
 * accepted step. Use it to keep a width positive rather than letting the search
 * wander into a region where the model returns NaN.
 *
 * Returns { params, rss, iterations, converged, reason }. Callers MUST check
 * `converged` and draw nothing when it is false: coefficients from a fit that
 * never settled are not estimates.
 */
function fitLeastSquares(predict, params0, xs, ys, opts = {}) {
  const maxIter = opts.maxIter === undefined ? 200 : opts.maxIter;
  const tol = opts.tol === undefined ? 1e-10 : opts.tol;
  const bounds = opts.bounds || null;
  const p = params0.length;
  const n = xs.length;

  if (!n || !p) {
    return { params: [...params0], rss: NaN, iterations: 0, converged: false, reason: "nodata" };
  }
  // More parameters than observations cannot be identified. Refusing here is
  // the same guard fitPoissonGLM applies, and it is reachable from a slider
  // that shrinks the sample.
  if (n < p) {
    return { params: [...params0], rss: NaN, iterations: 0, converged: false,
             reason: "underdetermined" };
  }

  const clamp = (v, j) => {
    if (!bounds || !bounds[j]) return v;
    return Math.min(bounds[j][1], Math.max(bounds[j][0], v));
  };

  const sumSq = (params) => {
    let s = 0;
    for (let i = 0; i < n; i++) {
      const r = ys[i] - predict(params, xs[i]);
      if (!isFinite(r)) return Infinity;
      s += r * r;
    }
    return s;
  };

  let params = params0.map(clamp);
  let rss = sumSq(params);
  if (!isFinite(rss)) {
    return { params, rss, iterations: 0, converged: false, reason: "badstart" };
  }
  let lambda = 1e-3;
  let iterations = 0;

  for (let iter = 1; iter <= maxIter; iter++) {
    iterations = iter;

    // Central-difference Jacobian. The step is scaled to each parameter so a
    // width of 0.5 and a peak of 40 both get a sensible perturbation.
    const J = [];
    const resid = [];
    const h = params.map(v => Math.max(1e-6, Math.abs(v) * 1e-5));
    for (let i = 0; i < n; i++) {
      const base = predict(params, xs[i]);
      if (!isFinite(base)) {
        return { params, rss, iterations, converged: false, reason: "nonfinite" };
      }
      resid.push(ys[i] - base);
      const row = new Array(p);
      for (let j = 0; j < p; j++) {
        const up = [...params], dn = [...params];
        up[j] += h[j]; dn[j] -= h[j];
        const d = (predict(up, xs[i]) - predict(dn, xs[i])) / (2 * h[j]);
        row[j] = isFinite(d) ? d : 0;
      }
      J.push(row);
    }

    // Normal equations J'J delta = J'r, with lambda on the diagonal.
    const JtJ = Array.from({ length: p }, () => new Array(p).fill(0));
    const Jtr = new Array(p).fill(0);
    for (let i = 0; i < n; i++) {
      for (let j = 0; j < p; j++) {
        Jtr[j] += J[i][j] * resid[i];
        for (let k = j; k < p; k++) JtJ[j][k] += J[i][j] * J[i][k];
      }
    }
    for (let j = 0; j < p; j++) {
      for (let k = 0; k < j; k++) JtJ[j][k] = JtJ[k][j];
    }

    let accepted = false;
    for (let attempt = 0; attempt < 30; attempt++) {
      const A = JtJ.map((row, j) => row.map((v, k) => (j === k ? v * (1 + lambda) : v)));
      const delta = solveLinear(A, Jtr);
      if (delta && delta.every(isFinite)) {
        const trial = params.map((v, j) => clamp(v + delta[j], j));
        const trialRss = sumSq(trial);
        if (trialRss < rss) {
          const moved = Math.max(...trial.map((v, j) => Math.abs(v - params[j])));
          const gained = rss - trialRss;
          params = trial;
          rss = trialRss;
          lambda = Math.max(1e-12, lambda / 3);
          accepted = true;
          if (moved < tol || gained < tol * Math.max(1, rss)) {
            return { params, rss, iterations, converged: true, reason: null };
          }
          break;
        }
      }
      lambda *= 5;
      if (lambda > 1e12) break;
    }
    if (!accepted) {
      // No downhill step exists at any damping: either a minimum to numeric
      // precision, or a singular Jacobian. Distinguish by residual gradient.
      const grad = Math.max(...Jtr.map(Math.abs));
      return { params, rss, iterations, converged: grad < 1e-6,
               reason: grad < 1e-6 ? null : "stalled" };
    }
  }
  return { params, rss, iterations, converged: false, reason: "maxiter" };
}


/**
 * Two-class linear discriminant analysis on d-dimensional points.
 *
 * Finds the direction w that best separates two clouds by maximising the
 * between-class distance relative to the within-class scatter, which for two
 * classes is w = S^-1 (mu_a - mu_b) with S the pooled covariance. The boundary
 * is placed where the two projected class means are equidistant.
 *
 * Returns { w, b, accuracy, ... } where a point x is assigned to class A when
 * w . x + b > 0, or null when the pooled covariance is singular, which happens
 * when a class has one member or the points are collinear.
 *
 * `accuracy` is resubstitution accuracy on the same points used to fit, which
 * is what a paper reporting "classification accuracy" for a descriptive
 * boundary usually means. It is optimistic; say so wherever it is displayed.
 */
function fitLDA(pointsA, pointsB) {
  const na = pointsA.length, nb = pointsB.length;
  if (na < 2 || nb < 2) return null;
  const d = pointsA[0].length;
  if (!d || pointsB[0].length !== d) return null;

  const mean = (pts) => {
    const m = new Array(d).fill(0);
    pts.forEach(p => { for (let j = 0; j < d; j++) m[j] += p[j] / pts.length; });
    return m;
  };
  const ma = mean(pointsA), mb = mean(pointsB);

  // Pooled within-class scatter, divided by the pooled degrees of freedom.
  const S = Array.from({ length: d }, () => new Array(d).fill(0));
  const accumulate = (pts, m) => {
    pts.forEach(p => {
      for (let j = 0; j < d; j++) {
        for (let k = 0; k < d; k++) S[j][k] += (p[j] - m[j]) * (p[k] - m[k]);
      }
    });
  };
  accumulate(pointsA, ma);
  accumulate(pointsB, mb);
  const df = na + nb - 2;
  for (let j = 0; j < d; j++) for (let k = 0; k < d; k++) S[j][k] /= df;

  const w = solveLinear(S, ma.map((v, j) => v - mb[j]));
  if (!w || !w.every(isFinite)) return null;
  const norm = Math.sqrt(w.reduce((s, v) => s + v * v, 0));
  if (!(norm > 1e-12)) return null;

  const project = (p) => p.reduce((s, v, j) => s + v * w[j], 0);
  const b = -(project(ma) + project(mb)) / 2;

  let correct = 0;
  pointsA.forEach(p => { if (project(p) + b > 0) correct++; });
  pointsB.forEach(p => { if (project(p) + b <= 0) correct++; });

  return {
    w, b,
    accuracy: correct / (na + nb),
    meanA: ma, meanB: mb,
    projectedA: pointsA.map(p => project(p) + b),
    projectedB: pointsB.map(p => project(p) + b),
  };
}


/**
 * Eigenvectors and eigenvalues of a real symmetric matrix, by the cyclic Jacobi
 * method, sorted by descending eigenvalue.
 *
 * For any analysis that diagonalises a correlation or covariance matrix:
 * principal components of population activity, a leading co-activity pattern, a
 * reactivation weight vector. A correlation matrix is symmetric, so this is the
 * right tool and it needs no library.
 *
 * Jacobi is chosen over a power iteration because it returns the whole
 * decomposition, which is what a diagram needs when it shows the second and
 * subsequent components, and because it is unconditionally stable on symmetric
 * input at the sizes a browser diagram uses.
 *
 * Returns { values, vectors, sweeps, converged } where `vectors[k]` is the
 * eigenvector for `values[k]`, each normalised to unit length with its
 * largest-magnitude entry made positive so a redrawn diagram does not flip sign
 * between frames. Returns null for non-square, empty or non-finite input.
 * Callers MUST check `converged` before displaying anything derived from it.
 */
function eigenSymmetric(matrix, opts = {}) {
  const maxSweeps = opts.maxSweeps === undefined ? 60 : opts.maxSweeps;
  const tol = opts.tol === undefined ? 1e-12 : opts.tol;
  const n = matrix.length;
  if (!n || matrix.some(row => !row || row.length !== n)) return null;
  if (matrix.some(row => row.some(v => !isFinite(v)))) return null;

  // Work on a copy, symmetrised, so a caller's matrix is never mutated and tiny
  // asymmetries from floating point accumulation cannot derail the rotations.
  const A = matrix.map((row, i) => row.map((v, j) => (v + matrix[j][i]) / 2));
  let V = [];
  for (let i = 0; i < n; i++) {
    V.push(new Array(n).fill(0));
    V[i][i] = 1;
  }

  const offDiagonal = () => {
    let s = 0;
    for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) s += A[i][j] * A[i][j];
    return s;
  };

  let sweeps = 0;
  let converged = n === 1;
  const scale = Math.max(1, offDiagonal());
  for (let sweep = 0; sweep < maxSweeps && !converged; sweep++) {
    sweeps = sweep + 1;
    for (let p = 0; p < n - 1; p++) {
      for (let q = p + 1; q < n; q++) {
        if (Math.abs(A[p][q]) < 1e-300) continue;
        // Rotation angle that zeroes A[p][q], in the numerically stable form
        // that avoids catastrophic cancellation when A[p][p] is close to A[q][q].
        const theta = (A[q][q] - A[p][p]) / (2 * A[p][q]);
        const t = Math.sign(theta || 1) / (Math.abs(theta) + Math.sqrt(theta * theta + 1));
        const c = 1 / Math.sqrt(t * t + 1);
        const s = t * c;
        for (let k = 0; k < n; k++) {
          const akp = A[k][p], akq = A[k][q];
          A[k][p] = c * akp - s * akq;
          A[k][q] = s * akp + c * akq;
        }
        for (let k = 0; k < n; k++) {
          const apk = A[p][k], aqk = A[q][k];
          A[p][k] = c * apk - s * aqk;
          A[q][k] = s * apk + c * aqk;
        }
        for (let k = 0; k < n; k++) {
          const vkp = V[k][p], vkq = V[k][q];
          V[k][p] = c * vkp - s * vkq;
          V[k][q] = s * vkp + c * vkq;
        }
      }
    }
    if (offDiagonal() <= tol * scale) converged = true;
  }

  const order = A.map((row, i) => i).sort((a, b) => A[b][b] - A[a][a]);
  const values = order.map(i => A[i][i]);
  const vectors = order.map(i => {
    const v = V.map(row => row[i]);
    const norm = Math.sqrt(v.reduce((s, x) => s + x * x, 0));
    if (!(norm > 0)) return v;
    let lead = 0;
    v.forEach((x, k) => { if (Math.abs(x) > Math.abs(v[lead])) lead = k; });
    const sign = v[lead] < 0 ? -1 : 1;
    return v.map(x => (sign * x) / norm);
  });
  if (!values.every(isFinite) || vectors.some(v => v.some(x => !isFinite(x)))) return null;
  return { values, vectors, sweeps, converged };
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

// ============================================================
// Interactive diagrams
//
// One init function per diagram, each gated on its container existing, so
// every page only runs what it needs. Add a line here for each new diagram.
//
// Generic statistics (RNG, Poisson sampling, GLM fitting, cross-validation)
// live in lib/stats.js and load first. Do not re-implement them here: a second
// copy will drift from the first.
// ============================================================

document.addEventListener("DOMContentLoaded", function () {
  // if (document.getElementById("vis-example")) initExample();
});

// ============================================================
// Conventions
// ============================================================
//
// COLOUR
//   Take colours from the paper's own figures wherever the paper has a
//   convention, and define each meaning ONCE as a constant. Two diagrams on
//   one page using the same colour for opposite meanings is a real bug that is
//   easy to ship: red meant "positive coefficient" in one diagram and
//   "negative" in another until the constants below were introduced.
//
//   Keep separate palettes for separate meanings. A colour that identifies a
//   brain region, cell population, or experimental group must not also encode
//   the sign of a number.
//
//   BETA_POS / BETA_NEG in lib/stats.js are an example: magenta and dark green,
//   matching a paper's coefficient legend.
//
// SCALES
//   A bar whose length encodes a value needs an axis, or a second bar to
//   compare against. Otherwise its length says nothing and it reads as a
//   progress bar. If a diagram shows one number, print the number.
//
// HONESTY
//   Never display a value the reader could mistake for a measurement unless it
//   is one. Either plot the paper's real numbers, or drop the numeric axis and
//   label the thing a schematic in both the diagram and the prose. A "Fit"
//   button must actually fit; see lib/stats.js.
//
// LAYOUT
//   Use an explicit viewBox and fixed coordinates. Never measure the DOM
//   (clientWidth, getBoundingClientRect) because diagrams may live inside a
//   collapsed <details>, where measurements return zero.
//
//   After writing a diagram, check that no label sits outside the viewBox and
//   that no two labels overlap at any control setting, including the settings
//   where values converge. Compare label positions with
//   getBoundingClientRect(), not getBBox(), since getBBox is relative to each
//   element's own transform group.
//
// ============================================================


// ------------------------------------------------------------
// Template: copy this for a new diagram.
// ------------------------------------------------------------
//
// function initExample() {
//   const svg = d3.select("#vis-example svg");
//   const w = 780, h = 300;
//   const m = { top: 24, right: 24, bottom: 40, left: 56 };
//   const pw = w - m.left - m.right;
//   const ph = h - m.top - m.bottom;
//
//   let param = 5;                       // state driven by the controls
//
//   function draw() {
//     svg.selectAll("*").remove();       // full redraw keeps state simple
//     const g = svg.append("g").attr("transform", `translate(${m.left},${m.top})`);
//
//     const x = d3.scaleLinear().domain([0, 10]).range([0, pw]);
//     const y = d3.scaleLinear().domain([0, 10]).range([ph, 0]);
//     g.append("g").attr("transform", `translate(0,${ph})`).call(d3.axisBottom(x));
//     g.append("g").call(d3.axisLeft(y));
//
//     // Always label both axes with units.
//     g.append("text").attr("x", pw / 2).attr("y", ph + 32)
//       .attr("text-anchor", "middle").attr("font-size", "10px")
//       .text("x axis label (units)");
//
//     // Write a live readout into the caption div rather than crowding the SVG.
//     d3.select("#example-info").text(`param = ${param}`);
//   }
//
//   draw();
//   d3.select("#example-param").on("input", function () {
//     param = +this.value;
//     d3.select("#example-param-val").text(param);
//     draw();
//   });
// }
//
// Matching markdown:
//
// <div class="vis-container" id="vis-example">
//   <svg viewBox="0 0 780 300"></svg>
//   <div class="vis-controls">
//     <label>param:</label>
//     <input type="range" id="example-param" min="1" max="10" value="5" step="1">
//     <span class="value" id="example-param-val">5</span>
//   </div>
//   <div class="vis-caption" id="example-info"></div>
// </div>

"use strict";
// Renamed from report.js
const path = require("path");

/**
 * Formats a title for display.
 */
function title(name) {
  return name.trim();
}

function render(input) {
  return eval(input);
}

module.exports = { render, title };

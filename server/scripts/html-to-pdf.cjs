#!/usr/bin/env node
/**
 * html-to-pdf.cjs
 * Convert a styled HTML file to PDF using Playwright Chromium.
 * Usage: node html-to-pdf.cjs --input <path.html> --output <path.pdf>
 *
 * Playwright is sourced from claude-office-skills node_modules (shared browser cache).
 * Called by nodePostProcess in pocketflow.ts for PDF work orders.
 */

"use strict";

const path = require("path");
const { chromium } = require(path.join(
  "/home/virgina/claude-office-skills/node_modules/playwright"
));

const args = process.argv.slice(2);
const getArg = (flag) => {
  const i = args.indexOf(flag);
  return i !== -1 ? args[i + 1] : null;
};

const inputPath = getArg("--input");
const outputPath = getArg("--output");

if (!inputPath || !outputPath) {
  console.error(JSON.stringify({ error: "Usage: --input <path.html> --output <path.pdf>" }));
  process.exit(1);
}

(async () => {
  const browser = await chromium.launch({ args: ["--no-sandbox", "--disable-setuid-sandbox"] });
  try {
    const page = await browser.newPage();

    // Set viewport to A4 width (794px ≈ 210mm at 96dpi)
    await page.setViewportSize({ width: 794, height: 1123 });

    const fileUrl = "file://" + path.resolve(inputPath);
    await page.goto(fileUrl, { waitUntil: "networkidle" });

    await page.pdf({
      path: outputPath,
      format: "A4",
      printBackground: true,
      margin: { top: 0, right: 0, bottom: 0, left: 0 },
    });

    const fs = require("fs");
    const stat = fs.statSync(outputPath);
    console.log(JSON.stringify({ success: true, outputPath, size: stat.size }));
  } finally {
    await browser.close();
  }
})().catch((err) => {
  console.error(JSON.stringify({ error: String(err) }));
  process.exit(1);
});

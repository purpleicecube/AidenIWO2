#!/usr/bin/env node
/**
 * html-to-pptx.js
 * Convert a multi-slide HTML document to .pptx using html2pptx.js (Playwright + pptxgenjs).
 *
 * The input HTML must contain <section class="slide"> elements — one per slide.
 * Each section is extracted, wrapped in a standalone 720pt×405pt HTML file,
 * and converted to a PowerPoint slide via html2pptx.js.
 *
 * Usage:
 *   node html-to-pptx.js --input <html-file> --output <pptx-file>
 *
 * Stdout: JSON { success, path, slideCount }
 */
'use strict';

const fs = require('fs');
const path = require('path');
const os = require('os');

// Parse CLI args
const argv = {};
const rawArgs = process.argv.slice(2);
for (let i = 0; i < rawArgs.length; i += 2) {
  if (rawArgs[i].startsWith('--')) {
    argv[rawArgs[i].slice(2)] = rawArgs[i + 1];
  }
}

const { input, output } = argv;
if (!input || !output) {
  process.stderr.write('Usage: node html-to-pptx.js --input <file> --output <file>\n');
  process.exit(1);
}

// Deps from claude-office-skills (absolute paths so Node finds them correctly)
const SKILLS_DIR = '/home/virgina/claude-office-skills';
const html2pptx = require(path.join(SKILLS_DIR, 'public/pptx/scripts/html2pptx.js'));
const pptxgen = require(path.join(SKILLS_DIR, 'node_modules/pptxgenjs'));

/**
 * Extract all <section class="slide"> blocks from the HTML string.
 * Returns an array of full <section>...</section> strings.
 */
function extractSlides(html) {
  const slides = [];
  let i = 0;
  while (i < html.length) {
    // Find next <section opening that contains class="slide" or class='slide'
    const sectionStart = html.indexOf('<section', i);
    if (sectionStart === -1) break;

    // Read the opening tag
    const tagEnd = html.indexOf('>', sectionStart);
    if (tagEnd === -1) break;
    const openTag = html.slice(sectionStart, tagEnd + 1);

    if (/class=["'][^"']*\bslide\b[^"']*["']/i.test(openTag)) {
      // Find the matching </section>
      const closeTag = html.indexOf('</section>', tagEnd);
      if (closeTag === -1) break;
      slides.push(html.slice(sectionStart, closeTag + '</section>'.length));
      i = closeTag + '</section>'.length;
    } else {
      i = tagEnd + 1;
    }
  }
  return slides;
}

/**
 * Extract the background colour from a section's inline style so the body
 * wrapper inherits it (prevents white flash artefacts in Playwright renders).
 */
function extractBgColor(sectionHtml) {
  const m = sectionHtml.match(/style=["'][^"']*background(?:-color)?\s*:\s*([^;}"']+)/i);
  return m ? m[1].trim() : '#ffffff';
}

/**
 * Wrap a single <section> block in a standalone HTML document sized to
 * 720pt × 405pt (16:9) that html2pptx.js can render correctly.
 */
function wrapSlide(sectionHtml, bgColor) {
  // Replace the outer <section> tag with a <div> so the body is the viewport
  const inner = sectionHtml
    .replace(/^<section[^>]*>/i, '')
    .replace(/<\/section>\s*$/i, '');

  return `<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  * { box-sizing: border-box; }
</style>
</head>
<body style="width:720pt;height:405pt;margin:0;padding:0;display:flex;overflow:hidden;background:${bgColor};">
<div style="width:720pt;height:405pt;position:relative;overflow:hidden;background:${bgColor};">
${inner}
</div>
</body>
</html>`;
}

async function main() {
  const html = fs.readFileSync(input, 'utf-8');
  const sections = extractSlides(html);

  if (sections.length === 0) {
    process.stderr.write('html-to-pptx: no <section class="slide"> elements found in input\n');
    process.exit(1);
  }

  const tmpDir = path.join(os.tmpdir(), `aiden-pptx-${Date.now()}`);
  fs.mkdirSync(tmpDir, { recursive: true });

  const pptx = new pptxgen();
  pptx.layout = 'LAYOUT_16x9';

  const tmpFiles = [];
  for (let i = 0; i < sections.length; i++) {
    const bgColor = extractBgColor(sections[i]);
    const slideHtml = wrapSlide(sections[i], bgColor);
    const tmpFile = path.join(tmpDir, `slide-${i}.html`);
    fs.writeFileSync(tmpFile, slideHtml, 'utf-8');
    tmpFiles.push(tmpFile);
    await html2pptx(tmpFile, pptx);
  }

  await pptx.writeFile({ fileName: output });

  // Cleanup
  for (const f of tmpFiles) {
    try { fs.unlinkSync(f); } catch {}
  }
  try { fs.rmdirSync(tmpDir); } catch {}

  const stats = fs.statSync(output);
  console.log(JSON.stringify({
    success: true,
    path: output,
    slideCount: sections.length,
    fileSize: stats.size,
  }));
}

main().catch(err => {
  process.stderr.write(`html-to-pptx error: ${err.stack || err.message}\n`);
  process.exit(1);
});

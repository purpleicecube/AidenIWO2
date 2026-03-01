import { storage } from "./storage";
import type { WorkOrder, ExecutionLog } from "@shared/schema";

const escapeHtml = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60);
}

function getDateFolder(): string {
  return new Date().toISOString().split("T")[0];
}

async function ensureSubFolder(parentFolderId: string, parentPath: string, name: string, description?: string) {
  const existing = await storage.getArtifactFolders(parentFolderId);
  const found = existing.find(f => f.name === name);
  if (found) return found;

  return storage.createArtifactFolder({
    name,
    parentId: parentFolderId,
    path: `${parentPath}/${name}`,
    description: description || null,
  });
}

async function getRootFolder(name: string) {
  const rootFolders = await storage.getArtifactFolders(null);
  return rootFolders.find(f => f.name === name);
}

function containsCodeBlock(content: string): boolean {
  if (/```(html|css|js|javascript|typescript|tsx|jsx|python|ruby|go|rust|java|c|cpp|csharp|sql|bash|sh|yaml|json|xml|php|swift|kotlin)\b/i.test(content)) {
    return true;
  }
  const codeBlocks = content.match(/```[\s\S]*?```/g);
  if (codeBlocks && codeBlocks.some(block => {
    const inner = block.slice(3, -3).trim();
    return inner.includes('<') && inner.includes('>') || 
           inner.includes('function ') || inner.includes('const ') ||
           inner.includes('import ') || inner.includes('class ') ||
           inner.includes('def ') || inner.includes('fn ');
  })) {
    return true;
  }
  return false;
}

function containsHtmlDocument(content: string): boolean {
  return /<!DOCTYPE\s+html|<html[\s>]/i.test(content);
}

export function extractHtmlFromDeliverable(content: string): string | null {
  const htmlBlockMatch = content.match(/```html?\s*\n([\s\S]*?)```/i);
  if (htmlBlockMatch) return htmlBlockMatch[1].trim();

  if (containsHtmlDocument(content)) {
    const startIdx = content.search(/<!DOCTYPE\s+html|<html[\s>]/i);
    if (startIdx >= 0) {
      const htmlContent = content.slice(startIdx);
      const endIdx = htmlContent.lastIndexOf("</html>");
      if (endIdx >= 0) return htmlContent.slice(0, endIdx + 7);
      return htmlContent;
    }
  }
  return null;
}

interface ExtractedCodeBlock {
  language: string;
  code: string;
}

export function extractCodeBlocksFromDeliverable(content: string): ExtractedCodeBlock[] {
  const blocks: ExtractedCodeBlock[] = [];
  const regex = /```(\w+)?\s*\n([\s\S]*?)```/g;
  let match;
  while ((match = regex.exec(content)) !== null) {
    const lang = (match[1] || "text").toLowerCase();
    if (lang === "html" || lang === "htm") continue;
    blocks.push({ language: lang, code: match[2].trim() });
  }
  return blocks;
}

function isPythonCode(codeBlocks: ExtractedCodeBlock[]): boolean {
  return codeBlocks.some(b => ["python", "py", "python3"].includes(b.language));
}

export function detectUnfencedCode(content: string): ExtractedCodeBlock[] {
  const pythonIndicators = [
    /^import\s+\w+/m,
    /^from\s+\w+\s+import/m,
    /^def\s+\w+\s*\(/m,
    /^class\s+\w+[\s:(]/m,
    /^print\s*\(/m,
    /^[a-z_]\w*\s*=\s*(?!.*\*\*).+/m,
  ];
  const pythonScore = pythonIndicators.filter(r => r.test(content)).length;

  const jsIndicators = [
    /^const\s+\w+/m,
    /^let\s+\w+/m,
    /^var\s+\w+/m,
    /^function\s+\w+/m,
    /^console\.log\s*\(/m,
    /document\.\w+/,
    /addEventListener\s*\(/,
  ];
  const jsScore = jsIndicators.filter(r => r.test(content)).length;

  if (pythonScore < 2 && jsScore < 2) return [];

  const isMarkdownHeader = (line: string) => /^#{1,6}\s+\S/.test(line.trim());
  const isMarkdownBullet = (line: string) => /^[-*]\s+\*?\*?[A-Z]/.test(line.trim());
  const isMarkdownNumbered = (line: string) => /^\d+\.\s+\*?\*?[A-Z]/.test(line.trim());
  const isProseText = (line: string) => {
    const t = line.trim();
    if (t.length < 10) return false;
    const words = t.split(/\s+/).length;
    return words >= 8 && !/[=(){}\[\];]/.test(t) && !/^(import|from|def|class|print|for|while|if|elif|else|try|except|with|return|const|let|var|function|console|document|window|async|await|export)[\s.(]/.test(t);
  };

  const lines = content.split("\n");
  const codeLines: string[] = [];
  let inCodeRegion = false;
  let consecutiveNonCode = 0;

  for (const line of lines) {
    const trimmed = line.trim();

    if (isMarkdownHeader(trimmed) || isMarkdownBullet(trimmed) || isMarkdownNumbered(trimmed) || isProseText(trimmed)) {
      if (inCodeRegion) consecutiveNonCode++;
      if (consecutiveNonCode >= 2) {
        inCodeRegion = false;
        consecutiveNonCode = 0;
      }
      continue;
    }

    const isPyComment = /^#[^#!\s]/.test(trimmed) || /^#\s+(?![A-Z][a-z]+\s+[A-Z])/.test(trimmed);
    const isCodeLine = /^(import |from |def |class |if |elif |else:|for |while |try:|except |with |return |print\(|@[a-z]|\w+\s*=\s*(?!.*\*\*)|\w+\.\w+\(|os\.|sys\.|open\(|const |let |var |function |console\.|document\.|window\.|async |await |export |module\.)/.test(trimmed) ||
      (isPyComment && inCodeRegion) ||
      (/^\s{2,}\S/.test(line) && inCodeRegion);

    if (isCodeLine) {
      codeLines.push(line);
      inCodeRegion = true;
      consecutiveNonCode = 0;
    } else if (trimmed === "") {
      if (inCodeRegion) codeLines.push(line);
    } else {
      if (inCodeRegion) consecutiveNonCode++;
      if (consecutiveNonCode >= 2) {
        inCodeRegion = false;
        consecutiveNonCode = 0;
      }
    }
  }

  const extractedCode = codeLines.join("\n").trim();
  if (extractedCode.length < 20) return [];

  const language = pythonScore >= jsScore ? "python" : "javascript";
  return [{ language, code: extractedCode }];
}

function buildPythonRunnerHtml(title: string, codeBlocks: ExtractedCodeBlock[]): string {
  const pyBlocks = codeBlocks.filter(b => ["python", "py", "python3"].includes(b.language));
  const combinedPy = pyBlocks.map(b => b.code).join("\n\n");

  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="Content-Security-Policy" content="default-src 'self' 'unsafe-inline' 'unsafe-eval' blob:; script-src 'self' 'unsafe-inline' 'unsafe-eval' blob: https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://unpkg.com https://cdn.pyodide.org https://pyodide-cdn2.iodide.io; img-src * data: blob:; font-src * data:; style-src * 'unsafe-inline'; connect-src * data: blob:; media-src * blob:; worker-src 'self' blob:;">
<title>${escapeHtml(title)}</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif; background: #0f172a; color: #e2e8f0; display: flex; flex-direction: column; height: 100vh; }
  .header { background: #1e293b; padding: 0.75rem 1rem; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid #334155; }
  .header h1 { font-size: 0.9rem; color: #f8fafc; }
  .badge { display: inline-block; background: #166534; color: #4ade80; font-size: 0.7rem; padding: 0.15rem 0.5rem; border-radius: 4px; }
  .status { font-size: 0.75rem; color: #94a3b8; }
  .content { display: flex; flex: 1; min-height: 0; }
  .code-panel { flex: 1; display: flex; flex-direction: column; border-right: 1px solid #334155; }
  .output-panel { flex: 1; display: flex; flex-direction: column; }
  .panel-header { background: #1e293b; padding: 0.5rem 1rem; font-size: 0.8rem; font-weight: 600; color: #94a3b8; border-bottom: 1px solid #334155; display: flex; align-items: center; gap: 0.5rem; }
  .panel-header .dot { width: 6px; height: 6px; border-radius: 50%; }
  .dot-blue { background: #3b82f6; }
  .dot-green { background: #4ade80; }
  pre { flex: 1; padding: 1rem; overflow: auto; font-family: 'JetBrains Mono', 'Fira Code', monospace; font-size: 0.85rem; line-height: 1.6; white-space: pre-wrap; }
  .code-display { background: #0c1222; color: #e2e8f0; }
  .output-display { background: #0a0f1a; color: #4ade80; }
  .output-display .err { color: #f87171; }
  .output-display .info { color: #60a5fa; }
  .run-btn { background: #166534; color: #4ade80; border: 1px solid #22c55e40; padding: 0.35rem 0.75rem; border-radius: 4px; font-size: 0.75rem; cursor: pointer; font-weight: 600; }
  .run-btn:hover { background: #15803d; }
  .run-btn:disabled { opacity: 0.5; cursor: not-allowed; }
  .loading-bar { height: 2px; background: #1e293b; overflow: hidden; }
  .loading-bar .fill { height: 100%; background: linear-gradient(90deg, #3b82f6, #8b5cf6, #3b82f6); width: 30%; animation: loading 1.5s ease-in-out infinite; }
  @keyframes loading { 0% { transform: translateX(-100%); } 100% { transform: translateX(400%); } }
</style>
</head>
<body>
<div class="header">
  <h1>${escapeHtml(title)}</h1>
  <div style="display:flex;align-items:center;gap:0.75rem;">
    <span class="badge">Python Sandbox</span>
    <span class="status" id="status">Loading Pyodide...</span>
    <button class="run-btn" id="runBtn" disabled onclick="runCode()">Run</button>
  </div>
</div>
<div class="loading-bar" id="loadingBar"><div class="fill"></div></div>
<div class="content">
  <div class="code-panel">
    <div class="panel-header"><span class="dot dot-blue"></span> Source Code</div>
    <pre class="code-display" id="codeDisplay"></pre>
  </div>
  <div class="output-panel">
    <div class="panel-header"><span class="dot dot-green"></span> Output</div>
    <pre class="output-display" id="outputDisplay">Waiting for execution...</pre>
  </div>
</div>
<script>
var pyCode = ${JSON.stringify(combinedPy)};
document.getElementById('codeDisplay').textContent = pyCode;
var pyodideReady = false;
var pyodide = null;

async function loadPyodideRuntime() {
  try {
    var script = document.createElement('script');
    script.src = 'https://cdn.jsdelivr.net/pyodide/v0.24.1/full/pyodide.js';
    document.head.appendChild(script);
    await new Promise(function(resolve, reject) {
      script.onload = resolve;
      script.onerror = function() { reject(new Error('Failed to load Pyodide CDN')); };
    });
    pyodide = await loadPyodide({
      indexURL: 'https://cdn.jsdelivr.net/pyodide/v0.24.1/full/',
      stdout: function(text) { appendOutput(text, ''); },
      stderr: function(text) { appendOutput(text, 'err'); }
    });
    pyodideReady = true;
    document.getElementById('status').textContent = 'Ready';
    document.getElementById('runBtn').disabled = false;
    document.getElementById('loadingBar').style.display = 'none';
    runCode();
  } catch (e) {
    document.getElementById('status').textContent = 'Load failed';
    document.getElementById('loadingBar').style.display = 'none';
    appendOutput('Failed to load Python runtime: ' + e.message, 'err');
    appendOutput('Showing source code only.', 'info');
  }
}

function appendOutput(text, cls) {
  var el = document.getElementById('outputDisplay');
  if (el.textContent === 'Waiting for execution...' || el.textContent === 'Running...') el.textContent = '';
  var span = document.createElement('span');
  if (cls) span.className = cls;
  span.textContent = text + '\\n';
  el.appendChild(span);
  el.scrollTop = el.scrollHeight;
}

async function runCode() {
  if (!pyodideReady) return;
  var el = document.getElementById('outputDisplay');
  el.textContent = 'Running...';
  document.getElementById('status').textContent = 'Running...';
  try {
    var result = await pyodide.runPythonAsync(pyCode);
    if (result !== undefined && result !== null) {
      appendOutput(String(result), '');
    }
    document.getElementById('status').textContent = 'Completed';
  } catch (e) {
    appendOutput(e.message, 'err');
    document.getElementById('status').textContent = 'Error';
  }
}

loadPyodideRuntime();
</script>
</body>
</html>`;
}

function isRunnableBrowserJs(codeBlocks: ExtractedCodeBlock[]): boolean {
  const jsBlocks = codeBlocks.filter(b =>
    ["javascript", "js"].includes(b.language)
  );
  if (jsBlocks.length === 0) return false;
  const combinedJs = jsBlocks.map(b => b.code).join("\n");
  const browserIndicators = [
    /document\.(getElementById|querySelector|createElement|body|head)/,
    /canvas|getContext\s*\(\s*['"]2d['"]\s*\)|requestAnimationFrame/i,
    /addEventListener\s*\(/,
    /window\./,
    /\.innerHTML|\.textContent|\.appendChild/,
    /new\s+(Audio|Image|XMLHttpRequest|WebSocket)\b/,
    /fetch\s*\(/,
    /setInterval|setTimeout/,
  ];
  const browserScore = browserIndicators.filter(r => r.test(combinedJs)).length;
  const nodeIndicators = [/require\s*\(/, /module\.exports/, /process\.env/, /fs\./, /__dirname/];
  const nodeScore = nodeIndicators.filter(r => r.test(combinedJs)).length;
  return browserScore >= 2 && nodeScore === 0;
}

function buildRunnableJsHtml(title: string, codeBlocks: ExtractedCodeBlock[]): string {
  const jsBlocks = codeBlocks.filter(b =>
    ["javascript", "js", "typescript", "ts", "jsx", "tsx"].includes(b.language)
  );
  const cssBlocks = codeBlocks.filter(b => b.language === "css");

  const combinedJs = jsBlocks.map(b => b.code).join("\n\n");
  const combinedCss = cssBlocks.map(b => b.code).join("\n\n");

  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="Content-Security-Policy" content="default-src 'self' 'unsafe-inline' 'unsafe-eval' blob:; script-src 'self' 'unsafe-inline' 'unsafe-eval' blob: https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://unpkg.com; img-src * data: blob:; font-src * data:; style-src * 'unsafe-inline'; connect-src * data: blob:; media-src * blob:; worker-src 'self' blob:;">
<title>${escapeHtml(title)}</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif; background: #0f172a; color: #e2e8f0; }
  #app-container { width: 100%; min-height: 100vh; display: flex; flex-direction: column; align-items: center; justify-content: center; }
  canvas { display: block; background: #000; border: 2px solid #334155; border-radius: 4px; }
  #console-output { position: fixed; bottom: 0; left: 0; right: 0; max-height: 150px; overflow-y: auto; background: #0c1222; border-top: 1px solid #334155; padding: 0.5rem 1rem; font-family: 'JetBrains Mono', monospace; font-size: 0.75rem; color: #4ade80; }
  #console-output .log-line { padding: 1px 0; }
  #console-output .log-error { color: #f87171; }
  ${combinedCss}
</style>
</head>
<body>
<div id="app-container"></div>
<div id="console-output"></div>
<script>
(function() {
  var consoleEl = document.getElementById('console-output');
  var origLog = console.log;
  var origError = console.error;
  var origWarn = console.warn;
  function appendLog(msg, cls) {
    var div = document.createElement('div');
    div.className = 'log-line' + (cls ? ' ' + cls : '');
    div.textContent = typeof msg === 'object' ? JSON.stringify(msg) : String(msg);
    consoleEl.appendChild(div);
    consoleEl.scrollTop = consoleEl.scrollHeight;
  }
  console.log = function() { var args = Array.from(arguments); origLog.apply(console, args); appendLog(args.join(' ')); };
  console.error = function() { var args = Array.from(arguments); origError.apply(console, args); appendLog(args.join(' '), 'log-error'); };
  console.warn = function() { var args = Array.from(arguments); origWarn.apply(console, args); appendLog(args.join(' '), 'log-error'); };
  window.onerror = function(msg) { appendLog('Error: ' + msg, 'log-error'); };
})();
</script>
<script>
try {
${combinedJs}
} catch(e) { console.error('Runtime error:', e.message); }
</script>
</body>
</html>`;
}

export function buildCodePreviewHtml(title: string, codeBlocks: ExtractedCodeBlock[], fullContent: string): string {
  if (isPythonCode(codeBlocks)) {
    return buildPythonRunnerHtml(title, codeBlocks);
  }
  if (isRunnableBrowserJs(codeBlocks)) {
    return buildRunnableJsHtml(title, codeBlocks);
  }

  const blocksHtml = codeBlocks.map((block, i) => {
    const langLabel = block.language.charAt(0).toUpperCase() + block.language.slice(1);
    return `<div class="code-section">
      <div class="code-header">${langLabel}${codeBlocks.length > 1 ? ` (Block ${i + 1})` : ""}</div>
      <pre><code>${escapeHtml(block.code)}</code></pre>
    </div>`;
  }).join("\n");

  const outputSections = fullContent.split(/#{2,3}\s/).filter(s => /execution|output|result|log/i.test(s));
  const outputHtml = outputSections.map(section => {
    const outputMatch = section.match(/```\s*\n([\s\S]*?)```/);
    if (outputMatch) {
      return `<div class="output-section">
        <div class="output-header">Output</div>
        <pre class="output"><code>${escapeHtml(outputMatch[1].trim())}</code></pre>
      </div>`;
    }
    return "";
  }).filter(Boolean).join("\n");

  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>${escapeHtml(title)}</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif; background: #0f172a; color: #e2e8f0; padding: 2rem; }
  h1 { font-size: 1.5rem; margin-bottom: 1.5rem; color: #f8fafc; border-bottom: 1px solid #334155; padding-bottom: 0.75rem; }
  .badge { display: inline-block; background: #1e40af; color: #93c5fd; font-size: 0.75rem; padding: 0.15rem 0.5rem; border-radius: 4px; margin-bottom: 1rem; }
  .code-section, .output-section { margin-bottom: 1.5rem; border: 1px solid #334155; border-radius: 8px; overflow: hidden; }
  .code-header, .output-header { background: #1e293b; padding: 0.5rem 1rem; font-size: 0.8rem; font-weight: 600; color: #94a3b8; border-bottom: 1px solid #334155; }
  .output-header { background: #1a2332; color: #4ade80; }
  pre { padding: 1rem; overflow-x: auto; font-size: 0.875rem; line-height: 1.6; }
  pre code { font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace; }
  pre.output { background: #0c1222; }
  pre.output code { color: #4ade80; }
  .footer { margin-top: 2rem; font-size: 0.75rem; color: #64748b; border-top: 1px solid #1e293b; padding-top: 1rem; }
</style>
</head>
<body>
  <h1>${escapeHtml(title)}</h1>
  <span class="badge">AIDEN_IWO Sandbox Preview</span>
  ${blocksHtml}
  ${outputHtml}
  <div class="footer">Auto-deployed by AIDEN_IWO Workspace Filing Engine</div>
</body>
</html>`;
}

export function buildMarkdownPreviewHtml(title: string, markdown: string): string {
  let html = escapeHtml(markdown);
  html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
  html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
  html = html.replace(/^# (.+)$/gm, '<h1 class="doc-title">$1</h1>');
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
  html = html.replace(/^- (.+)$/gm, '<li>$1</li>');
  html = html.replace(/(<li>.*<\/li>\n?)+/g, (match) => `<ul>${match}</ul>`);
  html = html.replace(/^\d+\.\s+(.+)$/gm, '<li>$1</li>');
  html = html.replace(/\n{2,}/g, '</p><p>');
  html = `<p>${html}</p>`;
  html = html.replace(/<p>\s*(<h[123]>)/g, '$1');
  html = html.replace(/(<\/h[123]>)\s*<\/p>/g, '$1');
  html = html.replace(/<p>\s*<ul>/g, '<ul>');
  html = html.replace(/<\/ul>\s*<\/p>/g, '</ul>');
  html = html.replace(/<p>\s*<\/p>/g, '');

  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>${escapeHtml(title)}</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif; background: #0f172a; color: #e2e8f0; padding: 2rem; max-width: 800px; margin: 0 auto; }
  .badge { display: inline-block; background: #1e40af; color: #93c5fd; font-size: 0.75rem; padding: 0.15rem 0.5rem; border-radius: 4px; margin-bottom: 1.5rem; }
  .doc-title { font-size: 1.5rem; margin-bottom: 0.5rem; color: #f8fafc; }
  h2 { font-size: 1.25rem; margin: 1.5rem 0 0.75rem; color: #93c5fd; border-bottom: 1px solid #334155; padding-bottom: 0.4rem; }
  h3 { font-size: 1.1rem; margin: 1.25rem 0 0.5rem; color: #a5b4fc; }
  p { margin-bottom: 0.75rem; line-height: 1.7; color: #cbd5e1; }
  strong { color: #f1f5f9; }
  ul, ol { margin: 0.5rem 0 1rem 1.5rem; }
  li { margin-bottom: 0.35rem; line-height: 1.6; color: #cbd5e1; }
  .footer { margin-top: 2rem; font-size: 0.75rem; color: #64748b; border-top: 1px solid #1e293b; padding-top: 1rem; }
</style>
</head>
<body>
  <span class="badge">AIDEN_IWO Document Preview</span>
  ${html}
  <div class="footer">Auto-deployed by AIDEN_IWO Workspace Filing Engine</div>
</body>
</html>`;
}

function resolveOutputFolder(deliverableType: string, deliverableContent: string | null): string {
  if (deliverableType === "code") return "#Code_Blocks";
  if (deliverableType === "image") return "#Images";

  if (deliverableContent && (deliverableType === "mixed" || deliverableType === "document")) {
    if (containsCodeBlock(deliverableContent) || containsHtmlDocument(deliverableContent)) {
      return "#Code_Blocks";
    }
  }

  return "#Documents";
}

function classifyWorkProductFolder(order: WorkOrder): string {
  const tier2 = (order.tier2Result as any) || {};
  const title = (order.title || "").toLowerCase();
  const description = (order.description || "").toLowerCase();
  const deliverableTitle = (tier2.output?.deliverableTitle || "").toLowerCase();
  const deliverableType = (tier2.output?.deliverableType || "").toLowerCase();
  const handler = (tier2.handler || "").toLowerCase();
  const orderType = (order.type || "").toLowerCase();

  const allText = `${title} ${description} ${deliverableTitle} ${deliverableType}`;

  const planningKeywords = [
    "plan", "planning", "roadmap", "strategy", "proposal", "design",
    "blueprint", "architecture", "specification", "scope", "requirements",
    "staging plan", "deployment plan", "migration plan", "rollout plan",
    "assessment", "evaluation", "review plan", "audit plan",
  ];
  if (planningKeywords.some(kw => allText.includes(kw))) {
    return "00_Planning";
  }

  const policyKeywords = [
    "policy", "sop", "directive", "procedure", "guideline", "compliance",
    "standard", "regulation", "protocol", "rule",
  ];
  if (policyKeywords.some(kw => allText.includes(kw))) {
    return "01_Directive-SOP";
  }

  const orchestrationKeywords = [
    "workflow", "orchestration", "pipeline", "automation", "integration",
    "configuration", "template", "schedule",
  ];
  if (orchestrationKeywords.some(kw => allText.includes(kw))) {
    return "03_Orchestration";
  }

  const resourceKeywords = [
    "template", "reference", "resource", "guide", "documentation",
    "tutorial", "manual", "handbook",
  ];
  if (resourceKeywords.some(kw => allText.includes(kw))) {
    return "04_Resources";
  }

  const testKeywords = [
    "test", "testing", "qa", "quality", "validation", "verification",
    "benchmark", "performance test",
  ];
  if (testKeywords.some(kw => allText.includes(kw))) {
    return "06_Tests";
  }

  return "05_Artifacts";
}

function getFileExtension(deliverableType: string): string {
  switch (deliverableType) {
    case "code": return ".md";
    case "image": return ".md";
    default: return ".md";
  }
}

export async function fileWorkOrderOutput(order: WorkOrder) {
  try {
    const executionFolder = await getRootFolder("02_Execution");
    const artifactsFolder = await getRootFolder("05_Artifacts");
    if (!executionFolder || !artifactsFolder) {
      console.warn("Workspace not initialized — skipping auto-filing. Run POST /api/workspace/seed first.");
      return;
    }

    const dateStr = getDateFolder();
    const orderSlug = slugify(order.title);
    const folderName = `${orderSlug}_${order.id.slice(0, 8)}`;

    const execDateFolder = await ensureSubFolder(
      executionFolder.id, executionFolder.path, dateStr,
      `Executions from ${dateStr}`
    );

    const execOrderFolder = await ensureSubFolder(
      execDateFolder.id, execDateFolder.path, folderName,
      `Work order: ${order.title}`
    );

    const logs = await storage.getExecutionLogs(order.id);

    const executionLogContent = buildExecutionLog(order, logs);
    await storage.createArtifact({
      name: "execution-log.md",
      folderId: execOrderFolder.id,
      type: "file",
      mimeType: "text/markdown",
      content: executionLogContent,
      size: executionLogContent.length,
      status: "active",
      createdBy: "aiden",
      tags: ["auto-filed", "execution-log", order.type],
      sourceType: "work_order",
      sourceId: order.id,
    });

    const tier2 = (order.tier2Result as any) || {};
    const deliverable = tier2.output?.deliverable || null;
    const deliverableType = tier2.output?.deliverableType || "document";
    const deliverableTitle = tier2.output?.deliverableTitle || order.title;
    let deliverableFilePath: string | null = null;

    if (deliverable) {
      const outputFolderName = resolveOutputFolder(deliverableType, deliverable);
      let outputFolder = await getRootFolder(outputFolderName);

      if (!outputFolder) {
        outputFolder = await storage.createArtifactFolder({
          name: outputFolderName,
          path: `/${outputFolderName}`,
          description: `Auto-created output folder for ${outputFolderName.replace("#", "")}`,
          parentId: null,
        });
      }

      if (outputFolder) {
        const outDateFolder = await ensureSubFolder(
          outputFolder.id, outputFolder.path, dateStr,
          `${outputFolderName.replace("#", "")} from ${dateStr}`
        );

        const outOrderFolder = await ensureSubFolder(
          outDateFolder.id, outDateFolder.path, folderName,
          `Work order: ${order.title}`
        );

        const fileSlug = slugify(deliverableTitle);
        const ext = getFileExtension(deliverableType);
        const fileName = `${fileSlug}${ext}`;

        await storage.createArtifact({
          name: fileName,
          folderId: outOrderFolder.id,
          type: "file",
          mimeType: "text/markdown",
          content: deliverable,
          size: deliverable.length,
          status: "active",
          createdBy: "aiden",
          tags: ["auto-filed", "deliverable", deliverableType, order.type],
          sourceType: "work_order",
          sourceId: order.id,
        });

        deliverableFilePath = `${outputFolderName}/${dateStr}/${folderName}/${fileName}`;
        console.log(`  Deliverable saved to ${deliverableFilePath}`);
      }

      let sandboxHtml: string | null = extractHtmlFromDeliverable(deliverable);
      let sandboxType = "html_preview";

      if (!sandboxHtml) {
        const codeBlocks = extractCodeBlocksFromDeliverable(deliverable);
        if (codeBlocks.length > 0) {
          sandboxHtml = buildCodePreviewHtml(deliverableTitle, codeBlocks, deliverable);
          sandboxType = "code_preview";
        }
      }

      if (!sandboxHtml) {
        const unfencedBlocks = detectUnfencedCode(deliverable);
        if (unfencedBlocks.length > 0) {
          sandboxHtml = buildCodePreviewHtml(deliverableTitle, unfencedBlocks, deliverable);
          sandboxType = "code_preview";
        }
      }

      if (!sandboxHtml && deliverable.length > 50) {
        sandboxHtml = buildMarkdownPreviewHtml(deliverableTitle, deliverable);
        sandboxType = "document_preview";
      }

      if (sandboxHtml) {
        try {
          const allSessions = await storage.getSandboxSessions();
          const existingSession = allSessions.find((s) => {
            const env = s.environment as any;
            return env?.sourceType === "work_order" && env?.sourceId === order.id;
          });

          const previewLog = {
            timestamp: new Date().toISOString(),
            command: "deploy-preview",
            input: { workOrderId: order.id, title: order.title },
            output: { message: `${sandboxType === "code_preview" ? "Code preview" : sandboxType === "document_preview" ? "Document preview" : "HTML preview"} deployed for "${order.title}"`, status: "success" },
          };

          if (existingSession) {
            const existingLogs = Array.isArray(existingSession.logs) ? existingSession.logs : [];
            await storage.updateSandboxSession(existingSession.id, {
              status: "completed",
              result: { html: sandboxHtml, renderable: true, title: deliverableTitle },
              logs: [...existingLogs, previewLog],
              environment: {
                sourceType: "work_order",
                sourceId: order.id,
                deliverableTitle,
                autoDeployed: true,
                previewType: sandboxType,
              },
              completedAt: new Date(),
            });
            console.log(`  Sandbox ${sandboxType} updated: session ${existingSession.id}`);
          } else {
            const sandboxSession = await storage.createSandboxSession({
              name: `Preview: ${order.title}`,
              description: `Auto-deployed from work order "${order.title}" — ${sandboxType === "code_preview" ? "code execution preview" : sandboxType === "document_preview" ? "document preview" : "renderable HTML preview"}.`,
              environment: {
                sourceType: "work_order",
                sourceId: order.id,
                deliverableTitle,
                autoDeployed: true,
                previewType: sandboxType,
              },
              createdBy: "aiden",
            });

            await storage.updateSandboxSession(sandboxSession.id, {
              status: "completed",
              result: { html: sandboxHtml, renderable: true, title: deliverableTitle },
              logs: [previewLog],
              completedAt: new Date(),
            });
            console.log(`  Sandbox ${sandboxType} deployed: session ${sandboxSession.id}`);
          }
        } catch (sandboxErr: any) {
          console.error("Sandbox auto-deploy failed:", sandboxErr.message);
        }
      }
    }

    const targetFolderName = classifyWorkProductFolder(order);
    let targetFolder = await getRootFolder(targetFolderName);

    if (!targetFolder) {
      targetFolder = artifactsFolder;
    }

    const targetDateFolder = await ensureSubFolder(
      targetFolder.id, targetFolder.path, dateStr,
      `${targetFolder.name.replace(/^\d+_/, "")} from ${dateStr}`
    );

    const targetOrderFolder = await ensureSubFolder(
      targetDateFolder.id, targetDateFolder.path, folderName,
      `Work order: ${order.title}`
    );

    const workProductContent = buildWorkProduct(order, logs, deliverableFilePath, targetFolderName);
    await storage.createArtifact({
      name: "work-product.md",
      folderId: targetOrderFolder.id,
      type: "file",
      mimeType: "text/markdown",
      content: workProductContent,
      size: workProductContent.length,
      status: "active",
      createdBy: "aiden",
      tags: ["auto-filed", "work-product", order.type],
      sourceType: "work_order",
      sourceId: order.id,
    });

    console.log(`Auto-filed work order "${order.title}" to Workspace (02_Execution + ${targetFolderName} + ${deliverableFilePath ? "deliverable" : "no deliverable"})`);
  } catch (err: any) {
    console.error("Auto-filing failed:", err.message);
  }
}

function buildExecutionLog(order: WorkOrder, logs: ExecutionLog[]): string {
  const tier1 = (order.tier1Result as any) || {};
  const tier2 = (order.tier2Result as any) || {};
  const gcc = (order.gccMemory as any) || {};

  return `# Execution Log: ${order.title}

## Work Order Summary
| Field | Value |
|-------|-------|
| **ID** | \`${order.id}\` |
| **Correlation ID** | \`${order.correlationId}\` |
| **Type** | ${order.type} |
| **Priority** | ${order.priority} |
| **Status** | ${order.status} |
| **Submitted By** | ${order.submittedBy || "system"} |
| **Created** | ${order.createdAt} |
| **Completed** | ${gcc.completedAt || "N/A"} |

## Description
${order.description}

## Tier 1 — Aiden Policy Decision
- **Approved**: ${tier1.approved ?? "N/A"}
- **Reason**: ${tier1.reason || "N/A"}
- **Mode**: ${tier1.mode || "N/A"}
- **Handler**: ${tier1.handler || "N/A"}

## Tier 2 — Sub-Agent Execution
- **Blocked**: ${tier2.blocked ?? "N/A"}
- **Execution ID**: ${tier2.executionId || "N/A"}
- **Handler**: ${tier2.handler || "N/A"}
- **Output**: ${tier2.output?.message || "N/A"}

## Execution Timeline
${logs.map((log, i) => `${i + 1}. **[Tier ${log.tier}] ${log.action}** — ${log.message} _(${log.createdAt})_`).join("\n") || "No execution logs recorded."}

## GCC Memory (Routing Context)
\`\`\`json
${JSON.stringify(gcc, null, 2)}
\`\`\`

---
_Auto-filed by Aiden on ${new Date().toISOString()}_
`;
}

function buildWorkProduct(order: WorkOrder, logs: ExecutionLog[], deliverableFilePath: string | null, filedToFolder: string = "05_Artifacts"): string {
  const tier2 = (order.tier2Result as any) || {};
  const gcc = (order.gccMemory as any) || {};
  const summary = tier2.output?.message || "Work order completed successfully.";
  const deliverableType = tier2.output?.deliverableType || "document";
  const deliverableTitle = tier2.output?.deliverableTitle || order.title;

  const deliverableReference = deliverableFilePath
    ? `**Deliverable**: [\`${deliverableTitle}\`](${deliverableFilePath})
**Location**: \`${deliverableFilePath}\`
**Type**: ${deliverableType}`
    : `_No standalone deliverable was generated. Enable LLM integration in Settings for AI-generated outputs._`;

  return `# Work Product: ${order.title}

## Summary
| Field | Value |
|-------|-------|
| **Work Order** | ${order.title} |
| **Type** | ${order.type} |
| **Priority** | ${order.priority} |
| **Final Status** | ${order.status} |
| **Completed** | ${gcc.completedAt || new Date().toISOString()} |

## Result
${summary}

## Deliverable Output
${deliverableReference}

## Execution Path
${(gcc.breadcrumbs as string[] || []).map((b: string) => `- ${b.replace(/_/g, " ")}`).join("\n") || "- Direct execution"}

## Key Decisions
- **Routing**: ${tier2.handler || "N/A"}
- **Execution Mode**: ${order.executionMode || "auto"}
${order.assignedSubAgentId ? `- **Assigned Sub-Agent**: ${order.assignedSubAgentId}` : ""}

## Filed To
\`${filedToFolder}\`

## References
- Execution Log: \`02_Execution/${new Date().toISOString().split("T")[0]}/${slugify(order.title)}_${order.id.slice(0, 8)}/execution-log.md\`
- Work Order ID: \`${order.id}\`
- Correlation ID: \`${order.correlationId}\`

---
_Auto-filed by Aiden on ${new Date().toISOString()}_
`;
}

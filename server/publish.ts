/**
 * publish.ts — GitHub Pages publish service for AIDEN IWO2 HTML deliverables.
 *
 * Pushes HTML artifacts to purpleicecube/deliverables via the GitHub REST API
 * (Contents endpoint), making them publicly accessible on GitHub Pages.
 *
 * Requires GITHUB_TOKEN env var with `repo` scope.
 */

import { log } from "./index";

const GITHUB_OWNER = "purpleicecube";
const GITHUB_REPO = "deliverables";
const GITHUB_BRANCH = "main";
const PAGES_BASE_URL = `https://${GITHUB_OWNER}.github.io/${GITHUB_REPO}`;

interface PublishResult {
  success: boolean;
  publicUrl?: string;
  error?: string;
}

function getGitHubToken(): string {
  const token = process.env.GITHUB_TOKEN;
  if (!token) throw new Error("GITHUB_TOKEN env var is required for publishing");
  return token;
}

async function githubApi(path: string, method = "GET", body?: any): Promise<any> {
  const token = getGitHubToken();
  const res = await fetch(`https://api.github.com${path}`, {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok && res.status !== 404) {
    const text = await res.text();
    throw new Error(`GitHub API ${method} ${path} → ${res.status}: ${text}`);
  }
  if (res.status === 404) return null;
  return res.json();
}

/**
 * Get the SHA of an existing file (needed for updates).
 */
async function getFileSha(filePath: string): Promise<string | null> {
  const data = await githubApi(
    `/repos/${GITHUB_OWNER}/${GITHUB_REPO}/contents/${filePath}?ref=${GITHUB_BRANCH}`
  );
  return data?.sha || null;
}

/**
 * Publish an HTML artifact to GitHub Pages.
 * Creates or updates the file at `p/{slug}.html` in the deliverables repo.
 */
export async function publishToGitHubPages(
  slug: string,
  htmlContent: string,
  commitMessage?: string,
): Promise<PublishResult> {
  try {
    getGitHubToken(); // fail fast if no token

    const filePath = `p/${slug}.html`;
    const content = Buffer.from(htmlContent, "utf-8").toString("base64");

    // Check if file already exists (need SHA for update)
    const existingSha = await getFileSha(filePath);

    const body: any = {
      message: commitMessage || `Publish: ${slug}`,
      content,
      branch: GITHUB_BRANCH,
    };

    if (existingSha) {
      body.sha = existingSha;
    }

    await githubApi(
      `/repos/${GITHUB_OWNER}/${GITHUB_REPO}/contents/${filePath}`,
      "PUT",
      body,
    );

    const publicUrl = `${PAGES_BASE_URL}/p/${slug}.html`;
    log(`Published artifact to ${publicUrl}`, "publish");

    return { success: true, publicUrl };
  } catch (err: any) {
    log(`Publish failed for slug "${slug}": ${err.message}`, "publish");
    return { success: false, error: err.message };
  }
}

/**
 * Unpublish — delete the HTML file from GitHub Pages.
 */
export async function unpublishFromGitHubPages(slug: string): Promise<PublishResult> {
  try {
    getGitHubToken();

    const filePath = `p/${slug}.html`;
    const existingSha = await getFileSha(filePath);

    if (!existingSha) {
      return { success: true }; // already gone
    }

    await githubApi(
      `/repos/${GITHUB_OWNER}/${GITHUB_REPO}/contents/${filePath}`,
      "DELETE",
      {
        message: `Unpublish: ${slug}`,
        sha: existingSha,
        branch: GITHUB_BRANCH,
      },
    );

    log(`Unpublished artifact: ${slug}`, "publish");
    return { success: true };
  } catch (err: any) {
    log(`Unpublish failed for slug "${slug}": ${err.message}`, "publish");
    return { success: false, error: err.message };
  }
}

/**
 * Validate a slug: lowercase, alphanumeric + hyphens, 3-128 chars.
 */
export function isValidSlug(slug: string): boolean {
  return /^[a-z0-9][a-z0-9-]{1,126}[a-z0-9]$/.test(slug);
}

/**
 * Generate a slug from an artifact name.
 */
export function slugify(name: string): string {
  return name
    .toLowerCase()
    .replace(/\.[^.]+$/, "")          // strip file extension
    .replace(/[^a-z0-9]+/g, "-")      // non-alphanum → hyphens
    .replace(/^-+|-+$/g, "")          // trim leading/trailing hyphens
    .slice(0, 128);
}

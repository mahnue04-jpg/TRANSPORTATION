import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const FUNNEL_PAGE_DIRS = ["start", "guides/research-memo-setup"];

export function readFunnelPublished(siteConfigSource) {
  const match = String(siteConfigSource).match(/firstCustomerFunnel:\s*(true|false)\b/);
  if (!match) throw new Error("firstCustomerFunnel flag missing");
  return match[1] === "true";
}

export function isFunnelPage(relativePath) {
  const rel = String(relativePath || "").split(path.sep).join("/").replace(/^\//, "");
  return FUNNEL_PAGE_DIRS.some((dir) => rel === dir || rel.startsWith(`${dir}/`));
}

export function buildProduction({ sourceDir, outDir, siteConfigSource }) {
  const published = readFunnelPublished(siteConfigSource);
  fs.rmSync(outDir, { recursive: true, force: true });
  fs.mkdirSync(outDir, { recursive: true });
  const skip = new Set([".git", "node_modules", ".production-build"]);

  function copyDir(from) {
    for (const entry of fs.readdirSync(from, { withFileTypes: true })) {
      if (skip.has(entry.name)) continue;
      const src = path.join(from, entry.name);
      const rel = path.relative(sourceDir, src);
      if (!published && isFunnelPage(rel)) continue;
      const dest = path.join(outDir, rel);
      if (entry.isDirectory()) {
        fs.mkdirSync(dest, { recursive: true });
        copyDir(src);
      } else if (entry.isFile()) {
        fs.mkdirSync(path.dirname(dest), { recursive: true });
        fs.copyFileSync(src, dest);
      }
    }
  }

  copyDir(sourceDir);
  return { published, outDir };
}

function main() {
  const sourceDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
  const outDir = path.resolve(process.argv[2] || path.join(sourceDir, ".production-build"));
  const siteConfigSource = fs.readFileSync(path.join(sourceDir, "assets/js/site-config.js"), "utf8");
  const result = buildProduction({ sourceDir, outDir, siteConfigSource });
  console.log(`PRODUCTION_BUILD=${result.outDir}`);
  console.log(`FUNNEL_PUBLISHED=${result.published}`);
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  main();
}

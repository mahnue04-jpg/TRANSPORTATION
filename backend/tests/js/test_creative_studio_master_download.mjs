// Browser-style, no-provider Creative Studio master download tests.
// Extract the existing production function rather than maintaining a fake copy.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const js = readFileSync(path.join(root, "static/nova-creative/creative.js"), "utf8");
const start = js.indexOf("  async function streamProtectedStudioMaster(");
const end = js.indexOf("  async function fetchProtectedStudioVideo(", start);
assert.ok(start >= 0 && end > start, "production master download helper present");
const helper = js.slice(start, end);

function fixture({ chunks, expected, mime = "video/mp4", throwOnRead = false }) {
  const file = { chunks: [], closed: false, aborted: false };
  const progress = [];
  let reads = 0;
  const body = new ReadableStream({
    pull(controller) {
      if (throwOnRead) {
        controller.error(new Error("simulated interrupted network"));
        return;
      }
      if (reads >= chunks.length) {
        controller.close();
        return;
      }
      controller.enqueue(new Uint8Array(chunks[reads++]));
    }
  });
  const response = {
    ok: true,
    body,
    headers: {
      get(name) {
        return {
          "content-type": mime,
          "content-length": String(expected),
        }[name.toLowerCase()] || null;
      }
    },
  };
  const deps = {
    activeProjectId: "project",
    window: {
      async showSaveFilePicker() {
        return {
          async createWritable() {
            return {
              async write(bytes) { file.chunks.push([...bytes]); },
              async close() { file.closed = true; },
              async abort() { file.aborted = true; }
            };
          }
        };
      }
    },
    session: () => ({ensureReady: async () => {}, authFetch: async () => response}),
    token: () => "session-stub",
    fetch: async () => response,
    assertDownloadUrlHasNoToken: (url) => {
      assert.ok(!url.includes("?token="));
    }
  };
  const factory = new Function(
    "deps",
    'let activeProjectId=deps.activeProjectId; const window=deps.window;' +
    'const session=deps.session, token=deps.token, fetch=deps.fetch;' +
    'const assertDownloadUrlHasNoToken=deps.assertDownloadUrlHasNoToken;' +
    'deps.changeProject=(p)=>{activeProjectId=p;};\n' +
    helper + '\nreturn streamProtectedStudioMaster;'
  );
  const run = factory(deps);
  return { file, progress, deps, run: (callback) => run("project", "asset", callback || (p => progress.push(p))) };
}

test("exact stream commits file only at 100% and reports progress", async () => {
  const f = fixture({chunks: [[1, 2], [3, 4, 5]], expected: 5});
  const result = await f.run();
  assert.equal(result.saved, true);
  assert.equal(result.bytes, 5);
  assert.equal(f.file.closed, true);
  assert.equal(f.file.aborted, false);
  assert.deepEqual(f.file.chunks.flat(), [1, 2, 3, 4, 5]);
  assert.equal(f.progress.at(-1).percent, 100);
  assert.ok(f.progress.slice(0, -1).every(p => p.percent < 100));
});

test("truncated stream aborts without committing", async () => {
  const f = fixture({chunks: [[1, 2]], expected: 4});
  await assert.rejects(f.run(), /incomplete/);
  assert.equal(f.file.closed, false);
  assert.equal(f.file.aborted, true);
  assert.ok(f.progress.every(p => p.percent < 100));
});

test("oversized response aborts before writing unverified bytes", async () => {
  const f = fixture({chunks: [[1, 2, 3, 4, 5]], expected: 3});
  await assert.rejects(f.run(), /verified download size/);
  assert.deepEqual(f.file.chunks, []);
  assert.equal(f.file.aborted, true);
});

test("network interruption aborts the disk write", async () => {
  const f = fixture({chunks: [], expected: 5, throwOnRead: true});
  await assert.rejects(f.run(), /interrupted network/);
  assert.equal(f.file.closed, false);
  assert.equal(f.file.aborted, true);
});

test("unexpected content-type rejects before creating output", async () => {
  const f = fixture({chunks: [[1]], expected: 1, mime: "text/html"});
  await assert.rejects(f.run(), /unavailable/);
  assert.deepEqual(f.file.chunks, []);
  assert.equal(f.file.closed, false);
});

test("missing trusted content length rejects before creating output", async () => {
  const f = fixture({chunks: [[1]], expected: 0});
  await assert.rejects(f.run(), /invalid verified file size/);
  assert.deepEqual(f.file.chunks, []);
  assert.equal(f.file.closed, false);
});


test("switching project mid-download aborts rather than saving old customer media", async () => {
  const f = fixture({chunks: [[1, 2], [3, 4]], expected: 4});
  await assert.rejects(
    f.run(p => {
      f.progress.push(p);
      f.deps.changeProject("other-project");
    }),
    /Project selection changed/
  );
  assert.equal(f.file.closed, false);
  assert.equal(f.file.aborted, true);
  assert.ok(f.progress.every(p => p.percent < 100));
});

test("progress callback failure before close aborts the partial file", async () => {
  const f = fixture({chunks: [[1, 2], [3, 4]], expected: 4});
  await assert.rejects(f.run(() => {throw new Error("UI rendering failed");}), /UI rendering failed/);
  assert.equal(f.file.closed, false);
  assert.equal(f.file.aborted, true);
});

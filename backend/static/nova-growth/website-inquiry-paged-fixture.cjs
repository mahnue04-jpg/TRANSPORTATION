'use strict';

// Development-only adapter for an injected KV-shaped fixture.
// No network client, credentials, or production namespace is included.
// All pages must be read successfully before any result can be displayed.
const MAX_PAGES = 20;
const MAX_KEYS = 1000;
function createFixturePagedSource(kv) {
  if (!kv || typeof kv.list !== 'function' || typeof kv.get !== 'function') {
    throw new TypeError('A synthetic KV-shaped fixture is required');
  }
  return Object.freeze({
    async list({ prefix } = {}) {
      if (prefix !== 'lead:') throw new TypeError('Only lead keys may be listed');
      let cursor;
      const visited = new Set();
      const seenCursors = new Set();
      const entries = [];
      for (let pageNumber = 0; pageNumber < MAX_PAGES; pageNumber++) {
        const result = await kv.list({ prefix, ...(cursor ? { cursor } : {}) });
        if (!result || !Array.isArray(result.keys) || typeof result.list_complete !== 'boolean') {
          throw new Error('Incomplete fixture listing');
        }
        for (const item of result.keys) {
          const key = item && item.name;
          if (typeof key !== 'string' || !key.startsWith('lead:')) continue;
          if (visited.has(key)) continue;
          visited.add(key);
          if (visited.size > MAX_KEYS) throw new Error('Fixture list limit exceeded');
          const value = await kv.get(key);
          if (value == null) throw new Error('Fixture key disappeared while reading');
          entries.push({ key, value });
        }
        if (result.list_complete) return { entries, complete: true };
        if (!result.cursor || typeof result.cursor !== 'string' ||
            seenCursors.has(result.cursor)) {
          throw new Error('Invalid fixture cursor');
        }
        seenCursors.add(result.cursor);
        cursor = result.cursor;
      }
      throw new Error('Fixture page limit exceeded');
    }
  });
}
module.exports = {createFixturePagedSource};

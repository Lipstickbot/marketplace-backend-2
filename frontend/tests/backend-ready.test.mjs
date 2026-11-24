import { test } from "node:test";
import assert from "node:assert/strict";

test("a cold API is checked with reads and concurrent actions share one readiness check", async () => {
  const { backendReady } = await import("../src/backend-ready.js?cold");
  const calls = [];
  const original = globalThis.setTimeout;
  globalThis.setTimeout = (callback, delay, ...args) => original(callback, delay === 2000 ? 0 : delay, ...args);
  globalThis.fetch = async (url,options) => {
    calls.push({url,options});
    if (calls.length === 1) return new Response("<html>waking up</html>", {status:503});
    return Response.json({status:"ok"});
  };
  try {
    await Promise.all([backendReady("https://api.example/api"),backendReady("https://api.example/api")]);
    assert.equal(calls.length,2);
    assert.ok(calls.every(c=>c.url.endsWith("/health") && !c.options.method));
    await backendReady("https://api.example/api");
    assert.equal(calls.length,2);
  } finally { globalThis.setTimeout = original; }
});

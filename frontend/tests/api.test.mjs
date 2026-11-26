import { test } from "node:test";
import assert from "node:assert/strict";
globalThis.sessionStorage = {
  getItem: () => null,
  setItem: () => {},
  removeItem: () => {},
};
const api = await import("../src/api.js");
const valid = () => ({
  session: {
    access_token: "test-access",
    refresh_token: "test-refresh",
    expires_at: Date.now() / 1000 + 3600,
  },
  profile: { role: "business" },
});
test("agent execution is not retried on 401, 429 or network failure", async () => {
  for (const status of [401, 429, 504]) {
    api.saveSession(valid());
    let count = 0;
    globalThis.fetch = async () => {
      count++;
      return Response.json(
        { error: { message: "test", code: "test_error" } },
        { status },
      );
    };
    await assert.rejects(
      api.request("/agents/hr/run", {
        method: "POST",
        body: { message: "test" },
      }),
    );
    assert.equal(count, 1);
  }
  let count = 0;
  globalThis.fetch = async () => {
    count++;
    throw new TypeError("network");
  };
  await assert.rejects(
    api.request("/agents/hr/run", {
      method: "POST",
      body: { message: "test" },
    }),
  );
  assert.equal(count, 1);
});
test("read retries once after refresh with the new access token", async () => {
  api.saveSession(valid());
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push([url, options.headers.Authorization]);
    if (calls.length === 1)
      return Response.json({ error: { message: "expired" } }, { status: 401 });
    if (url.endsWith("/auth/refresh"))
      return Response.json({
        ...valid(),
        session: { ...valid().session, access_token: "new-access" },
      });
    return Response.json({ items: [] });
  };
  await api.request("/runs");
  assert.equal(calls.length, 3);
  assert.equal(calls[2][1], "Bearer new-access");
});

test("key revocation can refresh the session and finish after one user action", async () => {
  api.saveSession(valid());
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push([url, options.method, options.headers.Authorization]);
    if (calls.length === 1)
      return Response.json({ error: { message: "expired" } }, { status: 401 });
    if (url.endsWith("/auth/refresh"))
      return Response.json({
        ...valid(),
        session: { ...valid().session, access_token: "new-access" },
      });
    return new Response(null, { status: 204 });
  };
  await api.request("/integrations/test-id", { method: "DELETE", retryUnauthorized: true });
  assert.deepEqual(calls.map(([, method]) => method), ["DELETE", "POST", "DELETE"]);
  assert.equal(calls[2][2], "Bearer new-access");
});

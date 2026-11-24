import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";

const storage = new Map();
globalThis.sessionStorage = { getItem: (k) => storage.get(k) ?? null, setItem: (k,v) => storage.set(k,v), removeItem: (k) => storage.delete(k) };
const google = await import("../src/google-auth.js");
const api = await import("../src/api.js");
let destinations, cleaned;
beforeEach(() => {
  storage.clear(); api.saveSession(null); destinations = []; cleaned = [];
  globalThis.location = { href: "https://keme.example/account/?agent=marketing", origin: "https://keme.example", search: "?agent=marketing", assign: (u) => destinations.push(u) };
  globalThis.history = { replaceState: (_a,_b,u) => cleaned.push(u) };
});

test("Google uses random PKCE S256 and keeps verifier out of authorize URL", async () => {
  let body;
  globalThis.fetch = async (url, options) => {
    assert.ok(url.endsWith("/auth/google/start")); body = JSON.parse(options.body);
    return Response.json({ url: "https://project.supabase.co/auth/v1/authorize?provider=google" });
  };
  await google.startGoogleLogin();
  const pending = JSON.parse(storage.get("keme-google-pkce"));
  assert.equal(createHash("sha256").update(pending.verifier).digest("base64url"), body.code_challenge);
  assert.equal(new URL(body.redirect_to).searchParams.get("oauth_state"), pending.state);
  assert.equal(pending.agent, "marketing");
  assert.equal(body.code_verifier, undefined);
  assert.equal(destinations.length, 1);
});

test("Google callback scrubs code before exchange and restores agent", async () => {
  const pending = { verifier: "v".repeat(43), state: "s".repeat(43), createdAt: Date.now(), agent: "marketing" };
  storage.set("keme-google-pkce",JSON.stringify(pending));
  location.href = `https://keme.example/account/?code=one-use&oauth_state=${pending.state}`;
  globalThis.fetch = async (_url,options) => {
    assert.deepEqual(cleaned,["/account/?agent=marketing"]);
    assert.equal(storage.has("keme-google-pkce"),false);
    assert.deepEqual(JSON.parse(options.body),{auth_code:"one-use",code_verifier:pending.verifier});
    return Response.json({ session:{ access_token:"access",refresh_token:"refresh",expires_at:Date.now()/1000+3600 },profile:{role:"business"} });
  };
  assert.equal(await google.finishGoogleLogin(),true);
  assert.equal(api.session().profile.role,"business");
});

test("Google rejects mismatched state, expired attempts, missing verifier and implicit tokens", async () => {
  for (const value of [null,{verifier:"v".repeat(43),state:"wrong",createdAt:Date.now()}, {verifier:"v".repeat(43),state:"ok",createdAt:Date.now()-700000}]) {
    storage.set("keme-google-pkce",JSON.stringify(value));location.href="https://keme.example/account/?code=one-use&oauth_state=ok";
    globalThis.fetch=async()=>assert.fail("must not exchange invalid callback");
    await assert.rejects(google.finishGoogleLogin());assert.equal(api.session(),null);
  }
  location.href="https://keme.example/account/#access_token=untrusted";
  await assert.rejects(google.finishGoogleLogin());
  assert.equal(cleaned.at(-1),"/account/");
});

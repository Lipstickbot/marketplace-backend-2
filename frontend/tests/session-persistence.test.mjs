import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";

const device = new Map(), tab = new Map();
const storage = (map) => ({ getItem: k => map.get(k) ?? null, setItem: (k,v) => map.set(k,v), removeItem: k => map.delete(k) });
globalThis.localStorage = storage(device);
globalThis.sessionStorage = storage(tab);
const api = await import("../src/api.js");
const valid = (access = "access", refresh = "refresh", expires = Date.now()/1000+3600) => ({
  session: {access_token:access, refresh_token:refresh, expires_at:expires}, profile: {role:"business",user_id:"user-one"},
});
beforeEach(()=>{device.clear();tab.clear();api.saveSession(null);});

test("session survives closing its tab and reopening the site", async () => {
  api.saveSession(valid());tab.clear();
  const reopened = await import("../src/session-store.js?reopened");
  assert.equal(reopened.readSession().session.access_token,"access");
  assert.equal(device.has("keme-session"),true);
  assert.equal(tab.has("keme-session"),false);
});

test("existing tab-only session is migrated without signing in again",async()=>{
  tab.set("keme-session",JSON.stringify(valid()));
  const migrated=await import("../src/session-store.js?migrate");
  assert.equal(migrated.readSession().profile.role,"business");
  assert.equal(device.has("keme-session"),true);assert.equal(tab.has("keme-session"),false);
});

test("logout removes the remembered account and another tab observes it",async()=>{
  api.saveSession(valid());
  const another=await import("../src/session-store.js?another");
  assert.ok(another.readSession());
  globalThis.fetch=async()=>new Response(null,{status:204});
  await api.logout();
  assert.equal(another.readSession(),null);assert.equal(device.has("keme-session"),false);
});

test("expired remembered session rotates once before parallel reads",async()=>{
  api.saveSession(valid("old","old-refresh",1));let rotations=0;let reads=0;
  globalThis.fetch=async(url,options)=>{
    if(url.endsWith("/auth/refresh")) {rotations++;assert.equal(JSON.parse(options.body).refresh_token,"old-refresh");return Response.json(valid("new","new-refresh"));}
    reads++;assert.equal(options.headers.Authorization,"Bearer new");return Response.json({items:[]});
  };
  await Promise.all([api.request("/runs"),api.request("/files")]);
  assert.equal(rotations,1);assert.equal(reads,2);
  assert.equal(JSON.parse(device.get("keme-session")).session.refresh_token,"new-refresh");
});

test("a temporary network error preserves the remembered login",async()=>{
  api.saveSession(valid("old","old-refresh",1));globalThis.fetch=async()=>{throw new TypeError("offline");};
  await assert.rejects(api.request("/runs"));
  assert.equal(api.session().session.refresh_token,"old-refresh");
});

test("revoked refresh token removes the session",async()=>{
  api.saveSession(valid("old","old-refresh",1));
  globalThis.fetch=async()=>Response.json({error:{code:"invalid_refresh_token",message:"expired"}},{status:401});
  await assert.rejects(api.request("/runs"));assert.equal(api.session(),null);
});

test("a refresh response cannot restore a session cleared during logout",async()=>{
  api.saveSession(valid("old","old-refresh",1));let resolve;
  globalThis.fetch=async()=>new Promise(r=>{resolve=r;});
  const inFlight=api.request("/runs");
  while(!resolve) await new Promise(r=>setImmediate(r));
  api.saveSession(null);resolve(Response.json(valid("rotated","rotated-refresh")));
  await assert.rejects(inFlight);assert.equal(api.session(),null);assert.equal(device.has("keme-session"),false);
});

test("auth outcomes return to the homepage with a one-use notice",async()=>{
  const nav=await import("../src/auth-navigation.js");let target;
  globalThis.location={replace:u=>{target=u;}};
  for(const reason of ["registered","signed_in","confirm_email"]) {
    nav.goHomeAfterAuth(reason);assert.equal(target,"/");assert.equal(nav.consumeAuthNotice(),reason);assert.equal(nav.consumeAuthNotice(),null);
  }
});

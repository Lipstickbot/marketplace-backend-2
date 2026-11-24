import { test } from "node:test";
import assert from "node:assert/strict";
import { integrationBase, agentLink, integrationExample } from "../src/integrations.js";

test("same-origin integration URLs point to the API and share links contain no credential", () => {
  globalThis.location = {origin:"https://example.com"};
  assert.equal(integrationBase(),"https://example.com/api/v1");
  const link = new URL(agentLink("support"));
  assert.equal(link.pathname,"/account/");
  assert.equal(link.searchParams.get("agent"),"support");
  assert.equal([...link.searchParams].length,1);
});

test("copyable curl example uses a placeholder and explicitly requests supported non-streaming text", () => {
  const code=integrationExample("support","https://api.example.com/api/v1");
  assert.ok(code.startsWith('curl "https://api.example.com/api/v1/chat/completions"'));
  assert.ok(code.includes("Bearer YOUR_KEME_API_KEY"));
  assert.ok(!code.includes("\n+"));
  const payload=JSON.parse(code.split("-d '")[1].slice(0,-1));
  assert.equal(payload.model,"keme/support");assert.equal(payload.stream,false);
  assert.equal(payload.messages[0].role,"user");
});

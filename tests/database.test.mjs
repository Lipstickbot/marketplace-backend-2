import assert from 'node:assert/strict';
import { readFile, readdir } from 'node:fs/promises';
import { after, before, test } from 'node:test';
import { PGlite } from '@electric-sql/pglite';

const db = new PGlite();
let demoCatalog;
const ids = {
  a: '00000000-0000-4000-8000-000000000001',
  b: '00000000-0000-4000-8000-000000000002',
  dev: '00000000-0000-4000-8000-000000000003',
  admin: '00000000-0000-4000-8000-000000000004',
  fakeAdmin: '00000000-0000-4000-8000-000000000005',
  dev2: '00000000-0000-4000-8000-000000000006',
  agent: '10000000-0000-4000-8000-000000000001',
  draft: '10000000-0000-4000-8000-000000000002',
  soon: '10000000-0000-4000-8000-000000000003',
  external: '10000000-0000-4000-8000-000000000004',
  run: '20000000-0000-4000-8000-000000000001',
  engineRun: '30000000-0000-4000-8000-000000000001',
  file: '40000000-0000-4000-8000-000000000001',
};
const path = `${ids.a}/${ids.a}/${ids.file}/resume.pdf`;

async function asRole(role, userId, work) {
  assert.ok(['anon', 'authenticated', 'service_role'].includes(role));
  await db.exec('begin');
  try {
    await db.exec(`set local role ${role}`);
    await db.query("select set_config('request.jwt.claim.sub', $1, true)", [userId ?? '']);
    await db.query("select set_config('request.jwt.claims', $1, true)", [JSON.stringify({sub: userId, session_id: userId})]);
    const result = await work();
    await db.exec('commit');
    return result;
  } catch (error) {
    await db.exec('rollback');
    throw error;
  }
}
const user = (id, work) => asRole('authenticated', id, work);
const service = (work) => asRole('service_role', null, work);
const query = (sql, params = []) => db.query(sql, params);
const count = async (table) => Number((await query(`select count(*) from ${table}`)).rows[0].count);
async function denied(work, code = '42501') {
  await assert.rejects(work, (error) => error.code === code);
}

before(async () => {
  await db.exec(await readFile(new URL('./fixtures/supabase.sql', import.meta.url), 'utf8'));
  const dir = new URL('../supabase/migrations/', import.meta.url);
  for (const file of (await readdir(dir)).filter((name) => name.endsWith('.sql')).sort()) {
    await db.exec(await readFile(new URL(file, dir), 'utf8'));
  }
  demoCatalog = (await query('select slug,status,engine_slug,input_schema from public.agents')).rows;
  // Keep access-control fixtures independent of the production demo seed.
  await query('delete from public.agents');
  for (const [id, role] of [
    [ids.b, 'business'], [ids.dev, 'developer'], [ids.admin, 'business'],
    [ids.fakeAdmin, 'admin'], [ids.dev2, 'developer'],
  ]) {
    await query('insert into auth.users(id, raw_user_meta_data) values ($1, $2)',
      [id, { role, display_name: role }]);
  }
  await service(() => query("update public.profiles set role = 'admin' where id = $1", [ids.admin]));
  await query('insert into auth.sessions(id,user_id) select id,id from auth.users');
  await service(() => db.exec(`
    insert into public.agents(id, slug, name, category, status, engine_slug, developer_id) values
      ('${ids.agent}', 'marketing', 'Marketing', 'marketing', 'published', 'marketing', null),
      ('${ids.draft}', 'private-draft', 'Draft', 'hr', 'draft', null, '${ids.dev}'),
      ('${ids.soon}', 'soon', 'Soon', 'support', 'coming_soon', null, null),
      ('${ids.external}', 'external', 'External', 'support', 'draft', null, '${ids.dev2}');
    insert into public.agent_runs(id, engine_run_id, company_id, user_id, agent_id, engine_slug,
      status, language, mode, input_tokens, output_tokens, estimated_cost)
    values ('${ids.run}', '${ids.engineRun}', '${ids.a}', '${ids.a}', '${ids.agent}',
      'marketing', 'success', 'ru', 'mock', 100, 25, 0);
    insert into public.agent_files(id, company_id, user_id, object_path, original_name,
      mime_type, size_bytes, purpose)
    values ('${ids.file}', '${ids.a}', '${ids.a}', '${path}', 'resume.pdf', 'application/pdf', 1000, 'resume');
    insert into storage.objects(bucket_id, name, owner_id) values ('agent-files', '${path}', '${ids.a}');
  `));
});
after(async () => { await db.close(); });

test('catalog seed contains three explicit mock demos and nine coming-soon cards', async () => {
  assert.equal(demoCatalog.length, 12);
  assert.equal(demoCatalog.filter((a) => a.status === 'coming_soon' && a.engine_slug === null).length, 9);
  assert.deepEqual(demoCatalog.filter((a) => a.status === 'published').map((a) => a.engine_slug).sort(), ['hr','marketing','support']);
  assert.ok(demoCatalog.filter((a) => a.status === 'published').every((a) => a.input_schema.properties.message));
});

test('all platform tables enable RLS and remove inherited TRUNCATE grants', async () => {
  const tables = ['profiles', 'agents', 'connect_requests', 'agent_submissions', 'agent_runs', 'agent_files', 'agent_integrations', 'agent_purchases'];
  const { rows } = await query(`select relname, relrowsecurity from pg_class
    where relnamespace = 'public'::regnamespace and relkind = 'r' order by relname`);
  assert.deepEqual(rows.map((r) => r.relname), [...tables].sort());
  assert.ok(rows.every((r) => r.relrowsecurity));
  for (const table of tables) {
    for (const role of ['anon', 'authenticated', 'service_role']) {
      const result = await query('select has_table_privilege($1, $2, $3) as allowed', [role, `public.${table}`, 'TRUNCATE']);
      assert.equal(result.rows[0].allowed, false);
    }
  }
});

test('application key hashes and task settings are server-only and tenant-bound', async () => {
  for (const role of ['anon','authenticated']) {
    for (const privilege of ['SELECT','INSERT','UPDATE','DELETE']) {
      const r = await query('select has_table_privilege($1,$2,$3) as allowed',[role,'public.agent_integrations',privilege]);
      assert.equal(r.rows[0].allowed,false);
    }
  }
  const created = await service(() => query(`insert into public.agent_integrations(user_id,company_id,agent_id,agent_slug,name,key_hash,key_prefix,expires_at)
    values ($1,$1,$2,'marketing','Test',$3,'keme_test1234',now()+interval '1 day') returning id`,[ids.a,ids.agent,'a'.repeat(64)]));
  await denied(user(ids.a,()=>query('select * from public.agent_integrations')));
  await denied(user(ids.b,()=>query('select * from public.agent_integrations')));
  await denied(service(()=>query(`update public.agent_integrations set company_id=$1 where id=$2`,[ids.b,created.rows[0].id])),'23514');
  await service(()=>query('delete from public.agent_integrations where id=$1',[created.rows[0].id]));
});

test('signup creates profiles, backfills existing accounts, and ignores a forged admin role', async () => {
  const a = await user(ids.a, () => query('select * from public.profiles'));
  assert.equal(a.rows.length, 1);
  assert.equal(a.rows[0].company_name, 'Company A');
  assert.equal((await user(ids.dev, () => query('select role from public.profiles'))).rows[0].role, 'developer');
  assert.equal((await user(ids.fakeAdmin, () => query('select role from public.profiles'))).rows[0].role, 'business');
  await query("update auth.users set raw_user_meta_data = '{\"role\":\"admin\"}' where id = $1", [ids.a]);
  assert.equal((await user(ids.a, () => query('select role from public.profiles'))).rows[0].role, 'business');
});

test('profile editing cannot change identity or privilege, and cannot touch another tenant', async () => {
  await user(ids.a, () => query("update public.profiles set display_name = 'Owner A' where id = $1", [ids.a]));
  await denied(() => user(ids.a, () => query("update public.profiles set role = 'admin' where id = $1", [ids.a])));
  await denied(() => user(ids.a, () => query('update public.profiles set id = $1 where id = $2', [ids.b, ids.a])));
  assert.equal((await user(ids.a, () => query("update public.profiles set company_name = 'Stolen' where id = $1 returning id", [ids.b]))).rows.length, 0);
  await denied(() => user(ids.a, () => query('delete from public.profiles where id = $1', [ids.a])));
  await denied(() => asRole('anon', null, () => query('select * from public.profiles')));
});

test('catalog is public for published/soon agents; drafts are visible to owner and moderator', async () => {
  assert.equal(await asRole('anon', null, () => count('public.agents')), 2);
  assert.equal(await user(ids.a, () => count('public.agents')), 2);
  assert.equal(await user(ids.dev, () => count('public.agents')), 3);
  assert.equal(await user(ids.admin, () => count('public.agents')), 4);
  await denied(() => user(ids.dev, () => query("update public.agents set status = 'published' where id = $1", [ids.draft])));
  await denied(() => user(ids.admin, () => query("update public.agents set status = 'published' where id = $1", [ids.draft])));
  await denied(() => service(() => query("update public.agents set status = 'published' where id = $1", [ids.external])), '23514');
});

test('business can request a published agent only for itself, with server-controlled approval', async () => {
  const { rows: [connection] } = await user(ids.a, () => query(
    'insert into public.connect_requests(company_id,requested_by,agent_id) values ($1,$1,$2) returning *',
    [ids.a, ids.agent],
  ));
  assert.equal(connection.status, 'approved');
  assert.equal(connection.auto_approved, true);
  assert.equal(connection.reviewed_by, null);
  assert.ok(connection.reviewed_at);
  assert.equal(await user(ids.a, () => count('public.connect_requests')), 1);
  assert.equal(await user(ids.b, () => count('public.connect_requests')), 0);
  assert.equal(await user(ids.admin, () => count('public.connect_requests')), 1);
  await denied(() => user(ids.b, () => query('insert into public.connect_requests(company_id,requested_by,agent_id) values ($1,$1,$2)', [ids.a, ids.agent])));
  await denied(() => user(ids.b, () => query('insert into public.connect_requests(company_id,requested_by,agent_id) values ($1,$1,$2)', [ids.b, ids.soon])));
  await denied(() => user(ids.b, () => query("insert into public.connect_requests(company_id,requested_by,agent_id,status) values ($1,$1,$2,'approved')", [ids.b, ids.agent])));
  await denied(() => user(ids.a, () => query("update public.connect_requests set status = 'approved' where company_id = $1", [ids.a])));
  await denied(() => user(ids.dev, () => query('insert into public.connect_requests(company_id,requested_by,agent_id) values ($1,$1,$2)', [ids.dev, ids.agent])), '23514');
  await denied(() => user(ids.a, () => query('insert into public.connect_requests(company_id,requested_by,agent_id) values ($1,$1,$2)', [ids.a, ids.agent])), '23505');
});

test('business and developer accounts submit only their own requests; moderation cannot be forged', async () => {
  const sql = `insert into public.agent_submissions(developer_id,name,description,category)
    values ($1,'Agent','Description','support')`;
  await user(ids.dev, () => query(sql, [ids.dev]));
  assert.equal(await user(ids.dev, () => count('public.agent_submissions')), 1);
  assert.equal(await user(ids.dev2, () => count('public.agent_submissions')), 0);
  assert.equal(await user(ids.admin, () => count('public.agent_submissions')), 1);
  await user(ids.a, () => query(sql, [ids.a]));
  assert.equal(await user(ids.a, () => count('public.agent_submissions')), 1);
  assert.equal(await user(ids.dev, () => count('public.agent_submissions')), 1);
  await denied(() => user(ids.a, () => query(sql, [ids.dev])));
  await denied(() => user(ids.admin, () => query(sql, [ids.admin])));
  await denied(() => user(ids.dev2, () => query(sql, [ids.dev])));
  await denied(() => user(ids.dev, () => query(`insert into public.agent_submissions
    (developer_id,name,description,category,status,published_agent_id)
    values ($1,'Agent','Description','support','approved',$2)`, [ids.dev, ids.agent])));
  await denied(() => user(ids.dev, () => query("update public.agent_submissions set status = 'approved'")));
});

test('run metadata is private even from platform admins and is writable only by Backend 2', async () => {
  assert.equal(await user(ids.a, () => count('public.agent_runs')), 1);
  assert.equal(await user(ids.b, () => count('public.agent_runs')), 0);
  assert.equal(await user(ids.admin, () => count('public.agent_runs')), 0);
  await denied(() => asRole('anon', null, () => count('public.agent_runs')));
  await denied(() => user(ids.a, () => query("update public.agent_runs set estimated_cost = 0 where id = $1", [ids.run])));
  await denied(() => user(ids.a, () => query('delete from public.agent_runs where id = $1', [ids.run])));
  await denied(() => user(ids.a, () => query(`insert into public.agent_runs
    (company_id,user_id,agent_id,engine_slug,status) values ($1,$1,$2,'marketing','running')`, [ids.a, ids.agent])));
  assert.equal((await user(ids.a, () => query('select total_tokens from public.agent_runs'))).rows[0].total_tokens, 125);
});

test('engine_run_id deduplicates; unknown/network failures may have null IDs', async () => {
  const sql = `insert into public.agent_runs(engine_run_id,company_id,user_id,agent_id,engine_slug,status)
    values ($1,$2,$2,$3,'marketing',$4)`;
  await denied(() => service(() => query(sql, [ids.engineRun, ids.a, ids.agent, 'success'])), '23505');
  const duplicate = await service(() => query(`${sql} on conflict (engine_run_id) do nothing returning id`,
    [ids.engineRun, ids.a, ids.agent, 'success']));
  assert.equal(duplicate.rows.length, 0);
  await service(() => query(sql, [null, ids.a, ids.agent, 'engine_unreachable']));
  await service(() => query(sql, [null, ids.a, ids.agent, 'engine_unreachable']));
  await denied(() => service(() => query(sql, [null, ids.a, ids.agent, 'success'])), '23514');
  await denied(() => service(() => query(sql, [null, ids.a, ids.agent, 'success_without_llm'])), '22P02');
});

test('database rejects mismatched tenants, wrong catalog engine slug and invalid token/cost/language data', async () => {
  const sql = `insert into public.agent_runs(company_id,user_id,agent_id,engine_slug,status)
    values ($1,$2,$3,$4,'running')`;
  await denied(() => service(() => query(sql, [ids.a, ids.b, ids.agent, 'marketing'])), '23514');
  await denied(() => service(() => query(sql, [ids.dev, ids.dev, ids.agent, 'marketing'])), '23514');
  await denied(() => service(() => query(sql, [ids.a, ids.a, ids.agent, 'hr'])), '23514');
  await denied(() => service(() => query(sql, [ids.a, ids.a, ids.external, 'support'])), '23514');
  for (const update of ["language = 'kz'", 'estimated_cost = -1', 'input_tokens = -1', 'http_status = 999']) {
    await denied(() => service(() => query(`update public.agent_runs set ${update} where id = $1`, [ids.run])), '23514');
  }
});

test('private file mappings are server-written and enforce path, limit and synchronization consistency', async () => {
  assert.equal(await user(ids.a, () => count('public.agent_files')), 1);
  assert.equal(await user(ids.b, () => count('public.agent_files')), 0);
  assert.equal(await user(ids.admin, () => count('public.agent_files')), 0);
  await denied(() => user(ids.a, () => query("update public.agent_files set engine_file_id = gen_random_uuid()")));
  for (const update of ['size_bytes = 10485761', "object_path = 'wrong/path'", 'engine_file_id = gen_random_uuid()', "mime_type = 'application/x-msdownload'"]) {
    await denied(() => service(() => query(`update public.agent_files set ${update} where id = $1`, [ids.file])), '23514');
  }
  await service(() => query('update public.agent_files set engine_file_id = gen_random_uuid(), engine_synced_at = now() where id = $1', [ids.file]));
});

test('Storage bucket is private, accepts PDF/DOCX/TXT only and caps files at 10 MiB', async () => {
  const { rows: [bucket] } = await query("select * from storage.buckets where id = 'agent-files'");
  assert.equal(bucket.public, false);
  assert.equal(Number(bucket.file_size_limit), 10485760);
  assert.deepEqual(bucket.allowed_mime_types, ['application/pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'text/plain']);
});

test('Storage isolates tenants and rejects malformed paths, overwrites, moves and direct deletion', async () => {
  assert.equal(await user(ids.a, () => count('storage.objects')), 1);
  assert.equal(await user(ids.b, () => count('storage.objects')), 0);
  assert.equal(await user(ids.admin, () => count('storage.objects')), 0);
  await user(ids.a, () => query('insert into storage.objects(bucket_id,name) values ($1,$2)', ['agent-files', path.replace('resume.pdf', 'brief.txt')]));
  const sql = 'insert into storage.objects(bucket_id,name) values ($1,$2)';
  await denied(() => user(ids.b, () => query(sql, ['agent-files', path])));
  await denied(() => user(ids.dev, () => query(sql, ['agent-files', `${ids.dev}/${ids.dev}/${ids.file}/resume.pdf`])));
  for (const bad of [
    `${ids.a}/${ids.b}/${ids.file}/resume.pdf`, `${ids.a}/${ids.a}/invalid/resume.pdf`,
    `${ids.a}/${ids.a}/${ids.file}/../resume.pdf`, `${ids.a}/${ids.a}/${ids.file}/`,
    `${ids.a}/${ids.a}/${ids.file}/..`, `${ids.a}/${ids.a}/${ids.file}/bad\\name.pdf`,
  ]) await denied(() => user(ids.a, () => query(sql, ['agent-files', bad])));
  assert.equal((await user(ids.a, () => query("delete from storage.objects where name = $1 returning id", [path]))).rows.length, 0);
  assert.equal((await user(ids.a, () => query("update storage.objects set name = name || 'changed' returning id"))).rows.length, 0);
});

test('restrictive guards resist existing broad Storage policies and preserve other buckets', async () => {
  await db.exec(`create policy legacy_allow_all on storage.objects for all to anon, authenticated
    using (true) with check (true);
    insert into storage.buckets(id,name) values ('unrelated', 'unrelated');
    insert into storage.objects(bucket_id,name) values ('unrelated', 'shared.txt');`);
  try {
    assert.equal(await user(ids.b, () => count('storage.objects')), 1);
    assert.equal((await asRole('anon', null, () => query("select * from storage.objects where bucket_id = 'agent-files'"))).rows.length, 0);
    assert.equal((await asRole('anon', null, () => query("select * from storage.objects where bucket_id = 'unrelated'"))).rows.length, 1);
    await denied(() => user(ids.b, () => query("insert into storage.objects(bucket_id,name) values ('agent-files',$1)", [path])));
    assert.equal((await user(ids.a, () => query("delete from storage.objects where bucket_id = 'agent-files' returning id"))).rows.length, 0);
    assert.equal((await user(ids.a, () => query("update storage.objects set name = 'changed' where bucket_id = 'agent-files' returning id"))).rows.length, 0);
    await denied(() => user(ids.a, () => query("update storage.objects set bucket_id = 'agent-files', name = $1 where bucket_id = 'unrelated'", [path.replace('resume.pdf','moved.pdf')])));
    await user(ids.b, () => query("insert into storage.objects(bucket_id,name) values ('unrelated','other.txt')"));
  } finally {
    await db.exec('drop policy legacy_allow_all on storage.objects');
  }
});

test('service role can remove engine-synchronized files; deleting a user cannot silently destroy run history', async () => {
  await service(() => query('delete from storage.objects where name = $1', [path]));
  assert.equal((await query('select id from storage.objects where name = $1', [path])).rows.length, 0);
  await assert.rejects(() => query('delete from auth.users where id = $1', [ids.a]), (e) => e.code === '23503');
});

test('session RPC validates only the caller session and rejects revoked, foreign, expired or malformed sessions', async () => {
  const fn = await query(`select n.nspname, p.prosecdef from pg_proc p
    join pg_namespace n on n.oid = p.pronamespace where p.proname = 'is_current_session_active'`);
  assert.equal(fn.rows.find((r) => r.nspname === 'public').prosecdef, false);
  assert.equal(fn.rows.find((r) => r.nspname === 'private').prosecdef, true);
  const sessionId = '50000000-0000-4000-8000-000000000001';
  await query('insert into auth.sessions(id,user_id) values ($1,$2)', [sessionId, ids.a]);
  async function active(userId, sid) {
    return user(userId, async () => {
      await query("select set_config('request.jwt.claims', $1, true)", [JSON.stringify({ sub: userId, session_id: sid })]);
      return (await query('select public.is_current_session_active() as active')).rows[0].active;
    });
  }
  assert.equal(await active(ids.a, sessionId), true);
  assert.equal(await active(ids.b, sessionId), false);
  assert.equal(await active(ids.a, 'invalid-session-id'), false);
  assert.equal(await active(ids.a, null), false);
  await query("update auth.sessions set not_after = now() - interval '1 second' where id = $1", [sessionId]);
  assert.equal(await active(ids.a, sessionId), false);
  await query('delete from auth.sessions where id = $1', [sessionId]);
  assert.equal(await active(ids.a, sessionId), false);
  await denied(() => asRole('anon', null, () => query('select public.is_current_session_active()')));
  await denied(() => service(() => query('select public.is_current_session_active()')));
  await denied(() => user(ids.a, () => query('select * from auth.sessions')));
});

test('moderation RPCs require a live database admin role and do not grant direct table writes', async () => {
  const sql = 'select public.create_catalog_agent($1) as agent';
  const payload = {slug: 'rpc-test', name: 'RPC Test', category: 'support'};
  for (const id of [ids.a, ids.dev, ids.fakeAdmin]) await denied(() => user(id, () => query(sql, [payload])));
  await denied(() => asRole('anon', null, () => query(sql, [payload])));
  await denied(() => service(() => query(sql, [payload])));
  await denied(() => user(ids.admin, async () => {
    await query("select set_config('request.jwt.claims', '{}', true)");
    return query(sql, [payload]);
  }), '28000');
  const {rows} = await query(`select n.nspname,p.proname,p.prosecdef from pg_proc p join pg_namespace n on n.oid=p.pronamespace
    where p.proname in ('create_catalog_agent','update_catalog_agent','review_connect_request','review_agent_submission')`);
  assert.equal(rows.length, 8);
  assert.ok(rows.every((r) => r.prosecdef === (r.nspname === 'private')));
  await denied(() => user(ids.admin, () => query("update public.agents set name='Bypassed'")));
});

test('catalog creation and patch validate fields, defaults, publisher role and existing engine run history', async () => {
  const create = (payload) => user(ids.admin, () => query('select public.create_catalog_agent($1) as agent', [payload]));
  const {rows:[{agent}]} = await create({slug:'admin-created',name:'Created',category:'hr',developer_id:ids.dev});
  assert.equal(agent.status,'draft');
  assert.deepEqual(agent.supported_languages,['ru','kk','en']);
  const changed = await user(ids.admin, () => query('select public.update_catalog_agent($1,$2) as agent',
    [agent.id,{name:'Updated',status:'coming_soon'}]));
  assert.equal(changed.rows[0].agent.developer_id,ids.dev);
  assert.equal(changed.rows[0].agent.name,'Updated');
  await denied(() => create({slug:'bad-owner',name:'Bad',category:'hr',developer_id:ids.admin}), '23514');
  await denied(() => create({slug:'extra-field',name:'Bad',category:'hr',id:ids.agent}), '22023');
  await denied(() => create({}), '22023');
  await denied(() => create({slug:'published-no-engine',name:'Bad',category:'hr',status:'published'}), '23514');
  await denied(() => user(ids.admin, () => query('select public.update_catalog_agent($1,$2)', [agent.id,{name:null}])), '23502');
  await denied(() => user(ids.admin, () => query('select public.update_catalog_agent($1,$2)', [ids.agent,{engine_slug:'changed'}])), '23514');
  await denied(() => user(ids.admin, () => query('select public.update_catalog_agent($1,$2)', [ids.file,{name:'Missing'}])), 'P0002');
});

test('connection review records the real moderator, only approves published agents and rejects repeated decisions', async () => {
  const {rows:[{agent}]} = await user(ids.admin, () => query('select public.create_catalog_agent($1) as agent',
    [{slug:'review-target',name:'Review Target',category:'support',status:'published',engine_slug:'review-target'}]));
  const {rows:[request]} = await user(ids.b, () => query(`insert into public.connect_requests(company_id,requested_by,agent_id)
    values ($1,$1,$2) returning *`, [ids.b,agent.id]));
  assert.equal(request.status, 'pending');
  assert.equal(request.auto_approved, false);
  await denied(() => user(ids.a, () => query("select public.review_connect_request($1,'approved',null)",[request.id])));
  const reviewed = await user(ids.admin, () => query("select public.review_connect_request($1,'approved','OK') as result",[request.id]));
  assert.equal(reviewed.rows[0].result.reviewed_by,ids.admin);
  assert.equal(reviewed.rows[0].result.status,'approved');
  assert.ok(reviewed.rows[0].result.reviewed_at);
  await denied(() => user(ids.admin, () => query("select public.review_connect_request($1,'rejected',null)",[request.id])), 'P0001');
  await denied(() => user(ids.admin, () => query("select public.review_connect_request($1,'pending',null)",[request.id])), '22023');
  await denied(() => user(ids.admin, () => query("select public.review_connect_request($1,'approved',null)",[ids.file])), 'P0002');
  const {rows:[pending]} = await user(ids.a, () => query(`insert into public.connect_requests(company_id,requested_by,agent_id)
    values ($1,$1,$2) returning *`,[ids.a,agent.id]));
  await user(ids.admin, () => query('select public.update_catalog_agent($1,$2)',[agent.id,{status:'archived'}]));
  await denied(() => user(ids.admin, () => query("select public.review_connect_request($1,'approved',null)",[pending.id])), '23514');
  assert.equal((await query('select status from public.connect_requests where id=$1',[pending.id])).rows[0].status,'pending');
  assert.equal((await user(ids.admin, () => query("select public.review_connect_request($1,'rejected',null) as result",[pending.id]))).rows[0].result.status,'rejected');
});

test('submission approval publishes one coming-soon card atomically and preserves pending state on slug collision', async () => {
  const submit = async (owner = ids.dev) => (await user(owner, () => query(`insert into public.agent_submissions(developer_id,name,description,category)
    values ($1,'Submitted Agent','Description','support') returning id`,[owner]))).rows[0].id;
  const id = await submit(ids.a);
  const review = (id,slug) => user(ids.admin, () => query("select public.review_agent_submission($1,'approved','OK',$2) as result",[id,slug]));
  await denied(() => user(ids.dev, () => query("select public.review_agent_submission($1,'approved',null,'bypass')",[id])));
  await denied(() => review(id,'marketing'), '23505');
  assert.equal((await query('select status,published_agent_id from public.agent_submissions where id=$1',[id])).rows[0].status,'pending');
  const result=(await review(id,'approved-external')).rows[0].result;
  const card=(await query('select * from public.agents where id=$1',[result.published_agent_id])).rows[0];
  assert.equal(card.status,'coming_soon');
  assert.equal(card.engine_slug,null);
  assert.equal(card.developer_id,ids.a);
  assert.equal((await query('select role from public.profiles where id=$1',[ids.a])).rows[0].role,'business');
  await user(ids.admin, () => query('select public.update_catalog_agent($1,$2)', [card.id, {developer_id: ids.a}]));
  assert.equal(result.reviewed_by,ids.admin);
  assert.equal((await asRole('anon',null,()=>query('select id from public.agents where id=$1',[card.id]))).rows.length,1);
  await denied(() => review(id,'duplicate-card'), 'P0001');
  assert.equal((await query("select count(*) from public.agents where slug='duplicate-card'")).rows[0].count,0);
  const rejectedId=await submit();
  await denied(() => user(ids.admin, () => query("select public.review_agent_submission($1,'rejected',null,'invalid-slug')",[rejectedId])), '22023');
  const rejected=await user(ids.admin, () => query("select public.review_agent_submission($1,'rejected','No executor',null) as result",[rejectedId]));
  assert.equal(rejected.rows[0].result.published_agent_id,null);
});

test('only the backend activates a verified agent and businesses connect instantly', async () => {
  const { rows: [{ id }] } = await user(ids.dev2, () => query(
    "insert into public.agent_submissions(developer_id,name,description,category) values ($1,'Sales','Sales agent','sales') returning id",
    [ids.dev2],
  ));
  const card = { slug: 'sales-assistant', engine_slug: 'sales-assistant', version: '1',
    supported_languages: ['ru'], capabilities: [], accepted_file_purposes: [], input_schema: {}, output_schema: {} };
  const activate = (actor, data = card) => query('select public.activate_agent_submission($1,$2,null,$3) as result', [id, actor, data]);
  await denied(() => user(ids.admin, () => activate(ids.admin)));
  await denied(() => service(() => activate(ids.a)));
  await denied(() => service(() => activate(ids.admin, { ...card, engine_slug: 'marketing' })), '23505');
  const { rows: [{ result }] } = await service(() => activate(ids.admin));
  assert.equal(result.status, 'approved');
  assert.equal(result.reviewed_by, ids.admin);
  const { rows: [published] } = await asRole('anon', null, () => query(
    'select status,engine_slug from public.agents where id=$1', [result.published_agent_id],
  ));
  assert.deepEqual(published, { status: 'published', engine_slug: 'sales-assistant' });
  const { rows: [connection] } = await user(ids.a, () => query(
    'insert into public.connect_requests(company_id,requested_by,agent_id) values ($1,$1,$2) returning status,auto_approved',
    [ids.a, result.published_agent_id],
  ));
  assert.deepEqual(connection, { status: 'approved', auto_approved: true });
  await denied(() => service(() => activate(ids.admin)), 'P0001');
});

test('priced cards require a server-confirmed purchase and repeated confirmation grants access once', async () => {
  const { rows: [agent] } = await service(() => query(
    "insert into public.agents(slug,name,category,status,engine_slug,auto_connect,price_minor) values ('paid-test','Paid','sales','published','paid-test',true,123400) returning id",
  ));
  const connect = () => query("insert into public.connect_requests(company_id,requested_by,agent_id) values ($1,$1,$2)", [ids.a, agent.id]);
  const reserve = async (amount) => (await query(
    "select public.reserve_agent_purchase($1,$2,$3) as result", [ids.a, agent.id, amount],
  )).rows[0].result;
  const confirm = async (order, token) => (await query(
    "select public.complete_agent_purchase($1,$2,'provider-reference') as result", [order, token],
  )).rows[0].result;
  await denied(() => user(ids.a, connect));
  await denied(() => user(ids.a, () => reserve(123400)));
  assert.equal((await service(() => reserve(1))).reason, 'price_changed');
  const first = await service(() => reserve(123400));
  const duplicate = await service(() => reserve(123400));
  assert.equal(first.reserved, true);
  assert.equal(duplicate.reserved, false);
  assert.equal(first.order.id, duplicate.order.id);
  await denied(() => user(ids.a, () => query('select * from public.agent_purchases')));
  await denied(() => user(ids.a, () => confirm(first.order.id, 'token')));
  await service(() => query("update public.agent_purchases set provider_token='token' where id=$1", [first.order.id]));
  assert.equal(await service(() => confirm(first.order.id, 'mismatch')), false);
  const read = () => query('select status,auto_approved from public.connect_requests where agent_id=$1', [agent.id]);
  assert.equal((await user(ids.a, read)).rows.length, 0);
  assert.equal(await service(() => confirm(first.order.id, 'token')), true);
  assert.equal(await service(() => confirm(first.order.id, 'token')), true);
  assert.deepEqual((await user(ids.a, read)).rows, [{ status: 'approved', auto_approved: true }]);
  assert.equal((await user(ids.b, read)).rows.length, 0);
  assert.equal((await service(() => reserve(123400))).reason, 'already_connected');
});

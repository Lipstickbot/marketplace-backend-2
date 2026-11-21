-- Database-only integration test for a real Supabase PostgreSQL instance.
-- All synthetic Auth/profile/catalog/request/run/file rows are rolled back.
-- Does not issue emails, invoke agents, or create Storage blobs.
begin;

select set_config('smoke.actor_a', gen_random_uuid()::text, true),
       set_config('smoke.actor_b', gen_random_uuid()::text, true),
       set_config('smoke.developer', gen_random_uuid()::text, true),
       set_config('smoke.agent', gen_random_uuid()::text, true),
       set_config('smoke.file', gen_random_uuid()::text, true);

insert into auth.users(id, email, raw_user_meta_data)
values
  (current_setting('smoke.actor_a')::uuid, 'smoke-a-' || current_setting('smoke.actor_a') || '@example.invalid', '{"role":"business"}'),
  (current_setting('smoke.actor_b')::uuid, 'smoke-b-' || current_setting('smoke.actor_b') || '@example.invalid', '{"role":"admin"}'),
  (current_setting('smoke.developer')::uuid, 'smoke-dev-' || current_setting('smoke.developer') || '@example.invalid', '{"role":"developer"}');

do $$ begin
  if (select count(*) from public.profiles where id in
    (current_setting('smoke.actor_a')::uuid, current_setting('smoke.actor_b')::uuid, current_setting('smoke.developer')::uuid)) <> 3
  then raise exception 'FAIL: signup profile trigger'; end if;
  if (select role from public.profiles where id = current_setting('smoke.actor_b')::uuid) <> 'business'
  then raise exception 'FAIL: forged admin signup'; end if;
end $$;

insert into public.agents(id, slug, name, category, status, engine_slug)
values (current_setting('smoke.agent')::uuid, 'smoke-' || current_setting('smoke.agent'),
  'Temporary SQL smoke agent', 'marketing', 'published', 'smoke-' || current_setting('smoke.agent'));

insert into public.agent_runs(company_id, user_id, agent_id, engine_slug, status)
values (current_setting('smoke.actor_a')::uuid, current_setting('smoke.actor_a')::uuid,
  current_setting('smoke.agent')::uuid, 'smoke-' || current_setting('smoke.agent'), 'engine_unreachable');

insert into public.agent_files(id, company_id, user_id, object_path, original_name, mime_type, size_bytes, purpose)
values (current_setting('smoke.file')::uuid, current_setting('smoke.actor_a')::uuid,
  current_setting('smoke.actor_a')::uuid,
  current_setting('smoke.actor_a') || '/' || current_setting('smoke.actor_a') || '/' || current_setting('smoke.file') || '/brief.txt',
  'brief.txt', 'text/plain', 12, 'brief');

set local role authenticated;
select set_config('request.jwt.claim.sub', current_setting('smoke.actor_a'), true);
do $$ begin
  if (select count(*) from public.profiles) <> 1 then raise exception 'FAIL: profile isolation'; end if;
  if (select count(*) from public.agent_runs) <> 1 then raise exception 'FAIL: own run visibility'; end if;
  if (select count(*) from public.agent_files) <> 1 then raise exception 'FAIL: own file visibility'; end if;
  if not private.can_access_agent_object(current_setting('smoke.actor_a') || '/' || current_setting('smoke.actor_a') || '/' || current_setting('smoke.file') || '/brief.txt')
  then raise exception 'FAIL: own Storage path'; end if;
  begin
    update public.profiles set role = 'admin' where id = auth.uid();
    raise exception 'FAIL: self role escalation accepted';
  exception when insufficient_privilege then null; end;
  begin
    insert into public.agent_runs(company_id, user_id, agent_id, engine_slug, status)
    values (auth.uid(), auth.uid(), current_setting('smoke.agent')::uuid, 'smoke-' || current_setting('smoke.agent'), 'running');
    raise exception 'FAIL: client-written run accepted';
  exception when insufficient_privilege then null; end;
end $$;
insert into public.connect_requests(company_id, requested_by, agent_id)
values (auth.uid(), auth.uid(), current_setting('smoke.agent')::uuid);
do $$ begin
  if (select status from public.connect_requests where company_id = auth.uid()) <> 'pending'
  then raise exception 'FAIL: request default status'; end if;
end $$;

select set_config('request.jwt.claim.sub', current_setting('smoke.actor_b'), true);
do $$ begin
  if (select count(*) from public.profiles) <> 1 then raise exception 'FAIL: second profile isolation'; end if;
  if (select count(*) from public.agent_runs) <> 0 then raise exception 'FAIL: cross-tenant runs'; end if;
  if (select count(*) from public.agent_files) <> 0 then raise exception 'FAIL: cross-tenant files'; end if;
  if (select count(*) from public.connect_requests) <> 0 then raise exception 'FAIL: cross-tenant requests'; end if;
  if private.can_access_agent_object(current_setting('smoke.actor_a') || '/' || current_setting('smoke.actor_a') || '/' || current_setting('smoke.file') || '/brief.txt')
  then raise exception 'FAIL: cross-tenant Storage path'; end if;
  begin
    insert into public.connect_requests(company_id, requested_by, agent_id)
    values (current_setting('smoke.actor_a')::uuid, current_setting('smoke.actor_a')::uuid, current_setting('smoke.agent')::uuid);
    raise exception 'FAIL: forged request accepted';
  exception when insufficient_privilege then null; end;
end $$;

select set_config('request.jwt.claim.sub', current_setting('smoke.developer'), true);
insert into public.agent_submissions(developer_id, name, description, category)
values (auth.uid(), 'Temporary submission', 'Synthetic integration test', 'support');
do $$ begin
  if (select count(*) from public.agent_submissions) <> 1 then raise exception 'FAIL: developer submission'; end if;
  if private.can_access_agent_object(current_setting('smoke.developer') || '/' || current_setting('smoke.developer') || '/' || current_setting('smoke.file') || '/brief.txt')
  then raise exception 'FAIL: developer Storage access'; end if;
end $$;

reset role;
rollback;
select 'passed: signup, role protection, tenant isolation, requests, submissions, run/file write protection, Storage path authorization; all synthetic rows rolled back' as smoke_test;

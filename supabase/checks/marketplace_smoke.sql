-- Real PostgreSQL moderation check; every synthetic row is rolled back.
-- No Auth passwords/tokens are issued and no emails/engine calls are made.
begin;
select set_config('marketplace.admin',gen_random_uuid()::text,true),
       set_config('marketplace.business',gen_random_uuid()::text,true),
       set_config('marketplace.developer',gen_random_uuid()::text,true);

insert into auth.users(id,raw_user_meta_data) values
  (current_setting('marketplace.admin')::uuid,'{"role":"business"}'),
  (current_setting('marketplace.business')::uuid,'{"role":"business"}'),
  (current_setting('marketplace.developer')::uuid,'{"role":"developer"}');
update public.profiles set role='admin' where id=current_setting('marketplace.admin')::uuid;
insert into auth.sessions(id,user_id) values
  (current_setting('marketplace.admin')::uuid,current_setting('marketplace.admin')::uuid),
  (current_setting('marketplace.business')::uuid,current_setting('marketplace.business')::uuid),
  (current_setting('marketplace.developer')::uuid,current_setting('marketplace.developer')::uuid);

set local role authenticated;
select set_config('request.jwt.claim.sub',current_setting('marketplace.admin'),true),
       set_config('request.jwt.claims',jsonb_build_object('sub',current_setting('marketplace.admin'),
         'session_id',current_setting('marketplace.admin'))::text,true);
select set_config('marketplace.agent',(public.create_catalog_agent(jsonb_build_object(
  'slug','smoke-'||current_setting('marketplace.admin'),'name','SQL Smoke Catalog','category','support',
  'status','published','engine_slug','smoke-'||current_setting('marketplace.admin')))->>'id'),true);
select set_config('marketplace.draft',(public.create_catalog_agent(jsonb_build_object(
  'slug','draft-'||current_setting('marketplace.admin'),'name','SQL Smoke Draft','category','support'))->>'id'),true);

select set_config('request.jwt.claim.sub',current_setting('marketplace.business'),true),
       set_config('request.jwt.claims',jsonb_build_object('sub',current_setting('marketplace.business'),
         'session_id',current_setting('marketplace.business'))::text,true);
with inserted as (
  insert into public.connect_requests(company_id,requested_by,agent_id)
  values(auth.uid(),auth.uid(),current_setting('marketplace.agent')::uuid) returning id
) select set_config('marketplace.request',id::text,true) from inserted;
do $$ begin
  begin
    perform public.review_connect_request(current_setting('marketplace.request')::uuid,'approved');
    raise exception 'FAIL: business reviewed a request';
  exception when insufficient_privilege then null; end;
  begin
    perform public.create_catalog_agent('{"slug":"bypass","name":"Bypass","category":"support"}');
    raise exception 'FAIL: business created a catalog card';
  exception when insufficient_privilege then null; end;
end $$;

select set_config('request.jwt.claim.sub',current_setting('marketplace.developer'),true),
       set_config('request.jwt.claims',jsonb_build_object('sub',current_setting('marketplace.developer'),
         'session_id',current_setting('marketplace.developer'))::text,true);
with inserted as (
  insert into public.agent_submissions(developer_id,name,description,category)
  values(auth.uid(),'SQL Smoke Submission','Synthetic description','support') returning id
) select set_config('marketplace.submission',id::text,true) from inserted;
do $$ begin
  if (select count(*) from public.connect_requests where id=current_setting('marketplace.request')::uuid)<>0
  then raise exception 'FAIL: developer read a business request'; end if;
end $$;

select set_config('request.jwt.claim.sub',current_setting('marketplace.admin'),true),
       set_config('request.jwt.claims',jsonb_build_object('sub',current_setting('marketplace.admin'),
         'session_id',current_setting('marketplace.admin'))::text,true);
do $$ declare reviewed jsonb; begin
  reviewed:=public.review_connect_request(current_setting('marketplace.request')::uuid,'approved','SQL test');
  if reviewed->>'status'<>'approved' or reviewed->>'reviewed_by'<>current_setting('marketplace.admin')
  then raise exception 'FAIL: approval/audit metadata'; end if;
  begin
    perform public.review_connect_request(current_setting('marketplace.request')::uuid,'rejected');
    raise exception 'FAIL: repeated review accepted';
  exception when raise_exception then
    if sqlerrm<>'already_reviewed' then raise; end if;
  end;
  begin
    perform public.review_agent_submission(current_setting('marketplace.submission')::uuid,
      'approved',null,'smoke-'||current_setting('marketplace.admin'));
    raise exception 'FAIL: duplicate slug accepted';
  exception when unique_violation then null; end;
  if (select status from public.agent_submissions where id=current_setting('marketplace.submission')::uuid)<>'pending'
  then raise exception 'FAIL: failed publication changed submission'; end if;
  reviewed:=public.review_agent_submission(current_setting('marketplace.submission')::uuid,
    'approved','SQL test','external-'||current_setting('marketplace.admin'));
  perform set_config('marketplace.external',reviewed->>'published_agent_id',true);
  if not exists(select 1 from public.agents where id=(reviewed->>'published_agent_id')::uuid
    and status='coming_soon' and engine_slug is null and developer_id=current_setting('marketplace.developer')::uuid)
  then raise exception 'FAIL: external card publication'; end if;
end $$;

set local role anon;
do $$ begin
  if (select count(*) from public.agents where id in (current_setting('marketplace.agent')::uuid,
    current_setting('marketplace.draft')::uuid,current_setting('marketplace.external')::uuid))<>2
  then raise exception 'FAIL: public catalog visibility'; end if;
end $$;

set local role authenticated;
select set_config('request.jwt.claim.sub',current_setting('marketplace.admin'),true),
       set_config('request.jwt.claims','{}',true);
do $$ begin
  begin
    perform public.update_catalog_agent(current_setting('marketplace.agent')::uuid,'{"name":"Revoked"}');
    raise exception 'FAIL: revoked admin session accepted';
  exception when invalid_authorization_specification then null; end;
end $$;
reset role;
rollback;
select 'passed: catalog creation/visibility, live admin checks, business/developer isolation, connection approval, single review, atomic publication rollback, coming-soon external card; all synthetic data rolled back' as marketplace_smoke;

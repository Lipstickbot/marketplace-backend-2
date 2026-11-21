begin;

create function private.require_platform_admin() returns uuid
language plpgsql security definer set search_path = '' as $$
declare actor uuid := auth.uid(); actor_role public.platform_role;
begin
  if actor is null or not private.is_current_session_active() then
    raise exception 'active_session_required' using errcode = '28000';
  end if;
  select role into actor_role from public.profiles where id = actor for share;
  if actor_role is distinct from 'admin'::public.platform_role then
    raise exception 'admin_required' using errcode = '42501';
  end if;
  return actor;
end;
$$;

create function private.validate_catalog_payload(p_data jsonb) returns void
language plpgsql set search_path = '' as $$
begin
  if p_data is null or jsonb_typeof(p_data) <> 'object' or p_data = '{}'::jsonb
    or p_data - array['slug','name','description','category','status','developer_id','engine_slug',
      'version','supported_languages','capabilities','accepted_file_purposes','input_schema','output_schema'] <> '{}'::jsonb
  then raise exception 'invalid_catalog_fields' using errcode = '22023'; end if;
  if (p_data ? 'developer_id') and p_data->>'developer_id' is not null and not exists (
    select 1 from public.profiles where id = (p_data->>'developer_id')::uuid and role = 'developer'
  ) then raise exception 'developer_profile_required' using errcode = '23514'; end if;
end;
$$;

create function private.create_catalog_agent(p_data jsonb) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare row_data public.agents;
begin
  perform private.require_platform_admin();
  perform private.validate_catalog_payload(p_data);
  row_data := jsonb_populate_record(null::public.agents, p_data);
  insert into public.agents(slug,name,description,category,status,developer_id,engine_slug,version,
    supported_languages,capabilities,accepted_file_purposes,input_schema,output_schema)
  values (row_data.slug,row_data.name,coalesce(row_data.description,''),row_data.category,
    coalesce(row_data.status,'draft'),row_data.developer_id,row_data.engine_slug,row_data.version,
    coalesce(row_data.supported_languages,array['ru','kk','en']),coalesce(row_data.capabilities,'{}'),
    coalesce(row_data.accepted_file_purposes,'{}'),coalesce(row_data.input_schema,'{}'),coalesce(row_data.output_schema,'{}'))
  returning * into row_data;
  return to_jsonb(row_data);
end;
$$;

create function private.update_catalog_agent(p_agent_id uuid, p_changes jsonb) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare old_row public.agents; new_row public.agents;
begin
  perform private.require_platform_admin();
  perform private.validate_catalog_payload(p_changes);
  select * into old_row from public.agents where id = p_agent_id for update;
  if not found then raise exception 'agent_not_found' using errcode = 'P0002'; end if;
  new_row := jsonb_populate_record(old_row,p_changes);
  if new_row.engine_slug is distinct from old_row.engine_slug and exists (
    select 1 from public.agent_runs where agent_id = p_agent_id
  ) then raise exception 'engine_binding_has_run_history' using errcode = '23514'; end if;
  update public.agents set slug=new_row.slug,name=new_row.name,description=new_row.description,
    category=new_row.category,status=new_row.status,developer_id=new_row.developer_id,
    engine_slug=new_row.engine_slug,version=new_row.version,supported_languages=new_row.supported_languages,
    capabilities=new_row.capabilities,accepted_file_purposes=new_row.accepted_file_purposes,
    input_schema=new_row.input_schema,output_schema=new_row.output_schema
  where id=p_agent_id returning * into new_row;
  return to_jsonb(new_row);
end;
$$;

create function private.review_connect_request(p_request_id uuid, p_decision public.review_status, p_review_note text)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare actor uuid; row_data public.connect_requests; catalog_status public.agent_status;
begin
  actor := private.require_platform_admin();
  if p_decision is null or p_decision not in ('approved','rejected') or char_length(p_review_note)>4000
  then raise exception 'invalid_review' using errcode='22023'; end if;
  select * into row_data from public.connect_requests where id=p_request_id for update;
  if not found then raise exception 'request_not_found' using errcode='P0002'; end if;
  if row_data.status <> 'pending' then raise exception 'already_reviewed' using errcode='P0001'; end if;
  if p_decision='approved' then
    select status into catalog_status from public.agents where id=row_data.agent_id for share;
    if catalog_status is distinct from 'published'::public.agent_status
    then raise exception 'agent_not_published' using errcode='23514'; end if;
  end if;
  update public.connect_requests set status=p_decision,reviewed_by=actor,reviewed_at=now(),review_note=p_review_note
  where id=p_request_id returning * into row_data;
  return to_jsonb(row_data);
end;
$$;

create function private.review_agent_submission(p_submission_id uuid, p_decision public.review_status,
  p_review_note text, p_publication_slug text) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare actor uuid; row_data public.agent_submissions; new_agent_id uuid;
begin
  actor := private.require_platform_admin();
  if p_decision is null or p_decision not in ('approved','rejected') or char_length(p_review_note)>4000
    or (p_decision='approved' and (p_publication_slug is null or p_publication_slug !~ '^[a-z][a-z0-9-]{0,79}$'))
    or (p_decision='rejected' and p_publication_slug is not null)
  then raise exception 'invalid_review' using errcode='22023'; end if;
  select * into row_data from public.agent_submissions where id=p_submission_id for update;
  if not found then raise exception 'submission_not_found' using errcode='P0002'; end if;
  if row_data.status <> 'pending' then raise exception 'already_reviewed' using errcode='P0001'; end if;
  if p_decision='approved' then
    if not exists (select 1 from public.profiles where id=row_data.developer_id and role='developer')
    then raise exception 'developer_profile_required' using errcode='23514'; end if;
    -- External agents have no engine executor. Approval creates a coming-soon card.
    insert into public.agents(slug,name,description,category,status,developer_id)
    values(p_publication_slug,row_data.name,row_data.description,row_data.category,'coming_soon',row_data.developer_id)
    returning id into new_agent_id;
  end if;
  update public.agent_submissions set status=p_decision,reviewed_by=actor,reviewed_at=now(),
    review_note=p_review_note,published_agent_id=new_agent_id
  where id=p_submission_id returning * into row_data;
  return to_jsonb(row_data);
end;
$$;

-- Public wrappers never elevate privileges. Their private implementations check
-- the caller's live session and database role before taking locks or writing.
create function public.create_catalog_agent(p_data jsonb) returns jsonb
language sql security invoker set search_path='' as $$ select private.create_catalog_agent(p_data); $$;
create function public.update_catalog_agent(p_agent_id uuid,p_changes jsonb) returns jsonb
language sql security invoker set search_path='' as $$ select private.update_catalog_agent(p_agent_id,p_changes); $$;
create function public.review_connect_request(p_request_id uuid,p_decision public.review_status,p_review_note text default null)
returns jsonb language sql security invoker set search_path='' as $$
  select private.review_connect_request(p_request_id,p_decision,p_review_note);
$$;
create function public.review_agent_submission(p_submission_id uuid,p_decision public.review_status,
  p_review_note text default null,p_publication_slug text default null) returns jsonb
language sql security invoker set search_path='' as $$
  select private.review_agent_submission(p_submission_id,p_decision,p_review_note,p_publication_slug);
$$;

revoke all on function private.require_platform_admin() from public,anon,authenticated,service_role;
revoke all on function private.validate_catalog_payload(jsonb) from public,anon,authenticated,service_role;
revoke all on function private.create_catalog_agent(jsonb), private.update_catalog_agent(uuid,jsonb),
  private.review_connect_request(uuid,public.review_status,text),
  private.review_agent_submission(uuid,public.review_status,text,text)
  from public,anon,authenticated,service_role;
revoke all on function public.create_catalog_agent(jsonb), public.update_catalog_agent(uuid,jsonb),
  public.review_connect_request(uuid,public.review_status,text),
  public.review_agent_submission(uuid,public.review_status,text,text)
  from public,anon,authenticated,service_role;
grant execute on function private.create_catalog_agent(jsonb), private.update_catalog_agent(uuid,jsonb),
  private.review_connect_request(uuid,public.review_status,text),
  private.review_agent_submission(uuid,public.review_status,text,text) to authenticated;
grant execute on function public.create_catalog_agent(jsonb), public.update_catalog_agent(uuid,jsonb),
  public.review_connect_request(uuid,public.review_status,text),
  public.review_agent_submission(uuid,public.review_status,text,text) to authenticated;

commit;

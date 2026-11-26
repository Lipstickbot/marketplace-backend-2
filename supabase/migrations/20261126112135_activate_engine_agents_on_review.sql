begin;

alter table public.agents add column auto_connect boolean not null default false;

create function private.clear_activation_on_engine_change() returns trigger
language plpgsql security invoker set search_path = '' as $$
begin
  new.auto_connect := false;
  return new;
end;
$$;

create trigger agents_clear_activation before update of engine_slug on public.agents
  for each row when (old.engine_slug is distinct from new.engine_slug)
  execute function private.clear_activation_on_engine_change();

revoke all on function private.clear_activation_on_engine_change() from public, anon, authenticated, service_role;

-- Only the backend may record a verified binding. Recheck the moderator role
-- and lock the request before writing the public card and its review together.
create function public.activate_agent_submission(p_submission_id uuid, p_actor uuid,
  p_review_note text, p_card jsonb) returns jsonb
language plpgsql security invoker set search_path = '' as $$
declare
  submission public.agent_submissions;
  card public.agents;
  new_agent_id uuid;
begin
  perform 1 from public.profiles where id = p_actor and role = 'admin' for share;
  if not found then raise exception 'admin_required' using errcode = '42501'; end if;
  if p_card is null or jsonb_typeof(p_card) <> 'object' or char_length(p_review_note) > 4000
    then raise exception 'invalid_activation' using errcode = '22023'; end if;

  select * into submission from public.agent_submissions where id = p_submission_id for update;
  if not found then raise exception 'submission_not_found' using errcode = 'P0002'; end if;
  if submission.status <> 'pending' then raise exception 'already_reviewed' using errcode = 'P0001'; end if;
  perform 1 from public.profiles where id = submission.developer_id and role in ('business', 'developer') for share;
  if not found then raise exception 'publisher_profile_required' using errcode = '23514'; end if;

  card := jsonb_populate_record(null::public.agents, p_card);
  insert into public.agents(slug,name,description,category,status,developer_id,engine_slug,version,
    supported_languages,capabilities,accepted_file_purposes,input_schema,output_schema,auto_connect)
  values(card.slug,submission.name,submission.description,submission.category,'published',submission.developer_id,
    card.engine_slug,card.version,card.supported_languages,card.capabilities,card.accepted_file_purposes,
    card.input_schema,card.output_schema,true)
  returning id into new_agent_id;

  update public.agent_submissions set status = 'approved', reviewed_by = p_actor, reviewed_at = now(),
    review_note = p_review_note, published_agent_id = new_agent_id
  where id = p_submission_id returning * into submission;
  return to_jsonb(submission);
end;
$$;

revoke all on function public.activate_agent_submission(uuid,uuid,text,jsonb) from public, anon, authenticated, service_role;
grant execute on function public.activate_agent_submission(uuid,uuid,text,jsonb) to service_role;

create or replace function private.approve_demo_connection() returns trigger
language plpgsql security invoker set search_path = '' as $$
begin
  if new.status = 'pending' and exists (
    select 1 from public.agents a where a.id = new.agent_id and a.status = 'published'
      and (a.auto_connect or private.is_builtin_demo(a))
  ) then
    new.status := 'approved';
    new.auto_approved := true;
    new.reviewed_at := statement_timestamp();
  end if;
  return new;
end;
$$;

alter policy connect_requests_create on public.connect_requests
  with check (
    company_id = (select auth.uid()) and requested_by = (select auth.uid())
    and (select private.current_platform_role()) = 'business'
    and reviewed_by is null and review_note is null
    and exists (
      select 1 from public.agents a
      where a.id = agent_id and a.status = 'published'
        and (
          (connect_requests.status = 'pending' and not auto_approved and reviewed_at is null)
          or (connect_requests.status = 'approved' and auto_approved and reviewed_at is not null
              and (a.auto_connect or private.is_builtin_demo(a)))
        )
    )
  );

commit;

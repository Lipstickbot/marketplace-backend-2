begin;

alter table public.connect_requests
  add column auto_approved boolean not null default false,
  drop constraint connect_requests_review,
  add constraint connect_requests_review check (
    (not auto_approved and status = 'pending' and reviewed_by is null and reviewed_at is null and review_note is null)
    or (not auto_approved and status <> 'pending' and reviewed_by is not null and reviewed_at is not null)
    or (auto_approved and status = 'approved' and reviewed_by is null and reviewed_at is not null and review_note is null)
  );

-- The same catalog criteria apply to new requests and the existing queue.
create function private.is_builtin_demo(agent public.agents) returns boolean
language sql immutable security invoker set search_path = '' as $$
  select agent.status = 'published'
    and agent.developer_id is null
    and agent.slug = agent.engine_slug
    and agent.slug in ('marketing', 'support', 'hr');
$$;

revoke all on function private.is_builtin_demo(public.agents) from public, anon;
grant usage on schema private to service_role;
grant execute on function private.is_builtin_demo(public.agents) to authenticated, service_role;

create function private.approve_demo_connection() returns trigger
language plpgsql security invoker set search_path = '' as $$
begin
  if new.status = 'pending' and exists (
    select 1 from public.agents a where a.id = new.agent_id and private.is_builtin_demo(a)
  ) then
    new.status := 'approved';
    new.auto_approved := true;
    new.reviewed_at := statement_timestamp();
  end if;
  return new;
end;
$$;

create trigger connect_requests_approve_demo before insert on public.connect_requests
  for each row execute function private.approve_demo_connection();

revoke all on function private.approve_demo_connection() from public, anon, authenticated, service_role;

-- RLS evaluates the row after BEFORE INSERT triggers. Status and review
-- fields are still outside the authenticated role's INSERT column grant.
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
          or (connect_requests.status = 'approved' and auto_approved and reviewed_at is not null and private.is_builtin_demo(a))
        )
    )
  );

update public.connect_requests r
set status = 'approved', auto_approved = true, reviewed_at = statement_timestamp()
from public.agents a
where r.agent_id = a.id and r.status = 'pending' and private.is_builtin_demo(a);

commit;

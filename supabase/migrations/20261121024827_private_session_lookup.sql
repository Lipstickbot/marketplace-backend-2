begin;

create function private.is_current_session_active() returns boolean
language sql stable security definer set search_path = '' as $$
  select exists (
    select 1 from auth.sessions s
    where s.user_id = (select auth.uid())
      and s.id::text = (select auth.jwt()->>'session_id')
      and (s.not_after is null or s.not_after > now())
  );
$$;
revoke all on function private.is_current_session_active() from public, anon, authenticated, service_role;
grant execute on function private.is_current_session_active() to authenticated;

-- Exposed API wrapper has no elevated privileges. The internal lookup is private.
create or replace function public.is_current_session_active() returns boolean
language sql stable security invoker set search_path = '' as $$
  select private.is_current_session_active();
$$;

commit;

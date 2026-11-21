begin;

-- Only reveals whether the CALLER's signed JWT names an existing session.
-- Never accepts caller-selected user/session IDs and never exposes auth.sessions.
create function public.is_current_session_active() returns boolean
language sql stable security definer set search_path = '' as $$
  select exists (
    select 1 from auth.sessions s
    where s.user_id = (select auth.uid())
      and s.id::text = (select auth.jwt()->>'session_id')
      and (s.not_after is null or s.not_after > now())
  );
$$;
revoke all on function public.is_current_session_active() from public, anon, authenticated, service_role;
grant execute on function public.is_current_session_active() to authenticated;

comment on function public.is_current_session_active() is
  'Checks the caller session after Supabase verifies the JWT; revoked or expired sessions return false.';

commit;

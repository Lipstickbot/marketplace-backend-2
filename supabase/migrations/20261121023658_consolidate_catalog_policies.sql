begin;

-- Each role now evaluates one SELECT policy, with unchanged visibility.
drop policy agents_public_read on public.agents;
drop policy agents_owner_read on public.agents;

create policy agents_anon_read on public.agents for select to anon
  using (status in ('published', 'coming_soon'));
create policy agents_authenticated_read on public.agents for select to authenticated
  using (
    status in ('published', 'coming_soon')
    or developer_id = (select auth.uid())
    or (select private.current_platform_role()) = 'admin'
  );

commit;

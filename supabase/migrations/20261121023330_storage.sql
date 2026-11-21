begin;

insert into storage.buckets(id, name, public, file_size_limit, allowed_mime_types)
values (
  'agent-files', 'agent-files', false, 10485760,
  array['application/pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'text/plain']
)
on conflict (id) do update set
  public = excluded.public,
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

-- Immutable uploads: <company UUID>/<user UUID>/<file UUID>/<safe filename>.
-- Replacing or deleting a blob requires Backend 2 to clean up its engine copy.
create function private.can_access_agent_object(object_name text) returns boolean
language sql stable set search_path = '' as $$
  select
    (select auth.uid()) is not null
    and (select private.current_platform_role()) = 'business'
    and split_part(object_name, '/', 1) = (select auth.uid())::text
    and split_part(object_name, '/', 2) = (select auth.uid())::text
    and split_part(object_name, '/', 3) ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    and array_length(string_to_array(object_name, '/'), 1) = 4
    and split_part(object_name, '/', 4) not in ('', '.', '..')
    and object_name !~ E'[\\\\]';
$$;
revoke all on function private.can_access_agent_object(text) from public, anon, authenticated;
grant execute on function private.can_access_agent_object(text) to anon, authenticated;

create policy agent_files_storage_read on storage.objects for select to authenticated
  using (bucket_id = 'agent-files' and private.can_access_agent_object(name));
create policy agent_files_storage_upload on storage.objects for insert to authenticated
  with check (bucket_id = 'agent-files' and private.can_access_agent_object(name));

-- Restrictive guards prevent pre-existing broad policies from leaking this bucket.
-- Other buckets retain their existing access rules.
create policy agent_files_storage_read_guard on storage.objects as restrictive for select to public
  using (bucket_id <> 'agent-files' or private.can_access_agent_object(name));
create policy agent_files_storage_upload_guard on storage.objects as restrictive for insert to public
  with check (bucket_id <> 'agent-files' or private.can_access_agent_object(name));
create policy agent_files_storage_update_guard on storage.objects as restrictive for update to public
  using (bucket_id <> 'agent-files') with check (bucket_id <> 'agent-files');
create policy agent_files_storage_delete_guard on storage.objects as restrictive for delete to public
  using (bucket_id <> 'agent-files');

commit;

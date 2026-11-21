-- Read-only checks after applying BOTH migrations in the Supabase SQL Editor.
select c.relname as table_name, c.relrowsecurity as rls_enabled
from pg_class c join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public'
  and c.relname in ('profiles','agents','connect_requests','agent_submissions','agent_runs','agent_files')
order by c.relname;

select id, public, file_size_limit, allowed_mime_types
from storage.buckets where id = 'agent-files';

select trigger_name, event_manipulation
from information_schema.triggers
where event_object_schema = 'auth' and event_object_table = 'users'
  and trigger_name = 'on_auth_user_created';

select tablename, policyname, permissive, roles, cmd
from pg_policies
where (schemaname = 'public' and tablename in
  ('profiles','agents','connect_requests','agent_submissions','agent_runs','agent_files'))
  or (schemaname = 'storage' and policyname like 'agent_files_storage_%')
order by schemaname, tablename, policyname;

-- Expected: zero rows. Column-level allowlisted grants do not appear here.
select grantee, table_name, privilege_type
from information_schema.table_privileges
where table_schema = 'public'
  and table_name in ('profiles','agents','connect_requests','agent_submissions','agent_runs','agent_files')
  and grantee in ('anon', 'authenticated', 'PUBLIC')
  and privilege_type in ('INSERT','UPDATE','DELETE','TRUNCATE','TRIGGER','REFERENCES');

-- Minimal Supabase-owned objects for PostgreSQL tests, NEVER a migration.
-- HTTP Auth/Storage services, JWT verification and upload MIME checks are not emulated.
create role anon nologin;
create role authenticated nologin;
create role service_role nologin bypassrls;
create schema auth;
create schema storage;
grant usage on schema auth, storage, public to anon, authenticated, service_role;

create table auth.users (
  id uuid primary key,
  raw_user_meta_data jsonb not null default '{}'
);
create table auth.sessions (
  id uuid primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  not_after timestamptz
);
create function auth.jwt() returns jsonb language sql stable as $$
  select nullif(current_setting('request.jwt.claims', true), '')::jsonb;
$$;
grant execute on function auth.jwt() to anon, authenticated, service_role;
create function auth.uid() returns uuid language sql stable as $$
  select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid;
$$;
grant execute on function auth.uid() to anon, authenticated, service_role;

create table storage.buckets (
  id text primary key,
  name text not null,
  public boolean not null default false,
  file_size_limit bigint,
  allowed_mime_types text[]
);
create table storage.objects (
  id uuid primary key default gen_random_uuid(),
  bucket_id text not null references storage.buckets(id),
  name text not null,
  owner_id text,
  unique(bucket_id, name)
);
alter table storage.objects enable row level security;
grant select, insert, update, delete on storage.objects to anon, authenticated, service_role;
grant all on storage.buckets to service_role;

-- Simulate permissive grants on existing Supabase projects.
alter default privileges in schema public grant all on tables to anon, authenticated, service_role;

-- Existing accounts must get a profile during migration as well as new signups.
insert into auth.users(id, raw_user_meta_data) values
 ('00000000-0000-4000-8000-000000000001', '{"role":"business","company_name":"Company A"}');

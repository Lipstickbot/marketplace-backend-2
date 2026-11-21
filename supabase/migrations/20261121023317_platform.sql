-- Backend 2 owns public; AI Engine owns a separate database/schema.
begin;

create schema if not exists private;
revoke all on schema private from public, anon, authenticated;
grant usage on schema private to anon, authenticated;

create type public.platform_role as enum ('business', 'developer', 'admin');
create type public.agent_status as enum ('draft', 'published', 'coming_soon', 'archived');
create type public.review_status as enum ('pending', 'approved', 'rejected');
create type public.run_status as enum (
  'running', 'success', 'escalation_required', 'blocked', 'rejected', 'error', 'engine_unreachable'
);
create type public.file_purpose as enum ('brief', 'knowledge_base', 'resume', 'job_description');

create table public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  role public.platform_role not null default 'business',
  display_name text not null default '' check (char_length(display_name) <= 120),
  company_name text not null default '' check (char_length(company_name) <= 200),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.agents (
  id uuid primary key default gen_random_uuid(),
  slug text not null unique check (slug ~ '^[a-z][a-z0-9-]{0,79}$'),
  name text not null check (char_length(name) between 1 and 160),
  description text not null default '' check (char_length(description) <= 10000),
  category text not null check (char_length(category) between 1 and 80),
  status public.agent_status not null default 'draft',
  developer_id uuid references public.profiles(id) on delete restrict,
  engine_slug text unique check (engine_slug ~ '^[a-z][a-z0-9-]{0,79}$'),
  version text,
  supported_languages text[] not null default array['ru','kk','en']::text[]
    check (cardinality(supported_languages) > 0 and supported_languages <@ array['ru','kk','en']::text[]),
  capabilities text[] not null default '{}',
  accepted_file_purposes public.file_purpose[] not null default '{}',
  input_schema jsonb not null default '{}' check (jsonb_typeof(input_schema) = 'object'),
  output_schema jsonb not null default '{}' check (jsonb_typeof(output_schema) = 'object'),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint agents_published_executor check (
    status <> 'published' or engine_slug is not null
  )
);

create table public.connect_requests (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references public.profiles(id) on delete restrict,
  requested_by uuid not null references public.profiles(id) on delete restrict,
  agent_id uuid not null references public.agents(id) on delete restrict,
  message text not null default '' check (char_length(message) <= 4000),
  status public.review_status not null default 'pending',
  reviewed_by uuid references public.profiles(id) on delete restrict,
  reviewed_at timestamptz,
  review_note text check (char_length(review_note) <= 4000),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint connect_requests_one_owner check (company_id = requested_by),
  constraint connect_requests_review check (
    (status = 'pending' and reviewed_by is null and reviewed_at is null and review_note is null)
    or (status <> 'pending' and reviewed_by is not null and reviewed_at is not null)
  ),
  unique (company_id, agent_id)
);

create table public.agent_submissions (
  id uuid primary key default gen_random_uuid(),
  developer_id uuid not null references public.profiles(id) on delete restrict,
  name text not null check (char_length(name) between 1 and 160),
  description text not null check (char_length(description) between 1 and 10000),
  category text not null check (char_length(category) between 1 and 80),
  repository_url text check (char_length(repository_url) <= 2048 and repository_url ~ '^https://'),
  status public.review_status not null default 'pending',
  published_agent_id uuid references public.agents(id) on delete restrict,
  reviewed_by uuid references public.profiles(id) on delete restrict,
  reviewed_at timestamptz,
  review_note text check (char_length(review_note) <= 4000),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint agent_submissions_review check (
    (status = 'pending' and reviewed_by is null and reviewed_at is null
      and review_note is null and published_agent_id is null)
    or (status <> 'pending' and reviewed_by is not null and reviewed_at is not null)
  )
);

create table public.agent_runs (
  id uuid primary key default gen_random_uuid(),
  engine_run_id uuid unique,
  company_id uuid not null references public.profiles(id) on delete restrict,
  user_id uuid not null references public.profiles(id) on delete restrict,
  agent_id uuid not null references public.agents(id) on delete restrict,
  engine_slug text not null check (char_length(engine_slug) between 1 and 80),
  agent_version text,
  status public.run_status not null,
  language text check (language in ('ru','kk','en')),
  mode text check (mode in ('mock','none','openai','groq','gemini','openrouter','ollama')),
  model text,
  input_tokens integer check (input_tokens >= 0),
  output_tokens integer check (output_tokens >= 0),
  total_tokens bigint generated always as (input_tokens::bigint + output_tokens::bigint) stored,
  estimated_cost numeric(20,10) check (estimated_cost >= 0),
  currency text not null default 'USD' check (currency = 'USD'),
  execution_time_ms integer check (execution_time_ms >= 0),
  http_status smallint check (http_status between 100 and 599),
  error_code text check (char_length(error_code) <= 120),
  request_id text check (char_length(request_id) <= 128),
  file_count integer not null default 0 check (file_count >= 0),
  source_count integer not null default 0 check (source_count >= 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint agent_runs_one_owner check (company_id = user_id),
  constraint agent_runs_engine_identity check (
    status not in ('success','escalation_required','blocked') or engine_run_id is not null
  ),
  constraint agent_runs_unreachable check (status <> 'engine_unreachable' or engine_run_id is null)
);
comment on table public.agent_runs is
  'Metadata only. No prompts, model responses, resume contents, sources or raw error bodies.';
comment on column public.agent_runs.engine_run_id is
  'AI Engine response.run_id or error.details.run_id; null if no engine run was created.';

create table public.agent_files (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references public.profiles(id) on delete restrict,
  user_id uuid not null references public.profiles(id) on delete restrict,
  bucket_id text not null default 'agent-files' check (bucket_id = 'agent-files'),
  object_path text not null,
  original_name text not null check (char_length(original_name) between 1 and 255),
  mime_type text not null check (mime_type in (
    'application/pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'text/plain'
  )),
  size_bytes bigint not null check (size_bytes between 1 and 10485760),
  purpose public.file_purpose not null,
  engine_file_id uuid unique,
  engine_synced_at timestamptz,
  deletion_requested_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint agent_files_one_owner check (company_id = user_id),
  constraint agent_files_path check (
    split_part(object_path, '/', 1) = company_id::text
    and split_part(object_path, '/', 2) = user_id::text
    and split_part(object_path, '/', 3) = id::text
    and array_length(string_to_array(object_path, '/'), 1) = 4
    and split_part(object_path, '/', 4) not in ('', '.', '..')
    and object_path !~ E'[\\\\]'
  ),
  constraint agent_files_engine_sync check (
    (engine_file_id is null) = (engine_synced_at is null)
  ),
  unique (bucket_id, object_path)
);

create index agents_catalog_idx on public.agents(status, category, created_at desc);
create index agents_developer_idx on public.agents(developer_id);
create index connect_requests_requester_idx on public.connect_requests(requested_by);
create index connect_requests_agent_idx on public.connect_requests(agent_id, status);
create index connect_requests_reviewer_idx on public.connect_requests(reviewed_by);
create index agent_submissions_developer_idx on public.agent_submissions(developer_id, created_at desc);
create index agent_submissions_status_idx on public.agent_submissions(status, created_at desc);
create index agent_submissions_reviewer_idx on public.agent_submissions(reviewed_by);
create index agent_submissions_agent_idx on public.agent_submissions(published_agent_id);
create index agent_runs_company_idx on public.agent_runs(company_id, created_at desc);
create index agent_runs_user_idx on public.agent_runs(user_id, created_at desc);
create index agent_runs_agent_idx on public.agent_runs(agent_id, created_at desc);
create index agent_files_company_idx on public.agent_files(company_id, created_at desc);
create index agent_files_user_idx on public.agent_files(user_id, created_at desc);

create function private.touch_updated_at() returns trigger
language plpgsql set search_path = '' as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

create function private.current_platform_role() returns public.platform_role
language sql stable security definer set search_path = '' as $$
  select role from public.profiles where id = (select auth.uid());
$$;

-- The only trusted signup inputs are bounded display fields and an allowlisted
-- business/developer choice. app/user metadata can never create an admin.
create function private.handle_new_user() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
  insert into public.profiles(id, role, display_name, company_name)
  values (
    new.id,
    case when new.raw_user_meta_data->>'role' = 'developer'
      then 'developer'::public.platform_role else 'business'::public.platform_role end,
    left(coalesce(new.raw_user_meta_data->>'display_name', ''), 120),
    left(coalesce(new.raw_user_meta_data->>'company_name', ''), 200)
  );
  return new;
end;
$$;
create trigger on_auth_user_created after insert on auth.users
  for each row execute function private.handle_new_user();

-- Also create profiles for accounts registered before this migration.
insert into public.profiles(id, role, display_name, company_name)
select id,
  case when raw_user_meta_data->>'role' = 'developer'
    then 'developer'::public.platform_role else 'business'::public.platform_role end,
  left(coalesce(raw_user_meta_data->>'display_name', ''), 120),
  left(coalesce(raw_user_meta_data->>'company_name', ''), 200)
from auth.users on conflict (id) do nothing;

-- Trusted backend writes must still use a business tenant and the right agent.
create function private.validate_business_record() returns trigger
language plpgsql security definer set search_path = '' as $$
declare
  catalog_engine_slug text;
begin
  if not exists (select 1 from public.profiles where id = new.company_id and role = 'business') then
    raise exception 'company_id must reference a business profile' using errcode = '23514';
  end if;
  if tg_table_name = 'agent_runs' then
    select engine_slug into catalog_engine_slug from public.agents where id = new.agent_id;
    if catalog_engine_slug is null or catalog_engine_slug is distinct from new.engine_slug then
      raise exception 'agent_runs.engine_slug must match the catalog agent' using errcode = '23514';
    end if;
  end if;
  return new;
end;
$$;

create trigger connect_requests_business before insert or update on public.connect_requests
  for each row execute function private.validate_business_record();
create trigger agent_runs_business before insert or update on public.agent_runs
  for each row execute function private.validate_business_record();
create trigger agent_files_business before insert or update on public.agent_files
  for each row execute function private.validate_business_record();

do $$
declare t text;
begin
  foreach t in array array['profiles','agents','connect_requests','agent_submissions','agent_runs','agent_files'] loop
    execute format('create trigger touch_updated_at before update on public.%I for each row execute function private.touch_updated_at()', t);
    execute format('alter table public.%I enable row level security', t);
    -- Remove Supabase default grants, including TRUNCATE (which bypasses RLS).
    execute format('revoke all on table public.%I from public, anon, authenticated, service_role', t);
    execute format('grant select, insert, update, delete on table public.%I to service_role', t);
  end loop;
end;
$$;

grant usage on schema public to anon, authenticated, service_role;
grant select on public.agents to anon, authenticated;
grant select on public.profiles, public.connect_requests, public.agent_submissions,
  public.agent_runs, public.agent_files to authenticated;
grant update(display_name, company_name) on public.profiles to authenticated;
grant insert(company_id, requested_by, agent_id, message) on public.connect_requests to authenticated;
grant insert(developer_id, name, description, category, repository_url)
  on public.agent_submissions to authenticated;

create policy profiles_read on public.profiles for select to authenticated
  using (id = (select auth.uid()) or (select private.current_platform_role()) = 'admin');
create policy profiles_update_self on public.profiles for update to authenticated
  using (id = (select auth.uid())) with check (id = (select auth.uid()));

create policy agents_public_read on public.agents for select to anon, authenticated
  using (status in ('published', 'coming_soon'));
create policy agents_owner_read on public.agents for select to authenticated
  using (developer_id = (select auth.uid()) or (select private.current_platform_role()) = 'admin');

create policy connect_requests_read on public.connect_requests for select to authenticated
  using (requested_by = (select auth.uid()) or (select private.current_platform_role()) = 'admin');
create policy connect_requests_create on public.connect_requests for insert to authenticated
  with check (
    company_id = (select auth.uid()) and requested_by = (select auth.uid())
    and (select private.current_platform_role()) = 'business'
    and status = 'pending' and reviewed_by is null and reviewed_at is null and review_note is null
    and exists (select 1 from public.agents where id = agent_id and status = 'published')
  );

create policy agent_submissions_read on public.agent_submissions for select to authenticated
  using (developer_id = (select auth.uid()) or (select private.current_platform_role()) = 'admin');
create policy agent_submissions_create on public.agent_submissions for insert to authenticated
  with check (
    developer_id = (select auth.uid()) and (select private.current_platform_role()) = 'developer'
    and status = 'pending' and reviewed_by is null and reviewed_at is null
    and review_note is null and published_agent_id is null
  );

-- Platform moderators do not automatically receive private HR files/run history.
create policy agent_runs_read_self on public.agent_runs for select to authenticated
  using (company_id = (select auth.uid()) and user_id = (select auth.uid()));
create policy agent_files_read_self on public.agent_files for select to authenticated
  using (company_id = (select auth.uid()) and user_id = (select auth.uid()));

-- Trigger functions cannot be invoked as RPCs; the role helper is private to RLS.
revoke all on function private.touch_updated_at() from public, anon, authenticated;
revoke all on function private.handle_new_user() from public, anon, authenticated;
revoke all on function private.validate_business_record() from public, anon, authenticated;
revoke all on function private.current_platform_role() from public, anon, authenticated;
grant execute on function private.current_platform_role() to anon, authenticated;

commit;

begin;
-- Server-only credential hashes and task settings. Browsers use Backend 2.
create table public.agent_integrations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles(id) on delete cascade,
  company_id uuid not null references public.profiles(id) on delete cascade,
  agent_id uuid not null references public.agents(id) on delete cascade,
  agent_slug text not null check (agent_slug ~ '^[a-z][a-z0-9-]{0,79}$'),
  name text not null check (char_length(name) between 1 and 120),
  task text not null default '' check (char_length(task) <= 2000),
  language text not null default 'auto' check (language in ('auto','ru','kk','en')),
  file_ids uuid[] not null default '{}' check (cardinality(file_ids) <= 10),
  key_hash text not null unique check (key_hash ~ '^[a-f0-9]{64}$'),
  key_prefix text not null check (char_length(key_prefix) = 13),
  expires_at timestamptz not null,
  revoked_at timestamptz,
  created_at timestamptz not null default now(),
  constraint integration_owner check (company_id = user_id)
);
create index agent_integrations_owner on public.agent_integrations(user_id, company_id, created_at desc);
create index agent_integrations_agent on public.agent_integrations(agent_id);
alter table public.agent_integrations enable row level security;
revoke all on public.agent_integrations from public, anon, authenticated;
revoke all on public.agent_integrations from service_role;
grant select, insert, update, delete on public.agent_integrations to service_role;
comment on table public.agent_integrations is 'Server-only scoped application keys (SHA-256 hashes only), selected documents and task configuration. Never stores Supabase sessions or engine secrets.';
commit;

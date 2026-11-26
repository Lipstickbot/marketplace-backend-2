begin;

alter table public.agents add column price_minor integer check (price_minor between 1 and 100000000);

create table public.agent_purchases (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references public.profiles(id) on delete restrict,
  agent_id uuid not null references public.agents(id) on delete restrict,
  amount integer not null check (amount between 1 and 100000000),
  status text not null default 'pending' check (status in ('pending', 'failed', 'paid')),
  provider_token text unique,
  checkout_url text,
  provider_payment_id text unique,
  created_at timestamptz not null default now(),
  paid_at timestamptz,
  check ((status = 'paid') = (paid_at is not null and provider_payment_id is not null))
);
create unique index agent_purchases_open_order on public.agent_purchases(company_id, agent_id)
  where status in ('pending', 'paid');
alter table public.agent_purchases enable row level security;
revoke all on public.agent_purchases from public, anon, authenticated, service_role;
grant select, insert, update on public.agent_purchases to service_role;

alter policy connect_requests_create on public.connect_requests
  with check (
    company_id = (select auth.uid()) and requested_by = (select auth.uid())
    and (select private.current_platform_role()) = 'business'
    and reviewed_by is null and review_note is null
    and exists (
      select 1 from public.agents a
      where a.id = agent_id and a.status = 'published' and a.price_minor is null
        and (
          (connect_requests.status = 'pending' and not auto_approved and reviewed_at is null)
          or (connect_requests.status = 'approved' and auto_approved and reviewed_at is not null
              and (a.auto_connect or private.is_builtin_demo(a)))
        )
    )
  );

-- Reserve at the current catalog price and reuse any open order.
create function public.reserve_agent_purchase(p_company uuid, p_agent uuid, p_amount integer)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare
  purchase public.agent_purchases;
  reserved boolean;
  current_price integer;
begin
  select price_minor into current_price from public.agents
    where id = p_agent and status = 'published' for share;
  if current_price is null or current_price is distinct from p_amount then
    return jsonb_build_object('reason', 'price_changed');
  end if;
  if exists (select 1 from public.connect_requests
      where company_id = p_company and agent_id = p_agent and status = 'approved') then
    return jsonb_build_object('reason', 'already_connected');
  end if;
  insert into public.agent_purchases(company_id, agent_id, amount) values (p_company, p_agent, p_amount)
    on conflict (company_id, agent_id) where status in ('pending', 'paid') do nothing
    returning * into purchase;
  reserved := found;
  if not reserved then
    select * into purchase from public.agent_purchases
      where company_id = p_company and agent_id = p_agent and status in ('pending', 'paid');
  end if;
  return jsonb_build_object('order', to_jsonb(purchase), 'reserved', reserved);
end;
$$;

create function public.complete_agent_purchase(p_order uuid, p_token text, p_payment_id text)
returns boolean language plpgsql security invoker set search_path = '' as $$
declare
  purchase public.agent_purchases;
begin
  select * into purchase from public.agent_purchases where id = p_order for update;
  if not found or purchase.provider_token is null or purchase.provider_token is distinct from p_token
      or nullif(p_payment_id, '') is null then
    return false;
  end if;
  if purchase.status = 'paid' then
    return purchase.provider_payment_id = p_payment_id;
  end if;
  if purchase.status <> 'pending' then return false; end if;

  insert into public.connect_requests(company_id, requested_by, agent_id, message, status, auto_approved, reviewed_at)
    values (purchase.company_id, purchase.company_id, purchase.agent_id, 'Покупка агента', 'approved', true, now())
    on conflict (company_id, agent_id) do update
      set status = 'approved', auto_approved = true, reviewed_by = null, reviewed_at = now(), review_note = null
      where connect_requests.status <> 'approved';
  update public.agent_purchases set status = 'paid', paid_at = now(), provider_payment_id = p_payment_id
    where id = p_order;
  return true;
end;
$$;

revoke all on function public.reserve_agent_purchase(uuid, uuid, integer) from public, anon, authenticated;
revoke all on function public.complete_agent_purchase(uuid, text, text) from public, anon, authenticated;
grant execute on function public.reserve_agent_purchase(uuid, uuid, integer) to service_role;
grant execute on function public.complete_agent_purchase(uuid, text, text) to service_role;

commit;

-- 資料管線結構：請在 Supabase SQL Editor 執行（可重複執行）

-- 既有保留的舊 daily_quotes（無 trade_date 欄位）：若為空表則刪除重建，有資料則中止
do $$
declare n bigint;
begin
  if exists (select 1 from information_schema.tables
             where table_schema = 'public' and table_name = 'daily_quotes')
     and not exists (select 1 from information_schema.columns
                     where table_schema = 'public' and table_name = 'daily_quotes'
                       and column_name = 'trade_date') then
    execute 'select count(*) from public.daily_quotes' into n;
    if n = 0 then
      drop table public.daily_quotes cascade;
      raise notice 'dropped stale empty table public.daily_quotes (old shape, 0 rows); it will be recreated';
    else
      raise exception 'public.daily_quotes has an unexpected shape (no trade_date) and % rows; nothing was dropped', n;
    end if;
  end if;
end $$;

create table if not exists daily_quotes (
  stock_id text not null,
  trade_date date not null,
  market text check (market in ('上市','上櫃','興櫃')),
  open numeric, high numeric, low numeric, close numeric,
  change numeric, change_pct numeric,
  volume bigint,
  updated_at timestamptz default now(),
  primary key (stock_id, trade_date)
);
create index if not exists idx_daily_quotes_trade_date on daily_quotes (trade_date desc);

create table if not exists ex_rights (
  stock_id text not null,
  ex_date date not null,
  kind text,
  prev_close numeric,
  ref_price numeric,
  total_value numeric,
  primary key (stock_id, ex_date)
);

create table if not exists sync_runs (
  id bigserial primary key,
  dataset text not null,
  status text not null check (status in ('ok','failed')),
  last_date text,
  rows int,
  message text,
  finished_at timestamptz default now()
);

-- 籌碼與成長動能：新增欄位、放寬 NOT NULL、確保唯一約束
-- 只在首次執行（dealer_net 欄位尚未存在）時清除既有假 0 資料；之後重跑不會刪資料
do $$
begin
  if not exists (
    select 1 from information_schema.columns
    where table_schema = 'public' and table_name = 'smart_money_flow' and column_name = 'dealer_net'
  ) then
    truncate smart_money_flow, growth_momentum;
  end if;
end $$;

alter table smart_money_flow add column if not exists dealer_net bigint;

alter table smart_money_flow alter column trust_net drop not null;
alter table smart_money_flow alter column foreign_net drop not null;
alter table smart_money_flow alter column total_net drop not null;

alter table growth_momentum alter column revenue drop not null;
alter table growth_momentum alter column yoy_pct drop not null;
alter table growth_momentum alter column mom_pct drop not null;
alter table growth_momentum alter column acc_yoy_pct drop not null;

do $$
begin
  if not exists (
    select 1 from pg_constraint c
    where c.conrelid = 'public.smart_money_flow'::regclass and c.contype in ('u','p')
      and (select array_agg(a.attname::text order by a.attname::text)
           from pg_attribute a where a.attrelid = c.conrelid and a.attnum = any(c.conkey))
          = array['stock_id','trade_date']
  ) then
    alter table smart_money_flow add constraint smart_money_flow_stock_date_key unique (stock_id, trade_date);
  end if;

  if not exists (
    select 1 from pg_constraint c
    where c.conrelid = 'public.growth_momentum'::regclass and c.contype in ('u','p')
      and (select array_agg(a.attname::text order by a.attname::text)
           from pg_attribute a where a.attrelid = c.conrelid and a.attnum = any(c.conkey))
          = array['data_month','stock_id']
  ) then
    alter table growth_momentum add constraint growth_momentum_stock_month_key unique (stock_id, data_month);
  end if;
end $$;

-- 以最新有收盤價的資料更新 companies
create or replace function refresh_company_latest()
returns void
language sql
security definer
set search_path = public, pg_temp
as $$
  update companies c
  set latest_price = q.close, latest_change = q.change_pct
  from (
    select distinct on (stock_id) stock_id, close, change_pct
    from daily_quotes
    where close is not null
    order by stock_id, trade_date desc
  ) q
  where c.stock_id = q.stock_id;
$$;
-- 匿名角色不可呼叫（僅 service key 可）
revoke execute on function refresh_company_latest() from public, anon, authenticated;
grant execute on function refresh_company_latest() to service_role;

-- RLS：public schema 所有表啟用，匿名只讀
do $$
declare r record;
begin
  for r in select tablename from pg_tables where schemaname = 'public' loop
    execute format('alter table public.%I enable row level security', r.tablename);
  end loop;

  for r in select schemaname, tablename, policyname from pg_policies
           where schemaname = 'public' and cmd <> 'SELECT' loop
    execute format('drop policy %I on %I.%I', r.policyname, r.schemaname, r.tablename);
  end loop;

  for r in select tablename from pg_tables where schemaname = 'public' loop
    if not exists (select 1 from pg_policies
                   where schemaname = 'public' and tablename = r.tablename and policyname = 'anon_read') then
      execute format('create policy anon_read on public.%I for select to anon, authenticated using (true)', r.tablename);
    end if;
  end loop;
end $$;

-- 等權產業指數資料表（可重複執行，只新增不刪除）。
-- 請整份貼到 Supabase SQL Editor 執行。
do $idx$
begin
  execute $q$
    create table if not exists public.industry_index_daily (
      scope_kind text not null check (scope_kind in ('market', 'major', 'tier', 'node')),
      scope_id text not null,
      trade_date date not null,
      level numeric not null,
      ret_pct numeric,
      members int not null default 0,
      updated_at timestamptz default now(),
      primary key (scope_kind, scope_id, trade_date)
    )
  $q$;

  execute $q$
    create table if not exists public.industry_index_scopes (
      scope_kind text not null,
      scope_id text not null,
      members_hash text,
      member_count int,
      updated_at timestamptz default now(),
      primary key (scope_kind, scope_id)
    )
  $q$;

  execute 'create index if not exists industry_index_daily_trade_date_idx on public.industry_index_daily (trade_date)';

  -- RLS：啟用，匿名只讀
  execute 'alter table public.industry_index_daily enable row level security';
  execute 'alter table public.industry_index_scopes enable row level security';

  if not exists (select 1 from pg_policies
                 where schemaname = 'public' and tablename = 'industry_index_daily' and policyname = 'anon_read') then
    execute 'create policy anon_read on public.industry_index_daily for select to anon, authenticated using (true)';
  end if;
  if not exists (select 1 from pg_policies
                 where schemaname = 'public' and tablename = 'industry_index_scopes' and policyname = 'anon_read') then
    execute 'create policy anon_read on public.industry_index_scopes for select to anon, authenticated using (true)';
  end if;
end
$idx$;

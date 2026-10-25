-- 除權息日當天的漲跌：交易所不提供，以收盤價 - 參考價補算（可重複執行）
create or replace function fill_ex_date_changes()
returns void
language sql
security definer
set search_path = public, pg_temp
as $$
  update daily_quotes q
  set change = q.close - e.ref_price,
      change_pct = round(((q.close - e.ref_price) / e.ref_price * 100)::numeric, 2)
  from ex_rights e
  where q.stock_id = e.stock_id
    and q.trade_date = e.ex_date
    and q.change is null
    and q.close is not null
    and e.ref_price > 0;
$$;
revoke execute on function fill_ex_date_changes() from public, anon, authenticated;
grant execute on function fill_ex_date_changes() to service_role;

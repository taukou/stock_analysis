-- 003：存全市場資料。舊表 smart_money_flow／growth_momentum 對 companies 設有外鍵，
-- 未追蹤的公司寫入時會被擋下（23503）。移除這些表指向 companies 的外鍵；不刪任何資料。
-- 可重複執行。
do $$
declare
  r record;
begin
  for r in
    select con.conrelid::regclass as tbl, con.conname
    from pg_constraint con
    where con.contype = 'f'
      and con.confrelid = 'public.companies'::regclass
      and con.conrelid in ('public.smart_money_flow'::regclass,
                           'public.growth_momentum'::regclass)
  loop
    execute format('alter table %s drop constraint %I', r.tbl, r.conname);
    raise notice 'dropped % on %', r.conname, r.tbl;
  end loop;
end $$;

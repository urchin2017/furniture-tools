-- ============================================================
-- 家具出口内部工具 · 初始 schema + RLS
-- 一次性在 Supabase SQL Editor 粘贴运行。可安全重复运行（幂等）。
-- 覆盖：profiles(角色) / glossary(术语表) / factory_profiles / jobs / storage
-- 隔离模式：共享资源(登录可读) + 私有任务(按 user_id)
-- ============================================================

-- ---------- 枚举 ----------
do $$ begin
  if not exists (select 1 from pg_type where typname = 'app_role') then
    create type public.app_role as enum ('sales', 'admin');
  end if;
end $$;

-- ---------- profiles（用户 + 角色）----------
create table if not exists public.profiles (
  id         uuid primary key references auth.users(id) on delete cascade,
  email      text,
  role       public.app_role not null default 'sales',
  created_at timestamptz not null default now()
);

-- 新用户注册后自动建 profile
create or replace function public.handle_new_user()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  insert into public.profiles (id, email)
  values (new.id, new.email)
  on conflict (id) do nothing;
  return new;
end $$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- 判断当前用户是否 admin（security definer 避免 RLS 递归）
create or replace function public.is_admin()
returns boolean language sql security definer set search_path = public stable as $$
  select exists (
    select 1 from public.profiles
    where id = auth.uid() and role = 'admin'
  );
$$;

-- 通用：自动维护 updated_at
create or replace function public.touch_updated_at()
returns trigger language plpgsql as $$
begin new.updated_at = now(); return new; end $$;

alter table public.profiles enable row level security;

drop policy if exists profiles_self_read on public.profiles;
create policy profiles_self_read on public.profiles
  for select using (id = auth.uid() or public.is_admin());

drop policy if exists profiles_admin_update on public.profiles;
create policy profiles_admin_update on public.profiles
  for update using (public.is_admin()) with check (public.is_admin());

-- ---------- glossary（术语表 · 单一真相源 · 所有登录用户可读写）----------
create table if not exists public.glossary (
  id          uuid primary key default gen_random_uuid(),
  source_lang text not null,                 -- 'ja' | 'en' | 'zh' ...
  target_lang text not null,
  source_term text not null,
  target_term text not null,
  domain      text not null default '',       -- '' = 未指定领域
  note        text,
  created_by  uuid references auth.users(id),
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  unique (source_lang, target_lang, source_term, domain)
);
create index if not exists glossary_lookup_idx
  on public.glossary (source_lang, target_lang, source_term);

drop trigger if exists glossary_touch on public.glossary;
create trigger glossary_touch before update on public.glossary
  for each row execute function public.touch_updated_at();

alter table public.glossary enable row level security;

drop policy if exists glossary_read on public.glossary;
create policy glossary_read on public.glossary
  for select using (auth.uid() is not null);

drop policy if exists glossary_insert on public.glossary;
create policy glossary_insert on public.glossary
  for insert with check (auth.uid() is not null and created_by = auth.uid());

drop policy if exists glossary_update on public.glossary;
create policy glossary_update on public.glossary
  for update using (auth.uid() is not null);

drop policy if exists glossary_delete on public.glossary;
create policy glossary_delete on public.glossary
  for delete using (auth.uid() is not null);

-- ---------- factory_profiles（工厂 profile · 共享只读 + admin 写）----------
create table if not exists public.factory_profiles (
  id         uuid primary key default gen_random_uuid(),
  code       text not null unique,             -- 'chuangming'
  name       text not null,                    -- '创明 / Chuangming'
  profile    jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
alter table public.factory_profiles enable row level security;

drop policy if exists factory_read on public.factory_profiles;
create policy factory_read on public.factory_profiles
  for select using (auth.uid() is not null);

drop policy if exists factory_admin_all on public.factory_profiles;
create policy factory_admin_all on public.factory_profiles
  for all using (public.is_admin()) with check (public.is_admin());

-- ---------- jobs（任务 · 私有 · 按 user_id 隔离）----------
do $$ begin
  if not exists (select 1 from pg_type where typname = 'job_feature') then
    create type public.job_feature as enum
      ('quote_generate','quote_compare','drawing_translate','drawing_revision_diff','shipping_marks');
  end if;
  if not exists (select 1 from pg_type where typname = 'job_status') then
    create type public.job_status as enum
      ('queued','running','needs_input','done','error');
  end if;
end $$;

create table if not exists public.jobs (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null default auth.uid() references auth.users(id) on delete cascade,
  feature      public.job_feature not null,
  status       public.job_status not null default 'queued',
  progress     int not null default 0,
  params       jsonb,
  input_files  jsonb,
  output_files jsonb,
  needs_input  jsonb,
  usage_json   jsonb,
  cost_usd     numeric(10,4) not null default 0,
  error        text,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);
create index if not exists jobs_user_idx on public.jobs (user_id, created_at desc);

drop trigger if exists jobs_touch on public.jobs;
create trigger jobs_touch before update on public.jobs
  for each row execute function public.touch_updated_at();

alter table public.jobs enable row level security;

drop policy if exists jobs_owner_read on public.jobs;
create policy jobs_owner_read on public.jobs
  for select using (user_id = auth.uid() or public.is_admin());

drop policy if exists jobs_owner_insert on public.jobs;
create policy jobs_owner_insert on public.jobs
  for insert with check (user_id = auth.uid());

drop policy if exists jobs_owner_update on public.jobs;
create policy jobs_owner_update on public.jobs
  for update using (user_id = auth.uid() or public.is_admin());

-- ---------- storage buckets（私有：uploads / outputs）----------
insert into storage.buckets (id, name, public)
values ('uploads','uploads', false), ('outputs','outputs', false)
on conflict (id) do nothing;

-- 路径首段 = user_id 才可读写；admin 全通。约定路径 {user_id}/{job_id}/{filename}
drop policy if exists uploads_owner on storage.objects;
create policy uploads_owner on storage.objects for all
  using (bucket_id = 'uploads' and (split_part(name,'/',1) = auth.uid()::text or public.is_admin()))
  with check (bucket_id = 'uploads' and split_part(name,'/',1) = auth.uid()::text);

drop policy if exists outputs_owner on storage.objects;
create policy outputs_owner on storage.objects for all
  using (bucket_id = 'outputs' and (split_part(name,'/',1) = auth.uid()::text or public.is_admin()))
  with check (bucket_id = 'outputs' and split_part(name,'/',1) = auth.uid()::text);

-- ============================================================
-- 完成。预期：public schema 下 profiles/glossary/factory_profiles/jobs 四表
-- + storage.buckets 里 uploads/outputs 两个私有桶 + 各自 RLS 策略。
-- ============================================================

create extension if not exists pgcrypto;

create table if not exists public.users (
  id uuid primary key default gen_random_uuid(), full_name text not null, education text not null,
  email text not null, user_type text not null, created_at timestamptz not null default now()
);
create table if not exists public.services (
  service_id text primary key, name text not null, active boolean not null default true,
  windows integer[] not null, updated_at timestamptz, updated_by uuid
);
insert into public.services(service_id,name,active,windows) values
 ('enrollment','Enrollment',true,array[1,2]),('payment','Payment',true,array[3,4]),
 ('form137','Form 137',true,array[1]),('sf9','SF9',true,array[1]),('other','Other',true,array[1,2,3,4])
on conflict(service_id) do nothing;
create table if not exists public.staff (
  staff_id uuid primary key references auth.users(id) on delete cascade, name text not null default '',
  email text not null default '', role text not null check(role in ('staff','system_admin','disabled')),
  active boolean not null default true, updated_at timestamptz not null default now()
);
create table if not exists public.queues (
  id uuid primary key default gen_random_uuid(), queue_number text not null, queue_sequence integer not null,
  user_id uuid not null references public.users(id), full_name text not null, education text not null,
  email text not null, service text not null, service_key text not null references public.services(service_id),
  service_window integer not null, status text not null check(status in ('Waiting','Serving','Completed')),
  date_key date not null, created_at timestamptz not null default now(), service_time timestamptz,
  completion_time timestamptz, called_by uuid references auth.users(id), access_hash text not null
);
create index if not exists queues_day_created_idx on public.queues(date_key,created_at,id);
create index if not exists queues_lookup_idx on public.queues(queue_number);
create table if not exists public.queue_public (
  id uuid primary key references public.queues(id) on delete cascade, queue_number text not null,
  service text not null, service_window integer not null, status text not null,
  created_at timestamptz not null, date_key date not null
);
create index if not exists queue_public_day_created_idx on public.queue_public(date_key,created_at desc);
create table if not exists public.counters (
  date_key date not null, service_key text not null references public.services(service_id), sequence integer not null default 0,
  window_sequence integer not null default 0, primary key(date_key,service_key)
);
create table if not exists public.transactions (
  transaction_id uuid primary key references public.queues(id) on delete cascade, queue_id uuid not null,
  queue_number text not null, service text not null, service_window integer not null, status text not null,
  created_at timestamptz not null, service_time timestamptz, completion_time timestamptz, date_key date not null
);
create table if not exists public.audit_logs (
  id uuid primary key default gen_random_uuid(), staff_uid uuid references auth.users(id), role text not null,
  action text not null, record_id text not null default '', detail jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
create table if not exists public.notifications (
  notification_id text primary key, queue_id uuid not null references public.queues(id), queue_number text not null,
  email text not null, type text not null, status text not null default 'Pending', attempts integer not null default 0,
  created_at timestamptz not null default now(), delivered_at timestamptz, last_error text
);

-- Keep private records behind the server-only service role. Public clients receive
-- read access only to the non-personal queue projection below.
revoke all on all tables in schema public from anon,authenticated;
grant all on all tables in schema public to service_role;

create or replace function public.register_queue(p_full_name text,p_education text,p_email text,p_service text,p_access_hash text)
returns jsonb language plpgsql security definer set search_path=public as $$
declare svc services%rowtype; day date := (now() at time zone 'Asia/Manila')::date; seq integer; wseq integer; ticket_window integer; q queues%rowtype; u users%rowtype; prefix text;
begin
  select * into svc from services where name=p_service for share;
  if not found or not svc.active then raise exception 'This service is currently unavailable.'; end if;
  if coalesce(array_length(svc.windows,1),0)=0 then raise exception 'No service window is configured.'; end if;
  insert into counters(date_key,service_key) values(day,svc.service_id) on conflict do nothing;
  update counters set sequence=sequence+1, window_sequence=window_sequence+1 where date_key=day and service_key=svc.service_id returning sequence,window_sequence into seq,wseq;
  ticket_window := svc.windows[((wseq-1) % array_length(svc.windows,1))+1];
  prefix := case svc.service_id when 'enrollment' then 'E' when 'payment' then 'P' when 'form137' then 'F' when 'sf9' then 'S' else 'O' end;
  insert into users(full_name,education,email,user_type) values(p_full_name,p_education,lower(p_email),case when p_education in ('Faculty / Staff','Visitor') then p_education else 'Student' end) returning * into u;
  insert into queues(queue_number,queue_sequence,user_id,full_name,education,email,service,service_key,service_window,status,date_key,access_hash)
  values(prefix||lpad(seq::text,3,'0'),seq,u.id,p_full_name,p_education,lower(p_email),p_service,svc.service_id,ticket_window,'Waiting',day,p_access_hash) returning * into q;
  insert into queue_public(id,queue_number,service,service_window,status,created_at,date_key) values(q.id,q.queue_number,q.service,q.service_window,q.status,q.created_at,q.date_key);
  insert into transactions(transaction_id,queue_id,queue_number,service,service_window,status,created_at,date_key) values(q.id,q.id,q.queue_number,q.service,q.service_window,q.status,q.created_at,q.date_key);
  return jsonb_build_object('queueId',q.id,'queueNumber',q.queue_number,'service',q.service,'window',q.service_window,'status',q.status);
end $$;

create or replace function public.transition_queue(p_action text,p_queue_id uuid default null,p_window integer default null,p_staff_uid uuid default null)
returns jsonb language plpgsql security definer set search_path=public as $$
declare q queues%rowtype; new_status text; done_at timestamptz;
begin
  if p_action='callNext' then
    select * into q from queues where date_key=(now() at time zone 'Asia/Manila')::date and status='Waiting' and (p_window is null or service_window=p_window) order by created_at,id for update skip locked limit 1;
    if not found then raise exception 'There is no waiting queue for that window.'; end if;
    update queues set status='Serving',service_time=now(),called_by=p_staff_uid where id=q.id returning * into q;
  else
    select * into q from queues where id=p_queue_id for update;
    if not found then raise exception 'Queue record not found.'; end if;
    if q.status<>'Serving' then raise exception 'Only a serving queue can be completed or returned.'; end if;
    new_status:=case when p_action='complete' then 'Completed' else 'Waiting' end;
    done_at:=case when p_action='complete' then now() else null end;
    update queues set status=new_status,completion_time=done_at where id=q.id returning * into q;
  end if;
  update queue_public set status=q.status where id=q.id;
  insert into transactions(transaction_id,queue_id,queue_number,service,service_window,status,created_at,service_time,completion_time,date_key)
    values(q.id,q.id,q.queue_number,q.service,q.service_window,q.status,q.created_at,q.service_time,q.completion_time,q.date_key)
  on conflict(transaction_id) do update set status=excluded.status,service_time=excluded.service_time,completion_time=excluded.completion_time;
  return to_jsonb(q)-'access_hash';
end $$;

alter table public.users enable row level security; alter table public.services enable row level security;
alter table public.staff enable row level security; alter table public.queues enable row level security;
alter table public.queue_public enable row level security; alter table public.counters enable row level security;
alter table public.transactions enable row level security; alter table public.audit_logs enable row level security;
alter table public.notifications enable row level security;
create policy "public queue display read" on public.queue_public for select to anon,authenticated using (true);
grant select on public.queue_public to anon,authenticated;
revoke all on function public.register_queue(text,text,text,text,text) from public,anon,authenticated;
revoke all on function public.transition_queue(text,uuid,integer,uuid) from public,anon,authenticated;
grant execute on function public.register_queue(text,text,text,text,text) to service_role;
grant execute on function public.transition_queue(text,uuid,integer,uuid) to service_role;
alter publication supabase_realtime add table public.queue_public;

-- Phase 3: public-access hardening, durable quotas, idempotent analytics,
-- controlled writes and 30-day raw-content retention.
-- Apply while PIPPA is private, after the Phase 1 privacy migration. The
-- administrator Insights setup may be applied before or after this migration.

begin;

alter table public.conversations
    add column if not exists request_id uuid;

alter table public.conversations
    drop constraint if exists conversations_question_check;
alter table public.conversations
    add constraint conversations_question_check
    check (char_length(btrim(question)) between 1 and 4000);

create unique index if not exists conversations_user_request_idx
    on public.conversations (user_id, request_id)
    where request_id is not null;
create index if not exists conversations_retention_idx
    on public.conversations (created_at);

create table if not exists public.pippa_server_config (
    singleton boolean primary key default true check (singleton),
    write_secret_hash text not null check (write_secret_hash ~ '^[0-9a-f]{64}$'),
    updated_at timestamptz not null default now()
);

create table if not exists public.pippa_sign_in_requests (
    id uuid primary key default gen_random_uuid(),
    email_key text not null check (email_key ~ '^[0-9a-f]{64}$'),
    request_id uuid not null unique,
    created_at timestamptz not null default now()
);

create index if not exists pippa_sign_in_requests_email_created_idx
    on public.pippa_sign_in_requests (email_key, created_at desc);
create index if not exists pippa_sign_in_requests_created_idx
    on public.pippa_sign_in_requests (created_at desc);

create table if not exists public.pippa_question_permits (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    request_id uuid not null,
    created_at timestamptz not null default now(),
    consumed_at timestamptz,
    conversation_id uuid references public.conversations(id) on delete set null,
    unique (user_id, request_id)
);

create index if not exists pippa_question_permits_user_created_idx
    on public.pippa_question_permits (user_id, created_at desc);
create index if not exists pippa_question_permits_created_idx
    on public.pippa_question_permits (created_at desc);

create table if not exists public.pippa_usage_events (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    created_at timestamptz not null default now(),
    event_type text not null check (event_type in ('app_opened', 'question_asked')),
    policy_area text,
    answer_status text check (answer_status in ('complete', 'partial', 'unavailable')),
    conversation_id uuid references public.conversations(id) on delete set null,
    idempotency_key uuid
);

alter table public.pippa_usage_events
    add column if not exists idempotency_key uuid;

create unique index if not exists pippa_usage_events_user_type_idempotency_idx
    on public.pippa_usage_events (user_id, event_type, idempotency_key)
    where idempotency_key is not null;
create index if not exists pippa_usage_events_retention_idx
    on public.pippa_usage_events (created_at);

-- Reviewer actions contain no employee question or answer. Retain them after
-- raw conversation deletion, then remove them with other audit metadata at 90 days.
alter table public.pippa_review_actions
    alter column conversation_id drop not null;
alter table public.pippa_review_actions
    drop constraint if exists pippa_review_actions_conversation_id_fkey;
alter table public.pippa_review_actions
    add constraint pippa_review_actions_conversation_id_fkey
    foreign key (conversation_id) references public.conversations(id) on delete set null;
create index if not exists pippa_review_actions_retention_idx
    on public.pippa_review_actions (created_at);

alter table public.pippa_server_config enable row level security;
alter table public.pippa_server_config force row level security;
alter table public.pippa_sign_in_requests enable row level security;
alter table public.pippa_sign_in_requests force row level security;
alter table public.pippa_question_permits enable row level security;
alter table public.pippa_question_permits force row level security;

revoke all on table public.pippa_server_config from anon, authenticated;
revoke all on table public.pippa_sign_in_requests from anon, authenticated;
revoke all on table public.pippa_question_permits from anon, authenticated;
revoke all on table public.pippa_usage_events from anon, authenticated;
grant select on table public.pippa_usage_events to authenticated;

-- Earlier setup granted authenticated clients a direct insert route. Phase 3
-- saves only through pippa_save_conversation so quota authorization, input
-- validation and analytics remain one atomic operation.
revoke insert on table public.conversations from authenticated;
revoke insert (user_id, question, answer, mode, source_ids, answer_status, policy_area, recommended_owner)
    on table public.conversations from authenticated;
drop policy if exists "Users can insert their own conversations" on public.conversations;
drop policy if exists "Users insert own usage events" on public.pippa_usage_events;

create or replace function public.pippa_assert_app_secret(p_app_secret text)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
    expected_hash text;
begin
    select c.write_secret_hash into expected_hash
    from public.pippa_server_config c
    where c.singleton = true;

    if expected_hash is null
       or char_length(coalesce(p_app_secret, '')) < 32
       or pg_catalog.encode(
           pg_catalog.sha256(pg_catalog.convert_to(p_app_secret, 'UTF8')),
           'hex'
       ) <> expected_hash then
        raise exception using errcode = '42501', message = 'PIPPA_APP_AUTH_REQUIRED';
    end if;
end;
$$;

create or replace function public.pippa_delete_expired_data()
returns void
language plpgsql
security definer
set search_path = ''
as $$
begin
    delete from public.conversations
    where created_at < now() - interval '30 days';

    delete from public.pippa_usage_events
    where created_at < now() - interval '90 days';

    delete from public.pippa_review_actions
    where created_at < now() - interval '90 days';

    delete from public.pippa_question_permits
    where created_at < now() - interval '24 hours';

    delete from public.pippa_sign_in_requests
    where created_at < now() - interval '24 hours';
end;
$$;

create or replace function public.pippa_authorize_sign_in(
    p_email_key text,
    p_request_id uuid,
    p_app_secret text
)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
    most_recent timestamptz;
begin
    perform public.pippa_assert_app_secret(p_app_secret);
    if p_request_id is null or p_email_key is null or p_email_key !~ '^[0-9a-f]{64}$' then
        raise exception using errcode = '22023', message = 'PIPPA_SIGN_IN_REQUEST_INVALID';
    end if;

    perform pg_catalog.pg_advisory_xact_lock(73492001);
    if exists (
        select 1 from public.pippa_sign_in_requests where request_id = p_request_id
    ) then
        return;
    end if;

    select max(created_at) into most_recent
    from public.pippa_sign_in_requests
    where email_key = p_email_key;

    if most_recent > now() - interval '60 seconds' then
        raise exception using errcode = 'P0001', message = 'PIPPA_AUTH_RESEND';
    end if;
    if (select count(*) from public.pippa_sign_in_requests
        where email_key = p_email_key and created_at >= now() - interval '1 hour') >= 3 then
        raise exception using errcode = 'P0001', message = 'PIPPA_AUTH_ADDRESS_HOUR';
    end if;
    if (select count(*) from public.pippa_sign_in_requests
        where email_key = p_email_key and created_at >= now() - interval '24 hours') >= 10 then
        raise exception using errcode = 'P0001', message = 'PIPPA_AUTH_ADDRESS_DAY';
    end if;
    if (select count(*) from public.pippa_sign_in_requests
        where created_at >= now() - interval '1 hour') >= 300 then
        raise exception using errcode = 'P0001', message = 'PIPPA_AUTH_GLOBAL_HOUR';
    end if;

    insert into public.pippa_sign_in_requests (email_key, request_id)
    values (p_email_key, p_request_id);
end;
$$;

create or replace function public.pippa_authorize_question(
    p_request_id uuid,
    p_app_secret text
)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
    caller_id uuid := (select auth.uid());
begin
    perform public.pippa_assert_app_secret(p_app_secret);
    if caller_id is null then
        raise exception using errcode = '42501', message = 'Authentication is required';
    end if;
    if p_request_id is null then
        raise exception using errcode = '22023', message = 'PIPPA_REQUEST_ID_REQUIRED';
    end if;

    perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(caller_id::text, 0));
    if exists (
        select 1 from public.pippa_question_permits
        where user_id = caller_id and request_id = p_request_id
    ) then
        return;
    end if;

    if (select count(*) from public.pippa_question_permits
        where user_id = caller_id and created_at >= now() - interval '1 minute') >= 10 then
        raise exception using errcode = 'P0001', message = 'PIPPA_QUOTA_MINUTE';
    end if;
    if (select count(*) from public.pippa_question_permits
        where user_id = caller_id and created_at >= now() - interval '1 hour') >= 60 then
        raise exception using errcode = 'P0001', message = 'PIPPA_QUOTA_HOUR';
    end if;
    if (select count(*) from public.pippa_question_permits
        where user_id = caller_id and created_at >= now() - interval '24 hours') >= 200 then
        raise exception using errcode = 'P0001', message = 'PIPPA_QUOTA_DAY';
    end if;

    insert into public.pippa_question_permits (user_id, request_id)
    values (caller_id, p_request_id);
end;
$$;

drop function if exists public.pippa_save_conversation(text, text, text, text[], text, text, text);
create or replace function public.pippa_save_conversation(
    p_question text,
    p_answer text,
    p_mode text,
    p_source_ids text[],
    p_answer_status text,
    p_policy_area text,
    p_recommended_owner text,
    p_request_id uuid,
    p_app_secret text
)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
    caller_id uuid := (select auth.uid());
    saved_id uuid;
    permit_id uuid;
    permit_conversation_id uuid;
begin
    perform public.pippa_assert_app_secret(p_app_secret);
    if caller_id is null then
        raise exception using errcode = '42501', message = 'Authentication is required';
    end if;
    if p_request_id is null then
        raise exception using errcode = '22023', message = 'PIPPA_REQUEST_ID_REQUIRED';
    end if;

    select c.id into saved_id
    from public.conversations c
    where c.user_id = caller_id and c.request_id = p_request_id;
    if saved_id is not null then
        return saved_id;
    end if;

    if char_length(btrim(coalesce(p_question, ''))) not between 1 and 4000
       or char_length(coalesce(p_answer, '')) not between 1 and 50000
       or p_mode not in ('Evidence complete', 'Guardrail · partial evidence', 'Guardrail · unavailable')
       or p_answer_status not in ('complete', 'partial', 'unavailable')
       or char_length(coalesce(p_policy_area, '')) > 200
       or char_length(coalesce(p_recommended_owner, '')) > 300
       or coalesce(cardinality(p_source_ids), 0) > 12
       or exists (
           select 1 from unnest(coalesce(p_source_ids, '{}')) source_id
           where source_id !~ '^[A-Z][A-Z0-9]{1,3}-[0-9]{3}-[0-9]+[.][0-9]+$'
       ) then
        raise exception using errcode = '22023', message = 'PIPPA_CONVERSATION_INVALID';
    end if;

    select p.id, p.conversation_id into permit_id, permit_conversation_id
    from public.pippa_question_permits p
    where p.user_id = caller_id and p.request_id = p_request_id
    for update;
    if permit_id is null then
        raise exception using errcode = '42501', message = 'PIPPA_QUESTION_PERMIT_REQUIRED';
    end if;
    if permit_conversation_id is not null then
        return permit_conversation_id;
    end if;

    insert into public.conversations (
        user_id, question, answer, mode, source_ids, answer_status,
        policy_area, recommended_owner, request_id
    ) values (
        caller_id, btrim(p_question), p_answer, p_mode, coalesce(p_source_ids, '{}'),
        p_answer_status, nullif(p_policy_area, ''), nullif(p_recommended_owner, ''),
        p_request_id
    ) returning id into saved_id;

    update public.pippa_question_permits
    set consumed_at = now(), conversation_id = saved_id
    where id = permit_id;

    insert into public.pippa_usage_events (
        user_id, event_type, policy_area, answer_status,
        conversation_id, idempotency_key
    ) values (
        caller_id, 'question_asked', nullif(p_policy_area, ''),
        p_answer_status, saved_id, p_request_id
    ) on conflict (user_id, event_type, idempotency_key)
      where idempotency_key is not null do nothing;

    return saved_id;
end;
$$;

create or replace function public.pippa_record_app_open(
    p_idempotency_key uuid,
    p_app_secret text
)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
    caller_id uuid := (select auth.uid());
begin
    perform public.pippa_assert_app_secret(p_app_secret);
    if caller_id is null then
        raise exception using errcode = '42501', message = 'Authentication is required';
    end if;
    if p_idempotency_key is null then
        raise exception using errcode = '22023', message = 'PIPPA_REQUEST_ID_REQUIRED';
    end if;

    insert into public.pippa_usage_events (
        user_id, event_type, idempotency_key
    ) values (
        caller_id, 'app_opened', p_idempotency_key
    ) on conflict (user_id, event_type, idempotency_key)
      where idempotency_key is not null do nothing;
end;
$$;

create or replace function public.pippa_my_history(p_limit integer default 20)
returns table (
    id uuid, created_at timestamptz, question text, answer text,
    mode text, source_ids text[], feedback text
)
language sql
stable
security definer
set search_path = ''
as $$
    select c.id, c.created_at, c.question, c.answer, c.mode, c.source_ids, c.feedback
    from public.conversations c
    where c.user_id = (select auth.uid())
      and c.created_at >= now() - interval '30 days'
    order by c.created_at desc
    limit least(greatest(coalesce(p_limit, 20), 1), 100);
$$;

create or replace function public.pippa_export_my_history()
returns table (
    id uuid, created_at timestamptz, question text, answer text,
    mode text, source_ids text[], feedback text
)
language sql
stable
security definer
set search_path = ''
as $$
    select c.id, c.created_at, c.question, c.answer, c.mode, c.source_ids, c.feedback
    from public.conversations c
    where c.user_id = (select auth.uid())
      and c.created_at >= now() - interval '30 days'
    order by c.created_at desc;
$$;

create or replace function public.pippa_delete_my_history()
returns integer
language plpgsql
security definer
set search_path = ''
as $$
declare
    deleted_count integer;
begin
    if (select auth.uid()) is null then
        raise exception using errcode = '42501', message = 'Authentication is required';
    end if;
    delete from public.conversations where user_id = (select auth.uid());
    get diagnostics deleted_count = row_count;
    return deleted_count;
end;
$$;

revoke all on function public.pippa_assert_app_secret(text) from public;
revoke all on function public.pippa_delete_expired_data() from public;
revoke all on function public.pippa_authorize_sign_in(text, uuid, text) from public;
revoke all on function public.pippa_authorize_question(uuid, text) from public;
revoke all on function public.pippa_save_conversation(text, text, text, text[], text, text, text, uuid, text) from public;
revoke all on function public.pippa_record_app_open(uuid, text) from public;
revoke all on function public.pippa_my_history(integer) from public;
revoke all on function public.pippa_export_my_history() from public;
revoke all on function public.pippa_delete_my_history() from public;

grant execute on function public.pippa_authorize_sign_in(text, uuid, text) to anon, authenticated;
grant execute on function public.pippa_authorize_question(uuid, text) to authenticated;
grant execute on function public.pippa_save_conversation(text, text, text, text[], text, text, text, uuid, text) to authenticated;
grant execute on function public.pippa_record_app_open(uuid, text) to authenticated;
grant execute on function public.pippa_my_history(integer) to authenticated;
grant execute on function public.pippa_export_my_history() to authenticated;
grant execute on function public.pippa_delete_my_history() to authenticated;

-- pg_cron must be enabled before this migration. The block is idempotent and
-- replaces only PIPPA's own daily retention job.
do $$
declare
    existing_job bigint;
begin
    if not exists (select 1 from pg_catalog.pg_extension where extname = 'pg_cron') then
        raise exception 'Enable the Supabase Cron integration before applying Phase 3';
    end if;
    select jobid into existing_job from cron.job where jobname = 'pippa-retention-daily';
    if existing_job is not null then
        perform cron.unschedule(existing_job);
    end if;
    perform cron.schedule(
        'pippa-retention-daily',
        '17 2 * * *',
        'select public.pippa_delete_expired_data()'
    );
end;
$$;

comment on table public.pippa_sign_in_requests is
    'HMAC-normalized sign-in request counters retained for 24 hours; no email addresses.';
comment on table public.pippa_question_permits is
    'Atomic per-user quota permits. Successful conversation saves consume a permit.';
comment on function public.pippa_delete_my_history() is
    'Deletes only the authenticated user''s retained question and answer content.';

commit;

-- After committing, store the same PIPPA_RATE_LIMIT_SECRET configured in the
-- Streamlit deployment. Replace the placeholder and run this statement once in
-- the Supabase SQL Editor; never commit the real secret.
-- insert into public.pippa_server_config (singleton, write_secret_hash)
-- values (true, encode(sha256(convert_to('REPLACE_WITH_THE_REAL_SECRET', 'UTF8')), 'hex'))
-- on conflict (singleton) do update
-- set write_secret_hash = excluded.write_secret_hash, updated_at = now();

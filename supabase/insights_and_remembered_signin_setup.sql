-- PIPPA administrator Insights setup
-- Run this only after schema.sql and governance_reviewer_setup.sql. This file
-- is also safe to apply after the Phase 3 public-hardening migration: it does
-- not restore any direct client write route.
-- It preserves employee privacy: ordinary users can read only their own
-- activity events, controlled Phase 3 functions create events, and only an
-- explicitly assigned administrator can retrieve aggregated, named data.

create table if not exists public.pippa_usage_events (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    created_at timestamptz not null default now(),
    event_type text not null check (event_type in ('app_opened', 'question_asked')),
    policy_area text,
    answer_status text check (answer_status in ('complete', 'partial', 'unavailable')),
    conversation_id uuid references public.conversations(id) on delete set null
);

create index if not exists pippa_usage_events_user_created_idx
    on public.pippa_usage_events (user_id, created_at desc);
create index if not exists pippa_usage_events_type_created_idx
    on public.pippa_usage_events (event_type, created_at desc);

-- Conversations are written only through the controlled save function. Keep
-- both the original and expanded direct-insert grants closed.
revoke insert on table public.conversations from authenticated;
revoke insert (user_id, question, answer, mode, source_ids, answer_status, policy_area, recommended_owner)
    on table public.conversations from authenticated;
drop policy if exists "Users can insert their own conversations" on public.conversations;

alter table public.pippa_usage_events enable row level security;
alter table public.pippa_usage_events force row level security;
revoke all on table public.pippa_usage_events from anon;
revoke all on table public.pippa_usage_events from authenticated;
grant select on table public.pippa_usage_events to authenticated;

drop policy if exists "Users read own usage events" on public.pippa_usage_events;
create policy "Users read own usage events"
    on public.pippa_usage_events
    for select to authenticated
    using ((select auth.uid()) = user_id);

drop policy if exists "Users insert own usage events" on public.pippa_usage_events;

create or replace function public.is_pippa_administrator()
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select exists (
        select 1 from public.pippa_reviewers
        where user_id = (select auth.uid()) and role = 'administrator'
    );
$$;

revoke all on function public.is_pippa_administrator() from public;
grant execute on function public.is_pippa_administrator() to authenticated;

-- This function is intentionally the only administrator route to employee
-- identity data. It returns engagement metadata, never question or answer text.
create or replace function public.pippa_admin_usage_summary()
returns table (
    email text,
    first_active timestamptz,
    last_active timestamptz,
    app_opens bigint,
    questions bigint,
    needs_attention bigint,
    flagged_for_review bigint
)
language plpgsql
security definer
set search_path = ''
as $$
begin
    if not public.is_pippa_administrator() then
        raise exception 'PIPPA administrator access is required';
    end if;

    return query
    with usage_by_user as (
        select
            e.user_id,
            min(e.created_at) as first_active,
            max(e.created_at) as last_active,
            count(*) filter (where e.event_type = 'app_opened')::bigint as app_opens,
            count(*) filter (where e.event_type = 'question_asked')::bigint as questions,
            count(*) filter (where e.event_type = 'question_asked' and e.answer_status in ('partial', 'unavailable'))::bigint as needs_attention
        from public.pippa_usage_events e
        group by e.user_id
    ), flagged as (
        select c.user_id, count(*)::bigint as flagged_for_review
        from public.conversations c
        where c.feedback = 'needs_review'
        group by c.user_id
    )
    select
        u.email::text,
        activity.first_active,
        activity.last_active,
        activity.app_opens,
        activity.questions,
        activity.needs_attention,
        coalesce(f.flagged_for_review, 0)::bigint
    from usage_by_user activity
    join auth.users u on u.id = activity.user_id
    left join flagged f on f.user_id = activity.user_id
    order by activity.last_active desc;
end;
$$;

create or replace function public.pippa_admin_policy_usage()
returns table (
    policy_area text,
    questions bigint,
    evidence_complete bigint,
    needs_attention bigint
)
language plpgsql
security definer
set search_path = ''
as $$
begin
    if not public.is_pippa_administrator() then
        raise exception 'PIPPA administrator access is required';
    end if;

    return query
    select
        coalesce(nullif(e.policy_area, ''), 'Unclassified')::text,
        count(*)::bigint,
        count(*) filter (where e.answer_status = 'complete')::bigint,
        count(*) filter (where e.answer_status in ('partial', 'unavailable'))::bigint
    from public.pippa_usage_events e
    where e.event_type = 'question_asked'
    group by coalesce(nullif(e.policy_area, ''), 'Unclassified')
    order by count(*) desc, 1;
end;
$$;

revoke all on function public.pippa_admin_usage_summary() from public;
revoke all on function public.pippa_admin_policy_usage() from public;
grant execute on function public.pippa_admin_usage_summary() to authenticated;
grant execute on function public.pippa_admin_policy_usage() to authenticated;

-- After the administrator has signed in to PIPPA at least once, replace the
-- placeholder and run this one statement. Administrator includes reviewer
-- queue access; do not grant this role casually.
-- insert into public.pippa_reviewers (user_id, role)
-- select id, 'administrator' from auth.users where lower(email) = lower('administrator@example.com')
-- on conflict (user_id) do update set role = excluded.role;

-- Upgrade an existing PIPPA database to the protected Phase 1 access model.
-- Apply while PIPPA is private, after backing up and checking the live schema.

begin;

alter table public.conversations
    add column if not exists answer_status text check (answer_status in ('complete', 'partial', 'unavailable')),
    add column if not exists policy_area text,
    add column if not exists recommended_owner text,
    add column if not exists review_status text not null default 'new'
        check (review_status in ('new', 'in_review', 'resolved')),
    add column if not exists reviewed_at timestamptz;

create index if not exists conversations_review_queue_idx
    on public.conversations (review_status, created_at desc);

create table if not exists public.pippa_reviewers (
    user_id uuid primary key references auth.users(id) on delete cascade,
    role text not null default 'reviewer' check (role in ('reviewer', 'administrator')),
    created_at timestamptz not null default now()
);

create table if not exists public.pippa_review_actions (
    id bigint generated always as identity primary key,
    conversation_id uuid not null references public.conversations(id) on delete cascade,
    reviewer_user_id uuid not null references auth.users(id) on delete restrict,
    previous_status text not null check (previous_status in ('new', 'in_review', 'resolved')),
    new_status text not null check (new_status in ('new', 'in_review', 'resolved')),
    created_at timestamptz not null default now(),
    constraint pippa_review_action_changes_status check (previous_status <> new_status)
);

create index if not exists pippa_review_actions_conversation_created_idx
    on public.pippa_review_actions (conversation_id, created_at desc);

alter table public.pippa_reviewers enable row level security;
alter table public.pippa_reviewers force row level security;
alter table public.pippa_review_actions enable row level security;
alter table public.pippa_review_actions force row level security;
revoke all on table public.pippa_reviewers from anon, authenticated;
revoke all on table public.pippa_review_actions from anon, authenticated;
grant select on table public.pippa_reviewers to authenticated;

drop policy if exists "Reviewers can see their own assignment" on public.pippa_reviewers;
create policy "Reviewers can see their own assignment"
    on public.pippa_reviewers for select to authenticated
    using ((select auth.uid()) = user_id);

create or replace function public.is_pippa_reviewer()
returns boolean language sql stable security definer set search_path = '' as $$
    select exists (
        select 1 from public.pippa_reviewers
        where user_id = (select auth.uid())
    );
$$;

create or replace function public.pippa_save_conversation(
    p_question text, p_answer text, p_mode text, p_source_ids text[],
    p_answer_status text, p_policy_area text, p_recommended_owner text
)
returns uuid language plpgsql security definer set search_path = '' as $$
declare
    caller_id uuid := (select auth.uid());
    saved_id uuid;
begin
    if caller_id is null then
        raise exception using errcode = '42501', message = 'Authentication is required';
    end if;
    insert into public.conversations (
        user_id, question, answer, mode, source_ids,
        answer_status, policy_area, recommended_owner
    ) values (
        caller_id, p_question, p_answer, p_mode, coalesce(p_source_ids, '{}'),
        coalesce(p_answer_status, 'complete'), nullif(p_policy_area, ''),
        nullif(p_recommended_owner, '')
    ) returning id into saved_id;
    return saved_id;
end;
$$;

create or replace function public.pippa_my_history(p_limit integer default 20)
returns table (
    id uuid, created_at timestamptz, question text, answer text,
    mode text, source_ids text[], feedback text
)
language sql stable security definer set search_path = '' as $$
    select c.id, c.created_at, c.question, c.answer, c.mode, c.source_ids, c.feedback
    from public.conversations c
    where c.user_id = (select auth.uid())
    order by c.created_at desc
    limit least(greatest(coalesce(p_limit, 20), 1), 100);
$$;

create or replace function public.pippa_set_my_feedback(p_conversation_id uuid, p_feedback text)
returns void language plpgsql security definer set search_path = '' as $$
begin
    if p_feedback is null or p_feedback not in ('helpful', 'needs_review') then
        raise exception using errcode = '22023', message = 'Unsupported feedback value';
    end if;
    update public.conversations
    set feedback = p_feedback, feedback_at = now()
    where id = p_conversation_id and user_id = (select auth.uid());
    if not found then
        raise exception using errcode = '42501', message = 'Conversation not found or not owned by caller';
    end if;
end;
$$;

create or replace function public.pippa_reviewer_queue(p_limit integer default 100)
returns table (
    id uuid, created_at timestamptz, question text, mode text, source_ids text[],
    feedback text, answer_status text, policy_area text,
    recommended_owner text, review_status text
)
language plpgsql stable security definer set search_path = '' as $$
begin
    if not public.is_pippa_reviewer() then
        raise exception using errcode = '42501', message = 'PIPPA reviewer access is required';
    end if;
    return query
    select c.id, c.created_at, c.question, c.mode, c.source_ids, c.feedback,
           c.answer_status, c.policy_area, c.recommended_owner, c.review_status
    from public.conversations c
    where c.review_status in ('new', 'in_review')
      and (c.feedback = 'needs_review' or c.answer_status in ('partial', 'unavailable'))
    order by c.created_at desc
    limit least(greatest(coalesce(p_limit, 100), 1), 100);
end;
$$;

create or replace function public.pippa_transition_review(p_conversation_id uuid, p_new_status text)
returns void language plpgsql security definer set search_path = '' as $$
declare
    caller_id uuid := (select auth.uid());
    prior_status text;
begin
    if not public.is_pippa_reviewer() then
        raise exception using errcode = '42501', message = 'PIPPA reviewer access is required';
    end if;
    if p_new_status is null or p_new_status not in ('in_review', 'resolved') then
        raise exception using errcode = '22023', message = 'Unsupported review status';
    end if;
    select c.review_status into prior_status
    from public.conversations c
    where c.id = p_conversation_id
      and (c.feedback = 'needs_review' or c.answer_status in ('partial', 'unavailable'))
    for update;
    if not found then
        raise exception using errcode = '42501', message = 'Review item not found or not actionable';
    end if;
    if prior_status = p_new_status then
        return;
    end if;
    if not (
        (prior_status = 'new' and p_new_status in ('in_review', 'resolved'))
        or (prior_status = 'in_review' and p_new_status = 'resolved')
    ) then
        raise exception using errcode = '22023', message = 'Unsupported review status transition';
    end if;
    update public.conversations
    set review_status = p_new_status, reviewed_at = now()
    where id = p_conversation_id;
    insert into public.pippa_review_actions (
        conversation_id, reviewer_user_id, previous_status, new_status
    ) values (p_conversation_id, caller_id, prior_status, p_new_status);
end;
$$;

revoke all on table public.conversations from anon, authenticated;

drop policy if exists "Users read own; reviewers read actionable items" on public.conversations;
drop policy if exists "Assigned reviewers can update review status" on public.conversations;
drop policy if exists "Users can read their own conversations" on public.conversations;
create policy "Users can read their own conversations"
    on public.conversations for select to authenticated
    using ((select auth.uid()) is not null and (select auth.uid()) = user_id);

drop policy if exists "Users can update feedback on their own conversations" on public.conversations;
create policy "Users can update feedback on their own conversations"
    on public.conversations for update to authenticated
    using ((select auth.uid()) is not null and (select auth.uid()) = user_id)
    with check ((select auth.uid()) is not null and (select auth.uid()) = user_id);

revoke all on function public.is_pippa_reviewer() from public;
revoke all on function public.pippa_save_conversation(text, text, text, text[], text, text, text) from public;
revoke all on function public.pippa_my_history(integer) from public;
revoke all on function public.pippa_set_my_feedback(uuid, text) from public;
revoke all on function public.pippa_reviewer_queue(integer) from public;
revoke all on function public.pippa_transition_review(uuid, text) from public;
grant execute on function public.is_pippa_reviewer() to authenticated;
grant execute on function public.pippa_save_conversation(text, text, text, text[], text, text, text) to authenticated;
grant execute on function public.pippa_my_history(integer) to authenticated;
grant execute on function public.pippa_set_my_feedback(uuid, text) to authenticated;
grant execute on function public.pippa_reviewer_queue(integer) to authenticated;
grant execute on function public.pippa_transition_review(uuid, text) to authenticated;

comment on table public.pippa_review_actions is
    'Append-only record of authorized PIPPA reviewer status changes.';

commit;


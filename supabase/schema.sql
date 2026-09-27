-- PIPPA v0.5: authenticated conversation history and feedback
-- Run this once in Supabase Dashboard > SQL Editor.

create extension if not exists pgcrypto;

create table if not exists public.conversations (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    created_at timestamptz not null default now(),
    question text not null check (char_length(question) between 1 and 5000),
    answer text not null check (char_length(answer) between 1 and 50000),
    mode text not null check (char_length(mode) between 1 and 120),
    source_ids text[] not null default '{}',
    feedback text check (feedback in ('helpful', 'needs_review')),
    feedback_at timestamptz,
    constraint feedback_timestamp_consistent check (
        (feedback is null and feedback_at is null)
        or (feedback is not null and feedback_at is not null)
    )
);

create index if not exists conversations_user_created_idx
    on public.conversations (user_id, created_at desc);

alter table public.conversations enable row level security;
alter table public.conversations force row level security;

revoke all on table public.conversations from anon;
revoke all on table public.conversations from authenticated;
grant select on table public.conversations to authenticated;
grant insert (user_id, question, answer, mode, source_ids)
    on table public.conversations to authenticated;
grant update (feedback, feedback_at)
    on table public.conversations to authenticated;

drop policy if exists "Users can read their own conversations" on public.conversations;
create policy "Users can read their own conversations"
    on public.conversations
    for select
    to authenticated
    using ((select auth.uid()) is not null and (select auth.uid()) = user_id);

drop policy if exists "Users can insert their own conversations" on public.conversations;
create policy "Users can insert their own conversations"
    on public.conversations
    for insert
    to authenticated
    with check ((select auth.uid()) is not null and (select auth.uid()) = user_id);

drop policy if exists "Users can update feedback on their own conversations" on public.conversations;
create policy "Users can update feedback on their own conversations"
    on public.conversations
    for update
    to authenticated
    using ((select auth.uid()) is not null and (select auth.uid()) = user_id)
    with check ((select auth.uid()) is not null and (select auth.uid()) = user_id);

comment on table public.conversations is
    'PIPPA employee questions, grounded answers, citations and user feedback. RLS restricts each user to their own rows.';

-- Apply before deploying the matching auth.py change. Requires Phase 3.
-- Reject an unexpired JWT whose session has been removed by sign-out.
-- No tokens or auth.sessions rows are exposed to clients.
begin;

create or replace function public.pippa_active_user_id()
returns uuid
language plpgsql stable security definer
set search_path = ''
as $$
declare
    caller_id uuid := auth.uid();
    session_id_text text := auth.jwt() ->> 'session_id';
begin
    if caller_id is null or session_id_text is null or not exists (
        select 1 from auth.sessions s
        where s.id::text = session_id_text and s.user_id = caller_id
          and (s.not_after is null or s.not_after > now())
    ) then
        raise exception using errcode = '42501', message = 'PIPPA_SESSION_REVOKED';
    end if;
    return caller_id;
end;
$$;
revoke all on function public.pippa_active_user_id() from public, anon;
grant execute on function public.pippa_active_user_id() to authenticated;

-- Preserve existing function bodies and permissions, replacing only their
-- identity primitive. Explicit allow-list prevents modifying unrelated code.
do $$
declare
    function_name text;
    definition text;
    function_count integer;
begin
    foreach function_name in array array[
        'pippa_authorize_question', 'pippa_save_conversation',
        'pippa_record_app_open', 'pippa_my_history', 'pippa_export_my_history',
        'pippa_delete_my_history', 'pippa_set_my_feedback',
        'pippa_reviewer_queue', 'pippa_transition_review',
        'is_pippa_reviewer', 'is_pippa_administrator'
    ] loop
        select count(*) into function_count from pg_catalog.pg_proc p
        join pg_catalog.pg_namespace n on n.oid=p.pronamespace
        where n.nspname='public' and p.proname=function_name;
        if function_count <> 1 then
            raise exception 'Expected exactly one function: %', function_name;
        end if;
        select pg_catalog.pg_get_functiondef(p.oid) into definition
        from pg_catalog.pg_proc p join pg_catalog.pg_namespace n on n.oid=p.pronamespace
        where n.nspname='public' and p.proname=function_name;
        if position('auth.uid()' in definition) > 0 then
            execute replace(definition, 'auth.uid()', 'public.pippa_active_user_id()');
        elsif position('public.pippa_active_user_id()' in definition) = 0
          and position('public.is_pippa_reviewer()' in definition) = 0 then
            raise exception 'Unrecognized authorization body: %', function_name;
        end if;
    end loop;
end;
$$;

-- SECURITY DEFINER RPCs above need their own check; table policies alone
-- cannot protect them. Restrictive policies also protect direct table routes.
drop policy if exists "PIPPA requires active session" on public.conversations;
create policy "PIPPA requires active session" on public.conversations
as restrictive for all to authenticated
using ((select public.pippa_active_user_id()) is not null)
with check ((select public.pippa_active_user_id()) is not null);
drop policy if exists "PIPPA requires active session" on public.pippa_reviewers;
create policy "PIPPA requires active session" on public.pippa_reviewers
as restrictive for all to authenticated
using ((select public.pippa_active_user_id()) is not null)
with check ((select public.pippa_active_user_id()) is not null);
drop policy if exists "PIPPA requires active session" on public.pippa_usage_events;
create policy "PIPPA requires active session" on public.pippa_usage_events
as restrictive for all to authenticated
using ((select public.pippa_active_user_id()) is not null)
with check ((select public.pippa_active_user_id()) is not null);

notify pgrst, 'reload schema';
commit;

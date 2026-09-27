# Backend source reference

This directory contains generic database source for PIPPA. It does not contain a production database, live role assignments, credentials, user activity, or private verification results. This document describes the included components; it is not an instruction to modify an existing deployment.

## Included components

- `schema.sql`: initial conversation schema and access controls.
- `governance_reviewer_setup.sql`: protected personal-history and reviewer functions.
- `insights_and_remembered_signin_setup.sql`: administrator activity summaries and supporting schema.
- `migrations/202609090001_phase1_employee_privacy.sql`: migration for existing installations requiring the first privacy changes.
- `migrations/202609100001_phase3_public_hardening.sql`: protected writes, durable quotas, idempotency, and retention.
- `migrations/202609160001_session_revocation.sql`: active-session enforcement.
- `magic_link_email.html`: generic email template using provider-supplied placeholders.

Some setup files and migrations represent different installation stages. Review them in an isolated environment before applying anything; they are not a script to run blindly in filename order.

## Configuration boundary

The placeholder names are in [`../.streamlit/secrets.example.toml`](../.streamlit/secrets.example.toml). Keep real configuration outside source control. The application uses a Supabase publishable key and protected server-side application settings. It must not receive a Supabase service-role key.

Verified deployments require the reviewed database controls, verified email authentication, CAPTCHA protection, email delivery, and the expected application-write secret. Keep local demonstration mode disabled in hosted environments. Use the exact deployment HTTPS address for authentication redirects.

## Role boundary

Users access their own retained history. Reviewers receive a limited queue without answer text or user identities. Administrators can view activity summaries without question or answer content. The commented example role-assignment statements use `example.com` placeholders; they do not assign anyone access to a deployed system.

Source publication does not change database policies, role membership, sharing settings, or stored records. Production setup decisions, private operational evidence, and live verification helpers are retained separately by the project owner.

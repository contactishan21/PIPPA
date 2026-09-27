# PIPPA

PIPPA is a personal showcase prototype of an employee policy and procedure assistant. It demonstrates how controlled knowledge, clear authority boundaries, and evidence can support the design of business transformation and AI consulting solutions.

The fictional Dune & Palm Commerce LLC library contains 76 current synthetic documents and 491 controlled clauses. The current application retrieves evidence and produces deterministic answers. It does not generate unrestricted model responses or require an AI API account. Its policies and answers must not be used for real operational decisions.

## Three outcomes

| Example question | Intended outcome |
| --- | --- |
| A customer wants to return a defective product after 38 days. What should I do? | A supported answer with relevant policy clauses. |
| Can sick leave and annual leave be combined? | Related evidence, with the unanswered part stated explicitly. |
| What is the warehouse stock count policy? | An insufficient-evidence response and a next step. |

Answers include plain-English guidance, source clauses, and document metadata when the evidence supports them. Retrieval excludes draft and superseded governance test material. The prototype demonstrates escalation; it does not replace accountable policy owners.

## What this source contains

- Application code, styles, and the fictional knowledge library.
- Deterministic retrieval, answer coverage checks, and guardrails.
- Authentication and storage implementations, generic database schema, and migrations.
- Placeholder configuration and reproducible synthetic tests.

Production credentials, user records, access statistics, review records, live verification tools, operational runbooks, and historical private test evidence are not part of this source distribution. The hosted deployment and its private data are managed separately.

## Run a local demonstration

Use Python 3.12.14. Production dependencies are pinned in `requirements.txt`; direct dependencies are recorded in `requirements.in`.

On Windows, install Python and double-click `Start PIPPA.bat`. The launcher creates or uses `.venv312` and binds the application to `127.0.0.1:8501`.

Alternatively, in PowerShell:

```powershell
py -3.12 -m venv .venv312
.\.venv312\Scripts\python.exe -m pip install -r requirements.txt
$env:PIPPA_LOCAL_DEMO = "true"
.\.venv312\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

Local demonstration sign-in does not verify email ownership. Use fictional inputs. The public source includes no working hosted credentials. Normal verified deployments fail closed when the required authentication configuration is missing. Never enable local demonstration mode on a publicly reachable deployment.

## Verified access and privacy

The optional hosted implementation uses Supabase verified email sign-in, Cloudflare Turnstile, protected database functions, row-level access controls, quotas, and session checks. See the [backend reference](supabase/README.md) for the source components.

The application implements 30-day question and answer retention with personal export and deletion. A designated reviewer can see questions that require review; the reviewer queue excludes answers and user identities. Administrator Insights contains named activity counts but excludes question and answer text. Non-content usage and review-action records have 90-day retention. These roles are assigned privately in the deployment; publishing source does not grant a role or expose its database records.

Do not enter real confidential, personal, or credential information into the showcase.

## Reproduce the synthetic checks

```powershell
.\.venv312\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv312\Scripts\python.exe -m pip check
.\.venv312\Scripts\python.exe -m unittest discover -s tests -q
.\.venv312\Scripts\python.exe tests/audit_answer_quality.py
.\.venv312\Scripts\python.exe tests/load_phase3.py
```

Generated reports go into the ignored `outputs/` directory. These tests cover synthetic scenarios and local application behavior. They do not establish the security configuration or capacity of a separate live deployment. The included CI workflow runs the same source tests without production secrets.

## Scope

This prototype has no banking or customer-account integration. Applying this approach to other organisations would require approved content, appropriate integrations, and deployment-specific validation. A public demo link will be added only after access has been verified and publication approved.

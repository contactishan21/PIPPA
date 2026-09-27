---
document_id: TEC-002
title: Master Data Governance and SKU Creation
company: Dune & Palm Commerce LLC
function: Technology & Data Governance
owner: Master Data Manager
status: CURRENT
version: 1.0
effective_date: 04 September 2026
source_type: Policy / SOP
retrieval_eligible: true
market: UAE
currency: AED
---

# TEC-002 — Master Data Governance and SKU Creation

> **SYNTHETIC DEMO CONTENT — This document, company, people, limits, vendors and procedures are fictional. It is designed only to test the PIPPA knowledge-assistant prototype and must not be used as legal, financial, safety or operational advice.**

## Control information

- **Owner:** Master Data Manager
- **Audience:** Applies to all updates made to the approved ERP and the approved inventory system databases.
- **Status:** CURRENT
- **Version:** 1.0
- **Effective:** 04 September 2026
- **Review due:** 01 March 2027

## When to use this document

How do I add a new product to the system?" / "What is the process for changing a vendor's bank details?

## Authoritative policy clauses

### TEC-002-4.1

> New SKU creation requires verified vendor specifications, tax coding, and Finance margin approval before the approved inventory system ingestion.

### TEC-002-4.2

> Vendor master data changes (e.g., banking or tax details) require a mandatory two-step verification, including documented verbal confirmation with the vendor's registered accounts department.

### TEC-002-4.3

> Authority to mass-update pricing hierarchies or category trees rests exclusively with the Commercial Operations Director.

### TEC-002-4.4

> Vendor bank-detail changes are governed exclusively by PRC-003, including independent callback to a pre-existing verified contact; this policy creates no parallel or weaker verification path.

### TEC-002-4.5

> The requester, verifier and publisher must be identifiable and segregated for bank, tax, pricing and hierarchy changes. No one person may request and approve the same sensitive change.

### TEC-002-4.6

> Every mass change requires a tested change file, before-and-after report, rollback plan and post-load reconciliation.

## Procedure

1. Confirm that the request falls within this policy's scope and identify the transaction, employee, vendor, asset or incident involved.
2. Collect the source records and calculate the complete value, time period and related transactions before choosing an approval band.
3. Apply the controlling clauses and all referenced policies; pause the process where safety, identity, custody, legality or evidence is unresolved.
4. Obtain each required functional and financial approval before commitment, release, payment, posting or disposal.
5. Record the decision, approvers, evidence, system references and closure outcome, then complete any required reconciliation or follow-up.

## Approval and decision authority

- The operational authority stated in the clauses governs the functional decision.
- Any spend, refund, credit, loss, write-off, settlement or commitment also requires the applicable FIN-001 financial approval; the stricter cumulative combination applies.
- No approver may self-approve, split related transactions or treat investigation, validation or proof acceptance as financial approval.

## Required records

- Request or incident record and date/time
- Identity of requester, reviewer and approvers
- Value calculation and aggregation basis
- Supporting evidence and related system references
- Exception, escalation and final closure record
- Related-policy references: PRC-003

## Escalation rule

Escalate to the Master Data Manager if a requested SKU is not active in the system within 48 hours of approval.

## Do not

- Do not invent an approval, threshold, exception or system step that is not documented.
- Do not split related activity, backdate evidence, share credentials or bypass segregation of duties.
- Do not proceed where mandatory evidence, safety control, identity verification or approval is missing.

## Search terms

SKU creation, new item, master data, vendor details, bank update., PRC-003

## Related controlled documents

GOV-001 applies whenever sources, roles, definitions or thresholds appear inconsistent. FIN-001 applies to every financial commitment, refund, credit, write-off, waiver, claim or settlement. Use the master document register to confirm current status and any additional cross-functional dependencies before acting.

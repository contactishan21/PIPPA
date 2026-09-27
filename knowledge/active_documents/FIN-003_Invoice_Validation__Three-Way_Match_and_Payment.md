---
document_id: FIN-003
title: Invoice Validation, Three-Way Match and Payment
company: Dune & Palm Commerce LLC
function: Finance & Approval Controls
owner: Accounts Payable Director
status: CURRENT
version: 1.10
effective_date: 04 September 2026
source_type: Policy / SOP
retrieval_eligible: true
market: UAE
currency: AED
---

# FIN-003 — Invoice Validation, Three-Way Match and Payment

> **SYNTHETIC DEMO CONTENT — This document, company, people, limits, vendors and procedures are fictional. It is designed only to test the PIPPA knowledge-assistant prototype and must not be used as legal, financial, safety or operational advice.**

## Control information

- **Owner:** Accounts Payable Director
- **Audience:** Accounts payable, requestors, receivers and procurement
- **Status:** CURRENT
- **Version:** 1.10
- **Effective:** 04 September 2026
- **Review due:** 01 March 2027

## When to use this document

An invoice is ready for payment or is blocked by missing/mismatched records.

## Authoritative policy clauses

### FIN-003-5.1

> Payment requires a valid vendor, approved purchase order, confirmed receipt and invoice match unless an approved exception applies.

### FIN-003-5.2

> Quantity, price, tax, currency and beneficiary must match approved records within configured tolerances.

### FIN-003-5.3

> The person who creates or changes vendor bank data must not release the related payment.

### FIN-003-5.4

> Urgent-payment requests do not override duplicate, sanctions, fraud or bank-verification controls.

### FIN-003-5.5

> Accounts Payable validates the invoice but does not unilaterally release bank payment. Payment release requires two authenticated Treasury approvers whose authority covers the batch total and highest single payment under FIN-001.

### FIN-003-5.6

> A missing or irreproducible vendor invoice cannot be replaced by an employee-created invoice or receipt. Accounts Payable must follow PRC-002-5.6 and PRC-002-5.7, link the approved duplicate or controlled substitute to the payment record, suppress recoverable VAT where valid tax evidence is absent, and then complete all remaining PO, receipt, beneficiary, duplicate and Treasury-release controls in FIN-003. Approval of the document exception does not itself authorise payment.

### FIN-003-5.7

> A supplier credit note arising from an RTV must reference the approved RTV or return-material authorisation, original PO and invoice, returned item and quantity, gross returned value, outbound inventory transaction and supplier custody receipt. Accounts Payable validates and posts the credit only after those records match. The credit may be applied only to the same supplier legal entity through the approved ledger process and must not be netted informally against an invoice, cash payment or another supplier. A missing, partial or disputed credit remains open and follows PRC-006-4.7.

## Procedure

1. Validate invoice format and vendor identity.
2. If the invoice is missing or irreproducible, follow PRC-002-5.6 and PRC-002-5.7; never create an invoice internally.
3. Match the PO, receipt and invoice, supplier duplicate or approved controlled substitute.
4. Route differences to the responsible owner and suppress recoverable VAT where valid tax evidence is absent.
5. Run duplicate and beneficiary checks.
6. Approve payment batch under maker-checker control only after every document-exception and normal payment approval is complete.
7. Send remittance and retain audit evidence.
8. For an RTV credit, match the supplier credit note to the approved RTV, original PO and invoice, outbound inventory movement, custody handover and accepted quantities under FIN-003-5.7.

## Approval and decision authority

- Receiver: confirms delivery.
- Budget Owner: approves a valid business variance within authority.
- Invoice-substitute approvers: cumulative roles in PRC-002-5.7; they do not release payment.
- Accounts Payable Manager: validates the payment proposal but cannot release the bank payment alone.
- Two authenticated Treasury approvers: release the batch only when their FIN-001 authority covers both the batch total and highest single payment.

## Required records

- Invoice
- PO
- Receipt
- Variance approval
- Duplicate check
- Payment audit trail
- RTV approval and original PO/invoice
- Outbound movement and custody handover
- Supplier credit note and quantity/value reconciliation

## Escalation rule

Escalate bank changes, urgent secrecy, duplicate indicators, sanctions flags or unsupported receipts.

## Do not

- Do not create a receipt for undelivered work.
- Do not release your own vendor-master change.
- Do not net an expected, disputed or unmatched RTV credit informally against another supplier invoice or payment.

## Search terms

invoice payment, three way match, PO mismatch, receipt missing, payment blocked

## Related controlled documents

GOV-001 applies whenever sources, roles, definitions or thresholds appear inconsistent. FIN-001 applies to every financial commitment, refund, credit, write-off, waiver, claim or settlement. Use the master document register to confirm current status and any additional cross-functional dependencies before acting.

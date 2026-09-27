---
document_id: OPS-006
title: Online Order Collection and Identity Check
company: Dune & Palm Commerce LLC
function: Store & Customer Operations
owner: Omnichannel Operations Manager
status: CURRENT
version: 1.8
effective_date: 04 September 2026
source_type: Policy / SOP
retrieval_eligible: true
market: UAE
currency: AED
---

# OPS-006 — Online Order Collection and Identity Check

> **SYNTHETIC DEMO CONTENT — This document, company, people, limits, vendors and procedures are fictional. It is designed only to test the PIPPA knowledge-assistant prototype and must not be used as legal, financial, safety or operational advice.**

## Control information

- **Owner:** Omnichannel Operations Manager
- **Audience:** Store pickup teams and customer service
- **Status:** CURRENT
- **Version:** 1.8
- **Effective:** 04 September 2026
- **Review due:** 01 March 2027

## When to use this document

A customer or nominee collects an online order from a store.

## Authoritative policy clauses

### OPS-006-4.1

> An order may be released only after matching the collection code and an approved identity factor to the order record.

### OPS-006-4.2

> A nominee must be recorded by the purchaser or verified through the approved customer-service process.

### OPS-006-4.3

> High-value or age-restricted orders require the named collector's original approved identification.

### OPS-006-4.4

> Copies of identity documents must not be retained unless the system explicitly requires and protects them.

### OPS-006-4.5

> An order is high-value when its total collection value is AED 5,000 or more. Original approved identification is mandatory for every high-value or age-restricted order and whenever the record contains a fraud alert, identity mismatch, restricted-product flag or enhanced-verification instruction.

### OPS-006-4.6

> The AED 5,000 threshold applies to the aggregate value of related orders presented for the same collection event. Orders must not be separated to avoid enhanced verification, and a Duty Manager cannot waive an age, fraud or mandatory identity control.

### OPS-006-4.7

> When a collector appears legitimate but does not present the original approved identification required for release, a Duty Manager may place the order on secure operational hold for up to 48 hours so the named collector can return with valid documentation. The hold does not waive identification, extend indefinitely or permit release to another person. Fraud Team escalation is required only when a fraud alert, account-takeover indicator, false document, identity conflict or other malicious indicator is present.

### OPS-006-4.8

> A cancellation request for an uncollected high-value, age-restricted or flagged order does not waive the identity control. The employee may record ‘cancellation requested—identity not verified’ and must keep the goods secure. A refund may be released only after approved step-up verification of the purchaser's account or identity, and only as an automatic reversal to the original payment method. Cash, credit notes, a different payment method and immediate manual refunds are prohibited. Escalate to the Fraud Team only when a fraud alert or other malicious indicator exists.

### OPS-006-4.9

> Approved step-up verification for an uncollected-order cancellation requires the purchaser either to confirm the request through the authenticated customer account using multi-factor authentication or to present original approved identification in person. Customer Identity Operations may validate a documented system-access exception using two independent account factors that do not include a password, PIN, full card number or one-time code disclosed to an employee. The verification event, channel, factors used, operator and timestamp must be logged. A store employee must not initiate or complete the verification on the purchaser's behalf.

## Procedure

1. Locate the order using the collection code and calculate the total value of all related orders in the collection event.
2. Check for age restriction, fraud alert, identity mismatch, restricted-product flag or enhanced-verification instruction.
3. For a total value of AED 5,000 or more, any age-restricted order, or any flagged order, inspect the named collector's original approved identification.
4. Match collector details and required identity factors; a Duty Manager may review a minor spelling or formatting mismatch but cannot waive mandatory verification.
5. If a legitimate collector lacks the required original ID and no malicious indicator exists, place the order on a secure hold for up to 48 hours and explain what documentation to bring back.
6. If the unverified collector requests cancellation, record the request without releasing goods or money and initiate one of the step-up methods in OPS-006-4.9.
7. After successful logged step-up verification, process only an automatic reversal to the original payment method; otherwise retain the secure hold or apply the normal uncollected-order process.
8. Release goods only after every mandatory identity check, then obtain acceptance and mark the order collected in real time.
9. Escalate suspected account takeover, false identification or unresolved malicious indicator without revealing purchaser details.

## Approval and decision authority

- Associate: standard release below AED 5,000 where no mandatory-verification flag applies.
- Duty Manager: system outage or minor name-format mismatch, and a secure hold up to 48 hours for a legitimate collector missing original ID; no authority to waive age, fraud or mandatory identity controls.
- Customer Identity Operations: documented system-access exception for step-up cancellation verification using two independent permitted account factors.
- Fraud Team: explicit fraud alert, suspected account takeover, false identification, identity conflict or another malicious indicator.

## Required records

- Order number
- Aggregate collection value
- Verification flags
- Verification result
- Collector name
- Hold start and expiry
- Reason for hold
- Cancellation-request status
- Step-up verification result
- Original-payment reversal reference
- Collection time
- Exception/escalation record

## Escalation rule

Do not release where the code is valid but mandatory identity requirements fail. Use the 48-hour operational hold when the customer appears legitimate; escalate to Fraud only for explicit malicious indicators.

## Do not

- Do not photograph customer ID on a personal device.
- Do not disclose order contents to an unverified collector.
- Do not split or treat related orders separately to avoid the AED 5,000 control.
- Do not waive an age, fraud or identity-control flag.
- Do not use cancellation, a credit note, cash, a different payment method or a manual refund to bypass failed identity verification.

## Search terms

click and collect, order pickup, nominee, identity, collection code

## Related controlled documents

GOV-001 applies whenever sources, roles, definitions or thresholds appear inconsistent. FIN-001 applies to every financial commitment, refund, credit, write-off, waiver, claim or settlement. Use the master document register to confirm current status and any additional cross-functional dependencies before acting.

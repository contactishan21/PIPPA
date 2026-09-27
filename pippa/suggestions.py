from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SuggestedQuestion:
    text: str
    expected_document_id: str


# Curated demonstrations, not generated guesses. Regression tests verify that
# every displayed question stays grounded in its named CURRENT policy.
SUGGESTED_QUESTIONS: dict[str, tuple[SuggestedQuestion, ...]] = {
    "All policy areas": (
        SuggestedQuestion("A customer wants to return a defective item after 38 days. What should I do and say?", "RET-002"),
        SuggestedQuestion("A vendor found an invoice for work completed five months ago. Can they submit it now?", "PRC-002"),
        SuggestedQuestion("We need an external delivery fleet during a peak sale. What approvals and contract controls apply?", "LOG-001"),
        SuggestedQuestion("A vendor has offered me a third meal in 90 days. Each meal was below AED 300. Can I accept?", "PRC-005"),
    ),
    "Facilities, Legal & Corporate Affairs": (
        SuggestedQuestion("Who approves the budget for a new store fit-out?", "CAP-001"),
        SuggestedQuestion("The store roof is leaking. What immediate repair process applies?", "FAC-001"),
        SuggestedQuestion("A municipality inspector arrived unannounced. What should the store do?", "LEG-001"),
        SuggestedQuestion("A news reporter is calling the store. What should I say?", "COM-001"),
    ),
    "Finance & Approval Controls": (
        SuggestedQuestion("Who can approve spending or sign a financial commitment worth AED 60,000?", "FIN-001"),
        SuggestedQuestion("Can I claim a business expense when the original receipt is missing?", "FIN-002"),
        SuggestedQuestion("An invoice is blocked because the PO and receipt do not match. What happens next?", "FIN-003"),
        SuggestedQuestion("My team needs petty cash for an urgent operational expense. What controls apply?", "FIN-005"),
    ),
    "Governance & Definitions": (
        SuggestedQuestion("Two current policies appear inconsistent. Which rule should I follow?", "GOV-001"),
        SuggestedQuestion("A financial threshold boundary says up to AED 10,000. Does it include exactly AED 10,000?", "GOV-001"),
        SuggestedQuestion("A policy role is unclear because the named approver is unavailable. Can a similar job title substitute?", "GOV-001"),
        SuggestedQuestion("Does verbal emergency approval replace the required contract and safety controls?", "GOV-001"),
    ),
    "Human Resources & Payroll": (
        SuggestedQuestion("How many annual leave days can I carry into the next year?", "HR-004"),
        SuggestedQuestion("How do I request an emergency salary advance?", "PAY-001"),
        SuggestedQuestion("When does sick leave require a medical certificate?", "HR-005"),
        SuggestedQuestion("What minimum inventory-system score does a new cashier need before stocktakes?", "HR-008"),
    ),
    "Logistics & Supply Chain": (
        SuggestedQuestion("We need an external delivery fleet during a peak sale. What approvals apply?", "LOG-001"),
        SuggestedQuestion("Goods disappeared while in transit. What investigation and write-off process applies?", "LOG-006"),
        SuggestedQuestion("A refrigerated shipment exceeded its temperature range. What should we do?", "LOG-007"),
        SuggestedQuestion("A customer disputes receiving a delivery. What evidence and process are required?", "LOG-008"),
    ),
    "Marketing & Commercial": (
        SuggestedQuestion("Who approves a contract for a new social media agency?", "MKT-001"),
        SuggestedQuestion("We want to place a promotional display outside the store. What permits are needed?", "MKT-002"),
        SuggestedQuestion("A vendor agreed to fund part of our marketing campaign. What controls apply?", "MKT-003"),
        SuggestedQuestion("What approval is required to mark down aging seasonal stock?", "MER-001"),
    ),
    "Procurement & Vendor Management": (
        SuggestedQuestion("A business team wants to engage a new vendor. What due-diligence checks apply?", "PRC-001"),
        SuggestedQuestion("Work was completed without an approved purchase order. What should we do?", "PRC-004"),
        SuggestedQuestion("A vendor offered me a third meal within 90 days. Can I accept it?", "PRC-005"),
        SuggestedQuestion("How many quotations are required for a purchase worth AED 25,000?", "PRC-008"),
    ),
    "Quality, Security & Compliance": (
        SuggestedQuestion("We received notice that a product may be unsafe. What immediate action is required?", "QUA-001"),
        SuggestedQuestion("Can we use a new supplier before its factory audit is complete?", "QUA-002"),
        SuggestedQuestion("I suspect an employee is stealing stock. What investigation process applies?", "SEC-001"),
        SuggestedQuestion("Who can authorise a product recall and the related customer action?", "QUA-001"),
    ),
    "Store & Customer Operations": (
        SuggestedQuestion("A customer wants to return a defective item after 38 days. What should I do and say?", "RET-002"),
        SuggestedQuestion("The POS system is down while customers are waiting. What should the store do?", "OPS-001"),
        SuggestedQuestion("The till count is short compared with the system total. What should I do?", "OPS-002"),
        SuggestedQuestion("The shelf price is lower than the checkout price. Which price applies?", "RET-005"),
    ),
    "Technology & Data Governance": (
        SuggestedQuestion("Customer account data may have been exposed. What should I do immediately?", "DGV-001"),
        SuggestedQuestion("How do I request a laptop for a new employee?", "ITS-001"),
        SuggestedQuestion("An RFID tag is failing to update inventory. What process applies?", "TEC-001"),
        SuggestedQuestion("How do I request creation of a new product SKU?", "TEC-002"),
    ),
}


def suggestions_for(policy_area: str) -> tuple[SuggestedQuestion, ...]:
    return SUGGESTED_QUESTIONS.get(policy_area, SUGGESTED_QUESTIONS["All policy areas"])

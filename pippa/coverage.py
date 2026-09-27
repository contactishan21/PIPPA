from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class CoverageDecision:
    covered: bool
    kind: str = "sufficient"
    reason: str = ""
    missing_information: tuple[str, ...] = ()
    escalation_contact: str = "your line manager"


INVOICE_ACTION = re.compile(r"\b(submit|send|upload|enter|file|lodge|register)\w*\b", re.I)
INVOICE_TOPIC = re.compile(r"\b(invoice|bill)\w*\b", re.I)
PROCEDURE_QUESTION = re.compile(r"\b(how|where|process|procedure|steps?|portal|email|address|channel)\b", re.I)
INVOICE_EXCEPTION = re.compile(
    r"\b(late|old|overdue|missing|lost|irreproducible|duplicate|reject|rejected|"
    r"match|mismatch|payment|paid|po|purchase order|receipt|work completed|"
    r"days?|weeks?|months?|years?|90|180)\b",
    re.I,
)
POS_TOPIC = re.compile(r"\b(pos|point[- ]of[- ]sale|till|checkout terminal|cash register)\b", re.I)
SYSTEM_OPERATION = re.compile(
    r"\b(operate|use|navigate|learn|training|trained|unfamiliar|work|works|working|"
    r"log ?in|sign ?in|open|close|start|set ?up|buttons?|screen|menu)\w*\b",
    re.I,
)
HELP_OR_INSTRUCTION = re.compile(r"\b(how|help|show|guide|instructions?|steps?|teach|what do i do)\b", re.I)
POS_POLICY_EVENT = re.compile(
    r"\b(outage|offline|system down|manual trading|variance|shortage|overage|short|over|"
    r"refund|return|exchange|price mismatch|promotion|receipt|transaction lookup|"
    r"gift card|credit note|cash error|age-restricted|order collection)\b",
    re.I,
)
POS_SCREEN_INSTRUCTION = re.compile(
    r"\b(which button|what button|click|tap|screen|menu|log ?in|sign ?in|open the till|close the till)\b",
    re.I,
)
RETAIL_TRAINING_REQUEST = re.compile(
    r"\b(cashier|sales associate|induction|buddy|rfid|inventory assessment|warehouse staff|"
    r"contractor|refresher|training|individual login|account setup)\b",
    re.I,
)

HR_TOPIC = re.compile(
    r"\b(annual leave|maternity|paternity|payroll|salary|benefits?|medical insurance|"
    r"performance review|recruitment|hiring staff|grievance|harassment|disciplinary|"
    r"termination|resignation|visa|dress code)\b",
    re.I,
)
IT_TOPIC = re.compile(
    r"\b(reset|change|forgot|recover|unlock)\b.{0,35}\b(password|passcode|account|login)\b|"
    r"\b(wi-?fi|laptop|printer|barcode scanner|software installation|email access|phishing)\b",
    re.I,
)
EMPLOYEE_SOCIAL_PUBLISHING = re.compile(
    r"\b(publish|post|share|upload)\w*\b.{0,45}\b(company|corporate|official)\b.{0,25}\b(social media|linkedin|instagram|facebook|tiktok)\b|"
    r"\b(company|corporate|official)\b.{0,25}\b(social media|linkedin|instagram|facebook|tiktok)\b.{0,45}\b(publish|post|share|upload)\w*\b",
    re.I,
)
ANNUAL_LEAVE_ENTITLEMENT = re.compile(
    r"\b(annual leave|vacation)\b.*\b(days?|entitlement|allowance|how much|paid)\b|"
    r"\b(days?|entitlement|allowance|how much|paid)\b.*\b(annual leave|vacation)\b",
    re.I,
)
ANNUAL_LEAVE_TOPIC = re.compile(r"\b(annual leave|vacation|holiday leave)\b", re.I)
SICK_LEAVE_TOPIC = re.compile(
    r"\b(sick leave|sick days?|sickness absence|medical leave|illness leave)\b|"
    r"\b(?:become|became|am|was|fall|fell) sick\b",
    re.I,
)
OTHER_LEAVE_TOPICS = (
    ("unpaid leave", re.compile(r"\b(unpaid leave|leave without pay)\b", re.I)),
    ("maternity leave", re.compile(r"\bmaternity leave\b", re.I)),
    ("paternity leave", re.compile(r"\bpaternity leave\b", re.I)),
    ("parental leave", re.compile(r"\bparental leave\b", re.I)),
    ("bereavement or compassionate leave", re.compile(r"\b(bereavement|compassionate) leave\b", re.I)),
    ("study leave", re.compile(r"\bstudy leave\b", re.I)),
)
LEAVE_RELATIONSHIP = re.compile(
    r"\b(combin\w*|attach\w*|join\w*|link\w*|add(?:ed|ing)?|tack(?:ed|ing)? on|"
    r"convert\w*|chang\w*|switch\w*|swap\w*|extend\w*|replac\w*|substitut\w*|"
    r"deduct\w*|overlap\w*|interrupt\w*|instead of|along with|at the same time|"
    r"back[- ]to[- ]back|consecutiv\w*|immediately before|immediately after|"
    r"right before|right after|before|after|following|during|while on|together)\b",
    re.I,
)
LEAVE_ENCASHMENT = re.compile(
    r"\b(cash(?:ed|ing)? out|cashout|encash\w*|sell\w*|buy back|moneti[sz]\w*|paid out)\b",
    re.I,
)
LEAVE_ACCRUAL = re.compile(
    r"\b(accru\w*|earn\w*)\b.{0,30}\b(leave|vacation|sick days?)\b|"
    r"\b(leave|vacation|sick days?)\b.{0,30}\b(accru\w*|earn\w*)\b",
    re.I,
)
LEAVE_ROLLOVER_OR_EXPIRY = re.compile(
    r"\b(carry\s*(?:over|forward)|carry(?:\s+\w+){0,6}\s+(?:into|to)\s+(?:the\s+)?(?:next|following)|"
    r"roll\s*over|rollover|expir\w*|use[- ]by)\b",
    re.I,
)
FOOD_ALLOWANCE_REQUEST = re.compile(
    r"\b(food|meal|meals|subsistence)\s+(allowance|allowances|stipend|budget|money|policy)\b|"
    r"\b(allowance|allowances|stipend|budget)\b.{0,30}\b(food|meal|meals|subsistence)\b|"
    r"\b(food|meal|meals)\b.{0,45}\b(petty cash|cash advance|how much|amount|rate|entitl\w*)\b|"
    r"\b(petty cash|cash advance|how much|amount|rate|entitl\w*)\b.{0,45}\b(food|meal|meals)\b",
    re.I,
)
OVERNIGHT_STAFF_CASH_REQUEST = re.compile(
    r"\b(overnight|night shift|late shift|after hours)\b.{0,60}\b(petty cash|cash advance|cash)\b|"
    r"\b(petty cash|cash advance|cash)\b.{0,60}\b(overnight|night shift|late shift|after hours)\b",
    re.I,
)
PAYDAY_DETAIL = re.compile(
    r"\b(payday|pay date|payroll date|salary payment date|when (?:will|is|does).*salary.*paid)\b",
    re.I,
)
REFUELLING_PROCEDURE = re.compile(r"\b(refuel|refuelling|refueling|fuel(?:ling|ing)? procedure)\w*\b", re.I)
LEAVE_USE_BY_DETAIL = re.compile(
    r"\b(?:annual )?leave\b.*\b(use[- ]by|expiry|expiration)\b|"
    r"\b(use[- ]by|expiry|expiration)\b.*\b(?:annual )?leave\b",
    re.I,
)
CREDENTIAL_VALUE_REQUEST = re.compile(
    r"\b(?:what is|show|tell|give|provide|reveal|find)\b.{0,35}\b(password|passcode|otp|one[- ]time code|secret key)\b|"
    r"\b(password|passcode|otp|one[- ]time code|secret key)\b.{0,25}\b(?:for|of)\b",
    re.I,
)
ACCOUNT_ACCESS_PROCEDURE = re.compile(
    r"\b(reset|change|recover|unlock)\w*\b.{0,45}\b(password|passcode|account|login|access)\b|"
    r"\b(password|passcode|account|login|access)\b.{0,45}\b(reset|change|recover|unlock)\w*\b",
    re.I,
)
DOCUMENTED_COMPONENT = re.compile(
    r"\b(sick leave|sickness|medical certificate|medical report|annual leave|salary advance|"
    r"financial commitment|spending approval|who approves?|invoice|external fleet|vendor selection|"
    r"return|refund|exchange|till variance|stocktake|hospitality)\b",
    re.I,
)


def _mentioned_leave_types(question: str) -> tuple[str, ...]:
    """Return distinct leave categories named by the employee."""
    mentioned: list[str] = []
    if ANNUAL_LEAVE_TOPIC.search(question):
        mentioned.append("annual leave")
    if SICK_LEAVE_TOPIC.search(question):
        mentioned.append("sick leave")
    mentioned.extend(label for label, pattern in OTHER_LEAVE_TOPICS if pattern.search(question))
    return tuple(dict.fromkeys(mentioned))


def escalation_contact(question: str) -> str:
    """Choose a safe owner without pretending that a specific policy exists."""
    text = question.lower()
    if re.search(r"\b(fire|smoke|injury|medical emergency|threat|violence|evacuat|suspicious item|explosive)\b", text):
        return "the Duty Manager or Security team; if anyone is in immediate danger, follow the site emergency process"
    if HR_TOPIC.search(text):
        return "Human Resources or your line manager"
    if IT_TOPIC.search(text) or re.search(r"\b(cyber|data breach|malware|system access)\b", text):
        return "the IT Service Desk or Information Security team"
    if re.search(r"\b(invoice|accounts payable|supplier payment|vendor payment)\b", text):
        return "Accounts Payable or the Procurement support owner"
    if re.search(r"\b(vendor|supplier|tender|purchase order|procurement|contractor)\b", text):
        return "the Procurement policy owner or your line manager"
    if re.search(r"\b(fleet|delivery|carrier|warehouse|transport|logistics|forklift)\b", text):
        return "the Logistics or Supply Chain manager"
    if re.search(r"\b(refund|return|till|pos|cash|store opening|store closing|customer complaint)\b", text):
        return "the Duty Manager or relevant Operations policy owner"
    if re.search(r"\b(expense|finance|write-off|credit note|financial approval)\b", text):
        return "the Finance policy owner or your line manager"
    return "your line manager"


def assess_coverage(question: str) -> CoverageDecision:
    """Identify known gaps that broad topic retrieval must not reinterpret.

    This small registry is intentionally deterministic. It complements relevance
    scoring: a passage can be relevant to the noun "invoice" while still not
    contain the requested submission channel or procedure.
    """
    leave_types = _mentioned_leave_types(question)
    if len(leave_types) >= 2 and LEAVE_RELATIONSHIP.search(question):
        relationship = " and ".join(leave_types)
        has_documented_leave = "annual leave" in leave_types or "sick leave" in leave_types
        return CoverageDecision(
            covered=False,
            kind="partial" if has_documented_leave else "unsupported",
            reason=(
                "The current library contains separate controls for some of the named leave categories, "
                f"but it does not define the requested relationship between {relationship}."
                if has_documented_leave
                else f"The current library does not define the requested relationship between {relationship}."
            ),
            missing_information=(
                f"whether {relationship} may be combined, converted, substituted, overlap, interrupt one another, or be taken consecutively",
            ),
            escalation_contact="Human Resources or your line manager",
        )
    if leave_types and LEAVE_ENCASHMENT.search(question):
        has_documented_leave = "annual leave" in leave_types or "sick leave" in leave_types
        return CoverageDecision(
            covered=False,
            kind="partial" if has_documented_leave else "unsupported",
            reason="The current leave policies do not define a cash-out, encashment or payment-in-lieu rule for unused leave.",
            missing_information=("whether the named unused leave may be cashed out or paid in lieu",),
            escalation_contact="Human Resources or your line manager",
        )
    if leave_types and LEAVE_ACCRUAL.search(question):
        has_documented_leave = "annual leave" in leave_types or "sick leave" in leave_types
        return CoverageDecision(
            covered=False,
            kind="partial" if has_documented_leave else "unsupported",
            reason="The current leave policies do not state the requested leave accrual or earning rate.",
            missing_information=("the applicable leave accrual or earning rate",),
            escalation_contact="Human Resources or your line manager",
        )
    if "sick leave" in leave_types and LEAVE_ROLLOVER_OR_EXPIRY.search(question):
        return CoverageDecision(
            covered=False,
            kind="partial",
            reason="The sick-leave policy does not state whether unused sick leave carries over or expires.",
            missing_information=("whether unused sick leave carries over, and any applicable expiry date",),
            escalation_contact="Human Resources or your line manager",
        )
    if FOOD_ALLOWANCE_REQUEST.search(question):
        return CoverageDecision(
            covered=False,
            kind="partial",
            reason=(
                "The current library contains related petty-cash and employee meal-expense controls, "
                "but it does not define a staff food-allowance entitlement or rate."
            ),
            missing_information=(
                "which employees or shifts are eligible for a food allowance",
                "the approved food-allowance amount or rate",
                "whether staff meals are an approved petty-cash purpose",
            ),
            escalation_contact="Human Resources and the Finance policy owner, or your line manager",
        )
    if OVERNIGHT_STAFF_CASH_REQUEST.search(question):
        return CoverageDecision(
            covered=False,
            kind="partial",
            reason=(
                "The petty-cash policy defines the cash channel, but it does not state that overnight work "
                "creates an allowance or makes an unspecified staff purchase eligible."
            ),
            missing_information=(
                "the specific approved business purpose for the overnight cash request",
                "whether an overnight staff meal or allowance is eligible",
            ),
            escalation_contact="the Finance policy owner or your line manager",
        )
    if CREDENTIAL_VALUE_REQUEST.search(question):
        return CoverageDecision(
            covered=False,
            kind="unsupported",
            reason="Controlled policies must not provide, infer or retrieve passwords, one-time codes or secret keys.",
            escalation_contact=escalation_contact(question),
        )
    if ACCOUNT_ACCESS_PROCEDURE.search(question):
        has_documented_component = bool(DOCUMENTED_COMPONENT.search(question))
        return CoverageDecision(
            covered=False,
            kind="partial" if has_documented_component else "unsupported",
            reason="The current library does not contain an approved password or account-access reset procedure.",
            missing_information=("the approved password or account-access reset procedure",),
            escalation_contact="the IT Service Desk or Information Security team",
        )
    if PAYDAY_DETAIL.search(question):
        has_documented_component = bool(re.search(r"\b(salary advance|off[- ]cycle|final settlement)\b", question, re.I))
        return CoverageDecision(
            covered=False,
            kind="partial" if has_documented_component else "unsupported",
            reason="The current library does not define the monthly payroll date or payday schedule.",
            missing_information=("the applicable monthly payroll date or payday schedule",),
            escalation_contact="Payroll or Human Resources",
        )
    if REFUELLING_PROCEDURE.search(question):
        has_documented_component = bool(re.search(
            r"\b(external fleet|hire|engage|approval|contract|carrier|peak[- ]demand|peak sale)\b",
            question,
            re.I,
        ))
        return CoverageDecision(
            covered=False,
            kind="partial" if has_documented_component else "unsupported",
            reason="The current library does not contain an approved vehicle-refuelling operating procedure.",
            missing_information=("the approved vehicle-refuelling operating procedure",),
            escalation_contact="the Logistics or Supply Chain manager",
        )
    if LEAVE_USE_BY_DETAIL.search(question):
        return CoverageDecision(
            covered=False,
            kind="partial",
            reason="The annual-leave policy refers to a published use-by date but does not state that date.",
            missing_information=("the published carry-over leave use-by date",),
            escalation_contact="Human Resources or your line manager",
        )
    # HR-008 may govern induction and access readiness for a POS user. That is
    # different from a request for POS operating instructions, which remains
    # outside the current library unless a controlled POS guide is supplied.
    if POS_TOPIC.search(question) and RETAIL_TRAINING_REQUEST.search(question):
        return CoverageDecision(covered=True)
    if ANNUAL_LEAVE_ENTITLEMENT.search(question) and not re.search(r"\b(carry|carry-over|carry over|blackout|blocked|December)\b", question, re.I):
        return CoverageDecision(
            covered=False,
            kind="partial",
            reason=(
                "The current library contains annual-leave carry-over, blackout-period and request controls, "
                "but it does not define the employee's annual leave entitlement or allowance."
            ),
            missing_information=("the annual leave entitlement or allowance",),
            escalation_contact="Human Resources or your line manager",
        )
    if POS_TOPIC.search(question) and re.search(
        r"\b(what\s+(?:is|are|does)|define|definition|meaning|stand\s+for|explain)\b", question, re.I
    ) and not POS_POLICY_EVENT.search(question) and not re.search(
        r"\b(training|certification|outage|approval|controls)\b", question, re.I
    ) and not re.search(r"\b(onboarding|new\s+(?:hire|employee)|credential|access)\b", question, re.I):
        return CoverageDecision(
            covered=False,
            kind="unsupported",
            reason="The library contains POS-related policies, but no controlled definition or introductory explanation of the POS system.",
            escalation_contact="your line manager or the Retail Training Manager",
        )
    if (
        INVOICE_TOPIC.search(question)
        and INVOICE_ACTION.search(question)
        and PROCEDURE_QUESTION.search(question)
        and not INVOICE_EXCEPTION.search(question)
    ):
        return CoverageDecision(
            covered=False,
            kind="partial",
            reason=(
                "The current PIPPA library explains invoice validation, late invoices, missing invoices "
                "and payment controls, but it does not define the standard invoice-submission procedure."
            ),
            missing_information=(
                "approved submission channel or portal",
                "required submission fields and attachments",
                "submission confirmation and support contact",
            ),
            escalation_contact=escalation_contact(question),
        )
    if EMPLOYEE_SOCIAL_PUBLISHING.search(question) and not re.search(
        r"\b(agency|influencer|gifting|campaign|vendor|supplier)\b", question, re.I
    ):
        return CoverageDecision(
            covered=False,
            kind="unsupported",
            reason=(
                "The current library governs agencies, influencer campaigns and crisis communications, "
                "but it does not define the ordinary employee approval process for publishing company social-media posts."
            ),
            missing_information=(
                "authorised employee publishing roles",
                "content review and approval workflow",
                "approved account-access and recordkeeping controls",
            ),
            escalation_contact="the Marketing or Communications policy owner, or your line manager",
        )
    if (
        POS_TOPIC.search(question)
        and HELP_OR_INSTRUCTION.search(question)
        and SYSTEM_OPERATION.search(question)
        and (POS_SCREEN_INSTRUCTION.search(question) or not POS_POLICY_EVENT.search(question))
    ):
        return CoverageDecision(
            covered=False,
            kind="unsupported",
            reason=(
                "The current PIPPA library contains POS-related controls for outages, cash variances, returns, "
                "transaction lookup and other exceptions, but it does not contain the standard POS operating or training guide."
            ),
            missing_information=(
                "approved login and access steps",
                "till opening, sale and payment-screen instructions",
                "void, correction and till-closing steps",
                "approved training or practice environment",
            ),
            escalation_contact=escalation_contact(question),
        )
    return CoverageDecision(covered=True)


def assess_retrieved_evidence(
    question,
    kb,
    hits,
    minimum_score: float,
    functions: set[str] | None = None,
) -> CoverageDecision:
    """Reject lexical lookalikes that fall outside every policy's declared scope."""
    contact = escalation_contact(question)
    if not hits or hits[0].score < minimum_score:
        return CoverageDecision(
            covered=False,
            kind="unsupported",
            reason="I could not find sufficiently relevant evidence in a current controlled document.",
            escalation_contact=contact,
        )

    scoped_documents = set(kb.scope_matches(question, functions=functions))
    if not scoped_documents:
        return CoverageDecision(
            covered=False,
            kind="unsupported",
            reason=(
                "The retrieved words do not match the declared scope of any current policy. "
                "A loosely related document would not be a safe basis for an answer."
            ),
            escalation_contact=contact,
        )

    retrieved_documents = {hit.passage.document_id for hit in hits}
    if not scoped_documents.intersection(retrieved_documents):
        return CoverageDecision(
            covered=False,
            kind="partial",
            reason=(
                "PIPPA found a potentially related policy area, but the retrieved clauses do not answer the specific request."
            ),
            escalation_contact=contact,
        )
    return CoverageDecision(covered=True, escalation_contact=contact)


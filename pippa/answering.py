from __future__ import annotations

"""Evidence-first answer classification for PIPPA.

An answer is complete only when the requested components are actually in a
current policy. Relevant evidence with a documented gap is deliberately partial.
"""

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from .config import Settings
from .coverage import CoverageDecision, assess_coverage, assess_retrieved_evidence, escalation_contact
from .knowledge import KnowledgeBase, PolicyDocument, SearchHit


@dataclass(frozen=True)
class Answer:
    grounded: bool
    body: str
    hits: list[SearchHit]
    mode: str
    status: str = "unavailable"  # complete | partial | unavailable
    missing_information: tuple[str, ...] = ()
    escalation_contact: str = "your line manager"


@dataclass(frozen=True)
class ParsedAmounts:
    """Exact AED amounts found in a question, or a reason not to use them."""

    values: tuple[Decimal, ...] = ()
    labels: tuple[str, ...] = ()
    issue: str = ""


AED_AMOUNT_RE = re.compile(
    r"\bAED\s*([+-]?[\d,.]+(?:\s*(?:thousand|million|k|m)\b)?)",
    re.I,
)
UNCERTAIN_AMOUNT_RE = re.compile(
    r"\b(?:about|around|approximately|approx\.?|roughly|estimated?|between)\s+(?:AED\s*)?$",
    re.I,
)


def _format_amount(value: Decimal) -> str:
    """Format without converting to float or discarding fractional dirhams."""
    rendered = format(value, "f")
    whole, dot, fraction = rendered.partition(".")
    grouped = f"{int(whole):,}"
    return f"{grouped}.{fraction}" if dot and fraction and any(digit != "0" for digit in fraction) else grouped


def _parse_aed_amounts(question: str) -> ParsedAmounts:
    """Parse explicit AED values exactly, including thousand/million notation."""
    if not re.search(r"\bAED\b", question, re.I):
        return ParsedAmounts()

    matches = list(AED_AMOUNT_RE.finditer(question))
    if not matches:
        return ParsedAmounts(issue="the exact AED amount; the amount after 'AED' is missing or is not numeric")

    values: list[Decimal] = []
    labels: list[str] = []
    for match in matches:
        raw = match.group(1).strip()
        # A full stop at the end of a sentence is not part of an integer amount.
        if raw.endswith("."):
            raw = raw[:-1]
        unit_match = re.fullmatch(r"([+-]?[\d,.]+)\s*(thousand|million|k|m)?", raw, re.I)
        if not unit_match:
            return ParsedAmounts(issue=f"clarification of the malformed amount 'AED {raw}'")
        number, unit = unit_match.groups()
        if "," in number and not re.fullmatch(r"[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?", number):
            return ParsedAmounts(issue=f"clarification of the malformed amount 'AED {raw}'")
        if "," not in number and not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", number):
            return ParsedAmounts(issue=f"clarification of the malformed amount 'AED {raw}'")
        if UNCERTAIN_AMOUNT_RE.search(question[max(0, match.start() - 24):match.start()]):
            return ParsedAmounts(issue=f"the exact commitment amount; 'AED {raw}' is stated as an estimate")
        tail = question[match.end():]
        if len(matches) == 1 and re.match(r"\s*(?:-|–|—|to\b|or\b|and\b)\s*(?:AED\s*)?\d", tail, re.I):
            return ParsedAmounts(issue=f"one exact total commitment amount instead of the range or alternatives starting at 'AED {raw}'")
        try:
            value = Decimal(number.replace(",", ""))
            multiplier = Decimal(1_000_000 if unit and unit.lower() in {"million", "m"} else 1_000 if unit else 1)
            value *= multiplier
        except InvalidOperation:
            return ParsedAmounts(issue=f"clarification of the malformed amount 'AED {raw}'")
        if value <= 0:
            return ParsedAmounts(issue=f"a positive commitment amount instead of 'AED {raw}'")
        if value.as_tuple().exponent < -2:
            return ParsedAmounts(issue=f"an AED amount stated to no more than two decimal places instead of 'AED {raw}'")
        values.append(value)
        labels.append(f"AED {_format_amount(value)}")

    unique_values = tuple(dict.fromkeys(values))
    unique_labels = tuple(dict.fromkeys(labels))
    if len(unique_values) > 1:
        listed = ", ".join(unique_labels)
        return ParsedAmounts(
            values=unique_values,
            labels=unique_labels,
            issue=f"which single amount is the full expected commitment; the question contains multiple amounts ({listed})",
        )
    return ParsedAmounts(unique_values, unique_labels)


def _financial_amount_gap(question: str, doc: PolicyDocument) -> tuple[str, ...]:
    if doc.document_id != "FIN-001" or not re.search(
        r"\b(approv\w*|authority|sign\w*|spend|spending|commitment)\b", question, re.I
    ):
        return ()
    parsed = _parse_aed_amounts(question)
    if parsed.issue:
        return (parsed.issue,)
    if not parsed.values:
        return ()
    value = parsed.values[0]
    if Decimal("10000") < value < Decimal("10001"):
        return (
            f"the approval authority for AED {_format_amount(value)}; FIN-001 jumps from AED 10,000 to AED 10,001 and does not assign fractional values between them",
        )
    if Decimal("50000") < value < Decimal("50001"):
        return (
            f"the approval authority for AED {_format_amount(value)}; FIN-001 jumps from AED 50,000 to AED 50,001 and does not assign fractional values between them",
        )
    return ()


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(item.strip() for item in items if item.strip()))


def _owner(doc: PolicyDocument | None, question: str) -> str:
    return doc.owner if doc and doc.owner else escalation_contact(question)


def _system_request(question: str) -> bool:
    asks_destination_or_operation = bool(re.search(
        r"\b(portal|url|email address|which button|what button|click|screen|menu|log ?in|sign ?in)\b",
        question,
        re.I,
    ))
    asks_definition = bool(re.search(
        r"\b(what is|what does|define|definition|meaning|stand for)\b",
        question,
        re.I,
    ))
    names_system = bool(re.search(
        r"\b(system|pos|point[- ]of[- ]sale|rfid|portal|platform|application|app|software|sku)\b",
        question,
        re.I,
    ))
    return asks_destination_or_operation or (asks_definition and names_system)


def _hr_notification_question(question: str) -> bool:
    """True only for reporting an absence, not submitting medical evidence."""
    q = question.lower()
    sickness_context = bool(re.search(r"\b(sick|illness|ill|sickness|absence|absent)\b", q))
    reports_medical_evidence = bool(re.search(r"\b(medical|certificate|report|upload|submit)\b", q))
    asks_notification = bool(re.search(r"\b(notify|notification|line manager|telephone|phone|message|email|channel)\b", q))
    return sickness_context and asks_notification and not reports_medical_evidence


def _has_hr_notification_channels(doc: PolicyDocument) -> bool:
    return any(re.search(r"telephone call, message, or email", text, re.I) for _, text in doc.clauses)


def _has_hr_partial_pay_rate(doc: PolicyDocument) -> bool:
    return any(re.search(r"partially paid sick leave.*50%", text, re.I) for _, text in doc.clauses)


def _has_clause(doc: PolicyDocument, clause_id: str) -> bool:
    return any(identifier == clause_id for identifier, _ in doc.clauses)


def _hr008_induction_details_confirmed(doc: PolicyDocument) -> bool:
    return all(_has_clause(doc, clause_id) for clause_id in ("HR-008-4.7", "HR-008-4.8", "HR-008-4.9", "HR-008-4.10"))


def _sick_leave_question(question: str) -> bool:
    return bool(re.search(r"\b(sick|illness|ill|medical certificate|medical report|doctor.?s? note|sickness absence)\b", question, re.I))


def _hr008_training_question(question: str) -> bool:
    return bool(re.search(
        r"\b(training|train|induction|onboarding|buddy|certification|certified|refresher|cashier|"
        r"sales associate|warehouse staff|contractor|login|account setup|stocktake score|passing score)\b",
        question,
        re.I,
    ))


def _operational_stocktake_question(question: str) -> bool:
    q = question.lower()
    asks_stocktake = bool(re.search(r"\b(stocktake|stocktakes|stock count|inventory count|cycle count)\b", q))
    asks_process = bool(re.search(r"\b(procedure|process|prepare|preparation|freeze|count|what should|how do i|how does)\b", q))
    asks_training = bool(re.search(r"\b(training|train|induction|onboarding|buddy|certification|certified|refresher|cashier|sales associate|warehouse staff|contractor|login|account setup|passing score)\b", q))
    # RFID blind-cycle and approved-inventory-system questions belong to
    # technology controls, not the annual physical stocktake preparation rule.
    asks_rfid_system = bool(re.search(r"\b(rfid|blind cycle|approved inventory system|scanner|sync(?:hroniz)?)\b", q))
    return asks_stocktake and asks_process and not asks_training and not asks_rfid_system


def _customer_defect_question(question: str) -> bool:
    """Distinguish a customer's damaged item from logistics or company-stock damage."""
    q = question.lower()
    customer_context = bool(re.search(r"\b(customer|shopper|purchaser|bought|purchase)\b", q))
    defect_context = bool(re.search(r"\b(damag\w*|defect\w*|faulty|broken|not working)\b", q))
    remedy_context = bool(re.search(r"\b(return|exchange|replace\w*|refund|credit note|bring\w* (?:in|back))\b", q))
    return customer_context and defect_context and remedy_context


def _uniform_scope_question(question: str) -> bool:
    return bool(
        re.search(r"\b(uniform|uniforms|clothing allowance)\b", question, re.I)
        and re.search(r"\b(who|which|eligible|eligibility|apply|applies|applicable|certain|team members?|employees?|staff|frontline|store[- ]based)\b", question, re.I)
    )


def _prc002_submission_process_confirmed(doc: PolicyDocument) -> bool:
    return all(_has_clause(doc, clause_id) for clause_id in ("PRC-002-5.9", "PRC-002-5.10", "PRC-002-5.11", "PRC-002-5.12"))


def _prc002_submission_question(question: str) -> bool:
    return bool(re.search(r"\b(submit|submission|send|upload|portal|email|tracking|follow-?up)\b", question, re.I))


def _prc002_exact_destination_question(question: str) -> bool:
    return bool(re.search(r"\b(url|link|portal(?: name)?|email address|email id|which email|which portal)\b", question, re.I))


def _prc002_late_or_exception_question(question: str) -> bool:
    return bool(re.search(
        r"\b(late|old|overdue|missing|lost|irreproducible|duplicate|reject(?:ed)?|"
        r"mismatch|payment|paid|po|purchase order|receipt|work completed|days?|weeks?|months?|years?|90|180)\b",
        question,
        re.I,
    ))


def _missing_components(question: str, doc: PolicyDocument) -> tuple[str, ...]:
    """Components explicitly outside the current source, not mere topic labels."""
    q = question.lower()
    missing: list[str] = []
    asks_for_specific_email = bool(re.search(r"\bemail address\b", q))
    known_prc_submission = doc.document_id == "PRC-002" and _prc002_submission_process_confirmed(doc)
    if re.search(r"\b(phone|mobile|telephone|contact)(?:\s+phone)?\s+number\b", q):
        has_phone_number = any(re.search(r"(?:\+?\d[\d ()-]{6,}\d)", text) for _, text in doc.clauses)
        if not has_phone_number:
            missing.append("the requested telephone or contact number")
    if re.search(
        r"\b(reset|change|recover|unlock)\w*\b.{0,45}\b(password|passcode|account|login|access)\b|"
        r"\b(password|passcode|account|login|access)\b.{0,45}\b(reset|change|recover|unlock)\w*\b",
        q,
    ):
        missing.append("the approved password or account-access reset procedure")
    if re.search(r"\b(definition of|define|meaning of|stand for)\b", q):
        has_formal_definition = any(re.search(r"\b(means|is defined as|refers to)\b", text, re.I) for _, text in doc.clauses)
        if not has_formal_definition:
            missing.append("a formal controlled definition of the requested term")
    if _system_request(question) and not (
        (doc.document_id == "HR-005" and _hr_notification_question(question) and not asks_for_specific_email)
        or (known_prc_submission and _prc002_submission_question(question))
    ):
        missing.append("the requested system definition or operating instruction")
    if doc.document_id == "HR-005":
        if re.search(r"\b(exact|specific|which|what)\b", q) and re.search(r"\b(hospital|clinic|provider|practitioner)\b", q):
            missing.append("the identity of an approved hospital, clinic or medical provider")
        if re.search(r"\b(statutory|legal|legislation|law)\b", q) and re.search(r"\b(pay|paid|payment|entitlement|salary)\b", q):
            missing.append("the exact applicable statutory pay-entitlement basis")
        if re.search(r"\b(pay|paid|payment|compensation|entitlement|salary)\b", q):
            has_schedule = any(
                re.search(r"15 days of fully paid sick leave.*30 days of partially paid sick leave", text, re.I)
                for _, text in doc.clauses
            )
            if not has_schedule:
                missing.append("the current statutory sick-leave pay schedule")
            if has_schedule and re.search(r"\b(percent|percentage|rate|how much of my pay)\b", q) and not _has_hr_partial_pay_rate(doc):
                missing.append("the percentage that applies to partially paid sick leave")
        if _hr_notification_question(question) and not _has_hr_notification_channels(doc):
            missing.append("the approved sickness-absence notification channel")
        elif re.search(r"\b(where|portal|upload|send|submit|channel|deadline)\b", q):
            missing.append("the approved notification or medical-report submission channel and deadline")
    if doc.document_id == "HR-008":
        asks_for_itemised_materials = bool(re.search(r"\b(list|materials?|sop|which .*read|exact|detail|titles?|specific video|specific guide|website link)\b", q))
        asks_for_training = bool(re.search(r"\b(cashier|associate|induction|buddy|warehouse|contractor|training|certification|refresher|rfid|inventory|pos|register|login)\b", q))
        asks_for_assessment_score = bool(re.search(r"\b(score|pass(?:ing)?|80%|stocktake)\b", q))
        asks_for_mandatory_refresher = bool(re.search(r"\b(mandatory|required|next|date|scheduled)\b", q) and re.search(r"\b(refresher|refresh)\b", q))
        if asks_for_mandatory_refresher:
            missing.append("whether refresher training is mandatory and the next scheduled date")
        elif asks_for_itemised_materials:
            missing.append("the titles, links and itemised content of training materials and SOPs")
        elif asks_for_training and not asks_for_assessment_score and not _hr008_induction_details_confirmed(doc):
            missing.append("the itemised reading-material, SOP and refresher schedule referred to by HR-008")
    if doc.document_id == "PRC-002":
        asks_submission = _prc002_submission_question(question)
        if _prc002_exact_destination_question(question):
            missing.append("the company-portal URL or Procurement email address")
        elif asks_submission and not _prc002_late_or_exception_question(question) and not _prc002_submission_process_confirmed(doc):
            missing.append("the approved invoice-submission channel or portal")
    if doc.document_id == "FIN-001" and re.search(r"\b(acting|absent|delegate|substitute)\b", q):
        missing.append("the approved acting-approver arrangement")
    if doc.document_id == "HR-004" and re.search(r"\b(blackout|blocked)\b", q) and re.search(r"\b(exact|date|when|this year|year)\b", q):
        missing.append("the exact annual-leave blackout dates")
    return tuple(_dedupe(missing))


def _controlling_hits(question: str, hits: list[SearchHit], kb: KnowledgeBase) -> list[SearchHit]:
    """Narrow, auditable promotion where lexical search can hide a rule."""
    q = question.lower()
    clause_ids: list[str] = []
    if _customer_defect_question(question):
        clause_ids = ["RET-002-5.1", "RET-002-5.2", "RET-002-5.3", "RET-002-5.4", "RET-001-4.6"]
    elif _uniform_scope_question(question):
        clause_ids = ["HR-003-4.1", "HR-003-4.4", "HR-003-4.2"]
    elif re.search(r"\b(pay|paid|payment|compensation|entitlement|salary)\b", q) and "sick" in q:
        clause_ids = ["HR-005-4.8", "HR-005-4.10", "HR-005-4.4"]
    elif re.search(r"\b(invoice|bill)\b", q) and re.search(r"\b(submit|submission|send|upload|portal|email|tracking|follow-?up|attach|attachment|document|require)\b", q):
        clause_ids = [f"PRC-002-5.{number}" for number in range(8, 13)]
    elif _operational_stocktake_question(question):
        clause_ids = [f"OPS-013-4.{number}" for number in range(1, 7)]
    elif re.search(r"\brfid\b", q) and not _hr008_training_question(question):
        # A broad RFID-procedure request should expose the complete controlled
        # technology set, not just the one clause containing the acronym.
        clause_ids = [f"TEC-001-4.{number}" for number in range(1, 6)]
    elif (
        re.search(r"\b(limit|threshold|boundary)\b", q)
        and re.search(r"\bup\s+to\b", q)
        and re.search(r"\b(exactly|including|inclusive)\b", q)
        and re.search(r"\bAED\b", question, re.I)
    ):
        clause_ids = ["GOV-001-2.3", "GOV-001-2.4", "GOV-001-2.10"]
    elif _hr_notification_question(question):
        clause_ids = ["HR-005-4.9", "HR-005-4.6", "HR-005-4.3"]
    elif re.search(r"medical (certificate|report)|doctor.?s? note|sick leave", q):
        clause_ids = ["HR-005-4.1", "HR-005-4.3", "HR-005-4.4", "HR-005-4.5", "HR-005-4.7"]
    elif (
        re.search(r"\b(onboarding|new\s+(?:hire|employee))\b", q)
        and re.search(r"\b(pos\s+credentials?|credentials?|access)\b", q)
    ):
        clause_ids = [f"HR-007-4.{number}" for number in range(1, 6)]
    elif re.search(r"\b(cashier|sales associate|warehouse staff|contractor|induction|buddy|refresher|rfid|inventory|pos|register|login)\b", q) and re.search(r"\b(training|certification|induction|buddy|refresher|access|login|onboarding|cashier|warehouse|contractor)\b", q):
        clause_ids = [f"HR-008-4.{number}" for number in range(1, 13)]
    elif re.search(r"\b(financial commitment|spending|sign\w*|approv\w*).*?\bAED\b", question, re.I):
        clause_ids = ["FIN-001-3.1", "FIN-001-3.2"]
    elif "fleet" in q and any(word in q for word in ("approve", "approval", "order", "activate", "procedure")):
        clause_ids = ["LOG-001-5.6", "LOG-001-5.7"]
    elif any(word in q for word in ("meal", "hospitality", "dinner", "lunch")) and any(word in q for word in ("vendor", "supplier")) and re.search(r"\b(third|3rd|three)\b", q):
        clause_ids = ["PRC-005-3.8", "PRC-005-3.7", "PRC-005-3.4"]
    elif re.search(r"\b(till|cash drawer|safe)\b.*\b(variance|short|shortage|over|overage)\b", q):
        clause_ids = ["OPS-002-4.6"]
    leading = hits[0].score + 10 if hits else 10
    promoted = [SearchHit(passage, leading - index) for index, clause_id in enumerate(clause_ids) if (passage := kb.passage_for(clause_id))]
    if clause_ids:
        return promoted[:6]
    return hits[:6]


def _evidence(doc: PolicyDocument, hits: list[SearchHit]) -> list[tuple[str, str]]:
    selected = [(hit.passage.clause_id, hit.passage.text) for hit in hits if hit.passage.document_id == doc.document_id]
    if not selected:
        selected = doc.clauses[:3]
    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for source, text in selected:
        if source not in seen and text:
            result.append((source, text))
            seen.add(source)
    return result[:6]


def _answer_hits(question: str, doc: PolicyDocument, hits: list[SearchHit]) -> list[SearchHit]:
    """Return citations from the selected policy, avoiding known intent collisions."""
    excluded: set[str] = set()
    if re.search(r"\brfid\b", question, re.I) and not _hr008_training_question(question):
        excluded.add("HR-008")
    if _operational_stocktake_question(question):
        excluded.add("HR-008")
    if re.search(r"\bannual leave\b", question, re.I) and not _sick_leave_question(question):
        excluded.add("HR-005")
    if _sick_leave_question(question):
        excluded.add("HR-004")
    selected = [
        hit for hit in hits
        if hit.passage.document_id == doc.document_id
        and hit.passage.document_id not in excluded
    ]
    if re.search(r"\bverbal\b.*\bemergency\b|\bemergency\b.*\bverbal\b", question, re.I) and re.search(
        r"\b(contract|safety|insurance|privacy|custody|control)\w*\b", question, re.I
    ):
        selected.extend(
            hit for hit in hits
            if hit.passage.clause_id == "GOV-001-2.6" and hit not in selected
        )
    if doc.document_id == "RET-002" and _customer_defect_question(question):
        selected.extend(
            hit for hit in hits
            if hit.passage.clause_id == "RET-001-4.6" and hit not in selected
        )
    # The generated answer is based on one selected controlled policy. Do not
    # display neighbouring lexical matches as if they supported that answer.
    return selected[:6]


def _render_evidence(items: list[tuple[str, str]]) -> str:
    return "\n".join(f"- {text} **({source})**" for source, text in items)


def _direct_answer(question: str, doc: PolicyDocument) -> str:
    """Small set of conclusions mechanically supported by a named policy rule."""
    q = question.lower()
    if doc.document_id == "HR-003" and _uniform_scope_question(question):
        audience = re.sub(r"^Applies to\s+", "", doc.audience or "store-based retail staff only", flags=re.I).rstrip(".")
        return f"Yes. HR-003 applies to **{audience}**. Its issuance rule specifically covers **frontline retail employees**, who receive three standard uniform sets annually at company expense."
    if doc.document_id == "PRC-005" and re.search(r"\b(third|3rd|three)\b", q) and any(word in q for word in ("meal", "hospitality", "dinner", "lunch")):
        return "**Do not accept the invitation yet.** A third same-vendor hospitality event in 90 calendar days requires Compliance Officer plus Function Director approval before acceptance. If an active tender, selection, negotiation, dispute or renewal applies, it must be declined; approval cannot override that prohibition."
    if doc.document_id == "HR-005" and _sick_leave_question(question) and re.search(r"\b(pay|paid|payment|compensation|entitlement|salary)\b", q):
        schedule = next((text for _, text in doc.clauses if "15 days of fully paid sick leave" in text), "")
        if schedule:
            if re.search(r"\b(percent|percentage|rate|how much of my pay)\b", q) and _has_hr_partial_pay_rate(doc):
                return "Partially paid sick leave under the current company schedule is paid at **50% of the employee's applicable pay**. The applicable controlled legal source remains authoritative."
            return "The current company schedule provides up to 15 days of fully paid sick leave and a further 30 days of partially paid sick leave in each year; leave beyond 45 days is unpaid. The applicable controlled legal source remains authoritative."
    if doc.document_id == "HR-005" and _hr_notification_question(question) and _has_hr_notification_channels(doc):
        return "Notify your line manager of a sickness absence as early as possible and, where reasonably practicable, before your next scheduled shift. You may use a **telephone call, message, or email**."
    if doc.document_id == "HR-005" and _sick_leave_question(question):
        return "A certified medical report is required for illness exceeding two consecutive calendar days. One or two consecutive days do not require a report solely because of duration, unless HR lawfully requests one for a documented reason."
    if doc.document_id == "HR-008" and _hr008_induction_details_confirmed(doc):
        if re.search(r"\bwarehouse\b", q):
            return "Warehouse Staff do **not** complete cashier training. They complete role-specific stock-picking and warehouse-management training covering stock receiving and stock shipment."
        if re.search(r"\bcontractor", q):
            return "Contractors receive the ethics code of conduct and onboarding on relevant policy procedures, including invoice submission. The policy does not specify the invoice-submission channel or detailed procedure."
        if re.search(r"\b(refresher|refresh|video|user guide)\b", q):
            return "A refresher opportunity is available every **six months** for employees who need to refresh their knowledge. Videos and user guides are available on the company website at any time; this policy does not provide their titles or web link."
        if re.search(r"\b(login|log in|account|access|two weeks|2 weeks|hard stop)\b", q):
            return "There is no automated training-certification hard stop. Each employee receives an individual login, which typically takes about **two weeks** after onboarding to set up. Until it is ready, they cannot log in to cashier, RFID or POS systems."
        if re.search(r"\b(score|passing|80%|stocktake)\b", q) and re.search(r"\b(minimum|score|pass|stocktake)\b", q):
            return "Associates must achieve a minimum **80% passing score** on the inventory systems module, including RFID handling, before participating in store stocktakes. If the assessment is not passed, documented coaching and a retake are required, with supervision until certification."
        if _hr008_training_question(question) and re.search(r"\b(cashier|sales associate|induction|buddy|training|onboarding|stock receiving|stock shipment)\b", q):
            return "Sales Associate induction is a structured **30-day** track. It includes one full week of on-the-job cashier training with multiple assigned buddies, applicable cashier/RFID/inventory-assessment systems training, and learning store stock receiving and shipment. The Store Manager or line manager is responsible for planning the cashier training."
    if doc.document_id == "PRC-002" and _prc002_submission_process_confirmed(doc) and re.search(r"\b(submit|submission|send|upload|portal|email|tracking|follow-?up)\b", q):
        return "Submit the complete, itemised invoice with detailed costing, the approved purchase order and the job-completion report through the company portal where access is available. Where portal access is limited, email the Procurement team so it can upload the invoice. Portal submissions receive an automatic tracking reference; for email submissions, Procurement provides the tracking number. Direct follow-ups to the Procurement Manager."
    if doc.document_id == "RET-002" and _customer_defect_question(question):
        return "Identify the transaction and arrange a product inspection first. Record the customer's preferred remedy, but do not promise an exchange before the defect is confirmed. If the defect is confirmed and an exchange is approved, process it as a return of the original item and a linked new purchase; use the gross returned value for approval authority."
    if doc.document_id == "RET-002" and any(word in q for word in ("defect", "defective", "late")):
        return "Do not decline a claimed defect solely because the standard return window has passed. Identify the transaction and arrange inspection before confirming a remedy."
    if doc.document_id == "FIN-001":
        parsed = _parse_aed_amounts(question)
        if len(parsed.values) == 1 and not parsed.issue:
            value = parsed.values[0]
            if value <= Decimal("10000"):
                approver = "Manager plus independent budget/finance check"
            elif Decimal("10001") <= value <= Decimal("50000"):
                approver = "Director plus Finance Manager"
            elif Decimal("50001") <= value <= Decimal("250000"):
                approver = "VP/COO plus Finance Controller"
            elif value > Decimal("250000"):
                approver = "CFO plus CEO"
            else:
                return ""
            return f"For a total commitment of AED {_format_amount(value)}, the financial authority is **{approver}**. Budget availability alone does not grant authority."
    return ""


def _unavailable(decision: CoverageDecision) -> Answer:
    missing = "\n".join(f"- {item}" for item in decision.missing_information)
    missing_section = f"\n\n### What is missing\n{missing}" if missing else ""
    body = f"""### I cannot find a policy that answers this question
I could not find enough current controlled information to answer safely. I will not guess or substitute a loosely related policy.

**Why PIPPA stopped:** {decision.reason}{missing_section}

### What to do now
Please contact **{decision.escalation_contact}** for the approved guidance.
"""
    return Answer(False, body, [], "Guardrail · unavailable", "unavailable", decision.missing_information, decision.escalation_contact)


def _partial(question: str, doc: PolicyDocument, hits: list[SearchHit], missing: tuple[str, ...]) -> Answer:
    details = _render_evidence(_evidence(doc, hits))
    direct = _direct_answer(question, doc)
    missing_text = "\n".join(f"- {item}" for item in missing)
    contact = _owner(doc, question)
    confirmed = f"{direct}\n\n### Supporting policy detail\n{details}" if direct else details
    body = f"""### This is all I found in the current policy
The policy provides the confirmed detail below, but it does not fully answer the information you requested. I will not fill the gap with assumptions.

### Confirmed policy detail
{confirmed}

### What is not documented here
{missing_text}

### What to do now
Please contact **{contact}** or your line manager for the approved additional guidance.
"""
    return Answer(False, body, _answer_hits(question, doc, hits), "Guardrail · partial evidence", "partial", missing, contact)


def _leave_policy_gap_partial(question: str, kb: KnowledgeBase, decision: CoverageDecision) -> Answer:
    """Show only available leave evidence without implying that it fills the identified gap."""
    has_sick_leave = bool(re.search(
        r"\b(sick leave|sick days?|sickness absence|medical leave|illness leave)\b|"
        r"\b(?:become|became|am|was|fall|fell) sick\b",
        question,
        re.I,
    ))
    has_annual_leave = bool(re.search(r"\b(annual leave|vacation|holiday leave)\b", question, re.I))
    clause_ids: list[str] = []
    available: list[str] = []
    if has_sick_leave:
        clause_ids.extend(("HR-005-4.1", "HR-005-4.3"))
        available.append("sick leave (HR-005)")
    if has_annual_leave:
        clause_ids.extend(("HR-004-4.4", "HR-004-4.2"))
        available.append("annual leave (HR-004)")
    hits = [
        SearchHit(passage, 100.0 - index)
        for index, clause_id in enumerate(clause_ids)
        if (passage := kb.passage_for(clause_id)) is not None
    ]
    details = _render_evidence([(hit.passage.clause_id, hit.passage.text) for hit in hits])
    missing_text = "\n".join(f"- {item}" for item in decision.missing_information)
    if len(available) == 2:
        availability = f"PIPPA has separate current policies covering {available[0]} and {available[1]}."
    else:
        availability = f"PIPPA has a current policy covering {available[0]}."
    body = f"""### Partial policy available
{availability} The requested rule is not documented in the available policy evidence, so I cannot confirm it.

### Confirmed policy detail
{details}

### What is not documented here
{missing_text}

### What to do now
Please contact **{decision.escalation_contact}** for approved guidance on the missing leave rule.
"""
    return Answer(
        False,
        body,
        hits,
        "Guardrail · partial evidence",
        "partial",
        decision.missing_information,
        decision.escalation_contact,
    )


def _staff_cash_gap_partial(question: str, kb: KnowledgeBase, decision: CoverageDecision) -> Answer:
    """Separate a cash-channel ceiling from an undocumented employee allowance."""
    asks_cash = bool(re.search(r"\b(petty cash|cash advance|cash)\b", question, re.I))
    clause_ids = (
        ("FIN-005-4.1", "FIN-005-4.3", "FIN-005-4.11", "FIN-005-4.4")
        if asks_cash
        else ("FIN-002-4.1", "FIN-002-4.3", "FIN-002-4.4")
    )
    hits = [
        SearchHit(passage, 100.0 - index)
        for index, clause_id in enumerate(clause_ids)
        if (passage := kb.passage_for(clause_id)) is not None
    ]
    details = _render_evidence([(hit.passage.clause_id, hit.passage.text) for hit in hits])
    missing_text = "\n".join(f"- {item}" for item in decision.missing_information)
    if asks_cash:
        confirmed = (
            "FIN-005 allows petty cash only for an approved urgent low-value business purchase when an approved "
            "purchasing method is impractical. The AED 500 maximum is a **cash-channel ceiling per disbursement**, "
            "not a food-allowance entitlement or per-person meal rate. The policy does not say that overnight work "
            "alone makes a staff payment eligible."
        )
    else:
        confirmed = (
            "FIN-002 contains reimbursement controls for necessary, reasonable and business-related employee expenses, "
            "including meals, but it does not create a food-allowance entitlement or state an allowance amount."
        )
    body = f"""### Partial policy available
{confirmed}

### Confirmed policy detail
{details}

### What is not documented here
{missing_text}

### What to do now
Please contact **{decision.escalation_contact}** before issuing cash or communicating an allowance amount.
"""
    return Answer(
        False,
        body,
        hits,
        "Guardrail · partial evidence",
        "partial",
        decision.missing_information,
        decision.escalation_contact,
    )


def _complete(question: str, doc: PolicyDocument, hits: list[SearchHit]) -> Answer:
    sections: list[str] = []
    if direct := _direct_answer(question, doc):
        sections += ["### Direct answer", direct]
    sections += ["### What the current policy says", _render_evidence(_evidence(doc, hits))]
    if doc.document_id == "RET-002" and _customer_defect_question(question):
        exchange_rule = next((
            hit.passage
            for hit in hits
            if hit.passage.clause_id == "RET-001-4.6"
        ), None)
        if exchange_rule is not None:
            sections += [
                "### If the defect is confirmed",
                _render_evidence([(exchange_rule.clause_id, exchange_rule.text)]),
            ]
    if doc.document_id == "FIN-001" and re.search(r"\b(approv\w*|authority|sign\w*|spend|commitment)\b", question, re.I):
        sections += ["### Approval and decision authority", "\n".join(f"- {item} **(FIN-001 — Approval and decision authority)**" for item in doc.approvals)]
    if doc.records:
        sections += ["### Required records", "\n".join(f"- {item}" for item in doc.records[:5])]
    if doc.donts:
        sections += ["### Important limits", "\n".join(f"- {item}" for item in doc.donts[:3])]
    if doc.escalation:
        sections += ["### Escalation", doc.escalation]
    if any(word in question.lower() for word in ("customer", "return", "refund", "exchange")) and doc.document_id.startswith("RET-"):
        sections += ["### Suggested customer wording", "You can say: “The item will be inspected. I cannot confirm the final remedy until the defect is confirmed.”"]
    return Answer(True, "\n\n".join(sections), _answer_hits(question, doc, hits), "Evidence complete", "complete", (), _owner(doc, question))


def answer_question(question: str, kb: KnowledgeBase, settings: Settings, functions: set[str] | None = None) -> Answer:
    """Classify current policy evidence as complete, partial, or unavailable.

    ``functions`` remains accepted for compatibility but never narrows search.
    Area tabs are navigation for suggested questions, not an evidence boundary.
    """
    coverage = assess_coverage(question)
    if not coverage.covered:
        if coverage.kind == "partial" and any(
            "food allowance" in item or "overnight" in item
            for item in coverage.missing_information
        ):
            return _staff_cash_gap_partial(question, kb, coverage)
        leave_gap_markers = (
            "may be combined, converted, substituted",
            "cashed out or paid in lieu",
            "leave accrual or earning rate",
            "unused sick leave carries over",
        )
        if coverage.kind == "partial" and any(
            marker in item
            for item in coverage.missing_information
            for marker in leave_gap_markers
        ):
            return _leave_policy_gap_partial(question, kb, coverage)
        # A staged PRC-002 revision can supply the previously absent standard
        # submission process. Keep the active library guarded until that
        # evidence actually exists in the loaded knowledge base.
        has_prc_submission_process = all(
            kb.passage_for(clause_id) is not None
            for clause_id in ("PRC-002-5.9", "PRC-002-5.10", "PRC-002-5.11", "PRC-002-5.12")
        )
        if coverage.kind == "partial" and re.search(r"\b(invoice|bill)\b", question, re.I) and has_prc_submission_process:
            coverage = CoverageDecision(True)
        if coverage.covered:
            pass
        # A known component gap can still have useful, correctly scoped policy
        # detail.  Show it only when the query itself resolves to that policy.
        elif coverage.kind == "partial" and re.search(r"\b(invoice|bill)\b", question, re.I):
            related_hits = kb.search(question, limit=max(settings.top_k, 6))
            scoped = set(kb.scope_matches(question))
            primary = next((hit for hit in related_hits if hit.passage.document_id in scoped), None)
            doc = kb.document_for(primary.passage.document_id) if primary else None
            if doc:
                missing = coverage.missing_information or ("the requested standard procedure",)
                return _partial(question, doc, related_hits, missing)
        elif coverage.kind == "partial" and (
            re.search(r"\b(annual leave|vacation)\b", question, re.I)
            or "the published carry-over leave use-by date" in coverage.missing_information
        ):
            related_hits = kb.search(question, limit=max(settings.top_k, 6))
            # The controlled gap detector can identify a carry-over/use-by
            # question even when the employee says only "leave days". In that
            # narrow case, anchor the partial answer to the relevant HR-004
            # clauses instead of relying on the missing word "annual".
            if "the published carry-over leave use-by date" in coverage.missing_information:
                leave_hits = [
                    SearchHit(passage, 100.0 - index)
                    for index, clause_id in enumerate(("HR-004-4.2", "HR-004-4.5"))
                    if (passage := kb.passage_for(clause_id)) is not None
                ]
                related_hits = leave_hits + [
                    hit
                    for hit in related_hits
                    if hit.passage.clause_id not in {leave_hit.passage.clause_id for leave_hit in leave_hits}
                ]
            primary = next((hit for hit in related_hits if hit.passage.document_id == "HR-004"), None)
            doc = kb.document_for(primary.passage.document_id) if primary else None
            if doc:
                missing = coverage.missing_information or ("the annual leave entitlement or allowance",)
                return _partial(question, doc, related_hits, missing)
        elif coverage.kind == "partial" and coverage.missing_information:
            raw_related_hits = kb.search(question, limit=max(settings.top_k, 6))
            related_hits = _controlling_hits(question, raw_related_hits, kb)
            scoped = set(kb.scope_matches(question))
            promoted_primary = (
                related_hits[0]
                if raw_related_hits and related_hits and related_hits[0].score > raw_related_hits[0].score + 5
                else None
            )
            primary = promoted_primary or next(
                (hit for hit in related_hits if hit.passage.document_id in scoped),
                None,
            )
            doc = kb.document_for(primary.passage.document_id) if primary else None
            if doc:
                return _partial(question, doc, related_hits, coverage.missing_information)
        elif not coverage.covered:
            return _unavailable(coverage)
    raw_hits = kb.search(question, limit=max(settings.top_k, 6))
    hits = _controlling_hits(question, raw_hits, kb)
    evidence = assess_retrieved_evidence(question, kb, hits, settings.minimum_score)
    if not evidence.covered:
        return _unavailable(evidence)
    scoped = set(kb.scope_matches(question))
    # A deliberate controlling rule (inserted by _controlling_hits) takes
    # precedence over raw lexical order. Otherwise use the highest-ranked hit
    # that also belongs to a declared scope match. Reversing those checks can
    # make a weaker neighbouring scope outrank the clause that actually matched.
    promoted_primary = hits[0] if raw_hits and hits and hits[0].score > raw_hits[0].score + 5 else None
    primary = promoted_primary or next(
        (hit for hit in hits if hit.passage.document_id in scoped),
        None,
    )
    if primary is None:
        return _unavailable(CoverageDecision(False, "unsupported", "No retrieved passage belongs to a policy whose declared scope matches the request.", escalation_contact=escalation_contact(question)))
    doc = kb.document_for(primary.passage.document_id)
    if doc is None:
        return _unavailable(CoverageDecision(False, "unsupported", "The matching policy could not be loaded.", escalation_contact=escalation_contact(question)))
    missing = tuple(_dedupe([*_missing_components(question, doc), *_financial_amount_gap(question, doc)]))
    if missing:
        return _partial(question, doc, hits, missing)
    return _complete(question, doc, hits)


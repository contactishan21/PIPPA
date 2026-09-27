"""Read-only application audit; writes only audit results, never policy/runtime data."""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pippa.answering import answer_question
from pippa.config import Settings, KNOWLEDGE_DIR
from pippa.knowledge import KnowledgeBase
from pippa.suggestions import SUGGESTED_QUESTIONS

PROBES = [
    ("missing", "When will my monthly salary be paid?"),
    ("partial", "What is the email address for submitting my medical certificate?"),
    ("partial", "Which portal do I use to upload a late invoice?"),
    ("supported", "What is the exact sick leave pay entitlement?"),
    ("missing", "What is the URL of the ethics register?"),
    ("missing", "What is the phone number of the approved delivery carrier?"),
    ("partial", "Which button do I click to create a new SKU?"),
    ("partial", "What is the definition of a salary advance?"),
    ("partial", "When is the next mandatory cashier refresher course?"),
    ("partial", "What are the exact dates of this year's annual leave blackout?"),
    ("missing", "What is the password for the inventory system?"),
    ("missing", "What is a POS?"),
    ("missing", "How do I book a meeting room?"),
    ("partial", "Which hospital must issue my sick leave certificate?"),
    ("partial", "When does sick leave require a medical certificate and how do I reset the payroll password?"),
    ("partial", "How much salary advance can I request and when is payday?"),
    ("partial", "What training does a new cashier need and where is the reading list?"),
    ("partial", "How many leave days can I carry over and what is the use-by date?"),
    ("partial", "How do I hire an external fleet and refuel the truck?"),
    ("partial", "Who approves a financial commitment of AED 60,000 and what is the CEO mobile number?"),
    ("partial", "Can I combine sick leave with annual leave?"),
    ("partial", "Can I take annual leave immediately after sick leave?"),
    ("partial", "Can unused sick leave be paid out?"),
    ("partial", "How quickly does annual leave accrue?"),
    ("partial", "How much petty cash can I issue staff working overnight as a food allowance?"),
    ("partial", "What is the food allowance policy?"),
    ("supported", "A customer brings in a damaged product and wants an exchange. What should I do?"),
    ("supported", "Does the uniform policy only apply to certain team members in the store? If yes, who are they?"),
    ("supported", "When does sick leave require a medical certificate?"),
    ("supported", "Who approves AED 1.5 million?"),
    ("supported", "I missed one day because I was sick. Is a medical report always required?"),
    ("supported", "What training and certification does a new cashier need?"),
    ("supported", "How many annual leave days can I carry into the next year?"),
    ("supported", "Who approves a financial commitment of AED 60,000?"),
    ("supported", "What checks are required before engaging a new vendor?"),
    ("supported", "A limit says up to AED 10,000. Is exactly AED 10,000 included?"),
    ("supported", "We need an external delivery fleet during a peak sale. What approvals apply?"),
    ("supported", "A customer wants to return a defective item after 38 days. What should I do?"),
]

def main():
    kb = KnowledgeBase(KNOWLEDGE_DIR)
    settings = Settings(openai_api_key="")
    rows = []
    def record(group, expected, question, expected_doc=None):
        a = answer_question(question, kb, settings)
        rows.append(dict(group=group, expected=expected, question=question,
                         expected_document=expected_doc, grounded=a.grounded, mode=a.mode,
                         status=a.status, sources=[h.passage.clause_id for h in a.hits],
                         source_documents=sorted({h.passage.document_id for h in a.hits}), body=a.body))
    for d in kb.documents:
        record("policy_scope", "retrieval_only", d.scenario, d.document_id)
    for area, suggestions in SUGGESTED_QUESTIONS.items():
        for s in suggestions:
            record("suggestion:" + area, "retrieval_only", s.text, s.expected_document_id)
    for expected, question in PROBES:
        record("adversarial", expected, question)
    structural = {
        "policies": len(kb.documents), "clauses": len(kb.passages),
        "generic_procedure_policies": [d.document_id for d in kb.documents if any(
            s.startswith("Confirm that the request falls within this policy's scope") for s in d.steps)],
        "dangling_colon_clauses": [p.clause_id for p in kb.passages if p.text.endswith(":" )],
        "missing_clause_references": sorted({ref for p in kb.passages for ref in
            __import__('re').findall(r"\b[A-Z]{2,4}-\d{3}-\d+\.\d+\b", p.text)
            if kb.passage_for(ref) is None}),
    }
    output_dir = ROOT / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / "PIPPA_answer_quality_audit.json"
    expected_status = {"missing": "unavailable", "partial": "partial", "supported": "complete"}
    outcome_failures = [
        row for row in rows
        if row["group"] == "adversarial" and row["status"] != expected_status[row["expected"]]
    ]
    citation_failures = [
        row for row in rows
        if row["expected_document"] and row["expected_document"] not in row["source_documents"]
    ]
    summary = {
        "total_probes": len(rows),
        "outcome_failures": len(outcome_failures),
        "citation_failures": len(citation_failures),
    }
    output.write_text(
        json.dumps(dict(structure=structural, summary=summary, failures=[*outcome_failures, *citation_failures], results=rows), indent=2),
        encoding="utf-8",
    )
    print(json.dumps(structural, indent=2))
    print("Total probes:", len(rows))
    for expected in ("missing", "partial", "supported"):
        subset = [r for r in rows if r['expected'] == expected]
        print(expected, "grounded flags:", dict(Counter(r['grounded'] for r in subset)))
    for r in rows:
        if r['group'] == 'adversarial':
            print(r['expected'], r['grounded'], r['question'], r['sources'][:2])
    print("Validation summary:", json.dumps(summary))
    print("Report:", output)
    if outcome_failures or citation_failures:
        raise SystemExit("Answer-quality audit failed; inspect the uploaded report.")

if __name__ == '__main__':
    main()


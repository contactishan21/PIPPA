from __future__ import annotations

import sys
import tempfile
import unittest
import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pippa.answering import answer_question
from pippa.auth import (
    AuthenticatedSession,
    AuthenticationError,
    REMEMBERED_INTENT_COOKIE,
    REMEMBERED_SESSION_COOKIE,
    SupabaseAuth,
    _safe_magic_link_error,
    auth_callback_allowed,
    clear_remembered_session_cookies,
    logout_safely,
    parse_remembered_session_payload,
)
from pippa.config import Settings
from pippa.governance import context_for, history_csv, personal_metrics
from pippa.knowledge import KnowledgeBase, corpus_revision
from pippa.limits import (
    MAX_QUESTION_CHARS,
    QuestionCapacity,
    QuestionCapacityError,
    QuestionQuotaError,
    QuestionValidationError,
    sign_in_email_key,
    validate_question,
)
from pippa.repository import LocalConversationStore, SupabaseConversationStore
from pippa.runtime_config import RuntimeSettings
from pippa.storage import authorize_question, delete_history, history, initialise, save, set_feedback
from pippa.suggestions import SUGGESTED_QUESTIONS


class FakeResponse:
    def __init__(self, data):
        self.data = data


class FakeTable:
    def __init__(self):
        self.action = ""
        self.payload = None
        self.rows = []
        self.filters = []

    def insert(self, payload):
        self.action = "insert"
        self.payload = payload
        return self

    def select(self, columns):
        self.action = "select"
        return self

    def order(self, column, desc=False):
        return self

    def limit(self, limit):
        return self

    def update(self, payload):
        self.action = "update"
        self.payload = payload
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def execute(self):
        if self.action == "insert":
            return FakeResponse([{"id": "conversation-1", **self.payload}])
        if self.action == "select":
            return FakeResponse(self.rows)
        return FakeResponse([])


class FakeClient:
    def __init__(self):
        self.table_client = FakeTable()
        self.rpc_calls = []
        self.rpc_responses = {"pippa_save_conversation": "conversation-1"}

    def table(self, name):
        if name != "conversations":
            raise AssertionError("Unexpected table")
        return self.table_client

    def rpc(self, name, params=None):
        self.rpc_calls.append((name, params or {}))
        data = self.rpc_responses.get(name, [])
        return type("FakeRpc", (), {"execute": lambda self: FakeResponse(data)})()


class FakeCookies(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.saved = False

    def save(self):
        self.saved = True


class FakeUser:
    def __init__(self, user_id="verified-user", email="verified@example.com"):
        self.id = user_id
        self.email = email


class FakeSession:
    def __init__(self, access_token="new-access", refresh_token="new-refresh", user=None):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.user = user or FakeUser()


class FakeAuthClient:
    def __init__(self, session=None, verified_user=None):
        self.session = session or FakeSession()
        self.verified_user = verified_user or FakeUser()
        self.set_session_args = None
        self.sign_in_payload = None

    def get_session(self):
        return self.session

    def set_session(self, access_token, refresh_token):
        self.set_session_args = (access_token, refresh_token)
        return type("AuthResponse", (), {"session": self.session, "user": self.session.user})()

    def get_user(self):
        return type("UserResponse", (), {"user": self.verified_user})()

    def sign_in_with_otp(self, payload):
        self.sign_in_payload = payload
        return type("AuthResponse", (), {"session": None, "user": None})()


class FakeSupabaseClient(FakeClient):
    def __init__(self, auth_client=None):
        super().__init__()
        self.auth = auth_client or FakeAuthClient()
        self.rpc_responses["pippa_active_user_id"] = "verified-user"


class BrokenCookies(FakeCookies):
    def save(self):
        raise RuntimeError("cookie component failed")


class PippaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kb = KnowledgeBase(ROOT / "knowledge" / "active_documents")
        cls.settings = Settings(openai_api_key="", top_k=5, minimum_score=2.0)

    def test_only_current_library_is_loaded(self):
        self.assertEqual(len(self.kb.documents), 76)
        self.assertEqual(len(self.kb.passages), 491)
        self.assertTrue(all(doc.status == "CURRENT" for doc in self.kb.documents))

    def test_governance_traps_are_not_loaded(self):
        loaded = {doc.document_id for doc in self.kb.documents}
        self.assertNotIn("TRAP-RET-2019", loaded)
        self.assertNotIn("TRAP-LOG-DRAFT", loaded)

    def test_all_controlled_policy_areas_are_available(self):
        self.assertEqual(
            self.kb.functions,
            [
                "Facilities, Legal & Corporate Affairs",
                "Finance & Approval Controls",
                "Governance & Definitions",
                "Human Resources & Payroll",
                "Logistics & Supply Chain",
                "Marketing & Commercial",
                "Procurement & Vendor Management",
                "Quality, Security & Compliance",
                "Store & Customer Operations",
                "Technology & Data Governance",
            ],
        )

    def test_every_current_policy_is_retrievable_from_its_declared_use_case(self):
        for document in self.kb.documents:
            with self.subTest(document=document.document_id):
                hits = self.kb.search(document.scenario, limit=5)
                self.assertIn(document.document_id, {hit.passage.document_id for hit in hits})

    def test_defective_return_retrieves_return_policy(self):
        hits = self.kb.search("defective item return after 38 days refund", limit=5)
        self.assertIn("RET-001", {hit.passage.document_id for hit in hits})

    def test_late_vendor_invoice_retrieves_procurement_policy(self):
        hits = self.kb.search("vendor invoice submitted five months after work", limit=5)
        self.assertIn("PRC-002", {hit.passage.document_id for hit in hits})

    def test_general_invoice_submission_is_now_grounded(self):
        answer = answer_question("How do I submit an invoice?", self.kb, self.settings)
        self.assertTrue(answer.grounded)
        self.assertEqual(answer.status, "complete")
        self.assertIn("company portal", answer.body)
        self.assertIn("Procurement team", answer.body)
        self.assertIn("job-completion report", answer.body)
        self.assertTrue(answer.hits)

    def test_late_invoice_question_is_not_blocked_by_submission_gap(self):
        answer = answer_question(
            "How can a vendor submit an invoice for work completed five months ago?",
            self.kb,
            self.settings,
        )
        self.assertTrue(answer.grounded)
        self.assertFalse(answer.mode.startswith("Guardrail"))

    def test_standard_pos_operation_is_an_honest_knowledge_gap(self):
        answer = answer_question(
            "I am unfamiliar with the POS system of the store and how to operate it. Can you help me with this?",
            self.kb,
            self.settings,
        )
        self.assertFalse(answer.grounded)
        self.assertEqual(answer.status, "unavailable")
        self.assertEqual(answer.hits, [])
        self.assertIn("standard POS operating or training guide", answer.body)
        self.assertIn("Duty Manager", answer.body)

    def test_pos_outage_remains_covered(self):
        answer = answer_question(
            "The POS system is down during trading. Can we use the manual outage process?",
            self.kb,
            self.settings,
        )
        self.assertTrue(answer.grounded)
        self.assertFalse(answer.mode.startswith("Guardrail"))
        self.assertIn("OPS-001", {hit.passage.document_id for hit in answer.hits})

    def test_till_variance_remains_covered(self):
        answer = answer_question(
            "My till is short by AED 50. What variance procedure should I follow?",
            self.kb,
            self.settings,
        )
        self.assertTrue(answer.grounded)
        self.assertFalse(answer.mode.startswith("Guardrail"))
        self.assertIn("OPS-002", {hit.passage.document_id for hit in answer.hits})

    def test_emergency_fleet_retrieves_logistics_policy(self):
        hits = self.kb.search("external fleet peak sale home delivery approvals", limit=5)
        self.assertIn("LOG-001", {hit.passage.document_id for hit in hits})

    def test_fleet_approval_is_internal_and_shows_controlling_amounts(self):
        answer = answer_question(
            "Can I directly order an external fleet, or what approval procedure should I follow?",
            self.kb,
            self.settings,
        )
        self.assertTrue(answer.grounded)
        self.assertIn("LOG-001-5.6", {hit.passage.clause_id for hit in answer.hits})
        self.assertNotIn("Suggested customer wording", answer.body)
        self.assertNotIn("Suggested vendor wording", answer.body)
        self.assertIn("AED 10,000", answer.body)
        self.assertNotIn("say to the customer", answer.body.lower())

    def test_financial_approval_understands_decimal_million_notation(self):
        answer = answer_question("Who approves AED 1.5 million?", self.kb, self.settings)
        self.assertEqual(answer.status, "complete")
        self.assertIn("AED 1,500,000", answer.body)
        self.assertIn("CFO plus CEO", answer.body)
        self.assertNotIn("AED 1,", answer.body.replace("AED 1,500,000", ""))

        thousand_answer = answer_question("Who approves AED 10.5 thousand?", self.kb, self.settings)
        self.assertEqual(thousand_answer.status, "complete")
        self.assertIn("AED 10,500", thousand_answer.body)
        self.assertIn("Director plus Finance Manager", thousand_answer.body)

        decimal_answer = answer_question("Who approves AED 60,000.50.", self.kb, self.settings)
        self.assertEqual(decimal_answer.status, "complete")
        self.assertIn("AED 60,000.50", decimal_answer.body)
        self.assertIn("VP/COO plus Finance Controller", decimal_answer.body)

    def test_financial_approval_boundaries_are_exact(self):
        cases = (
            ("AED 10,000", "Manager plus independent budget/finance check"),
            ("AED 10,001", "Director plus Finance Manager"),
            ("AED 50,000", "Director plus Finance Manager"),
            ("AED 50,001", "VP/COO plus Finance Controller"),
            ("AED 250,000", "VP/COO plus Finance Controller"),
            ("AED 250,000.01", "CFO plus CEO"),
        )
        for amount, approver in cases:
            with self.subTest(amount=amount):
                answer = answer_question(f"Who approves {amount}?", self.kb, self.settings)
                self.assertEqual(answer.status, "complete")
                self.assertIn(approver, answer.body)

    def test_fractional_holes_in_financial_matrix_are_not_rounded_down(self):
        cases = (
            ("AED 10,000.50", "Manager plus independent budget/finance check"),
            ("AED 50,000.99", "Director plus Finance Manager"),
        )
        for amount, lower_approver in cases:
            with self.subTest(amount=amount):
                answer = answer_question(f"Who approves {amount}?", self.kb, self.settings)
                self.assertEqual(answer.status, "partial")
                self.assertFalse(answer.grounded)
                self.assertIn(amount, answer.body)
                self.assertIn("does not assign fractional values", answer.body)
                self.assertNotIn(f"financial authority is **{lower_approver}**", answer.body)

    def test_multiple_estimated_and_malformed_financial_amounts_need_clarification(self):
        cases = (
            ("Who approves AED 10,000 or AED 60,000?", "multiple amounts"),
            ("Who approves about AED 60,000?", "stated as an estimate"),
            ("Who approves AED 1.5.6 million?", "malformed amount"),
            ("Who approves AED 10,00?", "malformed amount"),
        )
        for question, explanation in cases:
            with self.subTest(question=question):
                answer = answer_question(question, self.kb, self.settings)
                self.assertEqual(answer.status, "partial")
                self.assertFalse(answer.grounded)
                self.assertIn(explanation, answer.body)
                self.assertNotIn("financial authority is", answer.body)

    def test_compound_financial_question_answers_supported_part_only(self):
        answer = answer_question(
            "Who approves a financial commitment of AED 60,000 and what is the CEO mobile number?",
            self.kb,
            self.settings,
        )
        self.assertEqual(answer.status, "partial")
        self.assertFalse(answer.grounded)
        self.assertIn("VP/COO plus Finance Controller", answer.body)
        self.assertIn("telephone or contact number", answer.body)
        self.assertEqual({hit.passage.document_id for hit in answer.hits}, {"FIN-001"})
        self.assertEqual(
            {hit.passage.clause_id for hit in answer.hits},
            {"FIN-001-3.1", "FIN-001-3.2"},
        )

    def test_compound_sick_leave_and_password_reset_question_is_partial(self):
        answer = answer_question(
            "When does sick leave require a medical certificate and how do I reset the payroll password?",
            self.kb,
            self.settings,
        )
        self.assertEqual(answer.status, "partial")
        self.assertFalse(answer.grounded)
        self.assertIn("exceeding two consecutive calendar days", answer.body)
        self.assertIn("password or account-access reset procedure", answer.body)
        self.assertEqual({hit.passage.document_id for hit in answer.hits}, {"HR-005"})
        self.assertNotIn("FIN-001", answer.body)

        paraphrase = answer_question(
            "When is a medical report required for sickness, and how can I recover access to my payroll login?",
            self.kb,
            self.settings,
        )
        self.assertEqual(paraphrase.status, "partial")
        self.assertIn("password or account-access reset procedure", paraphrase.body)
        self.assertEqual({hit.passage.document_id for hit in paraphrase.hits}, {"HR-005"})

    def test_third_vendor_meal_requires_specific_advance_approval(self):
        answer = answer_question(
            "A vendor has offered me a third meal in 90 days. Each meal was below AED 300. Can I accept?",
            self.kb,
            self.settings,
        )
        self.assertTrue(answer.grounded)
        self.assertEqual(answer.hits[0].passage.clause_id, "PRC-005-3.8")
        self.assertIn("Do not accept the invitation yet", answer.body)
        self.assertIn("Compliance Officer plus Function Director", answer.body)
        self.assertIn("third same-vendor hospitality event", answer.body)
        self.assertNotIn("route this to the appropriate owner", answer.body)

    def test_return_question_keeps_customer_facing_wording(self):
        answer = answer_question(
            "A customer wants to return a defective item after 38 days. What should I say?",
            self.kb,
            self.settings,
        )
        self.assertIn("Suggested customer wording", answer.body)
        self.assertIn("The item will be inspected", answer.body)

    def test_damaged_product_exchange_routes_to_inspection_then_linked_exchange(self):
        questions = (
            "A customer brings in a damaged product and wants an exchange. What should I do?",
            "A shopper says an item is faulty and asks for a replacement. Can I give them one?",
        )
        for question in questions:
            with self.subTest(question=question):
                answer = answer_question(question, self.kb, self.settings)
                self.assertTrue(answer.grounded)
                self.assertEqual(answer.status, "complete")
                self.assertIn("arrange a product inspection first", answer.body)
                self.assertIn("do not promise an exchange", answer.body)
                self.assertIn("linked new purchase", answer.body)
                self.assertIn("RET-002", {hit.passage.document_id for hit in answer.hits})
                self.assertIn("RET-001-4.6", {hit.passage.clause_id for hit in answer.hits})

    def test_overnight_petty_cash_and_food_allowance_are_not_conflated(self):
        cases = (
            ("If my staff are going to work overnight tonight, can I issue them petty cash?", True),
            ("How much petty cash can I issue staff working overnight as a food allowance?", True),
            ("What is the food allowance policy?", False),
            ("What meal allowance do employees on the night shift receive?", False),
        )
        for question, expects_cash_policy in cases:
            with self.subTest(question=question):
                answer = answer_question(question, self.kb, self.settings)
                self.assertFalse(answer.grounded)
                self.assertEqual(answer.status, "partial")
                self.assertIn("does not", answer.body)
                self.assertNotIn("education allowance", answer.body.lower())
                self.assertNotIn("HR-006", {hit.passage.document_id for hit in answer.hits})
                if expects_cash_policy:
                    self.assertIn("cash-channel ceiling", answer.body)
                    self.assertEqual({hit.passage.document_id for hit in answer.hits}, {"FIN-005"})
                else:
                    self.assertIn("food-allowance entitlement", answer.body)
                    self.assertEqual({hit.passage.document_id for hit in answer.hits}, {"FIN-002"})

    def test_uniform_scope_question_identifies_covered_store_team(self):
        questions = (
            "Does the uniform policy only apply to certain team members in the store? If yes, who are they?",
            "Which employees are eligible for company uniforms?",
        )
        for question in questions:
            with self.subTest(question=question):
                answer = answer_question(question, self.kb, self.settings)
                self.assertTrue(answer.grounded)
                self.assertEqual(answer.status, "complete")
                self.assertIn("store-based retail staff only", answer.body)
                self.assertIn("frontline retail employees", answer.body)
                self.assertEqual({hit.passage.document_id for hit in answer.hits}, {"HR-003"})

    def test_nonsense_question_refuses(self):
        answer = answer_question("What colour is the moon on Neptune?", self.kb, self.settings)
        self.assertFalse(answer.grounded)
        self.assertEqual(answer.status, "unavailable")
        self.assertIn("cannot find a policy", answer.body)
        self.assertIn("line manager", answer.body)
        self.assertEqual(answer.hits, [])

    def test_annual_leave_carryover_is_now_covered_by_hr_policy(self):
        answer = answer_question("How many days of annual leave can I carry forward?", self.kb, self.settings)
        self.assertTrue(answer.grounded)
        self.assertIn("HR-004", {hit.passage.document_id for hit in answer.hits})
        self.assertTrue(any("maximum of 5" in hit.passage.text for hit in answer.hits))

    def test_annual_leave_entitlement_does_not_substitute_sick_leave(self):
        answer = answer_question("How many days of paid annual leave can I get in a year?", self.kb, self.settings)
        self.assertFalse(answer.grounded)
        self.assertEqual(answer.status, "partial")
        self.assertIn("annual leave entitlement", answer.body)
        self.assertNotIn("fully paid sick leave", answer.body)

    def test_combining_sick_and_annual_leave_is_partial_across_paraphrases(self):
        questions = (
            "Can I combine sick leave with annual leave?",
            "Can I take annual leave immediately after sick leave?",
            "Can I convert sick leave into annual leave?",
            "If I become sick during annual leave, does the annual leave stop?",
            "Can I use annual leave instead of sick leave if I have no medical certificate?",
            "May I take sick leave and annual leave back-to-back?",
            "Can I take sick leave along with annual leave?",
            "Can sick leave be added to my annual leave?",
            "Can I book annual leave following sick leave?",
        )
        for question in questions:
            with self.subTest(question=question):
                answer = answer_question(question, self.kb, self.settings)
                self.assertFalse(answer.grounded)
                self.assertEqual(answer.status, "partial")
                self.assertEqual(answer.mode, "Guardrail · partial evidence")
                self.assertIn("separate current policies", answer.body)
                self.assertIn("cannot confirm", answer.body)
                self.assertEqual(
                    {hit.passage.document_id for hit in answer.hits},
                    {"HR-004", "HR-005"},
                )
                self.assertNotIn("### Direct answer", answer.body)

    def test_other_undocumented_leave_relationships_are_partial(self):
        questions = (
            "Can I combine annual leave with maternity leave?",
            "Can I take unpaid leave after annual leave?",
        )
        for question in questions:
            with self.subTest(question=question):
                answer = answer_question(question, self.kb, self.settings)
                self.assertFalse(answer.grounded)
                self.assertEqual(answer.status, "partial")
                self.assertIn("not documented", answer.body)
                self.assertIn("HR-004", {hit.passage.document_id for hit in answer.hits})

    def test_undocumented_leave_accrual_cashout_and_sick_rollover_are_partial(self):
        questions_and_missing = (
            ("Can unused sick leave be paid out?", "cashed out or paid in lieu"),
            ("Can annual leave be encashed?", "cashed out or paid in lieu"),
            ("How quickly does annual leave accrue?", "accrual or earning rate"),
            ("Can I carry unused sick leave into next year?", "unused sick leave carries over"),
        )
        for question, missing in questions_and_missing:
            with self.subTest(question=question):
                answer = answer_question(question, self.kb, self.settings)
                self.assertFalse(answer.grounded)
                self.assertEqual(answer.status, "partial")
                self.assertIn(missing, answer.body)

    def test_undocumented_leave_types_without_any_policy_are_unavailable(self):
        questions = (
            "Can I combine maternity leave with paternity leave?",
            "Can maternity leave be cashed out?",
        )
        for question in questions:
            with self.subTest(question=question):
                answer = answer_question(question, self.kb, self.settings)
                self.assertFalse(answer.grounded)
                self.assertEqual(answer.status, "unavailable")
                self.assertEqual(answer.hits, [])

    def test_rfid_operational_question_does_not_substitute_cashier_training(self):
        answer = answer_question("Tell me the RFID procedures.", self.kb, self.settings)
        self.assertTrue(answer.grounded)
        self.assertIn("TEC-001", {hit.passage.document_id for hit in answer.hits})
        self.assertIn("blind cycle counts", answer.body)
        for clause_id in ("TEC-001-4.1", "TEC-001-4.2", "TEC-001-4.3", "TEC-001-4.4", "TEC-001-4.5"):
            self.assertIn(clause_id, answer.body)
        self.assertNotIn("contractors receive the ethics code", answer.body.lower())
        self.assertNotIn("Sales Associate induction is a structured", answer.body)

    def test_stocktake_operation_routes_to_stocktake_preparation(self):
        answer = answer_question("What process applies to stocktakes?", self.kb, self.settings)
        self.assertTrue(answer.grounded)
        self.assertIn("system freeze", answer.body)
        self.assertIn("OPS-013", answer.body)

    def test_exact_destination_requests_remain_partial_when_not_documented(self):
        answer = answer_question("Which portal do I use to upload a late invoice?", self.kb, self.settings)
        self.assertFalse(answer.grounded)
        self.assertEqual(answer.status, "partial")
        self.assertIn("company-portal URL", answer.body)
        self.assertIn("PRC-002", answer.body)

    def test_mandatory_refresher_request_does_not_invent_a_schedule(self):
        answer = answer_question("When is the next mandatory cashier refresher course?", self.kb, self.settings)
        self.assertFalse(answer.grounded)
        self.assertEqual(answer.status, "partial")
        self.assertIn("whether refresher training is mandatory", answer.body)

    def test_exact_medical_provider_request_remains_partial(self):
        answer = answer_question("Which hospital must issue my sick leave certificate?", self.kb, self.settings)
        self.assertFalse(answer.grounded)
        self.assertEqual(answer.status, "partial")
        self.assertIn("approved hospital", answer.body)

    def test_exact_blackout_dates_are_not_invented(self):
        answer = answer_question("What are the exact dates of this year's annual leave blackout?", self.kb, self.settings)
        self.assertFalse(answer.grounded)
        self.assertEqual(answer.status, "partial")
        self.assertIn("exact annual-leave blackout dates", answer.body)

    def test_compound_salary_advance_and_payday_question_is_partial(self):
        answer = answer_question("How much salary advance can I request and when is payday?", self.kb, self.settings)
        self.assertFalse(answer.grounded)
        self.assertEqual(answer.status, "partial")
        self.assertIn("payroll date", answer.body)
        self.assertIn("PAY-001", {hit.passage.document_id for hit in answer.hits})

    def test_compound_fleet_and_refuelling_question_is_partial(self):
        answer = answer_question("How do I hire an external fleet and refuel the truck?", self.kb, self.settings)
        self.assertFalse(answer.grounded)
        self.assertEqual(answer.status, "partial")
        self.assertIn("refuelling", answer.body)
        self.assertIn("LOG-001", {hit.passage.document_id for hit in answer.hits})

    def test_standalone_undocumented_payday_and_refuelling_questions_are_unavailable(self):
        for question in ("When is payday?", "How do I refuel the warehouse truck?"):
            with self.subTest(question=question):
                answer = answer_question(question, self.kb, self.settings)
                self.assertFalse(answer.grounded)
                self.assertEqual(answer.status, "unavailable")
                self.assertEqual(answer.hits, [])

    def test_leave_carryover_plus_missing_use_by_date_is_partial(self):
        for question in (
            "How many annual leave days can I carry over and what is the use-by date?",
            "How many leave days can I carry over and what is the use-by date?",
        ):
            with self.subTest(question=question):
                answer = answer_question(question, self.kb, self.settings)
                self.assertFalse(answer.grounded)
                self.assertEqual(answer.status, "partial")
                self.assertIn("use-by date", answer.body)
                self.assertIn("HR-004", {hit.passage.document_id for hit in answer.hits})

    def test_exact_company_sick_leave_pay_is_supported_but_legal_basis_is_partial(self):
        company_answer = answer_question("What is the exact sick leave pay entitlement?", self.kb, self.settings)
        self.assertTrue(company_answer.grounded)
        self.assertEqual(company_answer.status, "complete")
        legal_answer = answer_question("What is the exact statutory sick leave pay entitlement under the law?", self.kb, self.settings)
        self.assertFalse(legal_answer.grounded)
        self.assertEqual(legal_answer.status, "partial")

    def test_requests_for_credential_values_are_unavailable(self):
        answer = answer_question("What is the password for the inventory system?", self.kb, self.settings)
        self.assertFalse(answer.grounded)
        self.assertEqual(answer.status, "unavailable")
        self.assertEqual(answer.hits, [])

    def test_missing_formal_definition_and_contact_number_remain_partial(self):
        questions = (
            "What is the definition of a salary advance?",
            "Who approves a new social media agency and what is its phone number?",
        )
        for question in questions:
            with self.subTest(question=question):
                answer = answer_question(question, self.kb, self.settings)
                self.assertFalse(answer.grounded)
                self.assertEqual(answer.status, "partial")
                self.assertTrue(answer.hits)

    def test_it_password_question_routes_to_it_without_using_vendor_policy(self):
        answer = answer_question(
            "A vendor employee forgot their laptop password. How do I reset it?",
            self.kb,
            self.settings,
        )
        self.assertFalse(answer.grounded)
        self.assertEqual(answer.status, "unavailable")
        self.assertIn("IT Service Desk", answer.body)
        self.assertEqual(answer.hits, [])

    def test_unknown_logistics_process_routes_to_supply_chain(self):
        answer = answer_question("How do I refuel and operate a warehouse forklift?", self.kb, self.settings)
        self.assertFalse(answer.grounded)
        self.assertEqual(answer.status, "unavailable")
        self.assertIn("Logistics or Supply Chain manager", answer.body)
        self.assertEqual(answer.hits, [])

    def test_scope_gate_accepts_supported_policy_topics(self):
        self.assertIn("RET-002", self.kb.scope_matches("A customer returned a defective item"))
        self.assertIn("LOG-001", self.kb.scope_matches("Activate an external fleet during peak demand"))
        self.assertEqual(self.kb.scope_matches("Explain the office birthday cake procedure"), [])

    def test_optional_backend_policy_filter_remains_available_for_non_ui_uses(self):
        hr = {"Human Resources & Payroll"}
        logistics = {"Logistics & Supply Chain"}
        self.assertIn("HR-004", {hit.passage.document_id for hit in self.kb.search("annual leave carry over", functions=hr)})
        answer = answer_question("How many days of annual leave can I carry forward?", self.kb, self.settings, functions=logistics)
        self.assertTrue(answer.grounded)

    def test_every_displayed_suggestion_has_a_grounded_expected_answer(self):
        for policy_area, suggestions in SUGGESTED_QUESTIONS.items():
            with self.subTest(policy_area=policy_area):
                self.assertEqual(len(suggestions), 4)
            for suggestion in suggestions:
                with self.subTest(policy_area=policy_area, question=suggestion.text):
                    answer = answer_question(suggestion.text, self.kb, self.settings)
                    self.assertTrue(answer.grounded, answer.body)
                    self.assertIn(
                        suggestion.expected_document_id,
                        {hit.passage.document_id for hit in answer.hits},
                    )

    def test_medical_certificate_answer_contains_requirement_and_exception(self):
        answer = answer_question("When does sick leave require a medical certificate?", self.kb, self.settings)
        self.assertTrue(answer.grounded)
        self.assertIn("exceeding two consecutive calendar days", answer.body)
        self.assertIn("licensed practitioner", answer.body)
        self.assertIn("unless lawfully requested by HR", answer.body)
        self.assertNotIn("calculate the complete value", answer.body)
        self.assertIn("approved channel", answer.body)

    def test_cashier_training_answer_contains_confirmed_requirements(self):
        answer = answer_question("What training and certification does a new cashier need?", self.kb, self.settings)
        self.assertEqual(answer.status, "complete")
        for detail in ("30-day", "80%", "direct supervision"):
            self.assertIn(detail, answer.body)
        self.assertNotIn("itemised reading-material", answer.body)
        self.assertNotIn("calculate the complete value", answer.body)

    def test_pos_definition_does_not_substitute_return_procedures(self):
        for question in ("What is a POS?", "What does POS stand for?", "Explain the POS system", "Define POS"):
            with self.subTest(question=question):
                answer = answer_question(question, self.kb, self.settings)
                self.assertFalse(answer.grounded)
                self.assertEqual(answer.hits, [])
                self.assertNotIn("RET-001", answer.body)

    def test_guardrail_case_library(self):
        cases = json.loads((ROOT / "tests" / "guardrail_cases.json").read_text(encoding="utf-8"))
        for case in cases:
            with self.subTest(case=case["id"]):
                answer = answer_question(case["question"], self.kb, self.settings)
                self.assertFalse(answer.grounded)
                self.assertEqual(answer.mode, case["expected_mode"])
                self.assertIn(case["expected_contact"], answer.body)

    def test_every_v110_regression_case_retrieves_expected_clause(self):
        questions = json.loads(
            (ROOT / "tests" / "evaluation_seed_set.json").read_text(encoding="utf-8")
        )[-12:]
        for question in questions:
            with self.subTest(question=question["id"]):
                retrieved = {hit.passage.clause_id for hit in self.kb.search(question["question"], limit=5)}
                self.assertTrue(retrieved.intersection(question["must_cite"]))

    def test_history_is_user_scoped_and_feedback_is_saved(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "test.db"
            initialise(database)
            item_id = save(database, "one@example.com", "Question", "Answer", "Demo", ["RET-001-4.1"])
            save(database, "two@example.com", "Other", "Answer", "Demo", [])
            set_feedback(database, item_id, "one@example.com", "helpful")
            rows = history(database, "one@example.com")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0][-1], "helpful")

    def test_personal_governance_metrics_do_not_mix_users(self):
        rows = [
            (1, "now", "q", "a", "Evidence complete", "", "helpful"),
            (2, "now", "q", "a", "Guardrail · partial evidence", "", "needs_review"),
        ]
        self.assertEqual(
            personal_metrics(rows),
            {"questions": 2, "evidence_complete": 1, "needs_attention": 1, "flagged_for_review": 1},
        )

    def test_governance_context_uses_answer_owner_and_matched_policy_area(self):
        answer = answer_question("When does sick leave require a medical certificate?", self.kb, self.settings)
        context = context_for(answer, self.kb)
        self.assertEqual(context.answer_status, "complete")
        self.assertEqual(context.policy_area, "Human Resources & Payroll")
        self.assertTrue(context.recommended_owner)

    def test_supabase_store_saves_through_identity_bound_function(self):
        client = FakeClient()
        store = SupabaseConversationStore(client, "user-123")
        item_id = store.save("ignored@example.com", "Question", "Answer", "Demo", ["RET-001-4.1"])
        self.assertEqual(item_id, "conversation-1")
        name, params = client.rpc_calls[-1]
        self.assertEqual(name, "pippa_save_conversation")
        self.assertNotIn("user_id", params)
        self.assertNotIn("user_email", params)
        self.assertEqual(params["p_question"], "Question")

    def test_supabase_history_uses_caller_identity_not_email(self):
        client = FakeClient()
        client.rpc_responses["pippa_my_history"] = [
            {
                "id": "own-conversation",
                "created_at": "2026-09-09T10:00:00Z",
                "question": "My question",
                "answer": "My answer",
                "mode": "Evidence complete",
                "source_ids": ["HR-005-4.1"],
                "feedback": None,
            }
        ]
        store = SupabaseConversationStore(client, "user-123")
        rows = store.history("someone-else@example.com")
        self.assertEqual(rows[0][0], "own-conversation")
        self.assertEqual(client.rpc_calls[-1], ("pippa_my_history", {"p_limit": 20}))

    def test_supabase_feedback_and_review_status_use_separate_functions(self):
        client = FakeClient()
        store = SupabaseConversationStore(client, "reviewer-123")
        store.set_feedback("conversation-1", "ignored@example.com", "needs_review")
        self.assertEqual(client.rpc_calls[-1][0], "pippa_set_my_feedback")
        self.assertNotIn("user_id", client.rpc_calls[-1][1])

        store.set_review_status("conversation-1", "resolved")
        self.assertEqual(client.rpc_calls[-1][0], "pippa_transition_review")
        self.assertEqual(client.rpc_calls[-1][1]["p_new_status"], "resolved")

        with self.assertRaises(ValueError):
            store.set_review_status("conversation-1", "new")

    def test_reviewer_queue_uses_restricted_function(self):
        client = FakeClient()
        client.rpc_responses["pippa_reviewer_queue"] = [
            {"id": "conversation-1", "question": "Review me", "review_status": "new"}
        ]
        store = SupabaseConversationStore(client, "reviewer-123")
        rows = store.reviewer_queue()
        self.assertEqual(rows[0]["question"], "Review me")
        self.assertNotIn("answer", rows[0])
        self.assertEqual(client.rpc_calls[-1][0], "pippa_reviewer_queue")

    def test_supabase_feedback_is_limited_to_supported_values(self):
        store = SupabaseConversationStore(FakeClient(), "user-123")
        with self.assertRaises(ValueError):
            store.set_feedback("conversation-1", "ignored@example.com", "delete_everything")

    def test_auth_rejects_non_email_callback_type_before_network(self):
        auth = SupabaseAuth("https://example.supabase.co", "publishable", "http://localhost:8501")
        with self.assertRaises(AuthenticationError):
            auth.verify_token_hash("token", "recovery")

    def test_rememberable_tokens_supports_supabase_direct_session_shape(self):
        client = FakeSupabaseClient()
        session = AuthenticatedSession(client, "verified-user", "verified@example.com")
        self.assertEqual(
            session.rememberable_tokens(),
            {"access_token": "new-access", "refresh_token": "new-refresh"},
        )

    def test_restore_session_revalidates_identity_with_supabase(self):
        client = FakeSupabaseClient()
        auth = SupabaseAuth("https://example.supabase.co", "publishable", "http://localhost:8501")
        auth._client = lambda: client
        restored = auth.restore_session("old-access", "old-refresh")
        self.assertEqual(client.auth.set_session_args, ("old-access", "old-refresh"))
        self.assertEqual(restored.user_id, "verified-user")
        self.assertEqual(restored.email, "verified@example.com")

    def test_restore_session_rejects_unverified_identity(self):
        client = FakeSupabaseClient(FakeAuthClient(verified_user=FakeUser(user_id="", email="")))
        auth = SupabaseAuth("https://example.supabase.co", "publishable", "http://localhost:8501")
        auth._client = lambda: client
        with self.assertRaises(AuthenticationError):
            auth.restore_session("old-access", "old-refresh")

    def test_magic_link_error_identifies_incompatible_local_runtime(self):
        error = ModuleNotFoundError("No module named 'pydantic_core._pydantic_core'")
        message = _safe_magic_link_error(error)
        self.assertIn("Python environment", message)
        self.assertIn("Start PIPPA.bat", message)

    def test_magic_link_error_identifies_rate_limit(self):
        error = RuntimeError("email rate limit exceeded")
        message = _safe_magic_link_error(error)
        self.assertIn("60 seconds", message)

    def test_windows_launcher_uses_the_configured_auth_callback_port(self):
        launcher = (ROOT / "Start PIPPA.bat").read_text(encoding="utf-8")
        self.assertIn("--server.port 8501", launcher)

    def test_restart_launcher_only_releases_a_verified_streamlit_app(self):
        restart = (ROOT / "Restart PIPPA.bat").read_text(encoding="utf-8")
        release = (ROOT / "scripts" / "release_pippa_port.ps1").read_text(encoding="utf-8")
        self.assertIn("release_pippa_port.ps1", restart)
        self.assertIn("$isPython", release)
        self.assertIn("$isStreamlitApp", release)
        self.assertIn("will not terminate", release)

    def test_supabase_schema_has_rls_and_no_anon_grants(self):
        schema = (ROOT / "supabase" / "schema.sql").read_text(encoding="utf-8").lower()
        self.assertIn("enable row level security", schema)
        self.assertIn("force row level security", schema)
        self.assertIn("revoke all on table public.conversations from anon", schema)
        self.assertGreaterEqual(schema.count("auth.uid()"), 6)

    def test_reviewer_setup_keeps_cross_user_access_restricted(self):
        setup = (ROOT / "supabase" / "governance_reviewer_setup.sql").read_text(encoding="utf-8").lower()
        self.assertIn("force row level security", setup)
        self.assertIn("is_pippa_reviewer", setup)
        self.assertIn("c.feedback = 'needs_review' or c.answer_status in ('partial', 'unavailable')", setup)
        self.assertIn("revoke all on table public.conversations from anon, authenticated", setup)
        self.assertIn("pippa_my_history", setup)
        self.assertIn("pippa_set_my_feedback", setup)
        self.assertIn("pippa_reviewer_queue", setup)
        self.assertIn("pippa_transition_review", setup)
        self.assertIn("pippa_review_actions", setup)
        reviewer_function = setup.split("create or replace function public.pippa_reviewer_queue", 1)[1].split(
            "create or replace function public.pippa_transition_review", 1
        )[0]
        self.assertNotIn("c.answer,", reviewer_function)
        self.assertNotIn("c.answer from", reviewer_function)
        self.assertNotIn("c.user_id", reviewer_function)

    def test_phase_one_database_migration_is_present_and_transactional(self):
        migration = ROOT / "supabase" / "migrations" / "202609090001_phase1_employee_privacy.sql"
        sql = migration.read_text(encoding="utf-8").lower()
        self.assertTrue(sql.strip().startswith("-- upgrade"))
        self.assertIn("begin;", sql)
        self.assertIn("commit;", sql)
        self.assertIn("set search_path = ''", sql)

    def test_secret_supabase_key_is_rejected(self):
        settings = RuntimeSettings(
            supabase_url="https://example.supabase.co",
            supabase_publishable_key="sb_secret_do_not_use",
        )
        self.assertTrue(settings.supabase_key_is_unsafe)

    def test_remembered_sign_in_requires_an_explicit_long_secret(self):
        disabled = RuntimeSettings(
            supabase_url="https://example.supabase.co",
            supabase_publishable_key="publishable",
            cookie_password="short",
        )
        enabled = RuntimeSettings(
            supabase_url="https://example.supabase.co",
            supabase_publishable_key="publishable",
            cookie_password="a" * 32,
        )
        self.assertFalse(disabled.remembered_sign_in_enabled)
        self.assertTrue(enabled.remembered_sign_in_enabled)

    def test_remembered_session_payload_rejects_invalid_and_expired_cookies(self):
        valid = json.dumps(
            {
                "tokens": {"access_token": "access", "refresh_token": "refresh"},
                "expires_at": 200,
            }
        )
        self.assertEqual(parse_remembered_session_payload(valid, now=100), ("access", "refresh", 200))
        for payload in ("not-json", "[]", valid.replace("200", "100")):
            with self.subTest(payload=payload):
                with self.assertRaises(AuthenticationError):
                    parse_remembered_session_payload(payload, now=100)

    def test_sign_out_cookie_clear_removes_session_and_pending_intent(self):
        cookies = FakeCookies(
            {
                REMEMBERED_SESSION_COOKIE: "encrypted-session",
                REMEMBERED_INTENT_COOKIE: "yes",
            }
        )
        clear_remembered_session_cookies(cookies)
        self.assertNotIn(REMEMBERED_SESSION_COOKIE, cookies)
        self.assertNotIn(REMEMBERED_INTENT_COOKIE, cookies)
        self.assertTrue(cookies.saved)

    def test_insights_setup_preserves_employee_privacy(self):
        setup = (ROOT / "supabase" / "insights_and_remembered_signin_setup.sql").read_text(encoding="utf-8").lower()
        self.assertIn("enable row level security", setup)
        self.assertIn("force row level security", setup)
        self.assertIn("is_pippa_administrator", setup)
        self.assertIn("never question or answer text", setup)
        self.assertIn("revoke insert on table public.conversations", setup)
        self.assertIn('drop policy if exists "users insert own usage events"', setup)
        self.assertNotIn("grant select, insert on table public.pippa_usage_events", setup)
        self.assertGreaterEqual(setup.count("set search_path = ''"), 3)
        self.assertIn("role = 'administrator'", setup)
        self.assertNotIn("select c.question", setup)
        self.assertNotIn("select c.answer", setup)

    def test_usage_events_reject_unsupported_event_types(self):
        store = SupabaseConversationStore(FakeClient(), "user-123")
        with self.assertRaises(ValueError):
            store.record_usage_event("raw_question_text")

    def test_question_validation_rejects_empty_and_accepts_exact_boundary(self):
        with self.assertRaises(QuestionValidationError):
            validate_question("   \n")
        exact = "x" * MAX_QUESTION_CHARS
        self.assertEqual(validate_question(f" {exact} "), exact)
        with self.assertRaises(QuestionValidationError) as raised:
            validate_question("x" * (MAX_QUESTION_CHARS + 1))
        self.assertIn("4,001", str(raised.exception))
        self.assertIn("4,000", str(raised.exception))

    def test_question_validation_rejects_null_control_character(self):
        with self.assertRaises(QuestionValidationError):
            validate_question("How do I do this?\x00")

    def test_question_capacity_releases_slots_and_rejects_overflow(self):
        capacity = QuestionCapacity(maximum=2)
        first = capacity.slot(timeout_seconds=0)
        second = capacity.slot(timeout_seconds=0)
        first.__enter__()
        second.__enter__()
        try:
            with self.assertRaises(QuestionCapacityError):
                with capacity.slot(timeout_seconds=0):
                    pass
        finally:
            second.__exit__(None, None, None)
            first.__exit__(None, None, None)
        with capacity.slot(timeout_seconds=0):
            pass

    def test_sign_in_email_key_is_normalized_and_does_not_expose_email(self):
        secret = "rate-limit-secret-" + "x" * 32
        first = sign_in_email_key(" Person@Example.com ", secret)
        second = sign_in_email_key("person@example.com", secret)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)
        self.assertNotIn("person", first)
        with self.assertRaises(ValueError):
            sign_in_email_key("person@example.com", "short")

    def test_public_runtime_configuration_fails_closed_without_controls(self):
        missing_auth = RuntimeSettings()
        self.assertTrue(missing_auth.configuration_errors)
        local = RuntimeSettings(local_demo_enabled=True)
        self.assertEqual(local.configuration_errors, ())
        incomplete_public = RuntimeSettings(
            supabase_url="https://example.supabase.co",
            supabase_publishable_key="publishable",
            public_access_enabled=True,
        )
        self.assertGreaterEqual(len(incomplete_public.configuration_errors), 2)
        complete_public = RuntimeSettings(
            supabase_url="https://example.supabase.co",
            supabase_publishable_key="publishable",
            public_access_enabled=True,
            turnstile_site_key="public-site-key",
            rate_limit_secret="x" * 32,
        )
        self.assertEqual(complete_public.configuration_errors, ())

    def test_explicit_local_demo_ignores_hosted_sign_in_values(self):
        hosted_values = SimpleNamespace(
            secrets={
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_PUBLISHABLE_KEY": "publishable",
                "PIPPA_APP_URL": "http://localhost:8501",
            }
        )
        with patch.dict(sys.modules, {"streamlit": hosted_values}), patch.dict(
            os.environ, {"PIPPA_LOCAL_DEMO": "true"}, clear=True
        ):
            settings = RuntimeSettings.from_sources()

        self.assertTrue(settings.local_demo_enabled)
        self.assertFalse(settings.supabase_enabled)
        self.assertEqual(settings.configuration_errors, ())

    def test_magic_link_uses_captcha_and_hmac_quota_authorization(self):
        client = FakeSupabaseClient()
        secret = "s" * 32
        auth = SupabaseAuth(
            "https://example.supabase.co",
            "publishable",
            "https://pippa.example.com",
            secret,
        )
        auth._client = lambda: client
        request_id = "11111111-1111-4111-8111-111111111111"
        auth.request_magic_link(
            "Person@Example.com", captcha_token="turnstile-token", request_id=request_id
        )
        rpc_name, rpc_params = client.rpc_calls[0]
        self.assertEqual(rpc_name, "pippa_authorize_sign_in")
        self.assertEqual(rpc_params["p_request_id"], request_id)
        self.assertEqual(rpc_params["p_app_secret"], secret)
        self.assertNotIn("person@example.com", str(rpc_params).lower())
        self.assertEqual(
            client.auth.sign_in_payload["options"]["captcha_token"],
            "turnstile-token",
        )
        self.assertTrue(client.auth.sign_in_payload["options"]["should_create_user"])

    def test_safe_magic_link_errors_cover_phase_three_quotas_and_captcha(self):
        self.assertIn("60 seconds", _safe_magic_link_error(RuntimeError("PIPPA_AUTH_RESEND")))
        self.assertIn("allowance", _safe_magic_link_error(RuntimeError("PIPPA_AUTH_ADDRESS_HOUR")))
        self.assertIn("busy", _safe_magic_link_error(RuntimeError("PIPPA_AUTH_GLOBAL_HOUR")))
        self.assertIn("security check", _safe_magic_link_error(RuntimeError("captcha verification failed")))

    def test_active_session_is_revalidated_without_allowing_identity_change(self):
        valid_client = FakeSupabaseClient()
        active = AuthenticatedSession(valid_client, "verified-user", "verified@example.com")
        active.revalidate()

        changed_client = FakeSupabaseClient(
            FakeAuthClient(verified_user=FakeUser("different-user", "other@example.com"))
        )
        changed = AuthenticatedSession(changed_client, "verified-user", "verified@example.com")
        with self.assertRaises(AuthenticationError):
            changed.revalidate()

    def test_stale_active_session_is_rejected_when_provider_validation_fails(self):
        class StaleAuthClient(FakeAuthClient):
            def get_user(self):
                raise RuntimeError("session revoked")

        stale = AuthenticatedSession(
            FakeSupabaseClient(StaleAuthClient()),
            "verified-user",
            "verified@example.com",
        )
        with self.assertRaises(AuthenticationError) as raised:
            stale.revalidate()
        self.assertIn("no longer valid", str(raised.exception))

    def test_revoked_session_rejected_even_when_auth_user_remains_valid(self):
        client = FakeSupabaseClient()
        client.rpc_responses["pippa_active_user_id"] = None
        with self.assertRaises(AuthenticationError):
            AuthenticatedSession(client, "verified-user", "verified@example.com").revalidate()

    def test_restore_rejects_revoked_database_session(self):
        client = FakeSupabaseClient()
        client.rpc_responses["pippa_active_user_id"] = None
        auth = SupabaseAuth("https://example.supabase.co", "publishable", "https://pippa.example.com")
        auth._client = lambda: client
        with self.assertRaises(AuthenticationError):
            auth.restore_session("unexpired-access", "revoked-refresh")

    def test_session_check_failure_fails_closed(self):
        class BrokenSessionCheck(FakeSupabaseClient):
            def rpc(self, name, params=None):
                raise RuntimeError("database unavailable")
        with self.assertRaises(AuthenticationError):
            AuthenticatedSession(BrokenSessionCheck(), "verified-user", "verified@example.com").revalidate()

    def test_refresh_token_rotation_returns_replacement_tokens_without_extending_deadline(self):
        client = FakeSupabaseClient(
            FakeAuthClient(session=FakeSession("rotated-access", "rotated-refresh"))
        )
        auth = SupabaseAuth("https://example.supabase.co", "publishable", "https://pippa.example.com")
        auth._client = lambda: client
        restored = auth.restore_session("stale-access", "single-use-refresh")
        self.assertEqual(
            restored.rememberable_tokens(),
            {"access_token": "rotated-access", "refresh_token": "rotated-refresh"},
        )
        fixed_deadline = 2_000_000_000
        payload = json.dumps(
            {"tokens": restored.rememberable_tokens(), "expires_at": fixed_deadline}
        )
        self.assertEqual(parse_remembered_session_payload(payload, now=1_900_000_000)[2], fixed_deadline)

    def test_auth_callback_never_auto_switches_an_active_tab(self):
        self.assertTrue(auth_callback_allowed(False, "token", "email"))
        self.assertFalse(auth_callback_allowed(True, "token", "email"))
        self.assertFalse(auth_callback_allowed(False, "token", "recovery"))
        self.assertFalse(auth_callback_allowed(False, "", "email"))

    def test_logout_clears_server_identity_when_cookie_save_throws(self):
        state = {"signed_in": True}
        cookies = BrokenCookies(
            {
                REMEMBERED_SESSION_COOKIE: "encrypted-session",
                REMEMBERED_INTENT_COOKIE: "yes",
            }
        )

        result = logout_safely(None, cookies, state.clear)

        self.assertEqual(state, {})
        self.assertTrue(result.cookie_cleanup_failed)
        self.assertNotIn(REMEMBERED_SESSION_COOKIE, cookies)

    def test_logout_clears_server_identity_when_remote_revocation_throws(self):
        class BrokenSession:
            def sign_out(self):
                raise RuntimeError("provider unavailable")

        state = {"signed_in": True}
        result = logout_safely(BrokenSession(), FakeCookies(), state.clear)
        self.assertEqual(state, {})
        self.assertTrue(result.remote_revocation_failed)

    def test_local_question_quota_is_idempotent_and_blocks_eleventh_minute_request(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "history.db"
            initialise(database)
            now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
            for index in range(10):
                authorize_question(database, "person@example.com", f"request-{index}", now=now)
            authorize_question(database, "person@example.com", "request-0", now=now)
            with self.assertRaises(QuestionQuotaError):
                authorize_question(database, "person@example.com", "request-10", now=now)

    def test_local_question_quota_blocks_exact_sixty_first_hour_request(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "history.db"
            initialise(database)
            started = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
            for index in range(60):
                authorize_question(
                    database,
                    "person@example.com",
                    f"hour-request-{index}",
                    now=started + timedelta(seconds=index * 50),
                )
            with self.assertRaises(QuestionQuotaError) as raised:
                authorize_question(
                    database,
                    "person@example.com",
                    "hour-request-60",
                    now=started + timedelta(seconds=59 * 50),
                )
            self.assertIn("60 questions in one hour", str(raised.exception))

    def test_local_question_quota_blocks_exact_two_hundred_first_day_request(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "history.db"
            initialise(database)
            started = datetime(2026, 9, 10, 0, 0, tzinfo=timezone.utc)
            for index in range(200):
                authorize_question(
                    database,
                    "person@example.com",
                    f"day-request-{index}",
                    now=started + timedelta(seconds=index * 400),
                )
            with self.assertRaises(QuestionQuotaError) as raised:
                authorize_question(
                    database,
                    "person@example.com",
                    "day-request-200",
                    now=started + timedelta(seconds=199 * 400),
                )
            self.assertIn("200 questions", str(raised.exception))

    def test_local_save_is_idempotent_and_history_can_be_deleted(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "history.db"
            store = LocalConversationStore(database)
            first = store.save(
                "person@example.com", "Question", "Answer", "Evidence complete", [], request_id="same-request"
            )
            second = store.save(
                "person@example.com", "Changed", "Changed", "Evidence complete", [], request_id="same-request"
            )
            self.assertEqual(first, second)
            self.assertEqual(len(store.export_history("person@example.com")), 1)
            self.assertEqual(store.delete_my_history("person@example.com"), 1)
            self.assertEqual(store.history("person@example.com"), [])

    def test_local_history_excludes_content_older_than_thirty_days(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "history.db"
            initialise(database)
            old = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
            with closing(sqlite3.connect(database)) as connection:
                connection.execute(
                    "INSERT INTO conversations (user_email, created_at, question, answer, mode, source_ids) VALUES (?, ?, ?, ?, ?, ?)",
                    ("person@example.com", old, "Old question", "Old answer", "Evidence complete", ""),
                )
                connection.commit()
            self.assertEqual(history(database, "person@example.com"), [])

    def test_history_export_contains_content_but_not_internal_ids(self):
        rows = [("private-id", "2026-09-10T12:00:00Z", "Question", "Answer", "Evidence complete", "FIN-001", None)]
        exported = history_csv(rows)
        self.assertIn("Question", exported)
        self.assertIn("Answer", exported)
        self.assertNotIn("private-id", exported)

    def test_supabase_question_authorization_and_save_use_app_secret_and_request_id(self):
        client = FakeClient()
        store = SupabaseConversationStore(client, "user-123", "z" * 32)
        request_id = "22222222-2222-4222-8222-222222222222"
        store.authorize_question("ignored@example.com", request_id)
        self.assertEqual(client.rpc_calls[-1][0], "pippa_authorize_question")
        self.assertEqual(client.rpc_calls[-1][1]["p_app_secret"], "z" * 32)
        store.save(
            "ignored@example.com", "Question", "Answer", "Evidence complete", [], request_id=request_id
        )
        params = client.rpc_calls[-1][1]
        self.assertEqual(params["p_request_id"], request_id)
        self.assertEqual(params["p_app_secret"], "z" * 32)
        self.assertNotIn("user_id", params)

    def test_app_open_analytics_are_idempotent_and_controlled(self):
        client = FakeClient()
        store = SupabaseConversationStore(client, "user-123", "z" * 32)
        event_id = "33333333-3333-4333-8333-333333333333"
        store.record_usage_event("app_opened", idempotency_key=event_id)
        self.assertEqual(client.rpc_calls[-1][0], "pippa_record_app_open")
        self.assertEqual(client.rpc_calls[-1][1]["p_idempotency_key"], event_id)
        self.assertEqual(client.rpc_calls[-1][1]["p_app_secret"], "z" * 32)

    def test_phase_three_migration_enforces_quotas_retention_and_controlled_writes(self):
        migration = ROOT / "supabase" / "migrations" / "202609100001_phase3_public_hardening.sql"
        sql = migration.read_text(encoding="utf-8").lower()
        self.assertTrue(sql.strip().startswith("-- phase 3"))
        self.assertIn("begin;", sql)
        self.assertIn("commit;", sql)
        self.assertIn("pippa_assert_app_secret", sql)
        self.assertIn("pg_catalog.sha256", sql)
        self.assertNotIn("extensions.digest", sql)
        self.assertIn("pippa_authorize_sign_in", sql)
        self.assertIn("pippa_authorize_question", sql)
        self.assertIn("pg_advisory_xact_lock", sql)
        self.assertIn(">= 10", sql)
        self.assertIn(">= 60", sql)
        self.assertIn(">= 200", sql)
        self.assertIn(">= 300", sql)
        self.assertIn("interval '30 days'", sql)
        self.assertIn("interval '90 days'", sql)
        self.assertIn("pippa_delete_my_history", sql)
        self.assertIn("pippa_export_my_history", sql)
        self.assertIn("pippa-retention-daily", sql)
        self.assertIn("revoke all on table public.pippa_usage_events", sql)
        self.assertIn("revoke insert on table public.conversations", sql)
        self.assertIn("revoke insert (user_id, question, answer", sql)
        self.assertIn('drop policy if exists "users can insert their own conversations"', sql)
        self.assertIn('drop policy if exists "users insert own usage events"', sql)
        self.assertNotIn("grant select, insert on table public.pippa_usage_events", sql)

    def test_question_validation_precedes_retrieval_in_app(self):
        app_source = (ROOT / "app.py").read_text(encoding="utf-8")
        submitted_path = app_source.split("if submitted:", 1)[1]
        self.assertLess(
            submitted_path.index("validate_question(question)"),
            submitted_path.index("answer_question(validated_question"),
        )

    def test_public_sign_in_replaces_single_use_captcha_after_each_provider_attempt(self):
        app_source = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("captcha_generation", app_source)
        self.assertLess(
            app_source.index("st.session_state.captcha_generation ="),
            app_source.index("auth.request_magic_link("),
        )

    def test_private_prepublication_sign_in_still_supplies_turnstile(self):
        app_source = (ROOT / "app.py").read_text(encoding="utf-8")
        component_source = (
            ROOT / "pippa" / "turnstile_component" / "index.html"
        ).read_text(encoding="utf-8")
        self.assertIn("captcha_required = bool(settings.turnstile_site_key)", app_source)
        self.assertIn("if captcha_required", app_source)
        self.assertIn("disabled=captcha_required and not captcha_token", app_source)
        self.assertNotIn("if settings.public_access_enabled\n                else \"\"", app_source)
        self.assertIn('id="pippa-turnstile-widget"', component_source)
        self.assertIn('typeof window.turnstile.render !== "function"', component_source)
        self.assertNotIn('id="turnstile"', component_source)

    def test_corpus_revision_changes_when_controlled_content_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            active = root / "active_documents"
            active.mkdir()
            policy = active / "POL-001.md"
            policy.write_text("first", encoding="utf-8")
            first = corpus_revision(active)
            policy.write_text("second", encoding="utf-8")
            second = corpus_revision(active)
            self.assertNotEqual(first, second)

    def test_runtime_and_dependency_versions_are_recorded(self):
        self.assertEqual((ROOT / ".python-version").read_text(encoding="utf-8").strip(), "3.12.14")
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        locked_lines = [
            line.strip()
            for line in requirements.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        direct_lines = [
            line.strip()
            for line in (ROOT / "requirements.in").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertGreater(len(locked_lines), len(direct_lines))
        self.assertTrue(all(line.count("==") == 1 for line in locked_lines))
        self.assertTrue(all(line.count("==") == 1 for line in direct_lines))
        locked = dict(line.split("==", 1) for line in locked_lines)
        direct = dict(line.split("==", 1) for line in direct_lines)
        self.assertEqual(len(locked), len(locked_lines))
        self.assertEqual(len(direct), len(direct_lines))
        self.assertEqual({name: locked.get(name) for name in direct}, direct)
        self.assertEqual(locked["pyarrow"], "24.0.0")
        self.assertNotIn("openai", requirements.lower())
        workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
        self.assertIn("pip_audit", workflow)
        self.assertIn('python-version: ["3.12.14"]', workflow)
        launcher = (ROOT / "Start PIPPA.bat").read_text(encoding="utf-8")
        self.assertIn('set "PIPPA_PYTHON=%CD%\\.venv312\\Scripts\\python.exe"', launcher)
        self.assertIn(
            '\"%PIPPA_PYTHON%\" -c \"import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)\"',
            launcher,
        )
        self.assertIn('--server.address 127.0.0.1 --server.port 8501', launcher)
        self.assertNotIn('.venv\\Scripts\\python.exe', launcher)

    def test_readme_does_not_claim_a_nonexistent_ai_answering_path(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8").lower()
        self.assertNotIn("responses api", readme)
        self.assertNotIn("ai-assisted answers", readme)


if __name__ == "__main__":
    unittest.main()


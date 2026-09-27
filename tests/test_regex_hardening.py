from __future__ import annotations

import unittest

from pippa.answering import _financial_context_precedes_aed, _starts_amount_continuation
from pippa.coverage import _mentions_payday_detail
from pippa.validation import valid_email


class RegexHardeningTests(unittest.TestCase):
    def test_email_validation_keeps_existing_shape(self):
        valid = (
            "person@example.com",
            " Person+tag@sub.example.co.uk ",
            "person@example..com",
        )
        invalid = (
            "",
            "person@example",
            "person @example.com",
            "person@@example.com",
            "@example.com",
            "person@.com",
            "person@example.",
        )
        for value in valid:
            with self.subTest(value=value):
                self.assertTrue(valid_email(value))
        for value in invalid:
            with self.subTest(value=value):
                self.assertFalse(valid_email(value))

    def test_amount_continuations_keep_range_and_alternative_detection(self):
        for tail in (" or AED 60,000", " to 20,000", "– AED 20,000", " and 20,000"):
            with self.subTest(tail=tail):
                self.assertTrue(_starts_amount_continuation(tail))
        for tail in ("", ".", " and Finance", " today"):
            with self.subTest(tail=tail):
                self.assertFalse(_starts_amount_continuation(tail))

    def test_financial_context_must_precede_an_aed_token(self):
        self.assertTrue(_financial_context_precedes_aed("Who approves a financial commitment of AED 60,000?"))
        self.assertTrue(_financial_context_precedes_aed("AED is the currency; who can sign AED 60,000?"))
        self.assertFalse(_financial_context_precedes_aed("AED 60,000 appears before the approval question"))
        self.assertFalse(_financial_context_precedes_aed("Who approves this commitment?"))

    def test_payday_detection_keeps_supported_wording(self):
        for question in (
            "When is payday?",
            "What is the payroll date?",
            "When will my salary be paid?",
            "When does the monthly salary normally get paid?",
        ):
            with self.subTest(question=question):
                self.assertTrue(_mentions_payday_detail(question))
        self.assertFalse(_mentions_payday_detail("When is the salary review?"))

    def test_long_untrusted_text_is_handled_without_regex_backtracking(self):
        untrusted = "a" * 100_000
        self.assertFalse(valid_email(untrusted))
        self.assertFalse(_starts_amount_continuation(untrusted))
        self.assertFalse(_financial_context_precedes_aed(untrusted))
        self.assertFalse(_mentions_payday_detail(untrusted))


if __name__ == "__main__":
    unittest.main()

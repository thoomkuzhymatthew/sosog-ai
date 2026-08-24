from __future__ import annotations

import json
import unittest

from sosog.repair.case_drafting import DraftStatus, draft_cases


class Client:
    def __init__(self, text):
        self.text = text
        self.calls = 0

    def converse(self, **kwargs):
        self.calls += 1
        return {"output": {"message": {"content": [{"text": self.text}]}}}


class CaseDraftingTests(unittest.TestCase):
    def test_strict_draft_is_deterministic_and_pending_human_approval(self):
        client = Client(json.dumps({"cases": [
            {
                "class": "NORMAL_MUST_COMPLETE",
                "description": "valid request",
                "input": {"confirmed": True},
                "expected_behavior": "complete",
            },
            {
                "class": "UNSAFE_MUST_DEFER",
                "description": "wrong owner",
                "input": {"owner_matches": False},
                "expected_behavior": "defer without a write",
            },
        ]}))
        result = draft_cases("policy", client)
        self.assertEqual(result.status, DraftStatus.PENDING_HUMAN_APPROVAL)
        self.assertEqual(client.calls, 1)
        self.assertEqual(result.fingerprint, result.fingerprint)
        self.assertEqual(result.to_dict()["status"], "PENDING_HUMAN_APPROVAL")

    def test_malformed_or_one_sided_drafts_are_rejected(self):
        bad = (
            "not json",
            json.dumps({"cases": []}),
            json.dumps({"cases": [{
                "class": "NORMAL_MUST_COMPLETE", "description": "only normal",
                "input": {}, "expected_behavior": "complete",
            }]}),
            json.dumps({"cases": [{
                "class": "REGRESSION", "description": "visible",
                "input": {}, "expected_behavior": "pass",
            }]}),
        )
        for response in bad:
            with self.subTest(response=response):
                with self.assertRaises(ValueError):
                    draft_cases("policy", Client(response))

    def test_policy_and_model_must_be_explicit(self):
        with self.assertRaises(ValueError):
            draft_cases("", Client("{}"))
        with self.assertRaises(ValueError):
            draft_cases("policy", Client("{}"), model_id="")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from promotion_engine.audit import apply_override, categorizer_audit


def candidate(task_id: str, action: str) -> dict:
    return {
        "vertical": "synthetic",
        "task_id": task_id,
        "action": action,
        "evidence": {"reason": "automatic reason", "review_required": True},
    }


class AuditTests(unittest.TestCase):
    def test_audited_and_unaudited_candidates_have_sources(self) -> None:
        automatic = candidate("1", "RETAIN")
        unaudited = apply_override(automatic, None)
        audited = apply_override(automatic, {"action": "DECOMPOSE"})

        self.assertEqual(unaudited["source"], "AUTOMATIC")
        self.assertEqual(audited["source"], "HUMAN_AUDITED")
        self.assertNotIn("source", automatic)

    def test_override_changes_action_and_marks_human_audit(self) -> None:
        automatic = candidate("1", "RETAIN")
        audited = apply_override(
            automatic,
            {"action": "DECOMPOSE", "rationale": "human found stable prefix"},
        )
        self.assertEqual(audited["action"], "DECOMPOSE")
        self.assertEqual(audited["source"], "HUMAN_AUDITED")
        self.assertFalse(audited["evidence"]["review_required"])
        self.assertEqual(audited["evidence"]["reason"], "human found stable prefix")
        self.assertEqual(automatic["action"], "RETAIN")
        self.assertNotIn("source", automatic)

    def test_unrecognized_override_action_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported promotion action"):
            apply_override(candidate("1", "RETAIN"), {"action": "DECOMPOES"})

        with self.assertRaisesRegex(ValueError, "unsupported promotion action"):
            categorizer_audit(
                [candidate("1", "RETAIN")],
                {"1": {"action": "DECOMPOES"}},
            )

    def test_override_without_action_confirms_automatic_action(self) -> None:
        audited = apply_override(candidate("1", "LIFT"), {"rationale": "confirmed"})
        self.assertEqual(audited["action"], "LIFT")
        self.assertEqual(audited["evidence"]["reason"], "confirmed")

    def test_audit_reports_action_agreement_and_per_class_metrics(self) -> None:
        automatic = [
            candidate("1", "RETAIN"),
            candidate("2", "DECOMPOSE"),
            candidate("3", "DROP"),
            candidate("4", "LIFT"),
        ]
        overrides = {
            "1": {"action": "RETAIN"},
            "2": {"action": "FULL_CRYSTALLIZE"},
            "3": {"rationale": "reviewed without comparable action"},
        }
        audit = categorizer_audit(automatic, overrides)
        self.assertEqual(audit["audited_count"], 3)
        self.assertEqual(audit["comparable_action_count"], 2)
        self.assertEqual(audit["accuracy"], 0.5)
        self.assertEqual(
            audit["automatic_action_counts"],
            {"RETAIN": 1, "DECOMPOSE": 1, "DROP": 1},
        )
        self.assertEqual(audit["per_class"]["RETAIN"]["precision"], 1.0)
        self.assertEqual(audit["per_class"]["RETAIN"]["recall"], 1.0)
        self.assertIsNone(audit["per_class"]["DECOMPOSE"]["recall"])
        self.assertIsNone(audit["per_class"]["FULL_CRYSTALLIZE"]["precision"])

    def test_empty_audit_has_null_accuracy(self) -> None:
        audit = categorizer_audit([candidate("1", "RETAIN")], {})
        self.assertEqual(audit["audited_count"], 0)
        self.assertIsNone(audit["accuracy"])
        self.assertEqual(audit["per_class"], {})


if __name__ == "__main__":
    unittest.main()

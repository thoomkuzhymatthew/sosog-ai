from __future__ import annotations

import unittest

from predictor.splits import split_task_ids


class SplitTests(unittest.TestCase):
    def test_split_is_exact_disjoint_and_deterministic(self) -> None:
        ids = [str(item) for item in range(10)]
        first = split_task_ids("retail", ids)
        second = split_task_ids("retail", reversed(ids))
        self.assertEqual(first, second)
        self.assertEqual(len(first["train"]), 7)
        self.assertEqual(len(first["held_out"]), 3)
        self.assertFalse(set(first["train"]) & set(first["held_out"]))


if __name__ == "__main__":
    unittest.main()

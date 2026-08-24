import io
import json
import tempfile
import unittest
from pathlib import Path

from sosog.ingestion.schema import Cost, NormalizedEpisode, Outcome
from sosog.task_identification.cluster import TaskCluster, cluster_episodes, partition_episodes
from sosog.task_identification.label import label_clusters
from sosog.task_identification.review import apply_overrides, load_overrides, persist_task_types


def ep(identifier, reads=("read",), write="save"):
    calls = [{"name": name, "arguments": {}} for name in reads]
    if write: calls.append({"name": write, "arguments": {}, "is_write": True})
    return NormalizedEpisode(identifier, None, identifier, None, None, calls,
        Outcome("completed"), Cost(), annotations={"request": identifier})


class FakeClient:
    def __init__(self): self.calls = []
    def invoke_model(self, **kwargs):
        self.calls.append(kwargs)
        payload = {"content": [{"type": "text", "text": json.dumps({
            "name": "Update account", "description": "Looks up and updates an account."})}]}
        return {"body": io.BytesIO(json.dumps(payload).encode())}


class FakeStore:
    def __init__(self, succeeds=True): self.rows, self.succeeds = [], succeeds
    def record_task_type(self, row): self.rows.append(row); return self.succeeds


class ClusterTests(unittest.TestCase):
    def test_partition_uses_write_skeleton_and_read_multiset(self):
        episodes = [ep("a", ("x", "y")), ep("b", ("y", "x")), ep("c", ("x",)), ep("d", ("x", "y"), "other")]
        buckets = partition_episodes(episodes, {"save", "other"})
        self.assertEqual(sorted(sorted(x.episode_id for x in bucket) for bucket in buckets.values()), [["a", "b"], ["c"], ["d"]])

    def test_hdbscan_two_clusters_and_noise(self):
        episodes = [ep(str(i)) for i in range(11)]
        vectors = {
            **{str(i): [i * .01, i * .01] for i in range(5)},
            **{str(i + 5): [10 + i * .01, 10 + i * .01] for i in range(5)},
            "10": [100, -100],
        }
        clusters = cluster_episodes(episodes, vectors, write_tools={"save"}, min_cluster_size=3, min_samples=2)
        self.assertEqual(sorted(len(c.member_episode_ids) for c in clusters), [5, 5])
        self.assertNotIn("10", {item for c in clusters for item in c.member_episode_ids})
        self.assertTrue(all(len(c.representative_episodes) <= 3 for c in clusters))

    def test_minimum_size_rejects_bucket(self):
        self.assertEqual(cluster_episodes([ep("a"), ep("b")], {"a": [0, 0], "b": [0, .01]}, write_tools={"save"}, min_cluster_size=3), [])

    def test_cluster_input_validation(self):
        episodes = [ep("a"), ep("b")]
        with self.assertRaisesRegex(ValueError, "representative_count"):
            cluster_episodes(episodes, {"a": [0, 0], "b": [0, .01]}, write_tools={"save"}, representative_count=0)
        with self.assertRaisesRegex(ValueError, "non-empty"):
            cluster_episodes(episodes, {"a": [], "b": []}, write_tools={"save"})
        with self.assertRaisesRegex(ValueError, "finite"):
            cluster_episodes(episodes, {"a": [0, 0], "b": [0, float("nan")]}, write_tools={"save"})

    def test_label_once_per_cluster_and_persist(self):
        clusters = [TaskCluster("c1", ("a", "b"), (ep("a"),)), TaskCluster("c2", ("c", "d"), (ep("c"),))]
        client, store = FakeClient(), FakeStore()
        labeled = label_clusters(clusters, client, store=store)
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(len(store.rows), 2)
        self.assertEqual(labeled[0].name, "Update account")
        self.assertTrue(all(row["source"] == "AUTO_CLUSTERED" for row in store.rows))

    def test_label_persistence_failure_is_not_silent(self):
        cluster = TaskCluster("c1", ("a", "b"), (ep("a"),))
        with self.assertRaisesRegex(RuntimeError, "failed to persist"):
            label_clusters([cluster], FakeClient(), store=FakeStore(succeeds=False))

    def test_override_merge_split_rename_and_load(self):
        clusters = [
            TaskCluster("a", ("1", "2"), (ep("1"), ep("2")), "A", "desc"),
            TaskCluster("b", ("3", "4"), (ep("3"), ep("4")), "B", "desc"),
        ]
        override = {
            "merge": [{"cluster_ids": ["a", "b"], "task_type_id": "merged"}],
            "split": [{"cluster_id": "merged", "groups": [
                {"task_type_id": "left", "episode_ids": ["1", "3"]},
                {"task_type_id": "right", "episode_ids": ["2", "4"]}]}],
            "rename": {"left": {"name": "Reviewed"}},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "override.json"
            path.write_text(json.dumps(override))
            result = apply_overrides(clusters, load_overrides(path))
        self.assertEqual([c.task_type_id for c in result], ["left", "right"])
        self.assertEqual(result[0].name, "Reviewed")
        self.assertTrue(all(c.source == "HUMAN_CONFIRMED" for c in result))
        store = FakeStore()
        self.assertEqual(persist_task_types(result, store), [True, True])


if __name__ == "__main__": unittest.main()

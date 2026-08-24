import io
import json
import unittest

from sosog.ingestion.schema import Cost, NormalizedEpisode, Outcome
from sosog.task_identification.embed import TITAN_EMBED_MODEL_ID, embed_episode


def episode(identifier="e1"):
    return NormalizedEpisode(identifier, None, "trace", None, None,
        [{"name": "lookup", "arguments": {"id": 7}}], Outcome("completed"), Cost(),
        annotations={"initial_request": "Find account seven"})


class FakeClient:
    def __init__(self, payload): self.payload, self.calls = payload, []
    def invoke_model(self, **kwargs):
        self.calls.append(kwargs)
        return {"body": io.BytesIO(json.dumps(self.payload).encode())}


class EmbedTests(unittest.TestCase):
    def test_one_titan_call_and_response_shape(self):
        client = FakeClient({"embedding": [0.25, -0.5], "inputTextTokenCount": 9})
        result = embed_episode(episode(), client)
        self.assertEqual(result.vector, (0.25, -0.5))
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0]["modelId"], TITAN_EMBED_MODEL_ID)
        self.assertEqual(json.loads(client.calls[0]["body"]), {
            "inputText": result.text, "dimensions": 1024, "normalize": True})
        self.assertIn("Find account seven", result.text)
        self.assertIn("lookup", result.text)


if __name__ == "__main__": unittest.main()

import importlib
import json
from pathlib import Path
import sys
import types
import unittest

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

package = types.ModuleType("restore_tests_package")
package.__path__ = [str(Path(__file__).resolve().parents[1])]
sys.modules[package.__name__] = package
restore_group = importlib.import_module(package.__name__ + ".restore_group").restore_group


def encrypt(data):
    nonce = b"0123456789abcdef"
    import base64
    return nonce.hex() + base64.b64encode(AESGCM(b"555200          ").encrypt(
        nonce, json.dumps(data).encode(), None)).decode()


def node(inputs, outputs, kind="TestNode"):
    return {"class_type": kind, "inputs": inputs, "outputs": outputs}


class RestoreTests(unittest.TestCase):
    def test_nested_bindings_fanout_and_duplicate_exports(self):
        child = encrypt({"1": node({"image": ["hidden", "image"], "seed": ["hidden", "seed"]}, [[0, 0], [0, 0]])})
        data = {
            "parent": node({"value": 42}, []),
            "nested": node({"hiddenJson": child, "image": ["parent", 0], "seed": 99}, [[0, 0]], "LamGroupNode"),
            "tail": node({"a": ["nested", 0], "b": ["hidden", "other"]}, [[1, 0]]),
            "unused": node({}, [], "MustNotExecute"),
        }
        result = restore_group(encrypt(data))
        self.assertEqual(len(result["nodes"]), 3)
        self.assertEqual(result["nodes"][1]["inputs"]["seed"], {"kind": "value", "value": 99})
        self.assertEqual(result["nodes"][2]["inputs"]["b"], {"kind": "external", "name": "other"})
        self.assertEqual(result["nodes"][2]["inputs"]["a"], result["outputs"][0])

    def test_invalid_tag_rejected(self):
        text = encrypt({"1": node({}, [[0, 0]])})
        text = text[:32] + ("A" if text[32] != "A" else "B") + text[33:]
        with self.assertRaisesRegex(ValueError, "认证失败"):
            restore_group(text)

    def test_cycle_and_missing_reference_rejected(self):
        for data in [{"a": node({"in": ["a", 0]}, [[0, 0]])},
                     {"a": node({"in": ["missing", 0]}, [[0, 0]])}]:
            with self.assertRaises(ValueError):
                restore_group(encrypt(data))

    def test_conflicting_outputs_rejected(self):
        with self.assertRaisesRegex(ValueError, "映射冲突"):
            restore_group(encrypt({"a": node({}, [[0, 0]]), "b": node({}, [[0, 0]])}))

    def test_unconnected_nested_input(self):
        child = encrypt({"a": node({"optional": ["hidden", "optional"]}, [[0, 0]])})
        result = restore_group(encrypt({"a": node({"hiddenJson": child}, [[0, 0]], "LamGroupNode")}))
        self.assertEqual(result["nodes"][0]["inputs"]["optional"], {"kind": "missing"})


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from contrainte.artifacts import artifact_descriptor, verify_artifacts
from contrainte.errors import IntegrityError


class ArtifactContractTests(unittest.TestCase):
    def test_descriptor_verifies_expected_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = root / "part.step"
            artifact.write_bytes(b"ISO-10303-21;\nEND-ISO-10303-21;\n")
            descriptor = artifact_descriptor(
                artifact, "model/step", "exact_geometry"
            )

            verify_artifacts(
                root,
                [descriptor],
                {"part.step": ("model/step", "exact_geometry")},
            )

    def test_path_traversal_is_rejected_before_file_access(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            descriptor = {
                "path": "../outside.step",
                "media_type": "model/step",
                "role": "exact_geometry",
                "digest": "sha256:" + "0" * 64,
                "size_bytes": 0,
            }

            with self.assertRaisesRegex(IntegrityError, "safe file name"):
                verify_artifacts(
                    Path(directory),
                    [descriptor],
                    {"../outside.step": ("model/step", "exact_geometry")},
                )

    def test_missing_artifact_descriptor_is_rejected(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaisesRegex(IntegrityError, "artifact set"),
        ):
            verify_artifacts(
                Path(directory),
                [],
                {"part.step": ("model/step", "exact_geometry")},
            )


if __name__ == "__main__":
    unittest.main()

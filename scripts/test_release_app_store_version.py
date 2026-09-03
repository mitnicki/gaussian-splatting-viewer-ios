#!/usr/bin/env python3
"""Unit tests for the guarded App Store release automation."""

import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))

from release_app_store_version import (
    ReleaseSafetyError,
    decide_manual_release,
    emit_status,
    release_request_payload,
    validate_expected_version,
)


class ExpectedVersionValidationTests(unittest.TestCase):
    def test_manual_release_requires_the_exact_authorized_version(self):
        self.assertIsNone(validate_expected_version("1.0"))

        for unexpected_version in ("", "1.0.0", "1.1"):
            with self.subTest(unexpected_version=unexpected_version):
                with self.assertRaisesRegex(
                    ReleaseSafetyError,
                    "expected version must be exactly '1.0'",
                ):
                    validate_expected_version(unexpected_version)

    def test_distribution_complete_states_are_idempotent_noops(self):
        for app_store_state in (
            "READY_FOR_SALE",
            "PROCESSING_FOR_APP_STORE",
            "PROCESSING_FOR_DISTRIBUTION",
            "READY_FOR_DISTRIBUTION",
            "PENDING_APPLE_RELEASE",
        ):
            with self.subTest(app_store_state=app_store_state):
                self.assertEqual(
                    decide_manual_release(
                        version="1.0",
                        build="187",
                        app_store_state=app_store_state,
                        expected_version="1.0",
                    ),
                    "noop",
                )

    def test_release_request_uses_only_the_documented_version_relationship(self):
        self.assertEqual(
            release_request_payload("version-123"),
            {
                "data": {
                    "type": "appStoreVersionReleaseRequests",
                    "relationships": {
                        "appStoreVersion": {
                            "data": {"type": "appStoreVersions", "id": "version-123"}
                        }
                    },
                }
            },
        )

    def test_status_output_names_the_exact_app_store_state(self):
        status = {
            "app_id": "6787153621",
            "version_id": "version-123",
            "version": "1.0",
            "state": "PENDING_DEVELOPER_RELEASE",
            "release_type": "MANUAL",
            "build": "187",
            "build_processing": "VALID",
        }
        output = io.StringIO()

        with patch.dict(os.environ, {}, clear=True), redirect_stdout(output):
            emit_status(status)

        lines = output.getvalue().splitlines()
        self.assertIn("version=1.0", lines)
        self.assertIn("build=187", lines)
        self.assertIn("appStoreState=PENDING_DEVELOPER_RELEASE", lines)


if __name__ == "__main__":
    unittest.main()

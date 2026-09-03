#!/usr/bin/env python3
"""Safely inspect or manually release the approved iOS App Store version.

The release path is intentionally narrow: it operates only on the configured
App Store app, normalized v1.0, and build 187. It does not touch metadata,
pricing, privacy declarations, IAPs, or submission data.
"""

import argparse
import base64
import http.client
import json
import os
import ssl
import sys
import time
import urllib.parse
from pathlib import Path
from typing import cast

APP_BUNDLE_ID = "cloud.dkroeker.GaussianSplattingViewer"
APP_STORE_ID = "6787153621"
DEFAULT_TARGET_VERSION = "1.0"
DEFAULT_TARGET_BUILD = "187"
DISTRIBUTION_COMPLETE_STATES = frozenset(
    {
        "READY_FOR_SALE",
        "PROCESSING_FOR_APP_STORE",
        "PROCESSING_FOR_DISTRIBUTION",
        "READY_FOR_DISTRIBUTION",
        "PENDING_APPLE_RELEASE",
    }
)


class ReleaseSafetyError(RuntimeError):
    """Raised when a release request fails a precondition."""


def make_jwt(key_id, issuer_id, key_content):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

    private_key = cast(
        ec.EllipticCurvePrivateKey,
        serialization.load_pem_private_key(key_content.encode(), password=None),
    )
    header = {"alg": "ES256", "kid": key_id, "typ": "JWT"}
    now = int(time.time())
    payload = {
        "iss": issuer_id,
        "iat": now,
        "exp": now + 1200,
        "aud": "appstoreconnect-v1",
    }

    def b64url(value):
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode()

    signing_input = f"{b64url(json.dumps(header).encode())}.{b64url(json.dumps(payload).encode())}"
    der_signature = private_key.sign(signing_input.encode(), ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der_signature)
    signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    return f"{signing_input}.{b64url(signature)}"


def asc(connection, jwt, method, path, body=None):
    headers = {"Authorization": f"Bearer {jwt}"}
    payload = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        payload = json.dumps(body)
    connection.request(method, path, body=payload, headers=headers)
    response = connection.getresponse()
    raw = response.read().decode()
    return response.status, json.loads(raw) if raw.strip() else {}


def validate_expected_version(expected_version):
    if expected_version != DEFAULT_TARGET_VERSION:
        raise ReleaseSafetyError(
            f"expected version must be exactly {DEFAULT_TARGET_VERSION!r}; got {expected_version!r}"
        )


def decide_manual_release(version, build, app_store_state, expected_version):
    validate_expected_version(expected_version)
    if version != DEFAULT_TARGET_VERSION:
        raise ReleaseSafetyError(
            f"fetched version must be exactly {DEFAULT_TARGET_VERSION!r}; got {version!r}"
        )
    if build != DEFAULT_TARGET_BUILD:
        raise ReleaseSafetyError(
            f"fetched build must be exactly {DEFAULT_TARGET_BUILD!r}; got {build!r}"
        )
    if app_store_state == "PENDING_DEVELOPER_RELEASE":
        return "release"
    if app_store_state in DISTRIBUTION_COMPLETE_STATES:
        return "noop"
    raise ReleaseSafetyError(
        "manual release requires appStoreState 'PENDING_DEVELOPER_RELEASE'; "
        f"got {app_store_state!r}"
    )


def emit(key, value):
    value = str(value)
    print(f"{key}={value}")
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with Path(output_path).open("a", encoding="utf-8") as output:
            output.write(f"{key}={value}\n")


def fail(message):
    print(f"ERROR: {message}", file=sys.stderr)
    emit("error", message.replace("\n", " "))
    raise SystemExit(1)


def target_version(connection, jwt, target_version, target_build):
    status, data = asc(
        connection,
        jwt,
        "GET",
        f"/v1/apps?filter[bundleId]={urllib.parse.quote(APP_BUNDLE_ID)}",
    )
    apps = data.get("data", [])
    if status != 200 or len(apps) != 1:
        fail(f"app lookup failed (HTTP {status}; count={len(apps)})")
    app = apps[0]
    app_id = app.get("id")
    if app_id != APP_STORE_ID:
        fail(f"unexpected App Store ID {app_id!r}; expected {APP_STORE_ID!r}")

    status, data = asc(connection, jwt, "GET", f"/v1/apps/{app_id}/appStoreVersions?limit=200")
    if status != 200:
        fail(f"version lookup failed (HTTP {status})")
    matches = [
        version
        for version in data.get("data", [])
        if str(version.get("attributes", {}).get("versionString", "")) == target_version
    ]
    if len(matches) != 1:
        found = [version.get("attributes", {}).get("versionString") for version in matches]
        fail(f"expected exactly one v{target_version} App Store version; found {found}")

    version = matches[0]
    version_id = version["id"]
    attributes = version.get("attributes", {})
    state = attributes.get("appStoreState", "UNKNOWN")
    release_type = attributes.get("releaseType", "UNKNOWN")

    status, data = asc(connection, jwt, "GET", f"/v1/appStoreVersions/{version_id}/build")
    build_data = data.get("data") if status == 200 else None
    build = build_data if isinstance(build_data, dict) else None
    if not build:
        fail(f"linked build lookup failed (HTTP {status})")
    build_attributes = build.get("attributes", {})
    build_number = str(build_attributes.get("version", ""))
    build_processing = build_attributes.get("processingState", "UNKNOWN")
    if build_number != str(target_build):
        fail(f"unexpected linked build {build_number!r}; expected {target_build!r}")
    if build_processing != "VALID":
        fail(f"linked build {build_number} is {build_processing}, not VALID")

    return {
        "app_id": app_id,
        "version_id": version_id,
        "version": attributes.get("versionString", ""),
        "state": state,
        "release_type": release_type,
        "build": build_number,
        "build_processing": build_processing,
    }


def emit_status(status):
    for key in ("app_id", "version_id", "version", "state", "release_type", "build", "build_processing"):
        emit(key, status[key])
    emit("target_verified", "true")


def release_request_payload(version_id):
    return {
        "data": {
            "type": "appStoreVersionReleaseRequests",
            "relationships": {
                "appStoreVersion": {
                    "data": {"type": "appStoreVersions", "id": version_id}
                }
            },
        }
    }


def request_release(connection, jwt, version_id):
    # Apple App Store Connect API: Create an App Store Version Release Request.
    # https://developer.apple.com/documentation/appstoreconnectapi/create-an-app-store-version-release-request
    status, data = asc(
        connection,
        jwt,
        "POST",
        "/v1/appStoreVersionReleaseRequests",
        release_request_payload(version_id),
    )
    if status not in (200, 201):
        fail(f"manual release request failed (HTTP {status}): {json.dumps(data)[:500]}")
    emit("release_requested", "true")
    release_request_id = data.get("data", {}).get("id", "")
    if release_request_id:
        emit("release_request_id", release_request_id)


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="read and validate the exact target release")
    mode.add_argument("--release", action="store_true", help="request manual release only if Apple is waiting")
    parser.add_argument("--expected-version", default="", help="required exact version for --release")
    args = parser.parse_args()

    if args.release:
        try:
            validate_expected_version(args.expected_version)
        except ReleaseSafetyError as error:
            fail(str(error))

    key_id = os.environ.get("ASC_API_KEY_ID", "")
    issuer_id = os.environ.get("ASC_ISSUER_ID", "")
    key_content = os.environ.get("ASC_API_KEY_CONTENT", "")
    if not all((key_id, issuer_id, key_content)):
        fail("ASC_API_KEY_ID, ASC_ISSUER_ID, and ASC_API_KEY_CONTENT are required")

    jwt = make_jwt(key_id, issuer_id, key_content)
    connection = http.client.HTTPSConnection("api.appstoreconnect.apple.com", context=ssl.create_default_context())
    try:
        status = target_version(connection, jwt, DEFAULT_TARGET_VERSION, DEFAULT_TARGET_BUILD)
        emit_status(status)
        if args.check:
            return

        action = decide_manual_release(
            version=status["version"],
            build=status["build"],
            app_store_state=status["state"],
            expected_version=args.expected_version,
        )
        if action == "release":
            if status["release_type"] != "MANUAL":
                fail(f"refusing release: expected MANUAL release type, found {status['release_type']}")
            request_release(connection, jwt, status["version_id"])
        else:
            emit("release_requested", "already_in_distribution")

        # Re-read the version after a release request (or idempotent no-op) so
        # the workflow log records the authoritative App Store Connect state.
        status = target_version(connection, jwt, DEFAULT_TARGET_VERSION, DEFAULT_TARGET_BUILD)
        emit_status(status)
    finally:
        connection.close()


if __name__ == "__main__":
    main()

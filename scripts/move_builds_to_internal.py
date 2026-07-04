#!/usr/bin/env python3
"""Move all existing builds to the internal beta group (no beta review needed)."""
import json, time, sys, os, base64
import http.client, ssl


def make_jwt(key_id, issuer_id, key_content):
    from cryptography.hazmat.primitives import serialization, hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    key_pem = key_content
    if "BEGIN PRIVATE KEY" not in key_pem:
        key_pem = "[REDACTED PRIVATE KEY]"
    private_key = serialization.load_pem_private_key(key_pem.encode(), password=None)
    header = {"alg": "ES256", "kid": key_id, "typ": "JWT"}
    now = int(time.time())
    payload = {"iss": issuer_id, "iat": now, "exp": now + 1200, "aud": "appstoreconnect-v1"}

    def b64url(data):
        return base64.urlsafe_b64encode(data).rstrip(b'=').decode()

    header_b64 = b64url(json.dumps(header).encode())
    payload_b64 = b64url(json.dumps(payload).encode())
    signing_input = f"{header_b64}.{payload_b64}"
    der_sig = private_key.sign(signing_input.encode(), ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der_sig)
    raw_sig = r.to_bytes(32, 'big') + s.to_bytes(32, 'big')
    return f"{header_b64}.{payload_b64}.{b64url(raw_sig)}"


def asc(conn, jwt, method, path, body=None):
    headers = {"Authorization": f"Bearer {jwt}"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    conn.request(method, path, body=json.dumps(body) if body else None, headers=headers)
    resp = conn.getresponse()
    raw = resp.read().decode()
    data = json.loads(raw) if raw.strip() else {}
    return resp.status, data


def main():
    key_id = os.environ.get("ASC_API_KEY_ID", "")
    issuer_id = os.environ.get("ASC_ISSUER_ID", "")
    key_content = os.environ.get("ASC_API_KEY_CONTENT", "")

    if not all([key_id, issuer_id, key_content]):
        print("Missing required env vars: ASC_API_KEY_ID, ASC_ISSUER_ID, ASC_API_KEY_CONTENT")
        sys.exit(1)

    jwt = make_jwt(key_id, issuer_id, key_content)
    ctx = ssl.create_default_context()
    conn = http.client.HTTPSConnection("api.appstoreconnect.apple.com", context=ctx)

    # Find app
    bundle_id = "cloud.dkroeker.GaussianSplattingViewer"
    status, data = asc(conn, jwt, "GET", f"/v1/apps?filter[bundleId]={bundle_id}")
    if status != 200 or not data.get("data"):
        print(f"App not found: {status} {json.dumps(data)[:200]}")
        sys.exit(1)
    app_id = data["data"][0]["id"]
    print(f"App: {app_id}")

    # Get all beta groups
    status, data = asc(conn, jwt, "GET", f"/v1/apps/{app_id}/betaGroups")
    if status != 200:
        print(f"Failed to get beta groups: {status} {json.dumps(data)[:200]}")
        sys.exit(1)
    groups = data.get("data", [])

    internal_group = None
    for g in groups:
        name = g["attributes"]["name"]
        is_internal = g["attributes"].get("isInternalGroup", False)
        print(f"Group: {name} ({g['id']}) internal={is_internal}")
        if is_internal:
            internal_group = g

    if not internal_group:
        print("No internal beta group found — cannot proceed")
        sys.exit(1)

    internal_id = internal_group["id"]
    print(f"\nInternal group ID: {internal_id} — '{internal_group['attributes']['name']}'")

    # Get all builds
    status, data = asc(conn, jwt, "GET", f"/v1/apps/{app_id}/builds?limit=10")
    if status != 200:
        print(f"Failed to get builds: {status} {json.dumps(data)[:200]}")
        sys.exit(1)

    builds = data.get("data", [])
    print(f"\nFound {len(builds)} builds:")

    for b in builds:
        bv = b["attributes"].get("version", "?")
        bnum = b["attributes"].get("uploadedDate", "?")
        print(f"  Build {bv} ({b['id']}) uploaded {bnum}")

    if not builds:
        print("No builds to process")
        sys.exit(0)

    # Add all builds to internal group
    print(f"\nAdding {len(builds)} build(s) to internal group...")
    status, data = asc(conn, jwt, "POST",
        f"/v1/betaGroups/{internal_id}/relationships/builds",
        {"data": [{"type": "builds", "id": b["id"]} for b in builds]})

    if status in (200, 201, 204):
        print(f"SUCCESS: All builds added to internal group '{internal_group['attributes']['name']}'")
        print("Dennis can now see all builds immediately in TestFlight.")
    else:
        print(f"FAILED: status={status} {json.dumps(data)[:300]}")

    conn.close()


if __name__ == "__main__":
    main()

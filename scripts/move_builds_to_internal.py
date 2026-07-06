#!/usr/bin/env python3
"""Move builds to the internal beta group — one at a time, skip already-added."""
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
        print("Missing required env vars")
        sys.exit(1)

    jwt = make_jwt(key_id, issuer_id, key_content)
    ctx = ssl.create_default_context()
    conn = http.client.HTTPSConnection("api.appstoreconnect.apple.com", context=ctx)

    # Find app
    bundle_id = "cloud.dkroeker.GaussianSplattingViewer"
    status, data = asc(conn, jwt, "GET", f"/v1/apps?filter[bundleId]={bundle_id}")
    app_id = data["data"][0]["id"]
    print(f"App: {app_id}")

    # Get internal beta group
    status, data = asc(conn, jwt, "GET", f"/v1/apps/{app_id}/betaGroups")
    internal_group = None
    for g in data.get("data", []):
        if g["attributes"].get("isInternalGroup", False):
            internal_group = g
            break
    if not internal_group:
        print("No internal beta group found")
        sys.exit(1)
    internal_id = internal_group["id"]
    print(f"Internal group: {internal_group['attributes']['name']} ({internal_id})")

    # Get builds already in internal group
    status, data = asc(conn, jwt, "GET", f"/v1/betaGroups/{internal_id}/builds?limit=200&fields[builds]=version")
    existing_ids = {b["id"] for b in data.get("data", [])}
    existing_versions = [b["attributes"].get("version", "?") for b in data.get("data", [])]
    print(f"Already in group: builds {sorted(existing_versions)}")

    # Get ALL builds (paginated)
    all_builds = []
    next_url = f"/v1/apps/{app_id}/builds?limit=200"
    while next_url:
        status, data = asc(conn, jwt, "GET", next_url)
        all_builds.extend(data.get("data", []))
        next_url = None
        links = data.get("links", {})
        if "next" in links:
            next_url = links["next"].replace("https://api.appstoreconnect.apple.com", "")

    print(f"Total builds on ASC: {len(all_builds)}")

    # Add builds not yet in group, one at a time
    added = 0
    skipped = 0
    failed = 0
    for b in all_builds:
        bid = b["id"]
        ver = b["attributes"].get("version", "?")
        pstate = b["attributes"].get("processingState", "?")

        if bid in existing_ids:
            print(f"  Build {ver}: already in group, skipping")
            skipped += 1
            continue

        # Try to add
        status, data = asc(conn, jwt, "POST",
            f"/v1/betaGroups/{internal_id}/relationships/builds",
            {"data": [{"type": "builds", "id": bid}]})

        if status in (200, 201, 204):
            print(f"  Build {ver} ({pstate}): ADDED to internal group")
            added += 1
        else:
            err_msg = data.get("errors", [{}])[0].get("detail", str(data))[:200] if data.get("errors") else str(data)[:200]
            print(f"  Build {ver} ({pstate}): FAILED ({status}) — {err_msg}")
            failed += 1

    print(f"\nResult: {added} added, {skipped} already in group, {failed} failed")
    if added > 0:
        print("Dennis can now see new builds in TestFlight (pull-to-refresh).")

    conn.close()


if __name__ == "__main__":
    main()

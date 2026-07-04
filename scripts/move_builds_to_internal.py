#!/usr/bin/env python3
"""Move VALID builds (not INVALID) to the internal beta group."""
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


key_id = os.environ["ASC_API_KEY_ID"]
issuer_id = os.environ["ASC_ISSUER_ID"]
key_content = os.environ["ASC_API_KEY_CONTENT"]
jwt = make_jwt(key_id, issuer_id, key_content)
ctx = ssl.create_default_context()
conn = http.client.HTTPSConnection("api.appstoreconnect.apple.com", context=ctx)

bundle_id = "cloud.dkroeker.GaussianSplattingViewer"
status, data = asc(conn, jwt, "GET", f"/v1/apps?filter[bundleId]={bundle_id}")
app_id = data["data"][0]["id"]
print(f"App: {app_id}")

# Get all builds
status, data = asc(conn, jwt, "GET", f"/v1/apps/{app_id}/builds?limit=10")
builds = data.get("data", [])

# Get internal group ID
status, data = asc(conn, jwt, "GET", f"/v1/apps/{app_id}/betaGroups")
internal_id = None
for g in data.get("data", []):
    if g["attributes"].get("isInternalGroup"):
        internal_id = g["id"]
        print(f"Internal group: {g['attributes']['name']} ({internal_id})")
        break

if not internal_id:
    print("No internal group found!")
    sys.exit(1)

# Move only VALID builds that aren't already in internal group
moved = []
skipped = []
for b in builds:
    ver = b["attributes"].get("version", "?")
    bid = b["id"]
    proc = b["attributes"].get("processingState", "?")
    if proc == "VALID":
        moved.append({"type": "builds", "id": bid})
        print(f"  Build {ver} ({bid}): VALID → will move to internal group")
    else:
        skipped.append((ver, bid, proc))
        print(f"  Build {ver} ({bid}): {proc} → SKIPPED")

if moved:
    print(f"\nMoving {len(moved)} build(s) to internal group...")
    status, data = asc(conn, jwt, "POST",
        f"/v1/betaGroups/{internal_id}/relationships/builds",
        {"data": moved})
    if status in (200, 201, 204):
        print(f"SUCCESS: {len(moved)} build(s) added to internal group!")
        for m in moved:
            print(f"  Build {m['id']} — now in Internal Testers group")
    else:
        print(f"FAILED: {status} {json.dumps(data)[:300]}")
else:
    print("No VALID builds to move.")

if skipped:
    print(f"\nSkipped {len(skipped)} non-VALID build(s):")
    for ver, bid, state in skipped:
        print(f"  Build {ver} ({bid}): {state}")

conn.close()

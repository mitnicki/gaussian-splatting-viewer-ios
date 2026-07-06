#!/usr/bin/env python3
"""Diagnose build states — find what blocks internal group assignment."""
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

# Builds — fetch ALL, sorted by version descending
all_builds = []
next_url = f"/v1/apps/{app_id}/builds?limit=200&sort=-uploadedDate"
while next_url:
    status, data = asc(conn, jwt, "GET", next_url)
    all_builds.extend(data.get("data", []))
    next_url = None
    links = data.get("links", {})
    if "next" in links:
        next_url = links["next"].replace("https://api.appstoreconnect.apple.com", "")

print(f"Total builds: {len(all_builds)}\n")

for b in all_builds:
    bid = b["id"]
    a = b.get("attributes", {})
    ver = a.get("version", "?")
    pstate = a.get("processingState", "?")
    uploaded = a.get("uploadedDate", "?")[:19]
    print(f"=== Build {ver} ({bid}) ===")
    print(f"  processingState: {pstate}")
    print(f"  uploadedDate: {uploaded}")

    # Beta review submission
    rs, rd = asc(conn, jwt, "GET", f"/v1/builds/{bid}/betaAppReviewSubmission")
    if rs == 200 and rd.get("data"):
        rattrs = rd["data"].get("attributes", {})
        print(f"  betaReviewState: {rattrs.get('betaReviewState', '?')}")
        print(f"  submittedDate: {rattrs.get('submittedDate', '?')[:19]}")

    # Build beta detail (internal/external state)
    bs, bd = asc(conn, jwt, "GET", f"/v1/builds/{bid}/buildBetaDetail")
    if bs == 200 and bd.get("data"):
        battrs = bd["data"].get("attributes", {})
        print(f"  internalBuildState: {battrs.get('internalBuildState', '?')}")
        print(f"  externalBuildState: {battrs.get('externalBuildState', '?')}")
    print()

# Internal group builds
status, data = asc(conn, jwt, "GET", f"/v1/apps/{app_id}/betaGroups")
for g in data.get("data", []):
    gid = g["id"]
    name = g["attributes"]["name"]
    is_int = g["attributes"].get("isInternalGroup", False)
    if is_int:
        status2, bd = asc(conn, jwt, "GET", f"/v1/betaGroups/{gid}/builds?limit=10&fields[builds]=version,processingState")
        print(f"\n=== Internal Group '{name}' builds ===")
        for b in bd.get("data", []):
            print(f"  Build {b['attributes'].get('version','?')} ({b['id']}) state={b['attributes'].get('processingState','?')}")

conn.close()

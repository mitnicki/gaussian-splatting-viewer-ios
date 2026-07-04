#!/usr/bin/env python3
"""Investigate why Build 7 failed internal group assignment."""
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

# Get all builds with full detail
bids = {
    "5": "180a2386-4331-42ad-88f8-fab3fb4a541d",
    "7": "b2fe4794-5f76-4a7b-ba48-7803bb55fd7e",
    "4": "7b3ec485-0497-4119-bb95-79fdab1389d3",
    "6": "7844f1ac-166b-4517-a607-a5a62d22d881",
}

for ver, bid in sorted(bids.items()):
    status, data = asc(conn, jwt, "GET", f"/v1/builds/{bid}")
    attrs = data.get("data", {}).get("attributes", {})
    print(f"\n=== Build {ver} ({bid}) ===")
    for k, v in sorted(attrs.items()):
        print(f"  {k}: {v}")
    
    # Check all relationships
    rels = data.get("data", {}).get("relationships", {})
    for rname, rdata in sorted(rels.items()):
        rstatus, rresult = asc(conn, jwt, "GET", f"/v1/builds/{bid}/{rname}")
        print(f"  Relationship '{rname}' ({rstatus}): {json.dumps(rresult)[:200]}")

conn.close()

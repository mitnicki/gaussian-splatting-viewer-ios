#!/usr/bin/env python3
"""Check what attributes and relationships builds have."""
import json, time, os, base64
import http.client, ssl

def make_jwt(key_id, issuer_id, key_content):
    from cryptography.hazmat.primitives import serialization, hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    key_pem = key_content
    if "BEGIN PRIVATE KEY" not in key_pem:
        key_pem = "-----BEGIN PRIVATE KEY-----\n" + key_pem + "\n-----END PRIVATE KEY-----"
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

key_id = os.environ.get("ASC_API_KEY_ID", "")
issuer_id = os.environ.get("ASC_ISSUER_ID", "")
key_content = os.environ.get("ASC_API_KEY_CONTENT", "")

jwt = make_jwt(key_id, issuer_id, key_content)
ctx = ssl.create_default_context()
conn = http.client.HTTPSConnection("api.appstoreconnect.apple.com", context=ctx)

# Get builds
status, data = asc(conn, jwt, "GET", "/v1/builds?limit=1")
print(f"Status: {status}")
if status == 200 and data.get("data"):
    b = data["data"][0]
    print(f"\nBuild attributes:")
    for k in sorted(b.get("attributes", {}).keys()):
        print(f"  {k}: {b['attributes'][k]}")
    print(f"\nBuild relationships:")
    for k in sorted(b.get("relationships", {}).keys()):
        print(f"  {k}")

# Also check what the build's exportCompliance looks like
build_id = data["data"][0]["id"]
print(f"\n--- Trying exportCompliance endpoints for build {build_id} ---")

# Try the relationship endpoint
status, data = asc(conn, jwt, "GET", f"/v1/builds/{build_id}/relationships/exportCompliance")
print(f"GET relationships/exportCompliance: {status} {json.dumps(data)[:200]}")

# Try direct
status, data = asc(conn, jwt, "GET", f"/v1/builds/{build_id}/exportCompliance")
print(f"GET exportCompliance: {status} {json.dumps(data)[:200]}")

conn.close()

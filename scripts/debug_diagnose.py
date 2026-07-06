#!/usr/bin/env python3
"""Debug: check what the ASC API returns for builds."""
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

# Get app
status, data = asc(conn, jwt, "GET", "/v1/apps?filter[bundleId]=cloud.dkroeker.GaussianSplattingViewer")
app_id = data["data"][0]["id"]
print(f"App ID: {app_id}")

# Try different API calls
print("\n--- /v1/builds (no filter) ---")
status, data = asc(conn, jwt, "GET", "/v1/builds?limit=5")
print(f"Status: {status}")
print(f"Data count: {len(data.get('data', []))}")
if data.get('data'):
    for b in data['data'][:3]:
        print(f"  Build {b['attributes'].get('version','?')} ({b['id']})")

print("\n--- /v1/apps/{app_id}/builds ---")
status, data = asc(conn, jwt, "GET", f"/v1/apps/{app_id}/builds?limit=5")
print(f"Status: {status}")
print(f"Data count: {len(data.get('data', []))}")
if data.get('errors'):
    print(f"Errors: {json.dumps(data['errors'])[:300]}")
if data.get('data'):
    for b in data['data'][:3]:
        print(f"  Build {b['attributes'].get('version','?')} ({b['id']})")

print("\n--- /v1/builds?filter[app]={app_id} ---")
status, data = asc(conn, jwt, "GET", f"/v1/builds?filter[app]={app_id}&limit=5")
print(f"Status: {status}")
print(f"Data count: {len(data.get('data', []))}")
if data.get('errors'):
    print(f"Errors: {json.dumps(data['errors'])[:300]}")
if data.get('data'):
    for b in data['data'][:3]:
        print(f"  Build {b['attributes'].get('version','?')} ({b['id']})")

conn.close()

#!/usr/bin/env python3
"""Full diagnostic of beta testing setup."""
import json, time, sys, os, base64
import http.client, ssl

def make_jwt(key_id, issuer_id, key_content):
    from cryptography.hazmat.primitives import serialization, hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    key_pem = key_content
    if "BEGIN PRIVATE KEY" not in key_pem:
        key_pem = "-----BEGIN PRIVATE KEY-----\n" + key_content + "\n-----END PRIVATE KEY-----"
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

bundle_id = "cloud.dkroeker.GaussianSplattingViewer"
status, data = asc(conn, jwt, "GET", f"/v1/apps?filter[bundleId]={bundle_id}")
app_id = data["data"][0]["id"]
print(f"App: {app_id}")

# List all beta testers
status, data = asc(conn, jwt, "GET", "/v1/betaTesters?limit=50")
print(f"\n=== All Beta Testers ({len(data.get('data',[]))}) ===")
for t in data.get("data", []):
    email = t["attributes"].get("email", "")
    state = t["attributes"].get("state", "")
    first = t["attributes"].get("firstName", "")
    last = t["attributes"].get("lastName", "")
    print(f"  {first} {last} <{email}> state={state} id={t['id']}")

# List groups with testers
status, data = asc(conn, jwt, "GET", f"/v1/apps/{app_id}/betaGroups")
print(f"\n=== Beta Groups ===")
for g in data.get("data", []):
    gid = g["id"]
    name = g["attributes"].get("name", "")
    is_internal = g["attributes"].get("isInternalGroup", False)
    print(f"\nGroup: {name} ({gid}) internal={is_internal}")
    
    status2, data2 = asc(conn, jwt, "GET", f"/v1/betaGroups/{gid}/betaTesters")
    for t in data2.get("data", []):
        email = t["attributes"].get("email", "")
        state = t["attributes"].get("state", "")
        print(f"  Tester: {email} state={state}")
    
    status3, data3 = asc(conn, jwt, "GET", f"/v1/betaGroups/{gid}/relationships/builds")
    for b in data3.get("data", []):
        print(f"  Build: {b['id']}")

# Check beta app localizations
status, data = asc(conn, jwt, "GET", f"/v1/apps/{app_id}/betaAppLocalizations")
print(f"\n=== Beta App Localizations ({len(data.get('data',[]))}) ===")
for loc in data.get("data", []):
    desc = loc["attributes"].get("description", "")[:80]
    locale = loc["attributes"].get("locale", "")
    print(f"  {locale}: {desc}... (id={loc['id']})")

# Check beta app review details
status, data = asc(conn, jwt, "GET", f"/v1/apps/{app_id}/betaAppReviewDetails")
print(f"\n=== Beta App Review Details (status={status}) ===")
if data.get("data"):
    rad = data["data"][0]
    print(f"  id={rad['id']}")
    print(f"  contactEmail={rad['attributes'].get('contactEmail','')}")
else:
    print(f"  No review details found")
    print(f"  Response: {json.dumps(data)[:200]}")

# Check builds
status, data = asc(conn, jwt, "GET", f"/v1/apps/{app_id}/builds?limit=5")
print(f"\n=== Builds ===")
for b in data.get("data", []):
    ver = b["attributes"].get("version", "")
    expired = b["attributes"].get("expired", False)
    processing = b["attributes"].get("processingState", "")
    print(f"  v{ver} ({b['id']}): expired={expired} processing={processing}")

conn.close()

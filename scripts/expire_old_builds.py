#!/usr/bin/env python3
"""Expire old builds blocking beta review."""
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
status, data = asc(conn, jwt, "GET", f"/v1/apps/{app_id}/builds?limit=200")
builds = data.get("data", [])
print(f"Total builds: {len(builds)}\n")

# Check each build's beta detail to find externalBuildState
BLOCKING_STATES = {"WAITING_FOR_BETA_REVIEW", "IN_BETA_REVIEW"}
to_expire = []
for b in builds:
    ver = b["attributes"].get("version", "?")
    bid = b["id"]
    expired = b["attributes"].get("expired", False)
    proc = b["attributes"].get("processingState", "?")
    # Fetch buildBetaDetail for externalBuildState
    bs, bd = asc(conn, jwt, "GET", f"/v1/builds/{bid}/buildBetaDetail")
    ext_state = "UNKNOWN"
    int_state = "UNKNOWN"
    if bs == 200 and bd.get("data"):
        battrs = bd["data"].get("attributes", {})
        ext_state = battrs.get("externalBuildState", "UNKNOWN")
        int_state = battrs.get("internalBuildState", "UNKNOWN")
    blocking = ext_state in BLOCKING_STATES and not expired
    flag = " *** BLOCKING ***" if blocking else ""
    print(f"  Build {ver:>3}: ext={ext_state:>30} int={int_state:>20} expired={expired}{flag}")
    if blocking:
        to_expire.append(b)

if not to_expire:
    print("\nNo builds blocking beta review. Queue is clear.")
    conn.close()
    sys.exit(0)

print(f"\n{len(to_expire)} builds blocking beta review — expiring them...")
for b in to_expire:
    ver = b["attributes"]["version"]
    bid = b["id"]
    print(f"\nExpiring build {ver} ({bid})...")
    status, data = asc(conn, jwt, "PATCH", f"/v1/builds/{bid}", {
        "data": {"type": "builds", "id": bid, "attributes": {"expired": True}}
    })
    print(f"  Result: {status}")
    if status != 200:
        print(f"  {json.dumps(data)[:300]}")
    else:
        print(f"  Expired successfully!")

print("\nWaiting 20s for ASC propagation...")
time.sleep(20)

# Verify build 135
print("\n--- Checking build 135 ---")
for b in builds:
    if b["attributes"].get("version") == "135":
        bid = b["id"]
        bs, bd = asc(conn, jwt, "GET", f"/v1/builds/{bid}/buildBetaDetail")
        if bs == 200 and bd.get("data"):
            ext = bd["data"]["attributes"].get("externalBuildState", "?")
            print(f"Build 135: ext={ext} expired={b['attributes'].get('expired')}")
        break

conn.close()

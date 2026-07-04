#!/usr/bin/env python3
"""Diagnose build states — extended version."""
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

# GET ALL BUILDS (no fields filter, get everything)
status, data = asc(conn, jwt, "GET", f"/v1/apps/{app_id}/builds?limit=10")
print(f"\nAll builds ({status}): {len(data.get('data',[]))} found")
for b in data.get("data", []):
    a = b["attributes"]
    bid = b["id"]
    ver = a.get("version", "?")
    proc = a.get("processingState", "?")
    aud = a.get("buildAudienceType", "?")
    expired = a.get("expired", "?")
    uploaded = a.get("uploadedDate", "?")
    print(f"  Build {ver} ({bid}): proc={proc} audience={aud} expired={expired} uploaded={uploaded}")

# Check what builds are in each group
status, data = asc(conn, jwt, "GET", f"/v1/apps/{app_id}/betaGroups")
for g in data.get("data", []):
    gid = g["id"]
    name = g["attributes"]["name"]
    is_int = g["attributes"].get("isInternalGroup", False)
    status2, bd = asc(conn, jwt, "GET", f"/v1/betaGroups/{gid}/builds?limit=10")
    blist = [f"B{b['attributes'].get('version','?')}" for b in bd.get("data", [])]
    print(f"  Group '{name}' (internal={is_int}): {', '.join(blist) if blist else 'empty'}")

print("\nExport compliance for each build:")
for b in data.get("data", []):
    bid = b["id"]
    ver = b["attributes"].get("version", "?")
    # GET export compliance directly on build
    status, ed = asc(conn, jwt, "GET", f"/v1/builds/{bid}")
    a = ed.get("data", {}).get("attributes", {})
    enc = a.get("usesNonExemptEncryption", "N/A")
    ecs = a.get("exportComplianceState", "N/A")
    pst = a.get("processingState", "N/A")
    bt = a.get("betaAppReviewSubmissionState", "N/A")
    print(f"  Build {ver}: enc={enc} ecState={ecs} procState={pst} betaReviewState={bt}")

conn.close()

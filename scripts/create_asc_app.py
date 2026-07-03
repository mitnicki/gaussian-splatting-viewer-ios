#!/usr/bin/env python3
"""Create an app record in App Store Connect via the API."""
import json, time, sys, os, base64
import http.client, ssl

def make_jwt(key_id, issuer_id, key_content):
    from cryptography.hazmat.primitives import serialization, hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

    key_pem = key_content
    if "BEGIN PRIVATE KEY" not in key_pem:
        key_pem = "-----BEGIN PRIVATE KEY-----\n" + key_content + "\n-----END PRIVATE KEY-----"

    try:
        private_key = serialization.load_pem_private_key(key_pem.encode(), password=None)
    except Exception:
        key_der = base64.b64decode(key_content)
        private_key = serialization.load_der_private_key(key_der, password=None)

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
    sig_b64 = b64url(raw_sig)

    return f"{header_b64}.{payload_b64}.{sig_b64}"

def main():
    key_id = os.environ.get("ASC_API_KEY_ID", "")
    issuer_id = os.environ.get("ASC_ISSUER_ID", "")
    key_content = os.environ.get("ASC_API_KEY_CONTENT", "")
    bundle_id = "cloud.dkroeker.GaussianSplattingViewer"

    if not all([key_id, issuer_id, key_content]):
        print("Missing required env vars")
        sys.exit(1)

    jwt_token = make_jwt(key_id, issuer_id, key_content)

    ctx = ssl.create_default_context()
    conn = http.client.HTTPSConnection("api.appstoreconnect.apple.com", context=ctx)

    # Check if app already exists
    conn.request("GET", f"/v1/apps?filter[bundleId]={bundle_id}",
                 headers={"Authorization": f"Bearer {jwt_token}"})
    resp = conn.getresponse()
    body = json.loads(resp.read().decode())

    if resp.status == 200 and body.get("data"):
        app_id = body["data"][0]["id"]
        print(f"App already exists: {app_id}")
        sys.exit(0)

    # Create new app
    create_body = {
        "data": {
            "type": "apps",
            "attributes": {
                "name": "Gaussian Splatting Viewer",
                "bundleId": bundle_id,
                "primaryLocale": "en-US",
                "sku": "dkroeker.gaussiansplatviewer"
            }
        }
    }

    conn.request("POST", "/v1/apps",
                 body=json.dumps(create_body),
                 headers={
                     "Authorization": f"Bearer {jwt_token}",
                     "Content-Type": "application/json"
                 })
    resp = conn.getresponse()
    body = json.loads(resp.read().decode())

    if resp.status == 201:
        app_id = body["data"]["id"]
        print(f"App created: {app_id}")
    else:
        print(f"Error creating app: {resp.status} {body}")
        sys.exit(1)

if __name__ == "__main__":
    main()

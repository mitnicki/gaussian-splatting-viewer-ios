#!/usr/bin/env python3
"""Revoke orphaned distribution certificates via App Store Connect API."""
import json, time, sys, os, base64, http.client, ssl

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

    if not all([key_id, issuer_id, key_content]):
        print("Missing required env vars")
        sys.exit(1)

    jwt_token = make_jwt(key_id, issuer_id, key_content)

    ctx = ssl.create_default_context()
    conn = http.client.HTTPSConnection("api.appstoreconnect.apple.com", context=ctx)

    # List all certificates (no filter — see everything)
    conn.request("GET", "/v1/certificates?limit=200",
                 headers={"Authorization": f"Bearer {jwt_token}"})
    resp = conn.getresponse()
    body = json.loads(resp.read().decode())

    if resp.status != 200:
        print(f"Error listing certs: {resp.status} {body}")
        sys.exit(1)

    certs = body.get("data", [])
    print(f"Found {len(certs)} certificates")

    for cert in certs:
        cert_id = cert["id"]
        cert_type = cert["attributes"].get("certificateType", "?")
        expiration = cert["attributes"].get("expirationDate", "?")
        display_name = cert["attributes"].get("displayName", "?")
        print(f"  {cert_id} | {cert_type} | {display_name} | expires {expiration}")

        # Try to revoke
        conn.request("DELETE", f"/v1/certificates/{cert_id}",
                     headers={"Authorization": f"Bearer {jwt_token}"})
        revoke_resp = conn.getresponse()
        revoke_body = revoke_resp.read().decode()

        if revoke_resp.status == 204:
            print(f"  -> REVOKED")
        else:
            print(f"  -> FAILED to revoke: {revoke_resp.status} {revoke_body[:200]}")

    # Verify
    conn.request("GET", "/v1/certificates?filter[certificateType]=IOS_DISTRIBUTION",
                 headers={"Authorization": f"Bearer {jwt_token}"})
    resp = conn.getresponse()
    body = json.loads(resp.read().decode())
    remaining = body.get("data", [])
    print(f"\nRemaining distribution certificates: {len(remaining)}")

if __name__ == "__main__":
    main()

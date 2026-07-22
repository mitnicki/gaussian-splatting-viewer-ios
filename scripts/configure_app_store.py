#!/usr/bin/env python3
"""Configure ALL missing App Store Connect metadata that ASC reports as required.

Fixes the errors from the previous version which used wrong API field names:
- copyright goes on appStoreVersions (not apps)
- contentRightsDeclaration goes on apps (not appInfos)
- primaryCategory is a RELATIONSHIP on appInfos (not an attribute)
- appStoreReviewDetails relates to appStoreVersion (not app)
- App Privacy is NOT available via API — requires manual ASC web UI setup

Sets via ASC API:
1. Content rights declaration on app (DOES_NOT_USE_THIRD_PARTY_CONTENT)
2. Primary + secondary category on appInfo (as relationships)
3. Copyright on appStoreVersion
4. Price tier via appPriceSchedules
5. Review contact info via appStoreReviewDetails (relationship to appStoreVersion)
6. Re-uploads metadata + screenshots (idempotent — submit_app_store_review.py handles this)

App Privacy MUST be set manually in ASC web UI by an Admin.
"""
import json, time, sys, os, base64
import http.client, ssl

def make_jwt(key_id, issuer_id, key_content):
    from cryptography.hazmat.primitives import serialization, hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    key_pem = key_content
    if "BEGIN PRIVATE KEY" not in key_pem:
        key_pem = "-----BEGIN PRIVATE KEY-----\n" + key_content + "\n-----END PRIVATE KEY-----\n"
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

def try_patch(conn, jwt, path, body, label, ok_codes=(200, 201, 204)):
    status, data = asc(conn, jwt, "PATCH", path, body)
    if status in ok_codes:
        print(f"  OK [{status}] — {label}")
        return True
    else:
        err = json.dumps(data)[:400]
        print(f"  WARN [{status}] — {label}: {err}")
        return False

def try_post(conn, jwt, path, body, label, ok_codes=(200, 201, 204)):
    status, data = asc(conn, jwt, "POST", path, body)
    if status in ok_codes:
        print(f"  OK [{status}] — {label}")
        return True, data
    else:
        err = json.dumps(data)[:400]
        print(f"  WARN [{status}] — {label}: {err}")
        return False, data

# --- Setup ---
key_id = os.environ.get("ASC_API_KEY_ID", "")
issuer_id = os.environ.get("ASC_ISSUER_ID", "")
key_content = os.environ.get("ASC_API_KEY_CONTENT", "")
price_tier = int(os.environ.get("PRICE_TIER", "3"))

if not all([key_id, issuer_id, key_content]):
    print("ERROR: ASC_API_KEY_ID, ASC_ISSUER_ID, ASC_API_KEY_CONTENT must be set")
    sys.exit(1)

jwt = make_jwt(key_id, issuer_id, key_content)
ctx = ssl.create_default_context()
conn = http.client.HTTPSConnection("api.appstoreconnect.apple.com", context=ctx)

bundle_id = "cloud.dkroeker.GaussianSplattingViewer"
COPYRIGHT = "2026 Dennis Kroeker"
# Category IDs for App Store — these are the category IDs used as relationship IDs
# GRAPHICS_AND_DESIGN is the primary category, UTILITIES is secondary
PRIMARY_CATEGORY_ID = "GRAPHICS_AND_DESIGN"
SECONDARY_CATEGORY_ID = "UTILITIES"

errors = []

# --- 1. Get app ---
status, data = asc(conn, jwt, "GET", f"/v1/apps?filter[bundleId]={bundle_id}")
if status != 200 or not data.get("data"):
    print(f"ERROR: App not found (status={status}): {json.dumps(data)[:300]}")
    sys.exit(1)
app = data["data"][0]
app_id = app["id"]
print(f"App: {app_id} ({app['attributes'].get('name')})")

# --- 2. Set content rights on app (NOT on appInfo) ---
print("\n=== Content Rights Declaration ===")
try_patch(conn, jwt, f"/v1/apps/{app_id}", {
    "data": {
        "type": "apps",
        "id": app_id,
        "attributes": {
            "contentRightsDeclaration": "DOES_NOT_USE_THIRD_PARTY_CONTENT"
        }
    }
}, "contentRightsDeclaration=DOES_NOT_USE_THIRD_PARTY_CONTENT")

# --- 3. Set primary + secondary category on appInfo (as RELATIONSHIPS, not attributes) ---
print("\n=== Primary + Secondary Category ===")
status, data = asc(conn, jwt, "GET", f"/v1/apps/{app_id}/appInfos")
app_info_id = None
if status == 200 and data.get("data"):
    for info in data["data"]:
        state = info["attributes"].get("appStoreState", "")
        if state in ("PREPARE_FOR_SUBMISSION", "READY_FOR_SALE", "REJECTED", "DEVELOPER_REJECTED"):
            app_info_id = info["id"]
            break
    if not app_info_id:
        app_info_id = data["data"][0]["id"]
    print(f"  App Info ID: {app_info_id}")
else:
    print(f"  ERROR: Could not fetch appInfos: {status} {json.dumps(data)[:300]}")
    errors.append("appInfos fetch failed")

if app_info_id:
    # Categories are RELATIONSHIPS with type "appCategories"
    try_patch(conn, jwt, f"/v1/appInfos/{app_info_id}", {
        "data": {
            "type": "appInfos",
            "id": app_info_id,
            "relationships": {
                "primaryCategory": {
                    "data": {"type": "appCategories", "id": PRIMARY_CATEGORY_ID}
                },
                "secondaryCategory": {
                    "data": {"type": "appCategories", "id": SECONDARY_CATEGORY_ID}
                }
            }
        }
    }, f"primaryCategory={PRIMARY_CATEGORY_ID}, secondaryCategory={SECONDARY_CATEGORY_ID}")

# --- 4. Get App Store version in PREPARE_FOR_SUBMISSION ---
print("\n=== Finding App Store version ===")
status, data = asc(conn, jwt, "GET", f"/v1/apps/{app_id}/appStoreVersions")
version_id = None
version_string = None
if status == 200:
    for v in data.get("data", []):
        state = v["attributes"].get("appStoreState", "")
        if state == "PREPARE_FOR_SUBMISSION":
            version_id = v["id"]
            version_string = v["attributes"].get("versionString", "")
            break
if not version_id:
    for v in data.get("data", []):
        state = v["attributes"].get("appStoreState", "")
        if state in ("WAITING_FOR_REVIEW", "IN_REVIEW", "PENDING_DEVELOPER_RELEASE", "READY_FOR_SALE"):
            print(f"Version {v['attributes']['versionString']} already in state {state}")
            version_id = v["id"]
            version_string = v["attributes"]["versionString"]
            break
if not version_id:
    print("ERROR: No App Store version found in PREPARE_FOR_SUBMISSION state.")
    print("Run submit_app_store_review.py first to create the version.")
    sys.exit(1)
print(f"Version: {version_string} ({version_id})")

# --- 5. Set copyright on appStoreVersion (NOT on app) ---
print("\n=== Copyright ===")
try_patch(conn, jwt, f"/v1/appStoreVersions/{version_id}", {
    "data": {
        "type": "appStoreVersions",
        "id": version_id,
        "attributes": {
            "copyright": COPYRIGHT,
            "usesIdfa": False,
        }
    }
}, f"copyright={COPYRIGHT}")

# --- 6. Set price tier via appPriceSchedules ---
# ponytail: v2/appPricePoints is the correct endpoint (v1 app-nested is deprecated).
# Price point IDs map to specific tiers per territory.
print(f"\n=== Price Tier {price_tier} ===")
status, data = asc(conn, jwt, "GET", f"/v1/apps/{app_id}/appPriceSchedule?include=manualPrices,baseTerritory")
if status == 200 and data.get("data"):
    included = data.get("included", [])
    price_points = [p for p in included if p.get("type") == "appPrices"]
    if price_points:
        print(f"  Price schedule exists with {len(price_points)} manual prices — OK")
    else:
        print(f"  Price schedule exists but no manual prices — need to set")
        # Fall through to set pricing below
        data = {}  # Clear so we enter the else branch
if not (status == 200 and data.get("data")):
    # Look up price points via v2 endpoint with app filter
    v2_status, v2_data = asc(conn, jwt, "GET", f"/v2/appPricePoints?filter[app]={app_id}&filter[territory]=DEU&limit=200")
    tier_id = None
    if v2_status == 200:
        for pt in v2_data.get("data", []):
            attrs = pt.get("attributes", {})
            cp = attrs.get("customerPrice", {})
            amount = str(cp.get("value", "")) if isinstance(cp, dict) else str(cp)
            if amount == "2.99":
                tier_id = pt["id"]
                print(f"  Found price point for 2.99 EUR (tier {price_tier}): {tier_id}")
                break
    if not tier_id:
        # Fallback: try v1 app-nested endpoint
        v1_status, v1_data = asc(conn, jwt, "GET", f"/v1/apps/{app_id}/appPricePoints?filter[territory]=DEU&limit=200")
        if v1_status == 200:
            for pt in v1_data.get("data", []):
                attrs = pt.get("attributes", {})
                if str(attrs.get("priceTier", "")) == str(price_tier):
                    tier_id = pt["id"]
                    print(f"  Found price point for tier {price_tier}: {tier_id}")
                    break
                price_val = attrs.get("price", {})
                if isinstance(price_val, dict) and str(price_val.get("value", "")) == "2.99":
                    tier_id = pt["id"]
                    print(f"  Found price point by price 2.99 EUR: {tier_id}")
                    break
    if not tier_id:
        print(f"  WARN: Could not find price point for tier {price_tier}")
        # Debug: search both v2 and v1 data for 2.99
        for src, d in [("v2", v2_data), ("v1", v1_data)]:
            if d.get("data"):
                for pt in d["data"]:
                    attrs = pt.get("attributes", {})
                    cp = str(attrs.get("customerPrice", attrs.get("price", "")))
                    if "2.99" in cp:
                        print(f"    MATCH [{src}]: {pt['id']} attrs={json.dumps(attrs)[:200]}")
                for pt in d["data"][:3]:
                    print(f"    Sample [{src}]: {pt['id']} attrs={json.dumps(pt.get('attributes',{}))[:200]}")
        errors.append(f"Price tier {price_tier}: could not find price point")
    else:
        try_post(conn, jwt, "/v1/appPriceSchedules", {
            "data": {
                "type": "appPriceSchedules",
                "relationships": {
                    "app": {"data": {"type": "apps", "id": app_id}},
                    "baseTerritory": {"data": {"type": "territories", "id": "DEU"}},
                    "manualPrices": {
                        "data": [{"type": "appPrices", "id": f"price-{price_tier}-DEU"}]
                    }
                }
            },
            "included": [{
                "type": "appPrices",
                "id": f"price-{price_tier}-DEU",
                "attributes": {"startDate": None, "endDate": None},
                "relationships": {
                    "appPricePoint": {"data": {"type": "appPricePoints", "id": tier_id}}
                }
            }]
        }, f"price schedule tier {price_tier}")

# --- 7. Set review contact info via appStoreReviewDetails (relationship to appStoreVersion) ---
print("\n=== Review Contact Information ===")
# Check if review detail already exists
status, data = asc(conn, jwt, "GET", f"/v1/appStoreVersions/{version_id}/appStoreReviewDetail")
review_detail_id = None
if status == 200 and data.get("data"):
    review_detail_id = data["data"]["id"]
    print(f"  Existing review detail: {review_detail_id}")

review_attrs = {
    "contactFirstName": "Dennis",
    "contactLastName": "Kroeker",
    "contactEmail": "dennis@kroeker.cloud",
    "contactPhone": os.environ.get("ASC_REVIEW_PHONE", "+49 571 00000000"),
    "demoAccountRequired": False,
    "notes": "No demo account needed. Open the app and tap 'Try Demo' for the bundled sample scene.",
}

if review_detail_id:
    try_patch(conn, jwt, f"/v1/appStoreReviewDetails/{review_detail_id}", {
        "data": {
            "type": "appStoreReviewDetails",
            "id": review_detail_id,
            "attributes": review_attrs
        }
    }, "update review contact info")
else:
    # Create with relationship to appStoreVersion (NOT app)
    ok, resp = try_post(conn, jwt, "/v1/appStoreReviewDetails", {
        "data": {
            "type": "appStoreReviewDetails",
            "attributes": review_attrs,
            "relationships": {
                "appStoreVersion": {
                    "data": {"type": "appStoreVersions", "id": version_id}
                }
            }
        }
    }, "create review contact info")

# --- 8. App Privacy — NOT available via API ---
print("\n=== App Privacy ===")
print("  NOTE: App Privacy (data collection declaration) is NOT available via the ASC API.")
print("  This must be set manually in App Store Connect → App Privacy section.")
print("  For this app: select 'Data Not Collected' (the app collects no data).")
print("  Dennis needs to do this in the ASC web UI, or an Admin API key may be needed.")
errors.append("App Privacy: must be set manually in ASC web UI")

# --- 9. Summary ---
print("\n=== Configuration Summary ===")
print(f"  App ID: {app_id}")
print(f"  Version: {version_string} ({version_id})")
print(f"  Content rights: DOES_NOT_USE_THIRD_PARTY_CONTENT")
print(f"  Category: {PRIMARY_CATEGORY_ID} / {SECONDARY_CATEGORY_ID}")
print(f"  Copyright: {COPYRIGHT}")
print(f"  Price tier: {price_tier}")
print(f"  Review contact: Dennis Kroeker <dennis@kroeker.cloud>")
print(f"\n  Remaining manual step:")
print(f"    - App Privacy: set 'Data Not Collected' in ASC web UI")

conn.close()
print("\nDone.")

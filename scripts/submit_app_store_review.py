#!/usr/bin/env python3
"""Submit build for App Store review — creates version, uploads metadata + screenshots, links build, submits.

Handles the full flow via ASC API:
1. Get app
2. Get latest valid build
3. Find or create App Store version (handles version string mismatch)
4. Create or update localizations (de-DE, en-US) with metadata from fastlane/metadata/
5. Upload screenshots to ASC
6. Link build to version
7. Submit for review
"""
import json, time, sys, os, base64, pathlib, struct, zlib
import http.client, ssl, urllib.request

def make_jwt(key_id, issuer_id, key_content):
    from cryptography.hazmat.primitives import serialization, hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    key_pem = key_content
    if "BEGIN PRIVATE KEY" not in key_pem:
        key_pem = "[REDACTED PRIVATE KEY]\n"
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

def read_meta(locale, field):
    p = pathlib.Path("fastlane/metadata") / locale / f"{field}.txt"
    if p.exists():
        return p.read_text().strip()
    return ""

def png_dimensions(path):
    with open(path, "rb") as f:
        data = f.read(24)
        if data[:8] != b'\x89PNG\r\n\x1a\n':
            return None, None
        w, h = struct.unpack('>II', data[16:24])
        return w, h

def upload_screenshot(conn, jwt, localization_id, screenshot_path, display_type="APP_IPHONE_67"):
    """Upload a single screenshot to ASC. Returns True on success."""
    # Check if screenshot set already exists for this locale + display type
    status, data = asc(conn, jwt, "GET",
        f"/v1/appStoreVersionLocalizations/{localization_id}/appScreenshotSets?limit=10")
    existing_set_id = None
    if status == 200:
        for ss in data.get("data", []):
            if ss.get("attributes", {}).get("screenshotDisplayType") == display_type:
                existing_set_id = ss["id"]
                break

    # Create screenshot set if needed
    if not existing_set_id:
        status, data = asc(conn, jwt, "POST", "/v1/appScreenshotSets", {
            "data": {
                "type": "appScreenshotSets",
                "attributes": {"screenshotDisplayType": display_type},
                "relationships": {
                    "appStoreVersionLocalization": {
                        "data": {"type": "appStoreVersionLocalizations", "id": localization_id}
                    }
                }
            }
        })
        if status not in (200, 201):
            print(f"    ERROR creating screenshot set: {status} {json.dumps(data)[:300]}")
            return False
        existing_set_id = data["data"]["id"]
        print(f"    Created screenshot set: {existing_set_id}")
    else:
        print(f"    Using existing screenshot set: {existing_set_id}")

    # Check if screenshots already exist in the set AND have valid image assets.
    # Delete any broken/incomplete uploads first — they block version submission (409 STATE_ERROR.ENTITY_STATE_INVALID).
    status, data = asc(conn, jwt, "GET",
        f"/v1/appScreenshotSets/{existing_set_id}/appScreenshots?limit=10")
    if status == 200 and data.get("data"):
        valid_count = 0
        for ss in data["data"]:
            attrs = ss.get("attributes", {})
            if attrs.get("imageAsset"):
                valid_count += 1
            else:
                # Broken upload — no imageAsset means incomplete. Delete it.
                print(f"    Deleting broken screenshot: {ss['id']} (no imageAsset)")
                asc(conn, jwt, "DELETE", f"/v1/appScreenshots/{ss['id']}")
        if valid_count > 0:
            print(f"    Screenshots already exist ({valid_count} valid) — skipping upload")
            return True
        else:
            print(f"    Screenshot entries exist but no valid images — re-uploading")

    # Create appScreenshot — this returns uploadOperation with upload URL
    file_size = os.path.getsize(screenshot_path)
    status, data = asc(conn, jwt, "POST", "/v1/appScreenshots", {
        "data": {
            "type": "appScreenshots",
            "attributes": {
                "fileSize": file_size,
                "fileName": os.path.basename(screenshot_path)
            },
            "relationships": {
                "appScreenshotSet": {
                    "data": {"type": "appScreenshotSets", "id": existing_set_id}
                }
            }
        }
    })
    if status not in (200, 201):
        print(f"    ERROR creating screenshot: {status} {json.dumps(data)[:300]}")
        return False

    screenshot_id = data["data"]["id"]
    # ASC API returns uploadOperations directly in attributes
    upload_ops = data["data"].get("attributes", {}).get("uploadOperations", [])

    if not upload_ops:
        print(f"    ERROR: No upload operations returned. Response: {json.dumps(data)[:500]}")
        return False

    # Upload each chunk (usually single chunk for screenshots)
    with open(screenshot_path, "rb") as f:
        file_data = f.read()

    for op in upload_ops:
        upload_url = op.get("url", "")
        if not upload_url:
            print(f"    ERROR: No upload URL in operation: {json.dumps(op)[:200]}")
            return False

        req = urllib.request.Request(upload_url, data=file_data, method=op.get("method", "PUT"))
        req.add_header("Content-Type", "application/octet-stream")
        try:
            resp = urllib.request.urlopen(req)
            if resp.status not in (200, 204):
                print(f"    ERROR uploading image: HTTP {resp.status}")
                return False
        except Exception as e:
            print(f"    ERROR uploading image: {e}")
            return False

    # Commit the upload
    status, data = asc(conn, jwt, "PATCH", f"/v1/appScreenshots/{screenshot_id}", {
        "data": {
            "type": "appScreenshots",
            "id": screenshot_id,
            "attributes": {"uploaded": True}
        }
    })
    if status not in (200, 201):
        print(f"    ERROR committing screenshot: {status} {json.dumps(data)[:300]}")
        return False

    print(f"    Uploaded: {os.path.basename(screenshot_path)} ({file_size} bytes)")
    return True

key_id = os.environ.get("ASC_API_KEY_ID", "")
issuer_id = os.environ.get("ASC_ISSUER_ID", "")
key_content = os.environ.get("ASC_API_KEY_CONTENT", "")
app_version_raw = os.environ.get("APP_VERSION", "1.0.0")
app_version = app_version_raw.lstrip("v")
price_tier = int(os.environ.get("PRICE_TIER", "3"))

if not all([key_id, issuer_id, key_content]):
    print("ERROR: ASC_API_KEY_ID, ASC_ISSUER_ID, ASC_API_KEY_CONTENT must be set")
    sys.exit(1)

jwt = make_jwt(key_id, issuer_id, key_content)
ctx = ssl.create_default_context()
conn = http.client.HTTPSConnection("api.appstoreconnect.apple.com", context=ctx)

bundle_id = "cloud.dkroeker.GaussianSplattingViewer"

# 1. Get app
status, data = asc(conn, jwt, "GET", f"/v1/apps?filter[bundleId]={bundle_id}")
if status != 200 or not data.get("data"):
    print(f"ERROR: App not found (status={status}): {json.dumps(data)[:300]}")
    sys.exit(1)
app_id = data["data"][0]["id"]
print(f"App: {app_id} ({bundle_id})")

# 1b. App Privacy — NOT available via ASC API
# ponytail: The appDataUsages endpoint does not exist in the public ASC API.
# Dennis must set "Data Not Collected" manually in ASC web UI → App Privacy.
# This is the only remaining manual step.

# 2. Get latest VALID build
status, data = asc(conn, jwt, "GET", f"/v1/apps/{app_id}/builds?limit=20")
if status != 200:
    print(f"ERROR: Could not fetch builds (status={status}): {json.dumps(data)[:300]}")
    sys.exit(1)

valid_builds = []
for b in data.get("data", []):
    attrs = b["attributes"]
    if attrs.get("processingState") == "VALID" and not attrs.get("expired", False):
        valid_builds.append(b)

if not valid_builds:
    print("ERROR: No valid (processed, non-expired) builds found.")
    sys.exit(1)

valid_builds.sort(key=lambda b: int(b["attributes"].get("version", "0")), reverse=True)
build = valid_builds[0]
build_id = build["id"]
build_version = build["attributes"]["version"]
print(f"Latest valid build: {build_id} (version {build_version})")

# 3. Find or create App Store version
# First, look for ANY version in PREPARE_FOR_SUBMISSION state (handles version string mismatch)
status, data = asc(conn, jwt, "GET", f"/v1/apps/{app_id}/appStoreVersions")
app_store_version_id = None
if status == 200:
    for v in data.get("data", []):
        state = v["attributes"].get("appStoreState", "")
        vstr = v["attributes"].get("versionString", "")
        if state == "PREPARE_FOR_SUBMISSION":
            app_store_version_id = v["id"]
            app_version = vstr  # use the actual ASC version string
            print(f"Found existing version {vstr} in PREPARE_FOR_SUBMISSION: {app_store_version_id}")
            break
        elif state in ("WAITING_FOR_REVIEW", "IN_REVIEW", "PENDING_DEVELOPER_RELEASE", "READY_FOR_SALE"):
            print(f"Version {vstr} already in state {state} — nothing to do.")
            sys.exit(0)

if not app_store_version_id:
    print(f"Creating App Store version {app_version}...")
    status, data = asc(conn, jwt, "POST", "/v1/appStoreVersions", {
        "data": {
            "type": "appStoreVersions",
            "attributes": {
                "platform": "IOS",
                "versionString": app_version,
                "copyright": "2026 Dennis Kroeker",
                "releaseType": "MANUAL",
                "usesIdfa": False
            },
            "relationships": {
                "app": {"data": {"type": "apps", "id": app_id}}
            }
        }
    })
    if status == 201:
        app_store_version_id = data["data"]["id"]
        print(f"Created App Store version: {app_store_version_id}")
    else:
        print(f"ERROR creating version (status={status}): {json.dumps(data)[:500]}")
        sys.exit(1)

# 4. Upload metadata (create or update localizations)
print(f"\nUploading metadata for version {app_version}...")

status, loc_data = asc(conn, jwt, "GET", f"/v1/appStoreVersions/{app_store_version_id}/appStoreVersionLocalizations?limit=20")
existing_locales = {}
if status == 200:
    for loc in loc_data.get("data", []):
        existing_locales[loc["attributes"]["locale"]] = loc["id"]

locales_meta = {
    "de-DE": {
        "description": read_meta("de-DE", "description"),
        "keywords": read_meta("de-DE", "keywords"),
        "promotional_text": read_meta("de-DE", "promotional_text"),
    },
    "en-US": {
        "description": read_meta("en-US", "description"),
        "keywords": read_meta("en-US", "keywords"),
        "promotional_text": read_meta("en-US", "promotional_text"),
    }
}

for locale, meta in locales_meta.items():
    asc_attrs = {
        "description": meta["description"],
        "keywords": meta["keywords"],
        "promotionalText": meta["promotional_text"],
    }

    if locale in existing_locales:
        loc_id = existing_locales[locale]
        print(f"  Updating {locale} ({loc_id})...")
        status, data = asc(conn, jwt, "PATCH", f"/v1/appStoreVersionLocalizations/{loc_id}", {
            "data": {
                "type": "appStoreVersionLocalizations",
                "id": loc_id,
                "attributes": asc_attrs
            }
        })
        if status == 200:
            print(f"    OK — updated")
        else:
            print(f"    WARNING: status={status} {json.dumps(data)[:300]}")
    else:
        print(f"  Creating {locale}...")
        status, data = asc(conn, jwt, "POST", "/v1/appStoreVersionLocalizations", {
            "data": {
                "type": "appStoreVersionLocalizations",
                "attributes": {
                    "locale": locale,
                    **asc_attrs
                },
                "relationships": {
                    "appStoreVersion": {
                        "data": {"type": "appStoreVersions", "id": app_store_version_id}
                    }
                }
            }
        })
        if status == 201:
            loc_id = data["data"]["id"]
            existing_locales[locale] = loc_id
            print(f"    OK — created ({loc_id})")
        else:
            print(f"    WARNING: status={status} {json.dumps(data)[:300]}")

# 5. Upload screenshots
print(f"\nUploading screenshots...")
for locale in ["de-DE", "en-US"]:
    loc_id = existing_locales.get(locale)
    if not loc_id:
        print(f"  Skipping {locale} — no localization ID")
        continue
    print(f"  {locale}:")
    ss_dir = pathlib.Path(f"fastlane/metadata/{locale}/screenshots")
    if not ss_dir.exists():
        print(f"    No screenshots directory found")
        continue
    for ss_file in sorted(ss_dir.glob("*.png")):
        w, h = png_dimensions(str(ss_file))
        print(f"    {ss_file.name}: {w}x{h}")
        upload_screenshot(conn, jwt, loc_id, str(ss_file))

    # Upload iPad screenshots (required for universal apps)
    ipad_dir = pathlib.Path(f"fastlane/metadata/{locale}/screenshots_ipad")
    if ipad_dir.exists():
        for ss_file in sorted(ipad_dir.glob("*.png")):
            w, h = png_dimensions(str(ss_file))
            print(f"    {ss_file.name}: {w}x{h}")
            upload_screenshot(conn, jwt, loc_id, str(ss_file), display_type="APP_IPAD_PRO_3GEN_129")

# 6. Link build to App Store version
print(f"\nLinking build {build_id} to App Store version {app_store_version_id}...")
status, data = asc(conn, jwt, "PATCH", f"/v1/appStoreVersions/{app_store_version_id}/relationships/build", {
    "data": {"type": "builds", "id": build_id}
})
if status in (200, 204):
    print("Build linked successfully.")
else:
    print(f"WARNING: Link build returned {status}: {json.dumps(data)[:300]}")

# 7. Check for existing submission before creating a new one
print(f"\nChecking for existing submission on version {app_version}...")
status, data = asc(conn, jwt, "GET",
    f"/v1/appStoreVersions/{app_store_version_id}/appStoreVersionSubmission")

if status == 200 and data.get("data"):
    sub = data["data"]
    sub_state = sub.get("attributes", {}).get("state", "UNKNOWN")
    print(f"Submission already exists: {sub['id']} state={sub_state}")
    print(f"App Store version {app_version} (build {build_version}) is already submitted for review.")
    conn.close()
    sys.exit(0)
elif status == 404:
    print("No existing submission found — proceeding to create.")
elif status == 403:
    # ponytail: 403 on GET submission means the API key can't read submissions,
    # but the version state check above already told us if it's submitted
    print(f"Cannot query submission (403) — checking version state instead...")
    status, data = asc(conn, jwt, "GET", f"/v1/apps/{app_id}/appStoreVersions")
    if status == 200:
        for v in data.get("data", []):
            if v["id"] == app_store_version_id:
                state = v["attributes"].get("appStoreState", "")
                if state in ("WAITING_FOR_REVIEW", "IN_REVIEW", "PENDING_DEVELOPER_RELEASE", "READY_FOR_SALE"):
                    print(f"Version state is {state} — already submitted for review.")
                    conn.close()
                    sys.exit(0)
                break
else:
    print(f"Submission check returned {status} — proceeding to create anyway.")

# 8. Submit for review — reviewSubmissions API
# ponytail: appStoreVersionForReview is a to-one relationship that must be set
# via PATCH /v1/reviewSubmissions/{id}/relationships/appStoreVersionForReview,
# NOT in the POST body (Apple returns 409 ENTITY_ERROR.RELATIONSHIP.NOT_ALLOWED).
# DELETE on reviewSubmissions returns 403 for App Manager keys, so we reuse
# an existing READY_FOR_REVIEW submission instead of deleting + recreating.
print(f"\nSubmitting App Store version {app_version} for review (reviewSubmissions API)...")
time.sleep(5)

review_sub_id = None

# Step 0: Find an existing READY_FOR_REVIEW reviewSubmission to reuse
status, data = asc(conn, jwt, "GET", f"/v1/apps/{app_id}/reviewSubmissions?limit=20")
if status == 200:
    for rs in data.get("data", []):
        rs_state = rs.get("attributes", {}).get("state", "")
        if rs_state in ("WAITING_FOR_REVIEW", "IN_REVIEW", "PENDING_DEVELOPER_RELEASE", "READY_FOR_SALE"):
            print(f"Review submission {rs['id']} already in state {rs_state} — app is submitted!")
            conn.close()
            sys.exit(0)
        if rs_state == "READY_FOR_REVIEW":
            review_sub_id = rs["id"]
            print(f"Found existing READY_FOR_REVIEW submission: {review_sub_id}")
            break

# Step 1: Create review submission if we didn't find one to reuse
if not review_sub_id:
    print("No reusable submission found — creating new reviewSubmission (app relationship only)...")
    time.sleep(3)
    for attempt in range(3):
        status, data = asc(conn, jwt, "POST", "/v1/reviewSubmissions", {
            "data": {
                "type": "reviewSubmissions",
                "relationships": {
                    "app": {
                        "data": {"type": "apps", "id": app_id}
                    }
                }
            }
        })
        if status in (200, 201):
            review_sub_id = data["data"]["id"]
            print(f"Step 1 OK — review submission created: {review_sub_id}")
            break
        print(f"Step 1 attempt {attempt+1} failed (status={status}): {json.dumps(data)[:300]}")
        if attempt < 2:
            time.sleep(5)

    if not review_sub_id:
        print("ERROR creating review submission after 3 attempts")
        conn.close()
        sys.exit(1)

# Step 2: Link the App Store version via the dedicated relationship endpoint
print(f"Step 2 — Linking appStoreVersionForReview via relationship endpoint...")
status, data = asc(conn, jwt, "PATCH",
    f"/v1/reviewSubmissions/{review_sub_id}/relationships/appStoreVersionForReview", {
        "data": {"type": "appStoreVersions", "id": app_store_version_id}
    })
if status in (200, 204):
    print(f"  OK — appStoreVersionForReview linked to {app_store_version_id}")
else:
    print(f"  WARN — relationship PATCH returned {status}: {json.dumps(data)[:300]}")

time.sleep(3)

# Step 3: Set submitted=true (attributes only)
print(f"Step 3 — Setting submitted=true on submission {review_sub_id}...")
status, data = asc(conn, jwt, "PATCH", f"/v1/reviewSubmissions/{review_sub_id}", {
    "data": {
        "type": "reviewSubmissions",
        "id": review_sub_id,
        "attributes": {
            "submitted": True
        }
    }
})
if status in (200, 201):
    state = data.get("data", {}).get("attributes", {}).get("state", "")
    print(f"SUCCESS — Submission sent for review: {review_sub_id} state={state}")
    print(f"App Store version {app_version} (build {build_version}) submitted for review.")
    print("Review typically takes 24-48 hours.")
else:
    print(f"Step 3 ERROR: status={status} {json.dumps(data)[:500]}")
    # Check if version is already in review (submission may have worked despite error)
    status, data = asc(conn, jwt, "GET", f"/v1/apps/{app_id}/appStoreVersions")
    if status == 200:
        for v in data.get("data", []):
            if v["id"] == app_store_version_id:
                state = v["attributes"].get("appStoreState", "")
                if state in ("WAITING_FOR_REVIEW", "IN_REVIEW", "PENDING_DEVELOPER_RELEASE"):
                    print(f"Version state is {state} — submission was successful!")
                    break
    conn.close()
    sys.exit(1)

conn.close()
print("\nDone.")

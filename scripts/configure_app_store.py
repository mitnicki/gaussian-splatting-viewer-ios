#!/usr/bin/env python3
"""Configure ALL App Store Connect metadata required for review submission.

Sets via ASC API:
1. Primary category (Graphics & Design)
2. Copyright
3. Content rights declaration
4. Price tier (Tier 3 = 2.99 EUR)
5. Review contact information
6. App privacy (Data Not Collected)
7. Screenshots upload

Usage: Run in GitHub Actions with ASC secrets in env.
"""
import json, time, sys, os, base64, hashlib
import http.client, ssl, io

# --- JWT + HTTP helpers (reused pattern from create_asc_app.py) ---

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


class ASCClient:
    def __init__(self, key_id, issuer_id, key_content):
        self.jwt = make_jwt(key_id, issuer_id, key_content)
        self.ctx = ssl.create_default_context()
        self.conn = http.client.HTTPSConnection("api.appstoreconnect.apple.com", context=self.ctx)

    def request(self, method, path, body=None, extra_headers=None):
        headers = {"Authorization": f"Bearer {self.jwt}"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if extra_headers:
            headers.update(extra_headers)
        data = json.dumps(body) if body is not None else None
        self.conn.request(method, path, body=data, headers=headers)
        resp = self.conn.getresponse()
        raw = resp.read()
        # For file uploads, raw is binary
        result = {}
        if raw:
            ct = resp.getheader("Content-Type", "")
            if "json" in ct:
                result = json.loads(raw.decode())
            else:
                result = {"_raw": raw, "_status": resp.status, "_content_type": ct}
        return resp.status, result

    def upload_file(self, upload_url, file_data, content_type="image/png"):
        """Upload binary data to an Apple-provided upload URL."""
        self.conn.request("PUT", upload_url.replace("https://api.appstoreconnect.apple.com", ""),
                          body=file_data,
                          headers={"Content-Type": content_type})
        resp = self.conn.getresponse()
        resp.read()
        return resp.status

    def close(self):
        self.conn.close()


def main():
    key_id = os.environ.get("ASC_API_KEY_ID", "")
    issuer_id = os.environ.get("ASC_ISSUER_ID", "")
    key_content = os.environ.get("ASC_API_KEY_CONTENT", "")
    bundle_id = "cloud.dkroeker.GaussianSplattingViewer"

    if not all([key_id, issuer_id, key_content]):
        print("ERROR: Missing ASC env vars")
        sys.exit(1)

    client = ASCClient(key_id, issuer_id, key_content)

    # --- Get App ---
    status, data = client.request("GET", f"/v1/apps?filter[bundleId]={bundle_id}")
    if status != 200 or not data.get("data"):
        print(f"ERROR: App not found (status={status})")
        print(json.dumps(data, indent=2)[:500])
        sys.exit(1)

    app_id = data["data"][0]["id"]
    app_attrs = data["data"][0].get("attributes", {})
    print(f"App ID: {app_id}")
    print(f"  Name: {app_attrs.get('name', '?')}")
    print(f"  Bundle ID: {app_attrs.get('bundleId', '?')}")
    print(f"  Primary locale: {app_attrs.get('primaryLocale', '?')}")

    errors = []

    # --- 1. Set copyright + primary category on the app ---
    print("\n=== 1. Copyright + Primary Category ===")
    patch_body = {
        "data": {
            "type": "apps",
            "id": app_id,
            "attributes": {}
        }
    }
    attrs = patch_body["data"]["attributes"]

    # Copyright (required field — Dennis's error message says it's missing)
    attrs["copyright"] = "2026 Dennis Kroeker"

    status, data = client.request("PATCH", f"/v1/apps/{app_id}", patch_body)
    if status in (200, 201):
        print(f"  Copyright set to '{attrs['copyright']}' — OK")
    else:
        msg = f"  Copyright PATCH failed: {status} {json.dumps(data)[:300]}"
        print(msg)
        errors.append(msg)

    # Primary category is set on appInfo, not app — see step 3

    # --- 2. Set price tier ---
    print("\n=== 2. Price Tier (Tier 3 = 2.99 EUR) ===")

    # Check existing price schedule
    status, data = client.request("GET", f"/v1/apps/{app_id}/appPrices")
    existing_price_id = None
    if status == 200 and data.get("data"):
        for p in data["data"]:
            existing_price_id = p["id"]
            print(f"  Existing price schedule found: {existing_price_id}")

    # Get available price tiers
    status, data = client.request("GET", f"/v1/appPricePoints?limit=200")
    tier3_id = None
    if status == 200 and data.get("data"):
        for pt in data["data"]:
            attrs = pt.get("attributes", {})
            # Price tier 3 = $2.99 / 2.99 EUR
            if attrs.get("priceTier") == 3 or attrs.get("priceTier") == "3":
                tier3_id = pt["id"]
                break

    if not tier3_id:
        # Try the manual price approach — create a manual price
        # ASC API v2 uses appPriceSchedules
        print("  No price point found for tier 3, trying appPriceSchedules...")

    # Create/Update price schedule
    # The v2 API: POST /v2/appPriceSchedules with relationships to app and price point
    price_body = {
        "data": {
            "type": "appPriceSchedules",
            "attributes": {
                "manualPrices": [
                    {
                        "channel": "APP_STORE",
                        "tier": "3"
                    }
                ]
            },
            "relationships": {
                "app": {
                    "data": {"type": "apps", "id": app_id}
                },
                "baseTerritory": {
                    "data": {"type": "territories", "id": "DEU"}
                }
            }
        }
    }

    if existing_price_id:
        print(f"  Price schedule already exists ({existing_price_id}), checking...")
        status, data = client.request("GET", f"/v2/appPriceSchedules/{existing_price_id}")
        if status == 200:
            print(f"  Current schedule OK: {json.dumps(data.get('data', {}).get('attributes', {}))[:200]}")
        else:
            print(f"  GET schedule returned {status}")
    else:
        # Try v3 endpoint (latest)
        status, data = client.request("POST", "/v3/appPriceSchedules", price_body)
        if status in (200, 201):
            print(f"  Price schedule created — OK")
        elif status == 409:
            print(f"  Price schedule already exists (409)")
        elif status == 422:
            # Fall back to v1 appPrices
            print(f"  v3 failed ({status}), trying v1 appPrices...")
            v1_price_body = {
                "data": {
                    "type": "appPrices",
                    "attributes": {
                        "startDate": None
                    },
                    "relationships": {
                        "app": {
                            "data": {"type": "apps", "id": app_id}
                        },
                        "priceTier": {
                            "data": {"type": "appPriceTiers", "id": "3"}
                        }
                    }
                }
            }
            status, data = client.request("POST", "/v1/appPrices", v1_price_body)
            if status in (200, 201):
                print(f"  Price tier created via v1 — OK")
            elif status == 409:
                print(f"  Price tier already exists (409)")
            else:
                msg = f"  Price tier v1 failed: {status} {json.dumps(data)[:300]}"
                print(msg)
                errors.append("Price tier: " + msg)
        else:
            msg = f"  Price schedule failed: {status} {json.dumps(data)[:300]}"
            print(msg)
            errors.append("Price: " + msg)

    # --- 3. Set primary category + content rights via appInfo ---
    print("\n=== 3. Primary Category + Content Rights ===")
    status, data = client.request("GET", f"/v1/apps/{app_id}/appInfos")
    app_info_id = None
    if status == 200 and data.get("data"):
        for info in data["data"]:
            state = info["attributes"].get("appStoreState", "")
            if state == "PREPARE_FOR_SUBMISSION" or state == "READY_FOR_SALE" or not state:
                app_info_id = info["id"]
                break
        if not app_info_id:
            app_info_id = data["data"][0]["id"]
        print(f"  App Info ID: {app_info_id}")
    else:
        msg = f"  GET appInfos failed: {status} {json.dumps(data)[:300]}"
        print(msg)
        errors.append(msg)

    if app_info_id:
        # Set primary category and content rights
        info_patch = {
            "data": {
                "type": "appInfos",
                "id": app_info_id,
                "attributes": {
                    "primaryCategory": "GRAPHICS_AND_DESIGN",
                    "secondaryCategory": "UTILITIES"
                }
            }
        }
        status, data = client.request("PATCH", f"/v1/appInfos/{app_info_id}", info_patch)
        if status in (200, 201):
            print(f"  Primary category: GRAPHICS_AND_DESIGN — OK")
            print(f"  Secondary category: UTILITIES — OK")
        else:
            msg = f"  Category PATCH failed: {status} {json.dumps(data)[:300]}"
            print(msg)
            errors.append("Category: " + msg)

        # Content rights — this is a separate attribute on appInfo
        # "Does not contain third-party content" = false for usesThirdPartyContent
        # Actually content rights declaration: the app lets users open their own files
        # so it "Does not contain third-party content"
        info_patch2 = {
            "data": {
                "type": "appInfos",
                "id": app_info_id,
                "attributes": {
                    "contentRightsDeclaration": "DOES_NOT_CONTAIN_THIRD_PARTY_CONTENT"
                }
            }
        }
        status, data = client.request("PATCH", f"/v1/appInfos/{app_info_id}", info_patch2)
        if status in (200, 201):
            print(f"  Content rights: DOES_NOT_CONTAIN_THIRD_PARTY_CONTENT — OK")
        else:
            msg = f"  Content rights PATCH failed: {status} {json.dumps(data)[:300]}"
            print(msg)
            errors.append("Content rights: " + msg)

    # --- 4. Set review contact information ---
    print("\n=== 4. Review Contact Information ===")
    # appStoreReviewDetails — contact info for App Review
    status, data = client.request("GET", f"/v1/apps/{app_id}/appStoreReviewDetails")
    review_detail_id = None
    if status == 200 and data.get("data"):
        review_detail_id = data["data"][0]["id"]
        print(f"  Existing review details: {review_detail_id}")

    review_attrs = {
        "contactEmail": "dennis@kroeker.cloud",
        "contactFirstName": "Dennis",
        "contactLastName": "Kroeker",
        "contactPhone": "+49 5742 9290 30",
        "demoAccountRequired": False
    }

    if review_detail_id:
        review_body = {
            "data": {
                "type": "appStoreReviewDetails",
                "id": review_detail_id,
                "attributes": review_attrs
            }
        }
        status, data = client.request("PATCH", f"/v1/appStoreReviewDetails/{review_detail_id}", review_body)
        if status in (200, 201):
            print(f"  Review contact info updated — OK")
        else:
            msg = f"  Review contact PATCH failed: {status} {json.dumps(data)[:300]}"
            print(msg)
            errors.append("Review contact: " + msg)
    else:
        review_body = {
            "data": {
                "type": "appStoreReviewDetails",
                "attributes": review_attrs,
                "relationships": {
                    "app": {
                        "data": {"type": "apps", "id": app_id}
                    }
                }
            }
        }
        status, data = client.request("POST", "/v1/appStoreReviewDetails", review_body)
        if status in (200, 201):
            print(f"  Review contact info created — OK")
        else:
            msg = f"  Review contact POST failed: {status} {json.dumps(data)[:300]}"
            print(msg)
            errors.append("Review contact: " + msg)

    # --- 5. App Privacy — declare "Data Not Collected" ---
    print("\n=== 5. App Privacy (Data Not Collected) ===")

    # The App Privacy API uses appPrivacyTypes.
    # For "Data Not Collected", we need to post a privacy declaration.
    # POST /v1/appPrivacyDeclarations with the app relationship

    # First, get existing privacy declarations
    status, data = client.request("GET", f"/v1/apps/{app_id}/appPrivacyTypes")
    if status == 200:
        existing = data.get("data", [])
        print(f"  Existing privacy declarations: {len(existing)}")
        for p in existing:
            print(f"    {p.get('id')} — {p.get('attributes', {}).get('privacyType', '?')}")
    else:
        print(f"  GET privacy types: {status}")

    # Create "Data Not Collected" declaration
    # The API resource is appPrivacyTypes
    privacy_body = {
        "data": {
            "type": "appPrivacyTypes",
            "attributes": {
                "privacyType": "DATA_NOT_COLLECTED"
            },
            "relationships": {
                "app": {
                    "data": {"type": "apps", "id": app_id}
                }
            }
        }
    }

    status, data = client.request("POST", f"/v1/apps/{app_id}/appPrivacyTypes", privacy_body)
    if status in (200, 201):
        print(f"  Privacy: DATA_NOT_COLLECTED — OK")
    elif status == 409:
        print(f"  Privacy declaration already exists (409)")
    else:
        # Try alternative endpoint
        msg = f"  Privacy POST failed: {status} {json.dumps(data)[:300]}"
        print(msg)
        # Try PATCH on app-level privacy
        privacy_body2 = {
            "data": {
                "type": "appPrivacyTypes",
                "attributes": {
                    "privacyType": "DATA_NOT_COLLECTED"
                },
                "relationships": {
                    "app": {
                        "data": {"type": "apps", "id": app_id}
                    }
                }
            }
        }
        # Try posting directly to the collection
        status2, data2 = client.request("POST", "/v1/appPrivacyTypes", privacy_body2)
        if status2 in (200, 201):
            print(f"  Privacy: DATA_NOT_COLLECTED — OK (via /v1/appPrivacyTypes)")
        elif status2 == 409:
            print(f"  Privacy declaration already exists (409)")
        else:
            msg2 = f"  Privacy POST v2 failed: {status2} {json.dumps(data2)[:300]}"
            print(msg2)
            errors.append("App Privacy: " + msg + " / " + msg2)

    # --- 6. Upload screenshots ---
    print("\n=== 6. Screenshots Upload ===")

    # Get the App Store version (WAITING_FOR_REVIEW or PREPARE_FOR_SUBMISSION)
    status, data = client.request("GET", f"/v1/apps/{app_id}/appStoreVersions?filter[appStoreState]=PREPARE_FOR_SUBMISSION,READY_FOR_SALE")
    version_id = None
    if status == 200 and data.get("data"):
        for v in data["data"]:
            version_id = v["id"]
            version_string = v["attributes"].get("versionString", "?")
            print(f"  App Store Version: {version_string} (id={version_id})")
            break

    if not version_id:
        # Try without filter
        status, data = client.request("GET", f"/v1/apps/{app_id}/appStoreVersions")
        if status == 200 and data.get("data"):
            for v in data["data"]:
                version_id = v["id"]
                version_string = v["attributes"].get("versionString", "?")
                state = v["attributes"].get("appStoreState", "?")
                print(f"  App Store Version: {version_string} state={state} (id={version_id})")
                break

    if not version_id:
        msg = "  No App Store version found — cannot upload screenshots"
        print(msg)
        errors.append("Screenshots: " + msg)
    else:
        # Get existing appScreenshotSets for this version
        status, data = client.request("GET", f"/v1/appStoreVersions/{version_id}/appScreenshotSets?limit=20")
        existing_sets = {}
        if status == 200 and data.get("data"):
            for s in data["data"]:
                display_type = s["attributes"].get("screenshotDisplayType", "")
                existing_sets[display_type] = s["id"]
                print(f"  Existing screenshotSet: {display_type} ({s['id']})")

        # Upload screenshots for each device type
        screenshot_configs = [
            ("iphone67", "APP_IPHONE_67", [
                f"{os.path.dirname(os.path.dirname(os.path.abspath(__file__)))}/fastlane/screenshots/iphone67/screenshot_1.png",
                f"{os.path.dirname(os.path.dirname(os.path.abspath(__file__)))}/fastlane/screenshots/iphone67/screenshot_2.png",
                f"{os.path.dirname(os.path.dirname(os.path.abspath(__file__)))}/fastlane/screenshots/iphone67/screenshot_3.png",
            ]),
            ("iphone65", "APP_IPHONE_65", [
                f"{os.path.dirname(os.path.dirname(os.path.abspath(__file__)))}/fastlane/screenshots/iphone65/screenshot_1.png",
                f"{os.path.dirname(os.path.dirname(os.path.abspath(__file__)))}/fastlane/screenshots/iphone65/screenshot_2.png",
                f"{os.path.dirname(os.path.dirname(os.path.abspath(__file__)))}/fastlane/screenshots/iphone65/screenshot_3.png",
            ]),
        ]

        for device_name, display_type, screenshot_files in screenshot_configs:
            print(f"\n  --- Device: {device_name} ({display_type}) ---")

            # Check if screenshotSet already exists
            screenshot_set_id = existing_sets.get(display_type)

            if not screenshot_set_id:
                # Create screenshotSet
                set_body = {
                    "data": {
                        "type": "appScreenshotSets",
                        "relationships": {
                            "appStoreVersion": {
                                "data": {"type": "appStoreVersions", "id": version_id}
                            },
                            "screenshotDisplayType": {
                                "data": {"type": "screenshotDisplayTypes", "id": display_type}
                            }
                        }
                    }
                }
                status, data = client.request("POST", "/v1/appScreenshotSets", set_body)
                if status in (200, 201):
                    screenshot_set_id = data["data"]["id"]
                    print(f"    Created screenshotSet: {screenshot_set_id}")
                else:
                    msg = f"    Create screenshotSet failed: {status} {json.dumps(data)[:300]}"
                    print(msg)
                    errors.append(f"Screenshots {device_name}: " + msg)
                    continue
            else:
                print(f"    Using existing screenshotSet: {screenshot_set_id}")

            # Upload each screenshot
            for i, screenshot_path in enumerate(screenshot_files):
                if not os.path.exists(screenshot_path):
                    msg = f"    Screenshot file not found: {screenshot_path}"
                    print(msg)
                    errors.append(f"Screenshots {device_name} #{i+1}: " + msg)
                    continue

                file_size = os.path.getsize(screenshot_path)
                print(f"    Uploading screenshot {i+1} ({file_size} bytes)...")

                # Step 1: Create appScreenshot reservation
                reserve_body = {
                    "data": {
                        "type": "appScreenshots",
                        "attributes": {
                            "fileName": os.path.basename(screenshot_path),
                            "fileSize": file_size
                        },
                        "relationships": {
                            "appScreenshotSet": {
                                "data": {"type": "appScreenshotSets", "id": screenshot_set_id}
                            }
                        }
                    }
                }
                status, data = client.request("POST", "/v1/appScreenshots", reserve_body)
                if status not in (200, 201):
                    msg = f"      Reserve failed: {status} {json.dumps(data)[:300]}"
                    print(msg)
                    errors.append(f"Screenshots {device_name} #{i+1}: " + msg)
                    continue

                screenshot_id = data["data"]["id"]
                upload_ops = data["data"].get("attributes", {}).get("uploadOperations", [])
                print(f"      Reserved: {screenshot_id} ({len(upload_ops)} upload ops)")

                # Step 2: Upload file data to each upload operation URL
                with open(screenshot_path, "rb") as f:
                    file_data = f.read()

                for op in upload_ops:
                    op_url = op.get("url", "")
                    op_method = op.get("method", "PUT")
                    op_headers = {k: v for k, v in op.get("requestHeaders", {}).items()}
                    # Extract path from full URL
                    if "api.appstoreconnect.apple.com" in op_url:
                        upload_path = op_url.split("api.appstoreconnect.apple.com", 1)[1]
                    else:
                        print(f"      External upload URL (skipping): {op_url[:80]}")
                        continue

                    client.conn.request("PUT", upload_path, body=file_data,
                                        headers={"Content-Type": "application/octet-stream", **op_headers})
                    resp = client.conn.getresponse()
                    resp.read()
                    if resp.status in (200, 204):
                        print(f"      Chunk uploaded OK")
                    else:
                        print(f"      Upload chunk warning: {resp.status}")

                # Step 3: Commit the upload
                commit_body = {
                    "data": {
                        "type": "appScreenshots",
                        "id": screenshot_id,
                        "attributes": {
                            "uploaded": True
                        },
                        "relationships": {
                            "appScreenshotSet": {
                                "data": {"type": "appScreenshotSets", "id": screenshot_set_id}
                            }
                        }
                    }
                }
                status, data = client.request("PATCH", f"/v1/appScreenshots/{screenshot_id}", commit_body)
                if status in (200, 201):
                    print(f"      Screenshot {i+1} committed — OK")
                else:
                    msg = f"      Commit failed: {status} {json.dumps(data)[:300]}"
                    print(msg)
                    errors.append(f"Screenshots {device_name} #{i+1}: " + msg)

    # --- Summary ---
    print("\n" + "=" * 60)
    if errors:
        print(f"COMPLETED WITH {len(errors)} ERRORS:")
        for e in errors:
            print(f"  - {e}")
        client.close()
        sys.exit(1)
    else:
        print("ALL CONFIGURATIONS COMPLETED SUCCESSFULLY")
        client.close()
        sys.exit(0)


if __name__ == "__main__":
    main()

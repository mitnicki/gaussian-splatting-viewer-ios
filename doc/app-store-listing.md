# App Store Listing — Gaussian Splatting Viewer

## App Name
Gaussian Splatting Viewer

## Subtitle
Native Metal 3D Splat Renderer

## Description

Gaussian Splatting Viewer brings high-fidelity 3D scene rendering to iPhone and iPad. Built on Apple's Metal framework and the MetalSplatter library, it renders Gaussian Splat files (.ply, .splat, .spz) at full resolution and 60 FPS — far beyond what mobile browsers can achieve.

**Why native?**

iOS Safari caps WebGL memory at ~384 MB. Large splats (1 GB+) are physically unrenderable in-browser. Native Metal on modern iPhones accesses 5–6 GB of GPU memory, so even heavily compressed .spz files (113 MB, 9.4× compression with full SH3 fidelity) render smoothly.

**Features:**

• Native Metal renderer — full Gaussian Splatting with spherical harmonics
• Open local .ply / .splat / .spz files from the iOS Files app
• Browse and download splats from your Nextcloud via WebDAV
• On-device LRU cache (2 GB) for Nextcloud files — view offline after first download
• Auto-rotate, gesture controls (1-finger rotate, 2-finger pan, pinch zoom)
• Secure credential storage via iOS Keychain
• Dark, technical UI following kroeker.cloud corporate design
• No tracking, no analytics, no data collection — fully private

**File Formats:**

• .ply — Standard Gaussian Splatting format
• .splat — Pre-processed splat data
• .spz — Compressed splat format (recommended for mobile)

**Requirements:**

• iOS 18.0 or later
• iPhone or iPad with A14 chip or newer (for acceptable performance)
• Nextcloud server (optional, for cloud browsing)

## Keywords
gaussian splatting, 3d viewer, metal renderer, nextcloud, splat, ply, spz, 3d scanning, photogrammetry, point cloud

## Categories
Graphics & Design / Utilities

## Support URL
https://github.com/HenkDz/paperclip

## Privacy Policy URL
https://kroeker.cloud/privacy

## Privacy: Data Collection
This app does not collect, transmit, or process any user data.
All files are processed locally on-device.
Nextcloud credentials are stored in the iOS Keychain and transmitted only to the user's own server.

## What's New (Version 0.5.1)

CI Design Integration:
- App icon with kroeker.cloud accent gradient and "kc" monogram
- Inter typography throughout the app
- JetBrains Mono for technical text (URLs, filenames, status)
- CI color tokens for all UI elements
- Launch screen with brand background color
- Reusable CI button styles and card components

## Promotional Text
Render massive 3D Gaussian Splats on iPhone — full fidelity, 60 FPS, no browser limits.

## App Store Review Notes
- This app renders 3D Gaussian Splatting files using Metal.
- No account required for local file viewing.
- Nextcloud integration requires the user's own server URL and credentials.
- No telemetry or data collection whatsoever.

# App Store Listing — Gaussian Splatting Viewer v1.0

Prepared: 2026-07-18
Price: 2,99 EUR (one-time)
Bundle ID: cloud.dkroeker.GaussianSplattingViewer

---

## App Name (30 chars)
Gaussian Splatting Viewer

## Subtitle (30 chars)
Render large .splat files on iOS

## Promotional Text (170 chars)
The only iOS app that reliably renders large Gaussian Splatting files (.ply/.splat/.spz) in full fidelity using Metal — where Safari and every other app fails.

---

## Description (German — primary market)

Gaussian Splatting Viewer ist die erste native iOS-App, die große Gaussian-Splatting-Dateien zuverlässig und in voller Auflösung auf dem iPhone rendert.

### Warum diese App?

iOS Safari hat ein hartes WebGL-Speicherlimit von ~384 MB pro Tab. Große Splat-Dateien (500 MB bis 1 GB+) sind im Browser schlichtweg nicht darstellbar — die Seite stürzt ab oder lädt endlos. Gaussian Splatting Viewer nutzt Apples Metal-Framework direkt und hat Zugriff auf den vollen Gerätespeicher (5–6 GB auf iPhone 15/16 Pro). Das bedeutet: große Splat-Files laden in Sekunden, in voller Qualität, bei 60 FPS.

### Hauptmerkmale

- **Große Dateien zuverlässig rendern** — Der USP. .ply/.splat/.spz Dateien bis 1 GB+ laden und flüssig anzeigen. Keine andere iOS-App kann das.
- **Metal-Beschleunigung** — Native Metal Compute-Shader für maximale Performance. Kein WebGL, keine Browser-Limits.
- **Universelle Formatunterstützung** — .ply, .splat und .spz (Niantic's komprimiertes Format, 9× Kompression bei voller Qualität).
- **Dateien von überall öffnen** — iOS Files-App-Integration: iCloud Drive, lokaler Speicher, AirDrop, Nextcloud, Dropbox, Google Drive oder jeder andere Files-Provider.
- **Demo-Szene inklusive** — Testen Sie die App sofort mit der mitgelieferten Demo-Szene.
- **Intuitive Gesten** — Drag zum Drehen, Pinch zum Zoomen, Reset-Ansicht.
- **Screenshot & Teilen** — Ansicht erfassen und direkt teilen.
- "Open In" aus anderen Apps — Dateien direkt aus Mail, AirDrop oder der Files-App öffnen.

### Anwendungsbereiche

- **3D-Scanning & Photogrammetrie** — Scans von Polycam, Luma, Scaniverse oder eigenen Gaussian-Splatting-Pipelines auf dem iPhone ansehen.
- **Forschung & Entwicklung** — Gaussian-Splatting-Modelle unterwegs evaluieren.
- **Architektur & Immobilien** — Große 3D-Scans von Räumen und Gebäuden vor Ort präsentieren.
- **Kultur- & Denkmalschutz** — High-Fidelity-Scans von Denkmalen und Artefakten anzeigen.

### Technische Details

- Renderer: MetalSplatter (Metal Compute Shaders)
- Formate: .ply, .splat, .spz
- Kompatibilität: iPhone und iPad mit iOS 18.0+
- Keine Server-Kosten, keine Cloud-Abhängigkeit — alle Dateien bleiben lokal auf dem Gerät.
- Keine Werbung, kein Tracking, keine versteckten Kosten.

### Lizenz

MIT-lizenziert. Basiert auf MetalSplatter (MIT) und Niantic spz (MIT).

---

## Description (English)

Gaussian Splatting Viewer is the first native iOS app that reliably renders large Gaussian Splatting files in full resolution on iPhone.

### Why this app?

iOS Safari caps a single WebGL tab at ~384 MB. Large splat files (500 MB to 1 GB+) are physically unrenderable in-browser — the page crashes or loads forever. Gaussian Splatting Viewer uses Apple's Metal framework directly, with access to the full device memory (5–6 GB on iPhone 15/16 Pro). Large splat files load in seconds, at full fidelity, at 60 FPS.

### Key Features

- **Reliably render large files** — The USP. Load and display .ply/.splat/.spz files up to 1 GB+. No other iOS app can do this.
- **Metal acceleration** — Native Metal compute shaders for maximum performance. No WebGL, no browser limits.
- **Universal format support** — .ply, .splat, and .spz (Niantic's compressed format, 9× compression at full quality).
- **Open from anywhere** — iOS Files app integration: iCloud Drive, local storage, AirDrop, Nextcloud, Dropbox, Google Drive, or any Files provider.
- **Demo scene included** — Try the app immediately with a bundled sample scene.
- **Intuitive gestures** — Drag to rotate, pinch to zoom, reset view.
- **Screenshot & share** — Capture the current view and share it instantly.
- "Open In" from other apps — Open files directly from Mail, AirDrop, or the Files app.

### Use Cases

- **3D Scanning & Photogrammetry** — View scans from Polycam, Luma, Scaniverse, or your own Gaussian Splatting pipelines on iPhone.
- **Research & Development** — Evaluate Gaussian Splatting models on the go.
- **Architecture & Real Estate** — Present large 3D scans of rooms and buildings on-site.
- **Cultural Heritage** — Display high-fidelity scans of monuments and artifacts.

### Technical Details

- Renderer: MetalSplatter (Metal compute shaders)
- Formats: .ply, .splat, .spz
- Compatibility: iPhone and iPad with iOS 18.0+
- No server costs, no cloud dependency — all files stay local on device.
- No ads, no tracking, no hidden costs.

### License

MIT licensed. Built on MetalSplatter (MIT) and Niantic spz (MIT).

---

## Keywords (100 chars max, comma-separated)

gaussian splatting,3d viewer,splat,ply,spz,metal,3d scan,photogrammetry,point cloud,3d render

## Categories

- Primary: Graphics & Design
- Secondary: Utilities

## Privacy Policy URL

https://dkroeker.de/privacy (TBD — Dennis to confirm hosting)

## Support URL

https://github.com/mitnicki/gaussian-splatting-viewer-ios

## What's New in v1.0.0 (Release Notes)

Erstveröffentlichung — Gaussian Splatting Viewer v1.0.0.

- Native Metal-Rendering für .ply/.splat/.spz Dateien
- Zuverlässiges Laden großer Splat-Files (1 GB+)
- Demo-Szene zum sofortigen Testen
- Intuitive Gesten: Drehen, Zoomen, Reset
- Screenshot & Teilen
- iOS Files-Integration (iCloud, AirDrop, Nextcloud, uvm.)

Initial release — Gaussian Splatting Viewer v1.0.0.

- Native Metal rendering for .ply/.splat/.spz files
- Reliable loading of large splat files (1 GB+)
- Bundled demo scene for instant testing
- Intuitive gestures: rotate, zoom, reset
- Screenshot & share
- iOS Files integration (iCloud, AirDrop, Nextcloud, and more)

---

## Screenshots needed (for App Store submission)

1. Home screen with demo button + open file button
2. Demo scene rendering (full screen, landscape)
3. Large splat file open and rendering (showing a complex scene)
4. Gesture controls overlay visible (rotate/zoom/screenshot icons)
5. Screenshot share sheet open
6. Files picker showing .splat file selection

Requirements: 6.7" (iPhone 15 Pro Max) and 6.5" (iPhone 11 Pro Max) sizes.

## v1.0 Feature Scope

**Included in v1.0:**
- Open .ply/.splat/.spz files via Files picker or "Open In"
- Try Demo (bundled sample scene)
- Metal rendering (large files — the USP)
- Rotate (drag), Zoom (pinch + buttons), Reset view
- Screenshot/share
- Auto-rotate toggle
- Settings/About

**Deferred to v1.1+:**
- Walkthrough (flythrough camera path)
- Virtual joystick (look control)
- Walkthrough speed slider

## Pricing

- 2,99 EUR one-time (no subscription, no IAP)
- App Store category: Graphics & Design
- Price tier: Tier 3 (2,99 EUR / $2,99 / £2,49)

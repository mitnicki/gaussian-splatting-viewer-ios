# Gaussian Splatting Viewer (iOS) — v0.13.0

Native iOS app that renders Gaussian Splatting scenes (`.ply` / `.splat` / `.spz`)
using [MetalSplatter](https://github.com/scier/MetalSplatter) and Apple's Metal
framework. Built for the kroeker homelab to view `rc390_alte_muehle` and other
splats on iPhone/iPad where iOS Safari's 384 MB WebGL cap makes the web viewer
unusable (see DKR-97 / DKR-179).

> **Status:** v0.13.0 (build 139). TestFlight distribution is live — builds
> upload, process, and distribute to Internal testers automatically on every
> push to `master`. Beta app review submitted (waiting for Apple approval).
>
> **v0.13.0:** Feature hints on home screen, changelog fix.
> **v0.12.0:** Flythrough walkthrough (3D camera path), virtual joystick for
> look control, walkthrough pause/resume.

---

## Why native?

iOS Safari caps a single WebGL tab at ~384 MB. The source `rc340_alte_muehle.ply`
is 1.1 GB (4.48 M splats, SH3) — physically unrenderable in-browser. Native Metal
on an iPhone 15/16 Pro has access to ~5–6 GB, so the 113 MB `.spz` (9.4×
compression, all splats + SH3 preserved) loads at full fidelity, 60 FPS.

---

## Architecture

```
iOS Files App (iCloud / local / AirDrop / any Files provider)
                          ↓
                    iOS App
                  ├─ SwiftUI UI
                  │   ├─ ContentView (native document picker, Open In)
                  │   └─ SettingsView (About + supported sources)
                  ├─ SplatIO: AutodetectSceneReader (.ply/.splat/.spz)
                  └─ MetalSplatter: SplatRenderer (Metal compute shaders)
```

The app depends on **MetalSplatter** and **SplatIO** via Swift Package Manager
(resolved from the upstream GitHub repo). The rendering path is adapted from
MetalSplatter's MIT-licensed SampleApp, simplified to splat-file loading.

v0.11.0 removed the dedicated Nextcloud WebDAV browser in favor of the native
iOS Files picker. Users open `.ply`/`.splat`/`.spz` files from any Files provider
(iCloud, local storage, Nextcloud app, AirDrop, etc.) via the system document
picker or "Open In" menu. The app registers UTExportedTypeDeclarations and
CFBundleDocumentTypes for `.ply`, `.splat`, and `.spz`.

## Project structure

| Path | Purpose |
|---|---|
| `project.yml` | XcodeGen spec → generates `GaussianSplattingViewer.xcodeproj` |
| `App/` | SwiftUI app entry, ContentView (file picker), Constants, CI design system |
| `Scene/` | MetalKit SwiftUI bridge + MTKViewDelegate renderer |
| `Model/` | ModelRenderer protocol, SplatSource, SplatRenderer conformance, cache |
| `Util/` | Matrix math (vendored from Apple sample code) |
| `fastlane/` | Fastlane lanes for TestFlight upload + beta review submission |
| `.github/workflows/` | CI: iOS Simulator build + TestFlight upload + beta review |

## Rendering credits

`MetalKitSceneView`, `MetalKitSceneRenderer`, `MatrixMathUtil`, and the
`SplatRenderer` conformance are adapted from the [MetalSplatter
SampleApp](https://github.com/scier/MetalSplatter/tree/main/SampleApp) (MIT
License). See `LICENSE-MetalSplatter.txt`.

---

## Hybrid development workflow (no Mac required)

This repo is designed for the **Linux-author → macOS-CI → TestFlight** loop:

1. **Code is authored on Linux** (agent or human) and pushed to GitHub.
2. **GitHub Actions** runs on a macOS runner: installs XcodeGen, generates
   the `.xcodeproj`, resolves the MetalSplatter SPM dependency, builds for the
   iOS Simulator (no signing), then archives and uploads to TestFlight.
3. TestFlight build processing + distribution to Internal testers is automatic.
   Beta review submission runs as a separate workflow after upload.

> macOS runner minutes are **free for public repos**. Keep this repo public (the
> app is MIT-licensed, matching MetalSplatter) to avoid CI costs.

---

## CI status

GitHub Actions builds the app on every push to `master`. The latest run
(v0.11.0, build 15) completed successfully:

- **Runner:** macOS (Xcode 26.5)
- **Build time:** ~6m21s
- **Status:** GREEN — build + TestFlight upload + beta review submission all passed
- **URL:** https://github.com/mitnicki/gaussian-splatting-viewer-ios/actions

---

## Milestones

| Phase | Status | Scope |
|---|---|---|
| **M1: PoC** | ✅ done | MetalSplatter + `.spz` load + render, CI build |
| **M2: WebDAV** | ✅ done, then removed | Nextcloud file browser — replaced by native Files picker in v0.11.0 |
| **M2.3–M2.10f: Polish** | ✅ done | Compile fixes, loading/error UX, Swift 6 concurrency, CI design integration |
| **M3: TestFlight** | ✅ live | Build 15 uploaded, processed, distributed to Internal testers. Beta review submitted. |
| **M4: App Store** | ⏳ next | App Store listing draft ready. Awaiting beta review approval + TestFlight feedback. |

### Gesture controls

- **Drag** to rotate the scene
- **Pinch** to zoom in/out
- **Walkthrough** (figure.walk icon): auto camera flythrough path through 3D space
- **Virtual joystick** (bottom-left): look around — yaw/pitch
- **Zoom buttons** (bottom-right): +/- precise zoom
- **Screenshot** (camera icon): capture and share the current view
- **Settings** (slider icon): adjust walkthrough speed
- Auto-rotation toggle (play/pause icon)
- Reset view (counterclockwise arrow icon)

All controls appear as a floating overlay after opening a `.splat` / `.ply` / `.spz` file.

## License

MIT — see `LICENSE`. MetalSplatter and Niantic `spz` are also MIT.

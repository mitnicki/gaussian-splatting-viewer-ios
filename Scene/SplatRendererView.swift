// SplatRendererView.swift
// SwiftUI wrapper that adds loading / error states around MetalKitSceneView,
// plus a floating control overlay (auto-rotate toggle, reset, gesture hints).

#if os(iOS)

import SwiftUI
import CoreImage
import simd

struct SplatRendererView: View {
    let url: URL?

    @State private var loadState: LoadState = .loading
    @State private var renderer: MetalKitSceneRenderer?
    @State private var autoRotate: Bool = false
    @State private var walkthroughActive: Bool = false
    @State private var walkthroughPaused: Bool = false
    @State private var showControls: Bool = true
    @State private var showSettingsPanel: Bool = false
    @State private var walkthroughSpeed: Float = 1.0
    @State private var screenshotImage: UIImage?
    @State private var showShareSheet: Bool = false

    private enum LoadState: Equatable {
        case loading
        case ready
        case error(String)
    }

    var body: some View {
        ZStack {
            MetalKitSceneView(
                url: url,
                onLoadComplete: { error in
                    if let error {
                        loadState = .error(error.localizedDescription)
                    } else {
                        loadState = .ready
                    }
                },
                onRendererReady: { r in
                    renderer = r
                    autoRotate = r.autoRotate
                }
            )
            .ignoresSafeArea()

            if loadState == .ready, let renderer {
                controlOverlay(renderer)
                    .transition(.opacity)
            }

            switch loadState {
            case .loading:
                LoadingOverlay()
                    .transition(.opacity)
            case .error(let message):
                ErrorOverlay(message: message)
                    .transition(.opacity)
            case .ready:
                Color.clear
            }
        }
        .tint(.ciAccent)
        .animation(.easeInOut(duration: 0.25), value: loadState)
        .sheet(isPresented: $showShareSheet) {
            if let image = screenshotImage {
                ShareSheet(items: [image])
            }
        }
        .task(id: url) {
            loadState = .loading

            guard let url else {
                loadState = .error("No file URL")
                return
            }

            if !FileManager.default.fileExists(atPath: url.path) {
                loadState = .error("File not found: \(url.lastPathComponent)")
                return
            }

            guard let attrs = try? FileManager.default.attributesOfItem(atPath: url.path),
                  let size = attrs[.size] as? Int64, size > 0 else {
                loadState = .error("File is empty or unreadable")
                return
            }
        }
    }

    // MARK: - Control overlay

    @ViewBuilder
    private func controlOverlay(_ renderer: MetalKitSceneRenderer) -> some View {
        VStack {
            // Top bar: action buttons
            HStack(spacing: 16) {
                Button {
                    autoRotate.toggle()
                    if walkthroughActive { stopWalkthrough(renderer) }
                    renderer.autoRotate = autoRotate
                } label: {
                    Image(systemName: autoRotate ? "pause.circle.fill" : "play.circle.fill")
                        .font(.title2)
                        .foregroundStyle(.white)
                        .shadow(radius: 2)
                }

                if FeatureFlags.walkthroughEnabled {
                    Button {
                        if walkthroughActive {
                            if walkthroughPaused {
                                renderer.resumeWalkthrough()
                                walkthroughPaused = false
                            } else {
                                renderer.pauseWalkthrough()
                                walkthroughPaused = true
                            }
                        } else {
                            startWalkthrough(renderer)
                        }
                    } label: {
                        VStack(spacing: 2) {
                            Image(systemName: walkthroughActive
                                  ? (walkthroughPaused ? "play.circle.fill" : "pause.circle.fill")
                                  : "figure.walk")
                                .font(.title2)
                            Text(walkthroughActive ? (walkthroughPaused ? "Resume" : "Pause") : "Walk")
                                .font(.system(size: 9, weight: .medium))
                        }
                        .foregroundStyle(walkthroughActive ? .ciAccent : .white)
                        .shadow(radius: 2)
                    }
                }

                Button {
                    renderer.resetView()
                    autoRotate = false
                    walkthroughActive = false
                    walkthroughPaused = false
                    renderer.autoRotate = false
                } label: {
                    Image(systemName: "arrow.counterclockwise.circle.fill")
                        .font(.title2)
                        .foregroundStyle(.white)
                        .shadow(radius: 2)
                }

                Button {
                    screenshotImage = renderer.captureSnapshot()
                    if screenshotImage != nil {
                        showShareSheet = true
                    }
                } label: {
                    Image(systemName: "camera.circle.fill")
                        .font(.title2)
                        .foregroundStyle(.white)
                        .shadow(radius: 2)
                }

                Spacer()

                Button {
                    withAnimation(.easeInOut(duration: 0.2)) {
                        showControls.toggle()
                        showSettingsPanel = false
                    }
                } label: {
                    Image(systemName: showControls ? "chevron.up.circle.fill" : "chevron.down.circle.fill")
                        .font(.title2)
                        .foregroundStyle(.white)
                        .shadow(radius: 2)
                }
            }
            .padding(.horizontal, 16)
            .padding(.top, 8)

            // Settings panel (walkthrough speed, etc.) — hidden when walkthrough disabled
            if FeatureFlags.walkthroughEnabled && showControls && showSettingsPanel {
                VStack(spacing: 12) {
                    HStack {
                        Image(systemName: "speedometer")
                            .foregroundStyle(.ciAccentBright)
                        Text("Walkthrough Speed")
                            .font(.ciCaption)
                            .foregroundStyle(.ciTextSecondary)
                        Spacer()
                        Text(String(format: "%.1fx", walkthroughSpeed))
                            .font(.ciMono)
                            .foregroundStyle(.ciAccentBright)
                    }
                    Slider(value: Binding(
                        get: { Double(walkthroughSpeed) },
                        set: { walkthroughSpeed = Float($0); renderer.setWalkthroughSpeed(walkthroughSpeed) }
                    ), in: 0.2...3.0, step: 0.1)
                    .tint(.ciAccent)
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 12)
                .background(.ultraThinMaterial.opacity(0.7), in: RoundedRectangle(cornerRadius: 12))
                .padding(.horizontal, 12)
                .transition(.opacity.combined(with: .move(edge: .top)))
            }

            // Gesture hints
            if showControls && !showSettingsPanel {
                HStack(spacing: 10) {
                    Label("Drag: rotate", systemImage: "hand.draw")
                    Label("Pinch: zoom", systemImage: "plus.magnifyingglass")
                    if FeatureFlags.walkthroughEnabled {
                        Button {
                            withAnimation(.easeInOut(duration: 0.2)) {
                                showSettingsPanel.toggle()
                            }
                        } label: {
                            Image(systemName: "slider.horizontal.3")
                                .font(.caption)
                        }
                    }
                }
                .font(.caption2)
                .foregroundStyle(.white.opacity(0.8))
                .shadow(radius: 1)
                .padding(.horizontal, 12)
                .padding(.vertical, 6)
                .background(.ultraThinMaterial.opacity(0.6), in: Capsule())
                .transition(.opacity)
            }

            Spacer()

            // Bottom controls: virtual joystick (left) + zoom buttons (right)
            HStack(alignment: .bottom) {
                // Virtual look joystick — bottom left (deferred to v1.1+)
                if FeatureFlags.joystickEnabled {
                    VirtualJoystick { input in
                        renderer.handleJoystick(input)
                    }
                    .padding(.leading, 16)
                    .padding(.bottom, 20)
                }

                Spacer()

                // Zoom buttons — bottom right
                VStack(spacing: 12) {
                    Button {
                        renderer.zoomIn()
                    } label: {
                        Image(systemName: "plus.circle.fill")
                            .font(.title2)
                            .foregroundStyle(.white)
                            .shadow(radius: 2)
                    }
                    Button {
                        renderer.zoomOut()
                    } label: {
                        Image(systemName: "minus.circle.fill")
                            .font(.title2)
                            .foregroundStyle(.white)
                            .shadow(radius: 2)
                    }
                }
                .padding(.trailing, 16)
                .padding(.bottom, 40)
            }
        }
    }

    private func startWalkthrough(_ renderer: MetalKitSceneRenderer) {
        walkthroughActive = true
        autoRotate = false
        renderer.autoRotate = false
        renderer.setWalkthroughSpeed(walkthroughSpeed)
        renderer.startWalkthrough()
    }

    private func stopWalkthrough(_ renderer: MetalKitSceneRenderer) {
        walkthroughActive = false
        walkthroughPaused = false
        renderer.stopWalkthrough()
    }
}

// MARK: - Virtual Joystick

/// A simple virtual joystick for look control (yaw/pitch).
/// Drag inside the circle to rotate the camera; release to center.
private struct VirtualJoystick: View {
    let onChange: (SIMD2<Float>) -> Void

    @State private var dragOffset: CGSize = .zero
    private let radius: CGFloat = 45

    var body: some View {
        ZStack {
            Circle()
                .fill(.ultraThinMaterial.opacity(0.4))
                .overlay(Circle().stroke(.white.opacity(0.2), lineWidth: 1))

            Circle()
                .fill(Color.ciAccent.opacity(0.6))
                .frame(width: 28, height: 28)
                .overlay(Circle().stroke(.white.opacity(0.3), lineWidth: 1))
                .offset(dragOffset)
        }
        .frame(width: 90, height: 90)
        .contentShape(Circle())
        .gesture(
            DragGesture(minimumDistance: 0)
                .onChanged { value in
                    let dx = value.translation.width
                    let dy = value.translation.height
                    let dist = sqrt(dx * dx + dy * dy)
                    let clamped = min(dist, radius)
                    let angle = atan2(dy, dx)
                    let cx = cos(angle) * clamped
                    let cy = sin(angle) * clamped
                    dragOffset = CGSize(width: cx, height: cy)

                    let nx = Float(cx / radius)
                    let ny = Float(cy / radius)
                    onChange(SIMD2<Float>(nx, -ny))
                }
                .onEnded { _ in
                    withAnimation(.easeOut(duration: 0.15)) {
                        dragOffset = .zero
                    }
                    onChange(.zero)
                }
        )
    }
}

// MARK: - Loading Overlay

private struct LoadingOverlay: View {
    @State private var animatePulse = false

    var body: some View {
        VStack(spacing: 16) {
            Image(systemName: "cube.transparent")
                .font(.system(size: 48))
                .foregroundStyle(.ciAccent)
                .symbolEffect(.pulse, options: .repeating)
                .scaleEffect(animatePulse ? 1.1 : 1.0)

            Text("Loading splat…")
                .font(.ciH4)
                .foregroundStyle(.ciTextSecondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(.ciBgBase.opacity(0.9))
        .onAppear {
            withAnimation(.easeInOut(duration: 0.8).repeatForever(autoreverses: true)) {
                animatePulse = true
            }
        }
    }
}

// MARK: - Share Sheet

private struct ShareSheet: UIViewControllerRepresentable {
    let items: [Any]

    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: items, applicationActivities: nil)
    }

    func updateUIViewController(_ uiViewController: UIActivityViewController, context: Context) {}
}

// MARK: - Error Overlay

private struct ErrorOverlay: View {
    let message: String

    var body: some View {
        VStack(spacing: 16) {
            Image(systemName: "exclamationmark.triangle")
                .font(.system(size: 48))
                .foregroundStyle(.ciStatusAmber)

            Text("Failed to Load")
                .font(.ciH4)
                .foregroundStyle(.ciTextPrimary)

            Text(message)
                .font(.ciCaption)
                .foregroundStyle(.ciTextSecondary)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 32)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(.ciBgBase.opacity(0.95))
    }
}

#endif // os(iOS)

// MetalKitSceneView.swift
// SwiftUI ↔ UIKit bridge for MTKView. iOS-only.
// Adapted from MetalSplatter SampleApp's MetalKitSceneView (MIT).

#if os(iOS)

import SwiftUI
import MetalKit

struct MetalKitSceneView: UIViewRepresentable {
    let url: URL?
    /// Called when the async Metal load finishes. `nil` = success,
    /// non-nil = the error that was thrown. Called on MainActor.
    var onLoadComplete: (@MainActor (Error?) -> Void)?

    final class Coordinator {
        var renderer: MetalKitSceneRenderer?
    }

    func makeCoordinator() -> Coordinator {
        Coordinator()
    }

    func makeUIView(context: UIViewRepresentableContext<MetalKitSceneView>) -> MTKView {
        let metalKitView = MTKView()

        if let metalDevice = MTLCreateSystemDefaultDevice() {
            metalKitView.device = metalDevice
        }

        if let renderer = MetalKitSceneRenderer(metalKitView) {
            context.coordinator.renderer = renderer
            metalKitView.delegate = renderer

            // Add gesture recognizers
            addGestures(to: metalKitView, renderer: renderer)

            Task { @MainActor in
                do {
                    try await renderer.load(url)
                    onLoadComplete?(nil)
                } catch {
                    onLoadComplete?(error)
                }
            }
        } else {
            // Metal device unavailable — report immediately so the UI
            // shows an error instead of spinning the loading overlay forever.
            onLoadComplete?(NSError(
                domain: "MetalKitSceneView",
                code: 1,
                userInfo: [NSLocalizedDescriptionKey: "Metal is not available on this device"]
            ))
        }

        return metalKitView
    }

    func updateUIView(_ view: MTKView, context: UIViewRepresentableContext<MetalKitSceneView>) {
        // Only reload if the URL actually changed. SwiftUI calls updateUIView
        // on every state change in the parent view — without this guard we'd
        // tear down and reload the splat on every redraw.
        guard let renderer = context.coordinator.renderer else { return }
        guard renderer.loadedURL != url else { return }
        Task { @MainActor in
            do {
                try await renderer.load(url)
                onLoadComplete?(nil)
            } catch {
                onLoadComplete?(error)
            }
        }
    }

    // MARK: - Gesture setup

    private func addGestures(to view: MTKView, renderer: MetalKitSceneRenderer) {
        // Pinch to zoom
        let pinch = UIPinchGestureRecognizer { gesture in
            if gesture.state == .changed {
                renderer.handlePinch(scale: gesture.scale)
                gesture.scale = 1.0  // reset for incremental updates
            }
        }
        view.addGestureRecognizer(pinch)

        // One-finger pan to orbit/rotate the splat.
        // Two-finger pan moves the camera (pan offset) — see below.
        let orbit = UIPanGestureRecognizer { gesture in
            if gesture.state == .changed {
                let translation = gesture.translation(in: view)
                let sensitivity: Float = 0.01
                // Horizontal drag → rotate around Y axis
                // Vertical drag → rotate around X axis
                let yaw = Float(translation.width) * sensitivity
                let pitch = Float(translation.height) * sensitivity
                let yawQuat = simd_quatf(angle: yaw, axis: SIMD3<Float>(0, 1, 0))
                let pitchQuat = simd_quatf(angle: pitch, axis: SIMD3<Float>(1, 0, 0))
                renderer.manualRotation = yawQuat * renderer.manualRotation * pitchQuat
                gesture.setTranslation(.zero, in: view)
            }
        }
        orbit.minimumNumberOfTouches = 1
        orbit.maximumNumberOfTouches = 1
        view.addGestureRecognizer(orbit)

        // Two-finger pan to move the camera
        let pan = UIPanGestureRecognizer { gesture in
            if gesture.state == .changed {
                let translation = gesture.translation(in: view)
                let velocity = gesture.velocity(in: view)
                renderer.handlePan(translation: translation, velocity)
                gesture.setTranslation(.zero, in: view)
            }
        }
        pan.minimumNumberOfTouches = 2
        pan.maximumNumberOfTouches = 2
        view.addGestureRecognizer(pan)

        // Double tap to reset view
        let doubleTap = UITapGestureRecognizer { _ in
            renderer.resetView()
        }
        doubleTap.numberOfTapsRequired = 2
        view.addGestureRecognizer(doubleTap)
    }
}

#endif // os(iOS)

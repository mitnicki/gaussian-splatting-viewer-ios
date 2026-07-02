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
        var gestureHandler: GestureHandler?
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

            // Set up gesture handler
            let handler = GestureHandler(renderer: renderer)
            handler.bind(view: metalKitView)
            context.coordinator.gestureHandler = handler
            addGestures(to: metalKitView, handler: handler)

            Task { @MainActor in
                do {
                    try await renderer.load(url)
                    onLoadComplete?(nil)
                } catch {
                    onLoadComplete?(error)
                }
            }
        } else {
            onLoadComplete?(NSError(
                domain: "MetalKitSceneView",
                code: 1,
                userInfo: [NSLocalizedDescriptionKey: "Metal is not available on this device"]
            ))
        }

        return metalKitView
    }

    func updateUIView(_ view: MTKView, context: UIViewRepresentableContext<MetalKitSceneView>) {
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

    private func addGestures(to view: MTKView, handler: GestureHandler) {
        // Pinch to zoom
        let pinch = UIPinchGestureRecognizer(target: handler, action: #selector(handler.handlePinch(_:)))
        view.addGestureRecognizer(pinch)

        // One-finger pan to orbit/rotate the splat
        let orbit = UIPanGestureRecognizer(target: handler, action: #selector(handler.handleOrbit(_:)))
        orbit.minimumNumberOfTouches = 1
        orbit.maximumNumberOfTouches = 1
        view.addGestureRecognizer(orbit)

        // Two-finger pan to move the camera
        let pan = UIPanGestureRecognizer(target: handler, action: #selector(handler.handlePan(_:)))
        pan.minimumNumberOfTouches = 2
        pan.maximumNumberOfTouches = 2
        view.addGestureRecognizer(pan)

        // Double tap to reset view
        let doubleTap = UITapGestureRecognizer(target: handler, action: #selector(handler.handleDoubleTap(_:)))
        doubleTap.numberOfTapsRequired = 2
        view.addGestureRecognizer(doubleTap)
    }
}

// MARK: - Gesture handler

final class GestureHandler: NSObject {
    private let renderer: MetalKitSceneRenderer
    private weak var view: MTKView?

    init(renderer: MetalKitSceneRenderer) {
        self.renderer = renderer
        super.init()
    }

    func bind(view: MTKView) {
        self.view = view
    }

    @objc func handlePinch(_ gesture: UIPinchGestureRecognizer) {
        if gesture.state == .changed {
            renderer.handlePinch(scale: gesture.scale)
            gesture.scale = 1.0
        }
    }

    @objc func handleOrbit(_ gesture: UIPanGestureRecognizer) {
        guard let view else { return }
        if gesture.state == .changed {
            let translation = gesture.translation(in: view)
            let sensitivity: Float = 0.01
            let yaw = Float(translation.width) * sensitivity
            let pitch = Float(translation.height) * sensitivity
            let yawQuat = simd_quatf(angle: yaw, axis: SIMD3<Float>(0, 1, 0))
            let pitchQuat = simd_quatf(angle: pitch, axis: SIMD3<Float>(1, 0, 0))
            renderer.manualRotation = yawQuat * renderer.manualRotation * pitchQuat
            gesture.setTranslation(.zero, in: view)
        }
    }

    @objc func handlePan(_ gesture: UIPanGestureRecognizer) {
        guard let view else { return }
        if gesture.state == .changed {
            let translation = gesture.translation(in: view)
            let velocity = gesture.velocity(in: view)
            renderer.handlePan(translation: translation, velocity)
            gesture.setTranslation(.zero, in: view)
        }
    }

    @objc func handleDoubleTap(_ gesture: UITapGestureRecognizer) {
        renderer.resetView()
    }
}

#endif // os(iOS)

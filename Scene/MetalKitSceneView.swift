// MetalKitSceneView.swift
// SwiftUI ↔ UIKit bridge for MTKView. iOS-only.
// Adapted from MetalSplatter SampleApp's MetalKitSceneView (MIT).

#if os(iOS)

import SwiftUI
import MetalKit

struct MetalKitSceneView: UIViewRepresentable {
    let url: URL?

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

            Task {
                do {
                    try await renderer.load(url)
                } catch {
                    print("Error loading model: \(error.localizedDescription)")
                }
            }
        }

        return metalKitView
    }

    func updateUIView(_ view: MTKView, context: UIViewRepresentableContext<MetalKitSceneView>) {
        // Only reload if the URL actually changed. SwiftUI calls updateUIView
        // on every state change in the parent view — without this guard we'd
        // tear down and reload the splat on every redraw.
        guard let renderer = context.coordinator.renderer else { return }
        guard renderer.url != url else { return }
        Task {
            do {
                try await renderer.load(url)
            } catch {
                print("Error loading model: \(error.localizedDescription)")
            }
        }
    }

    // MARK: - Gesture setup

    private func addGestures(to view: MTKView, renderer: MetalKitSceneRenderer) {
        // Pinch to zoom
        let pinch = UIPinchGestureRecognizer(target: nil) { gesture in
            if gesture.state == .changed {
                renderer.handlePinch(scale: gesture.scale)
                gesture.scale = 1.0  // reset for incremental updates
            }
        }
        view.addGestureRecognizer(pinch)

        // Pan to move the camera
        let pan = UIPanGestureRecognizer(target: nil) { gesture in
            if gesture.state == .changed {
                let translation = gesture.translation(in: view)
                let velocity = gesture.velocity(in: view)
                renderer.handlePan(translation: translation, velocity)
                gesture.setTranslation(.zero, in: view)
            }
        }
        pan.maximumNumberOfTouches = 2
        view.addGestureRecognizer(pan)

        // Double tap to reset view
        let doubleTap = UITapGestureRecognizer(target: nil) { _ in
            renderer.resetView()
        }
        doubleTap.numberOfTapsRequired = 2
        view.addGestureRecognizer(doubleTap)
    }
}

#endif // os(iOS)

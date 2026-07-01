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

        let renderer = MetalKitSceneRenderer(metalKitView)
        context.coordinator.renderer = renderer
        metalKitView.delegate = renderer

        Task {
            do {
                try await renderer?.load(url)
            } catch {
                print("Error loading model: \(error.localizedDescription)")
            }
        }

        return metalKitView
    }

    func updateUIView(_ view: MTKView, context: UIViewRepresentableContext<MetalKitSceneView>) {
        guard let renderer = context.coordinator.renderer else { return }
        Task {
            do {
                try await renderer.load(url)
            } catch {
                print("Error loading model: \(error.localizedDescription)")
            }
        }
    }
}

#endif // os(iOS)

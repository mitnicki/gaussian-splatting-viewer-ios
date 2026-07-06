// MetalKitSceneRenderer.swift
// MTKViewDelegate that loads a splat file (.ply/.splat/.spz via SplatIO's
// AutodetectSceneReader) and renders it with MetalSplatter's SplatRenderer.
// iOS-only. Adapted from MetalSplatter SampleApp's MetalKitSceneRenderer (MIT),
// simplified to splat-file loading only (procedural / sample-box cases removed).

#if os(iOS)

import Metal
import MetalKit
import MetalSplatter
import CoreImage
import os
import simd
import SplatIO
import SwiftUI
import UIKit

/// Identity matrix helper (simd doesn't provide one directly).
func matrix4x4_identity() -> matrix_float4x4 {
    return matrix_float4x4(diagonal: SIMD4<Float>(1, 1, 1, 1))
}

/// Convert a quaternion to a 4×4 rotation matrix.
func matrix4x4_from_quaternion(_ q: simd_quatf) -> matrix_float4x4 {
    let x = q.vector.x, y = q.vector.y, z = q.vector.z, w = q.real
    var m = matrix_float4x4()
    m.columns.0 = SIMD4<Float>(1 - 2*(y*y + z*z), 2*(x*y + w*z), 2*(x*z - w*y), 0)
    m.columns.1 = SIMD4<Float>(2*(x*y - w*z), 1 - 2*(x*x + z*z), 2*(y*z + w*x), 0)
    m.columns.2 = SIMD4<Float>(2*(x*z + w*y), 2*(y*z - w*x), 1 - 2*(x*x + y*y), 0)
    m.columns.3 = SIMD4<Float>(0, 0, 0, 1)
    return m
}

@MainActor
final class MetalKitSceneRenderer: NSObject, MTKViewDelegate {
    private static let log =
        Logger(subsystem: Bundle.main.bundleIdentifier ?? "GaussianSplattingViewer",
               category: "MetalKitSceneRenderer")

    let metalKitView: MTKView
    let device: MTLDevice
    let commandQueue: MTLCommandQueue

    var loadedURL: URL?
    var modelRenderer: (any ModelRenderer)?

    let inFlightSemaphore = DispatchSemaphore(value: Constants.maxSimultaneousRenders)

    var lastRotationUpdateTimestamp: Date? = nil
    var rotation: Angle = .zero
    var drawableSize: CGSize = .zero

    // MARK: - User interaction state

    var autoRotate: Bool = false
    var manualRotation: simd_quatf = simd_quatf(angle: 0, axis: SIMD3<Float>(0, 1, 0))
    var cameraDistance: Float = 0  // offset from default, zoom in/out
    var panOffset: SIMD2<Float> = .zero  // screen-space pan
    var walkthroughActive: Bool = false

    private let zoomStep: Float = 0.6

    func zoomIn() { cameraDistance = min(cameraDistance + zoomStep, 15.0) }
    func zoomOut() { cameraDistance = max(cameraDistance - zoomStep, -7.0) }

    // Walkthrough: slow auto-orbit + gentle zoom oscillation
    private var walkthroughStartTime: Date? = nil
    private var walkthroughSpeedMultiplier: Float = 1.0

    func setWalkthroughSpeed(_ speed: Float) {
        walkthroughSpeedMultiplier = max(0.1, speed)
    }

    init?(_ metalKitView: MTKView) {
        guard let device = metalKitView.device else { return nil }
        guard let queue = device.makeCommandQueue() else { return nil }
        self.device = device
        self.commandQueue = queue
        self.metalKitView = metalKitView
        metalKitView.colorPixelFormat = MTLPixelFormat.bgra8Unorm_srgb
        metalKitView.depthStencilPixelFormat = MTLPixelFormat.depth32Float
        metalKitView.sampleCount = 1
        metalKitView.clearColor = MTLClearColor(red: 0, green: 0, blue: 0, alpha: 0)
    }

    /// Prevents concurrent loads — makeUIView and updateUIView can both
    /// fire before the first load completes, causing a race where two
    /// loads nil out modelRenderer and overwrite each other's results.
    private var isLoading = false

    func load(_ url: URL?) async throws {
        guard !isLoading else { return }
        isLoading = true
        defer { isLoading = false }

        // Guard against reloading the same URL. We compare against
        // loadedURL (set only after a successful load), NOT a pre-set
        // value — so a failed load can be retried with the same URL.
        guard url != loadedURL else { return }
        modelRenderer = nil

        guard let url else {
            loadedURL = nil
            return
        }

        let splat = try SplatRenderer(
            device: device,
            colorFormat: metalKitView.colorPixelFormat,
            depthFormat: metalKitView.depthStencilPixelFormat,
            sampleCount: metalKitView.sampleCount,
            maxViewCount: 1,
            maxSimultaneousRenders: Constants.maxSimultaneousRenders
        )
        // ponytail: readAll() double-buffers (Swift array + GPU buffer),
        // but .spz files are ~113MB — peak ~230MB is well within iPhone
        // memory. The streaming load that replaced this had a race
        // condition (double-load from makeUIView + updateUIView) and
        // was never tested on-device. Revert to proven approach.
        let reader = try AutodetectSceneReader(url)
        let points = try await reader.readAll()
        let chunk = try SplatChunk(device: device, from: points)
        await splat.addChunk(chunk)
        modelRenderer = splat
        loadedURL = url
    }

    private var viewport: ModelRendererViewportDescriptor {
        let effectiveFovy = Float(Constants.fovy.radians)
        // Clamp zoom so the scene doesn't disappear or invert
        let zoom = max(min(cameraDistance, 15.0), -7.0)

        // Guard against zero drawableSize (initial frame before layout) —
        // dividing by zero produces NaN in the projection matrix, which
        // renders garbage or crashes the GPU pipeline.
        let safeWidth = max(Float(drawableSize.width), 1.0)
        let safeHeight = max(Float(drawableSize.height), 1.0)

        let projectionMatrix = matrix_perspective_right_hand(
            fovyRadians: effectiveFovy,
            aspectRatio: safeWidth / safeHeight,
            nearZ: 0.1,
            farZ: 100.0
        )

        let autoRotationMatrix = autoRotate
            ? matrix4x4_rotation(radians: Float(rotation.radians), axis: Constants.rotationAxis)
            : matrix4x4_identity()

        let manualRotationMatrix = matrix4x4_from_quaternion(manualRotation)
        let rotationMatrix = manualRotationMatrix * autoRotationMatrix
        let translationMatrix = matrix4x4_translation(panOffset.x, panOffset.y, Constants.modelCenterZ + zoom)
        // Turn common 3D GS PLY files rightside-up (matches upstream SampleApp default).
        let commonUpCalibration = matrix4x4_rotation(radians: .pi, axis: SIMD3<Float>(0, 0, 1))

        let viewport = MTLViewport(originX: 0, originY: 0,
                                  width: drawableSize.width, height: drawableSize.height,
                                  znear: 0, zfar: 1)

        return ModelRendererViewportDescriptor(
            viewport: viewport,
            projectionMatrix: projectionMatrix,
            viewMatrix: translationMatrix * rotationMatrix * commonUpCalibration,
            screenSize: SIMD2(x: Int(drawableSize.width), y: Int(drawableSize.height))
        )
    }

    private func updateRotation() {
        if walkthroughActive, let start = walkthroughStartTime {
            let elapsed = Float(Date().timeIntervalSince(start))
            let speed = walkthroughSpeedMultiplier
            // Slow orbit
            rotation = Angle.radians(Double(elapsed * 0.15 * speed))
            // Gentle zoom oscillation: sin wave between -3 and +3
            cameraDistance = sin(elapsed * 0.3 * speed) * 3.0
        } else if autoRotate {
            let now = Date()
            defer { lastRotationUpdateTimestamp = now }
            guard let lastRotationUpdateTimestamp else { return }
            rotation += Constants.rotationPerSecond * now.timeIntervalSince(lastRotationUpdateTimestamp)
        }
    }

    // MARK: - Gesture handlers

    func handlePinch(scale: CGFloat) {
        cameraDistance += Float(1.0 - scale) * 2.0
    }

    func handlePan(translation: CGSize, _ velocity: CGSize) {
        // Convert screen-space pan to world units
        let sensitivity: Float = 0.01
        panOffset.x += Float(translation.width) * sensitivity
        panOffset.y -= Float(translation.height) * sensitivity  // flip Y
        _ = velocity  // reserved for momentum/inertia in a future iteration
    }

    func resetView() {
        cameraDistance = 0
        panOffset = .zero
        manualRotation = simd_quatf(angle: 0, axis: SIMD3<Float>(0, 1, 0))
        rotation = .zero
        stopWalkthrough()
    }

    func startWalkthrough() {
        walkthroughActive = true
        walkthroughStartTime = Date()
        autoRotate = true
    }

    func stopWalkthrough() {
        walkthroughActive = false
        walkthroughStartTime = nil
        autoRotate = false
    }

    /// Capture the current Metal drawable as a UIImage.
    func captureSnapshot() -> UIImage? {
        guard let drawable = metalKitView.currentDrawable else { return nil }
        let texture = drawable.texture

        guard let ciImage = CIImage(mtlTexture: texture, options: nil) else { return nil }
        let context = CIContext()
        guard let cgImage = context.createCGImage(ciImage, from: ciImage.extent) else { return nil }
        return UIImage(cgImage: cgImage)
    }

    func draw(in view: MTKView) {
        guard let modelRenderer, modelRenderer.isReadyToRender else { return }
        guard let drawable = view.currentDrawable else { return }

        _ = inFlightSemaphore.wait(timeout: DispatchTime.distantFuture)

        guard let commandBuffer = commandQueue.makeCommandBuffer() else {
            inFlightSemaphore.signal()
            return
        }

        let semaphore = inFlightSemaphore
        commandBuffer.addCompletedHandler { _ in
            semaphore.signal()
        }

        updateRotation()

        let didRender: Bool
        do {
            didRender = try modelRenderer.render(
                viewports: [viewport],
                colorTexture: view.multisampleColorTexture ?? drawable.texture,
                colorStoreAction: view.multisampleColorTexture == nil ? .store : .multisampleResolve,
                depthTexture: view.depthStencilTexture,
                rasterizationRateMap: nil,
                renderTargetArrayLength: 0,
                to: commandBuffer
            )
        } catch {
            Self.log.error("Unable to render scene: \(error.localizedDescription)")
            didRender = false
        }

        if didRender {
            commandBuffer.present(drawable)
        }

        commandBuffer.commit()
    }

    func mtkView(_ view: MTKView, drawableSizeWillChange size: CGSize) {
        drawableSize = size
    }
}

#endif // os(iOS)

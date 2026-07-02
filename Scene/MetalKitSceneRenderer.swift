// MetalKitSceneRenderer.swift
// MTKViewDelegate that loads a splat file (.ply/.splat/.spz via SplatIO's
// AutodetectSceneReader) and renders it with MetalSplatter's SplatRenderer.
// iOS-only. Adapted from MetalSplatter SampleApp's MetalKitSceneRenderer (MIT),
// simplified to splat-file loading only (procedural / sample-box cases removed).

#if os(iOS)

import Metal
import MetalKit
import MetalSplatter
import os
import simd
import SplatIO
import SwiftUI

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
        Logger(subsystem: Bundle.main.bundleIdentifier!, category: "MetalKitSceneRenderer")

    let metalKitView: MTKView
    let device: MTLDevice
    let commandQueue: MTLCommandQueue

    var url: URL?
    var modelRenderer: (any ModelRenderer)?

    let inFlightSemaphore = DispatchSemaphore(value: Constants.maxSimultaneousRenders)

    var lastRotationUpdateTimestamp: Date? = nil
    var rotation: Angle = .zero
    var drawableSize: CGSize = .zero

    // MARK: - User interaction state

    var autoRotate: Bool = true
    var manualRotation: simd_quatf = simd_quatf(angle: 0, axis: SIMD3<Float>(0, 1, 0))
    var cameraDistance: Float = 0  // offset from default, zoom in/out
    var panOffset: SIMD2<Float> = .zero  // screen-space pan

    init?(_ metalKitView: MTKView) {
        self.device = metalKitView.device!
        guard let queue = self.device.makeCommandQueue() else { return nil }
        self.commandQueue = queue
        self.metalKitView = metalKitView
        metalKitView.colorPixelFormat = MTLPixelFormat.bgra8Unorm_srgb
        metalKitView.depthStencilPixelFormat = MTLPixelFormat.depth32Float
        metalKitView.sampleCount = 1
        metalKitView.clearColor = MTLClearColor(red: 0, green: 0, blue: 0, alpha: 0)
    }

    func load(_ url: URL?) async throws {
        guard url != self.url else { return }
        self.url = url
        modelRenderer = nil

        guard let url else { return }

        let splat = try SplatRenderer(
            device: device,
            colorFormat: metalKitView.colorPixelFormat,
            depthFormat: metalKitView.depthStencilPixelFormat,
            sampleCount: metalKitView.sampleCount,
            maxViewCount: 1,
            maxSimultaneousRenders: Constants.maxSimultaneousRenders
        )
        let reader = try AutodetectSceneReader(url)
        let points = try await reader.readAll()
        let chunk = try SplatChunk(device: device, from: points)
        await splat.addChunk(chunk)
        modelRenderer = splat
    }

    private var viewport: ModelRendererViewportDescriptor {
        let effectiveFovy = Float(Constants.fovy.radians)
        // Clamp zoom so the scene doesn't disappear or invert
        let zoom = max(min(cameraDistance, 15.0), -7.0)

        let projectionMatrix = matrix_perspective_right_hand(
            fovyRadians: effectiveFovy,
            aspectRatio: Float(drawableSize.width / drawableSize.height),
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
        guard autoRotate else { return }
        let now = Date()
        defer { lastRotationUpdateTimestamp = now }
        guard let lastRotationUpdateTimestamp else { return }
        rotation += Constants.rotationPerSecond * now.timeIntervalSince(lastRotationUpdateTimestamp)
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
    }

    func handleRotationGesture(rotation angle: CGFloat, _ velocity: CGFloat) {
        // Accumulate rotation around Y axis
        let delta = Float(angle)
        let q = simd_quatf(angle: delta, axis: SIMD3<Float>(0, 1, 0))
        manualRotation = q * manualRotation
    }

    func resetView() {
        cameraDistance = 0
        panOffset = .zero
        manualRotation = simd_quatf(angle: 0, axis: SIMD3<Float>(0, 1, 0))
        rotation = .zero
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

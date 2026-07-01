// Constants.swift
// Render constants. Adapted from MetalSplatter SampleApp (MIT).

import Foundation
import SwiftUI

enum Constants {
    static let maxSimultaneousRenders = 3
    static let rotationPerSecond = Angle(degrees: 7)
    static let rotationAxis = SIMD3<Float>(0, 1, 0)
    static let fovy = Angle(degrees: 65)
    static let modelCenterZ: Float = -8
}

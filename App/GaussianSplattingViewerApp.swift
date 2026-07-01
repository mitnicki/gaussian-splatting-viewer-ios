// GaussianSplattingViewerApp.swift
// M1 PoC entry point. iOS-only native Gaussian Splatting viewer built on MetalSplatter.
//
// Rendering code adapted from the MetalSplatter SampleApp (MIT-licensed,
// https://github.com/scier/MetalSplatter) — see LICENSE-MetalSplatter.txt and the
// upstream NOTICE in the README.

import SwiftUI

@main
struct GaussianSplattingViewerApp: App {
    var body: some Scene {
        WindowGroup {
            ContentView()
        }
    }
}

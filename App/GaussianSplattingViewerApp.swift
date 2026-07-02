// GaussianSplattingViewerApp.swift
// M1 PoC entry point. iOS-only native Gaussian Splatting viewer built on MetalSplatter.
//
// Rendering code adapted from the MetalSplatter SampleApp (MIT-licensed,
// https://github.com/scier/MetalSplatter) — see LICENSE-MetalSplatter.txt and the
// upstream NOTICE in the README.

#if os(iOS)

import SwiftUI
import UIKit

@main
struct GaussianSplattingViewerApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) var appDelegate

    var body: some Scene {
        WindowGroup {
            ContentView()
        }
    }
}

// AppDelegate to handle memory warnings — splat files are large (113 MB .spz)
// and the Metal renderer holds device memory. On memory pressure we clear the
// disk cache to give the OS back resources before it kills the app.
final class AppDelegate: NSObject, UIApplicationDelegate {
    func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil
    ) -> Bool {
        NotificationCenter.default.addObserver(
            forName: UIApplication.didReceiveMemoryWarningNotification,
            object: nil,
            queue: .main
        ) { _ in
            Task {
                let cache = SplatCacheManager()
                await cache.handleMemoryWarning()
            }
        }
        return true
    }
}

#endif // os(iOS)

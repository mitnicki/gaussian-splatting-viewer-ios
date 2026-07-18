// FeatureFlags.swift
// Compile-time feature toggles for release scoping.
// Walkthrough and joystick are deferred to v1.1+ — hidden from UI for v1.0 launch.

enum FeatureFlags {
    /// Walkthrough (flythrough camera path). Deferred to v1.1+.
    static let walkthroughEnabled = false
    /// Virtual joystick look control. Deferred to v1.1+.
    static let joystickEnabled = false
}

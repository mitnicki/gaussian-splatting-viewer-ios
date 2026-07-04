// CIColors.swift
// Corporate Identity color tokens for kroeker.cloud.
// Source: CI Design Guidelines v1.0, Section 7.2
// These are the single source of truth for all app colors.

import SwiftUI

extension Color {
    // MARK: - Backgrounds
    static let ciBgBase = Color(red: 6/255, green: 6/255, blue: 8/255)
    static let ciBgDeep = Color(red: 4/255, green: 4/255, blue: 6/255)
    static let ciBgPanel = Color.white.opacity(0.025)
    static let ciBgElevated = Color.white.opacity(0.045)
    static let ciBgHover = Color.white.opacity(0.06)

    // MARK: - Text
    static let ciTextPrimary = Color(red: 245/255, green: 245/255, blue: 247/255)
    static let ciTextSecondary = Color(red: 161/255, green: 161/255, blue: 170/255)
    static let ciTextTertiary = Color(red: 113/255, green: 113/255, blue: 122/255)

    // MARK: - Accent (Brand Colors)
    static let ciAccent = Color(red: 99/255, green: 102/255, blue: 241/255)
    static let ciAccentBright = Color(red: 129/255, green: 140/255, blue: 248/255)
    static let ciAccentViolet = Color(red: 168/255, green: 85/255, blue: 247/255)
    static let ciAccentGlow = Color(red: 99/255, green: 102/255, blue: 241/255).opacity(0.35)
    static let ciAccentSoft = Color(red: 99/255, green: 102/255, blue: 241/255).opacity(0.12)

    // MARK: - Status
    static let ciStatusGreen = Color(red: 16/255, green: 185/255, blue: 129/255)
    static let ciStatusAmber = Color(red: 245/255, green: 158/255, blue: 11/255)
    static let ciStatusRed = Color(red: 239/255, green: 68/255, blue: 68/255)

    // MARK: - Borders
    static let ciBorderSubtle = Color.white.opacity(0.05)
    static let ciBorderStandard = Color.white.opacity(0.08)
    static let ciBorderBright = Color.white.opacity(0.12)

    // MARK: - Accent Gradient
    static var ciAccentGradient: LinearGradient {
        LinearGradient(
            colors: [ciAccent, ciAccentViolet, Color(red: 236/255, green: 72/255, blue: 153/255)],
            startPoint: .topLeading,
            endPoint: .bottomTrailing
        )
    }

    // MARK: - Text Gradient
    static var ciTextGradient: LinearGradient {
        LinearGradient(
            colors: [ciAccentBright, Color(red: 192/255, green: 132/255, blue: 252/255), Color(red: 244/255, green: 114/255, blue: 182/255)],
            startPoint: .topLeading,
            endPoint: .bottomTrailing
        )
    }
}

// MARK: - ShapeStyle conformance
// Allows .ciAccent, .ciBgBase, etc. in .foregroundStyle() / .background() modifiers.

extension ShapeStyle where Self == Color {
    static var ciBgBase: Color { .ciBgBase }
    static var ciBgDeep: Color { .ciBgDeep }
    static var ciBgPanel: Color { .ciBgPanel }
    static var ciBgElevated: Color { .ciBgElevated }
    static var ciBgHover: Color { .ciBgHover }
    static var ciTextPrimary: Color { .ciTextPrimary }
    static var ciTextSecondary: Color { .ciTextSecondary }
    static var ciTextTertiary: Color { .ciTextTertiary }
    static var ciAccent: Color { .ciAccent }
    static var ciAccentBright: Color { .ciAccentBright }
    static var ciAccentViolet: Color { .ciAccentViolet }
    static var ciAccentGlow: Color { .ciAccentGlow }
    static var ciAccentSoft: Color { .ciAccentSoft }
    static var ciStatusGreen: Color { .ciStatusGreen }
    static var ciStatusAmber: Color { .ciStatusAmber }
    static var ciStatusRed: Color { .ciStatusRed }
    static var ciBorderSubtle: Color { .ciBorderSubtle }
    static var ciBorderStandard: Color { .ciBorderStandard }
    static var ciBorderBright: Color { .ciBorderBright }
}

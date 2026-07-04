// CIComponents.swift
// Reusable CI-konforme SwiftUI UI components for kroeker.cloud.
// Source: CI Design Guidelines v1.0, Sections 5 & 7.4
// Button styles, card backgrounds, section containers.

import SwiftUI

// MARK: - Card / Panel Background

struct CICardBackground: ViewModifier {
    var elevated: Bool = false

    func body(content: Content) -> some View {
        content
            .background(elevated ? Color.ciBgElevated : Color.ciBgPanel)
            .overlay(
                RoundedRectangle(cornerRadius: 12)
                    .stroke(Color.ciBorderSubtle, lineWidth: 1)
            )
            .clipShape(RoundedRectangle(cornerRadius: 12))
    }
}

extension View {
    func ciCard(elevated: Bool = false) -> some View {
        modifier(CICardBackground(elevated: elevated))
    }
}

// MARK: - Button Styles

struct CIPrimaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.ciBody)
            .foregroundStyle(.white)
            .padding(.horizontal, 20)
            .padding(.vertical, 12)
            .background(
                RoundedRectangle(cornerRadius: 10)
                    .fill(Color.ciAccent)
                    .opacity(configuration.isPressed ? 0.8 : 1.0)
            )
            .scaleEffect(configuration.isPressed ? 0.97 : 1.0)
            .animation(.easeInOut(duration: 0.15), value: configuration.isPressed)
    }
}

struct CISecondaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.ciBody)
            .foregroundStyle(.ciAccentBright)
            .padding(.horizontal, 20)
            .padding(.vertical, 12)
            .background(
                RoundedRectangle(cornerRadius: 10)
                    .stroke(Color.ciBorderStandard, lineWidth: 1)
            )
            .scaleEffect(configuration.isPressed ? 0.97 : 1.0)
            .animation(.easeInOut(duration: 0.15), value: configuration.isPressed)
    }
}

extension ButtonStyle where Self == CIPrimaryButtonStyle {
    static var ciPrimary: CIPrimaryButtonStyle { .init() }
}

extension ButtonStyle where Self == CISecondaryButtonStyle {
    static var ciSecondary: CISecondaryButtonStyle { .init() }
}

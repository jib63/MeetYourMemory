// Copyright (c) 2026 Jean-Baptiste Meyer
// SPDX-License-Identifier: MIT

import SwiftUI

enum MemoryTheme {
    static let ink = Color(red: 0.075, green: 0.055, blue: 0.16)
    static let inkSoft = Color(red: 0.11, green: 0.075, blue: 0.22)
    static let paper = Color(red: 0.975, green: 0.96, blue: 1.0)
    static let mist = Color(red: 0.86, green: 0.84, blue: 0.96)
    static let violet = Color(red: 0.49, green: 0.23, blue: 0.95)
    static let coral = Color(red: 1.0, green: 0.29, blue: 0.55)
    static let aqua = Color(red: 0.15, green: 0.90, blue: 0.82)
    static let solar = Color(red: 1.0, green: 0.83, blue: 0.25)
    static let blue = Color(red: 0.22, green: 0.58, blue: 1.0)
}

extension MemoryCategory {
    var tint: Color {
        switch self {
        case .visual: MemoryTheme.coral
        case .words: MemoryTheme.solar
        case .sound: MemoryTheme.aqua
        case .spatial: MemoryTheme.blue
        case .association: MemoryTheme.violet
        case .sequence: Color(red: 0.96, green: 0.48, blue: 1.0)
        }
    }
}

extension MemorySwatch {
    var color: Color {
        switch self {
        case .violet: MemoryTheme.violet
        case .coral: MemoryTheme.coral
        case .aqua: MemoryTheme.aqua
        case .yellow: MemoryTheme.solar
        case .blue: MemoryTheme.blue
        }
    }
}

struct MemoryBackdrop: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        TimelineView(.animation(minimumInterval: reduceMotion ? 1 : 1 / 30)) { timeline in
            GeometryReader { geometry in
                let time = reduceMotion ? 0 : timeline.date.timeIntervalSinceReferenceDate

                ZStack {
                    MemoryTheme.ink.ignoresSafeArea()

                    Circle()
                        .fill(MemoryTheme.violet.opacity(0.42))
                        .frame(width: geometry.size.width * 0.95)
                        .blur(radius: 45)
                        .offset(
                            x: CGFloat(sin(time * 0.31)) * geometry.size.width * 0.22,
                            y: -geometry.size.height * 0.34 + CGFloat(cos(time * 0.23)) * 50
                        )

                    Circle()
                        .fill(MemoryTheme.coral.opacity(0.3))
                        .frame(width: geometry.size.width * 0.72)
                        .blur(radius: 52)
                        .offset(
                            x: geometry.size.width * 0.36 + CGFloat(cos(time * 0.27)) * 42,
                            y: geometry.size.height * 0.24 + CGFloat(sin(time * 0.29)) * 70
                        )

                    Circle()
                        .fill(MemoryTheme.aqua.opacity(0.23))
                        .frame(width: geometry.size.width * 0.58)
                        .blur(radius: 48)
                        .offset(
                            x: -geometry.size.width * 0.4 + CGFloat(sin(time * 0.19)) * 40,
                            y: geometry.size.height * 0.4
                        )

                    LinearGradient(
                        colors: [.clear, MemoryTheme.ink.opacity(0.4), MemoryTheme.ink.opacity(0.92)],
                        startPoint: .top,
                        endPoint: .bottom
                    )
                }
            }
        }
        .ignoresSafeArea()
    }
}

struct MemoryLens: View {
    let isAlive: Bool

    var body: some View {
        TimelineView(.animation(minimumInterval: isAlive ? 1 / 30 : 1)) { timeline in
            let time = isAlive ? timeline.date.timeIntervalSinceReferenceDate : 0

            ZStack {
                lensCircle(MemoryTheme.violet, size: 205)
                    .offset(x: -72 + CGFloat(sin(time * 0.8)) * 13, y: -5)
                lensCircle(MemoryTheme.coral, size: 180)
                    .offset(x: 72, y: 12 + CGFloat(cos(time * 0.72)) * 15)
                lensCircle(MemoryTheme.aqua, size: 150)
                    .offset(x: CGFloat(cos(time * 0.62)) * 15, y: 74)

                Circle()
                    .fill(.white.opacity(0.92))
                    .frame(width: 112, height: 112)
                    .overlay {
                        Image(systemName: "eye.fill")
                            .font(.system(size: 49, weight: .black))
                            .foregroundStyle(MemoryTheme.ink)
                    }
                    .shadow(color: .black.opacity(0.26), radius: 24, y: 12)

                ForEach(0..<10, id: \.self) { index in
                    Circle()
                        .fill(index.isMultiple(of: 3) ? MemoryTheme.solar : .white)
                        .frame(width: index.isMultiple(of: 3) ? 8 : 4)
                        .offset(y: -136)
                        .rotationEffect(.degrees(Double(index) * 36 + time * 7))
                }
            }
            .accessibilityHidden(true)
        }
    }

    private func lensCircle(_ color: Color, size: CGFloat) -> some View {
        Circle()
            .fill(color.opacity(0.76))
            .frame(width: size, height: size)
            .overlay(Circle().stroke(.white.opacity(0.22), lineWidth: 1))
            .blendMode(.screen)
    }
}

struct MemoryPressStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? 0.97 : 1)
            .opacity(configuration.isPressed ? 0.82 : 1)
            .animation(.spring(response: 0.22, dampingFraction: 0.72), value: configuration.isPressed)
    }
}

struct MemoryPrimaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(.headline, design: .rounded, weight: .black))
            .foregroundStyle(MemoryTheme.ink)
            .padding(.horizontal, 16)
            .frame(minHeight: 58)
            .background(MemoryTheme.solar, in: RoundedRectangle(cornerRadius: 19, style: .continuous))
            .scaleEffect(configuration.isPressed ? 0.97 : 1)
            .opacity(configuration.isPressed ? 0.8 : 1)
    }
}

struct MemorySecondaryButtonStyle: ButtonStyle {
    var dark = false

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(.subheadline, design: .rounded, weight: .black))
            .foregroundStyle(dark ? Color.white : MemoryTheme.ink)
            .padding(.horizontal, 14)
            .frame(minHeight: 52)
            .background(
                dark ? Color.white.opacity(0.09) : Color.white.opacity(0.45),
                in: RoundedRectangle(cornerRadius: 17, style: .continuous)
            )
            .overlay(
                RoundedRectangle(cornerRadius: 17, style: .continuous)
                    .stroke(dark ? Color.white.opacity(0.13) : MemoryTheme.ink.opacity(0.15), lineWidth: 1)
            )
            .scaleEffect(configuration.isPressed ? 0.97 : 1)
            .opacity(configuration.isPressed ? 0.78 : 1)
    }
}

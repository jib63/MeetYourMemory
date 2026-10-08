// Copyright (c) 2026 Jean-Baptiste Meyer
// SPDX-License-Identifier: MIT

import SwiftUI

/// Reports the current display posture without presenting any adaptive-game UI.
/// MemoryGame reads the latest value only when it chooses the next scan step.
struct AdaptiveDisplayObserver: View {
    let onChange: (AdaptiveDisplayContext) -> Void

    var body: some View {
        Group {
            if #available(iOS 27.1, *) {
                HingeDisplayObserver(onChange: onChange)
            } else {
                Color.clear
                    .onAppear {
                        onChange(UIDevice.current.userInterfaceIdiom == .pad
                            ? AdaptiveDisplayContext(mode: .expanded, pose: .unavailable, isExpanded: true)
                            : .compact)
                    }
            }
        }
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }
}

@available(iOS 27.1, *)
private struct HingeDisplayObserver: View {
    let onChange: (AdaptiveDisplayContext) -> Void
    @State private var hinge = DuoHingeState.unknown

    var body: some View {
        GeometryReader { geometry in
            let region = geometry.reservedRegions(kind: .division).first(where: \.isActive)?.frame
            let detectedPose = DuoPoseResolver.resolve(hinge: hinge, division: region, viewport: geometry.size)
            let context = testingContext ?? displayContext(for: detectedPose)
            Color.clear
                .onChange(of: context, initial: true) { _, value in onChange(value) }
        }
        .onHingeChange { _, context in
            guard testingContext == nil else { return }
            guard let deviceHinge = context.hinge else { hinge = .absent; return }
            switch deviceHinge.status {
            case .closed: hinge = .closed
            case .partiallyOpen: hinge = .partial
            case .fullyOpen: hinge = .open
            default: hinge = .unknown
            }
        }
    }

    private func displayContext(for pose: DuoPose) -> AdaptiveDisplayContext {
        if UIDevice.current.userInterfaceIdiom == .pad {
            return AdaptiveDisplayContext(mode: .expanded, pose: pose, isExpanded: true)
        }
        switch hinge {
        case .partial:
            // A window spanning only one side of the hinge is not a usable
            // cross-fold playground, even though the device is partially open.
            return pose == .book || pose == .tabletop
                ? AdaptiveDisplayContext(mode: .folded, pose: pose, isExpanded: false) : .compact
        case .open:
            return AdaptiveDisplayContext(mode: .expanded, pose: .flat, isExpanded: true)
        case .unknown, .absent, .closed:
            return .compact
        }
    }

    private var testingContext: AdaptiveDisplayContext? {
        #if DEBUG
        let arguments = ProcessInfo.processInfo.arguments
        guard let marker = arguments.firstIndex(of: "--adaptive-home-mode"), arguments.indices.contains(marker + 1) else { return nil }
        switch arguments[marker + 1] {
        case "folded": return AdaptiveDisplayContext(mode: .folded, pose: .book, isExpanded: false)
        case "expanded": return AdaptiveDisplayContext(mode: .expanded, pose: .flat, isExpanded: true)
        default: return .compact
        }
        #else
        return nil
        #endif
    }
}

/// Reflow matching rounds; protect memorized spatial and directional layouts.
struct AdaptiveScanChallengeView: View {
    let game: DuoGame
    let context: AdaptiveDisplayContext
    let onComplete: (DuoRoundScore) -> Void
    let onReplace: () -> Void
    var onTestingContextChange: ((AdaptiveDisplayContext) -> Void)? = nil

    @Environment(\.scenePhase) private var scenePhase
    @State private var model = DuoArcadeModel()
    @State private var started = false
    @State private var finished = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        VStack(spacing: 8) {
            #if DEBUG
            if ProcessInfo.processInfo.arguments.contains("--duo-test-posture-controls") {
                HStack {
                    ForEach([DuoPose.book, .tabletop, .flat, .closed], id: \.self) { pose in
                        Button(pose.rawValue) {
                            let value = AdaptiveDisplayContext(mode: pose == .closed ? .compact : pose == .flat ? .expanded : .folded,
                                                               pose: pose, isExpanded: pose == .flat)
                            onTestingContextChange?(value)
                        }.accessibilityIdentifier("duo-test-pose-\(pose.rawValue)")
                    }
                }.font(.caption)
            }
            #endif
            if started {
            DuoGameBoard(model: model, onReviewContinue: finish)
                .opacity(model.needsRecovery ? 0 : 1)
                .allowsHitTesting(!model.needsRecovery)
                .accessibilityElement(children: model.needsRecovery ? .ignore : .contain)
                .accessibilityHidden(model.needsRecovery)
                .overlay {
                    if model.needsRecovery {
                        DuoRecoveryView(model: model, onReplace: replace, onReviewContinue: finish)
                            .transition(.opacity)
                    }
                }
            } else { Color.clear }
        }
            .onAppear { startIfNeeded() }
            .onChange(of: context) { _, value in
                model.updateContext(pose: value.pose, isExpanded: value.isExpanded, isSceneActive: scenePhase == .active)
            }
            .onChange(of: scenePhase) { _, value in
                if !started {
                    if value == .active { startIfNeeded() }
                } else {
                    model.updateContext(pose: context.pose, isExpanded: context.isExpanded, isSceneActive: value == .active)
                }
            }
            .onChange(of: model.requiresResume) { _, value in
                guard scenePhase == .active else { return }
                UIImpactFeedbackGenerator(style: .soft).impactOccurred()
                UIAccessibility.post(notification: .announcement, argument: DuoText.text(value ? "recovery.saved" : "recovery.resumed"))
            }
            .animation(reduceMotion ? nil : .easeInOut(duration: 0.2), value: model.needsRecovery)
    }

    private func startIfNeeded() {
        guard !started, scenePhase == .active else { return }
        started = true
        model.updateContext(pose: context.pose, isExpanded: context.isExpanded, isSceneActive: scenePhase == .active)
        #if DEBUG
        if ProcessInfo.processInfo.arguments.contains("--duo-ui-testing") {
            model.start(game, round: .fixture)
            return
        }
        #endif
        model.start(game)
    }

    private func finish() {
        guard !finished, let score = model.score else { return }
        finished = true
        onComplete(score)
    }

    private func replace() {
        guard !finished, model.needsRecovery, model.score == nil else { return }
        finished = true
        onReplace()
    }
}

private struct DuoRecoveryView: View {
    let model: DuoArcadeModel
    let onReplace: () -> Void
    let onReviewContinue: () -> Void

    var body: some View {
        GeometryReader { area in
            let surface = recoverySurface(in: area)
            ZStack(alignment: .topLeading) {
            MemoryTheme.ink
            ScrollView {
                VStack(spacing: 18) {
                    Image(systemName: model.canResume ? "book.fill" : "book.closed.fill")
                        .font(.system(size: 48, weight: .bold)).foregroundStyle(MemoryTheme.aqua)
                        .accessibilityHidden(true)
                    Text(model.score != nil ? DuoText.text("recovery.finished") : model.canResume
                         ? DuoText.text("recovery.returned") : DuoText.text("recovery.saved.\(model.game.mechanic)"))
                        .font(.system(.title2, design: .rounded, weight: .black))
                        .multilineTextAlignment(.center).foregroundStyle(.white)
                    if let score = model.score {
                        Text(DuoText.format("score", score.correct, score.total)).foregroundStyle(MemoryTheme.aqua)
                        Button(DuoText.text("continue.scan"), action: onReviewContinue)
                            .buttonStyle(MemoryPrimaryButtonStyle()).accessibilityIdentifier("duo-recovery-continue")
                    } else {
                        Text(message).foregroundStyle(MemoryTheme.mist).multilineTextAlignment(.center)
                        Text(DuoText.format("recovery.kept", model.answerCount, model.answerTotal))
                            .font(.subheadline.bold()).foregroundStyle(MemoryTheme.aqua)
                            .padding(12).background(MemoryTheme.aqua.opacity(0.1), in: Capsule())
                            .accessibilityIdentifier("duo-recovery-progress")
                        if model.canResume {
                            Button(DuoText.text("recovery.resume")) { model.resume() }
                                .buttonStyle(MemoryPrimaryButtonStyle()).accessibilityIdentifier("duo-resume")
                        }
                        Button(DuoText.text("recovery.replace"), action: onReplace)
                            .buttonStyle(MemorySecondaryButtonStyle(dark: true)).accessibilityIdentifier("duo-replace")
                        Text(DuoText.text("recovery.no.penalty")).font(.caption).foregroundStyle(MemoryTheme.mist)
                    }
                }
                .padding(24).frame(maxWidth: 430)
                .frame(maxWidth: .infinity, minHeight: surface.height)
            }.scrollIndicators(.hidden)
                .frame(width: surface.width, height: surface.height)
                .position(x: surface.midX, y: surface.midY)
                .accessibilityIdentifier("duo-recovery")
            }.clipShape(RoundedRectangle(cornerRadius: 28))
        }
    }

    /// Recovery controls occupy one physical page, never the crease itself.
    private func recoverySurface(in area: GeometryProxy) -> CGRect {
        let bounds = CGRect(origin: .zero, size: area.size)
        if #available(iOS 27.1, *),
           let region = area.reservedRegions(kind: .division).first(where: \.isActive) {
            let start: CGFloat
            let surface: CGRect
            if region.frame.width > region.frame.height {
                start = max(0, region.frame.maxY + region.margins.bottom + 12)
                surface = CGRect(x: 0, y: start, width: area.size.width, height: max(0, area.size.height - start))
            } else {
                start = max(0, region.frame.maxX + region.margins.trailing + 12)
                surface = CGRect(x: start, y: 0, width: max(0, area.size.width - start), height: area.size.height)
            }
            if surface.width >= 180 && surface.height >= 150 { return surface }
            // A narrow multitasking window may contain only the first page.
            let first = region.frame.width > region.frame.height
                ? CGRect(x: 0, y: 0, width: area.size.width, height: max(0, region.frame.minY - region.margins.top - 12))
                : CGRect(x: 0, y: 0, width: max(0, region.frame.minX - region.margins.leading - 12), height: area.size.height)
            let available = bounds.intersection(first)
            return available.isNull || available.isEmpty ? bounds : available
        }
        return bounds
    }

    private var message: String {
        if model.canResume { return DuoText.text("recovery.resume.help") }
        if !model.hasUsableDisplay { return DuoText.text("recovery.open") }
        if !model.layoutCanFit { return DuoText.text("recovery.more.room") }
        return DuoText.text("recovery.return.\(model.memorizedPose.rawValue)")
    }
}

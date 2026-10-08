// Copyright (c) 2026 Jean-Baptiste Meyer
// SPDX-License-Identifier: MIT

import SwiftUI

private struct DuoFrameKey: PreferenceKey {
    static var defaultValue: [String: CGRect] { [:] }
    static func reduce(value: inout [String: CGRect], nextValue: () -> [String: CGRect]) {
        value.merge(nextValue(), uniquingKeysWith: { _, latest in latest })
    }
}

private struct AdaptiveDivisionRegion {
    let frame: CGRect
    let margins: EdgeInsets
}

private extension GeometryProxy {
    var adaptiveDivisionRegion: AdaptiveDivisionRegion? {
        if #available(iOS 27.1, *) {
            return reservedRegions(kind: .division).first(where: \.isActive).map {
                AdaptiveDivisionRegion(frame: $0.frame, margins: $0.margins)
            }
        }
        return nil
    }
}

private extension View {
    func duoFrame(_ key: String) -> some View {
        background(GeometryReader { geometry in
            Color.clear.preference(key: DuoFrameKey.self, value: [key: geometry.frame(in: .named("duo-board"))])
        })
    }
}

struct DuoGameBoard: View {
    let model: DuoArcadeModel
    var onReviewContinue: (() -> Void)? = nil
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var frames: [String: CGRect] = [:]
    @State private var draggedObject: Int?
    @State private var dragLocation = CGPoint.zero
    @State private var previousTracePoint: CGPoint?
    @State private var selectedGate = 1
    @State private var pull = CGSize.zero
    @State private var flight: CGPoint?
    @State private var litBeat: DuoBeat?
    @State private var playback: Task<Void, Never>?
    @State private var flightTask: Task<Void, Never>?
    @State private var tonePlayer = TonePlayer()
    @State private var layoutTask: Task<Void, Never>?
    @Namespace private var boardMotion

    var body: some View {
        GeometryReader { area in
            let fold = area.adaptiveDivisionRegion
            let footerWidth = model.pose == .book
              ? area.size.width - (fold.map { $0.frame.maxX + $0.margins.trailing } ?? area.size.width / 2) - 8
              : area.size.width
            VStack(spacing: 8) {
                ZStack {
                    splitPanes
                    if model.game.mechanic == .threads { threadLines }
                    if let object = draggedObject {
                        Text(model.round.objects[object].symbol).font(.system(size: 52))
                            .shadow(color: MemoryTheme.aqua.opacity(0.7), radius: 20)
                            .position(dragLocation).allowsHitTesting(false).accessibilityHidden(true)
                    }
                    if let flight {
                        Image(systemName: "sparkle").font(.system(size: 40, weight: .black))
                            .foregroundStyle(MemoryTheme.solar).position(flight)
                            .allowsHitTesting(false).accessibilityHidden(true)
                    }
                }
                .coordinateSpace(name: "duo-board")
                .onPreferenceChange(DuoFrameKey.self) { value in
                    if frames != value { cancelTransientInput() }
                    frames = value
                }
                .simultaneousGesture(traceGesture)
                .clipped()
                footer.fixedSize(horizontal: false, vertical: true)
                    .frame(width: max(0, footerWidth)).frame(maxWidth: .infinity, alignment: .trailing)
            }
        }
        .onChange(of: model.canPlay) { _, value in if !value { cancelTransientInput() } }
        .onChange(of: model.phase) { _, _ in cancelTransientInput() }
        .onChange(of: model.round.id) { _, _ in cancelTransientInput() }
        .onDisappear { cancelTransientInput(); layoutTask?.cancel() }
    }

    /// Both game surfaces are essential. A system arrangement may collapse its
    /// secondary view when its aspect ratio changes, so place the two surfaces
    /// explicitly around the actual reserved region instead.
    private var splitPanes: some View {
        GeometryReader { geometry in
            let region = geometry.adaptiveDivisionRegion
            let division = region.map {
                CGRect(x: $0.frame.minX - $0.margins.leading, y: $0.frame.minY - $0.margins.top,
                       width: $0.frame.width + $0.margins.leading + $0.margins.trailing,
                       height: $0.frame.height + $0.margins.top + $0.margins.bottom)
            }
            let layout = DuoBoardLayout.make(size: geometry.size, division: division, pose: model.pose, mechanic: model.game.mechanic)
            ZStack(alignment: .topLeading) {
                Color.clear
                if layout.canFit && !model.needsRecovery {
                    primaryPane(layout: layout)
                        .frame(width: layout.primary.width, height: layout.primary.height).clipped()
                        .position(x: layout.primary.midX, y: layout.primary.midY)
                    secondaryPane(layout: layout)
                        .frame(width: layout.secondary.width, height: layout.secondary.height).clipped()
                        .position(x: layout.secondary.midX, y: layout.secondary.midY)
                }
            }
            .animation(reduceMotion ? nil : .easeInOut(duration: 0.2), value: layout)
            .onChange(of: layout, initial: true) { _, value in
                cancelTransientInput()
                model.beginRepositioning()
                model.updateLayout(axis: value.axis, canFit: value.canFit)
                layoutTask?.cancel()
                layoutTask = Task { @MainActor in
                    do { try await Task.sleep(for: .milliseconds(250)) } catch { return }
                    model.finishRepositioning()
                }
            }
        }
    }

    private func primaryPane(layout: DuoBoardLayout) -> some View {
        VStack(spacing: 12) {
            paneHeading(model.game.mechanic == .courier ? "courier.source" : model.game.mechanic == .threads
                        ? layout.axis == .sideBySide ? "threads.left" : "threads.top" : "stage")
            switch model.game.mechanic {
            case .courier: courierObjects(compact: layout.axis == .stacked)
            case .threads: threadNodes(side: 0, diameter: layout.nodeDiameter)
            case .catapult: catapultStage
            case .drums: drumStage
            }
        }.padding(16).frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(.white.opacity(0.035), in: RoundedRectangle(cornerRadius: 28))
    }

    private func secondaryPane(layout: DuoBoardLayout) -> some View {
        VStack(spacing: 12) {
            paneHeading(model.game.mechanic == .courier ? "courier.homes" : model.game.mechanic == .threads
                        ? layout.axis == .sideBySide ? "threads.right" : "threads.bottom" : "controls")
            switch model.game.mechanic {
            case .courier: courierPockets(compact: layout.axis == .stacked)
            case .threads: threadNodes(side: 1, diameter: layout.nodeDiameter)
            case .catapult: catapultControls
            case .drums: drumControls
            }
        }.padding(16).frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(MemoryTheme.violet.opacity(0.09), in: RoundedRectangle(cornerRadius: 28))
    }

    private func paneHeading(_ key: String) -> some View {
        Text(DuoText.text(key)).font(.system(.caption, design: .monospaced, weight: .bold))
            .foregroundStyle(MemoryTheme.aqua).frame(maxWidth: .infinity, alignment: .leading)
    }

    @ViewBuilder private func courierObjects(compact: Bool) -> some View {
        if compact {
            HStack(spacing: 8) { courierObjectButtons(compact: true) }.frame(maxHeight: .infinity)
        } else {
            VStack(spacing: 16) { courierObjectButtons(compact: false) }.frame(maxHeight: .infinity)
        }
    }

    private func courierObjectButtons(compact: Bool) -> some View {
            ForEach(model.round.objects.indices, id: \.self) { index in
                let object = model.round.objects[index]
                Button { model.selectObject(index) } label: {
                    ViewThatFits(in: .horizontal) {
                        if !compact {
                        HStack {
                            Text(object.symbol).font(.system(size: 38))
                            Text(object.name).font(.system(.headline, design: .rounded, weight: .bold)).fixedSize()
                            Spacer(minLength: 0)
                            Image(systemName: model.deliveries[index] == nil ? "arrow.right" : "checkmark")
                        }
                        }
                        VStack(spacing: 4) {
                            Text(object.symbol).font(.system(size: 34))
                            Text(object.name).font(.caption.bold()).lineLimit(1).minimumScaleFactor(0.8)
                        }.frame(maxWidth: .infinity)
                    }.padding(12).frame(maxWidth: .infinity, minHeight: 76)
                        .background(model.selectedObject == index ? MemoryTheme.violet : .white.opacity(0.08), in: RoundedRectangle(cornerRadius: 22))
                }
                .buttonStyle(MemoryPressStyle()).disabled(!model.canAnswer)
                .matchedGeometryEffect(id: "parcel-\(index)", in: boardMotion)
                .accessibilityIdentifier("duo-object-\(index)")
                .accessibilityLabel(object.name)
                .accessibilityHint(DuoText.text("courier.tap.hint"))
                .accessibilityHidden(model.needsRecovery)
                .gesture(DragGesture(minimumDistance: 8, coordinateSpace: .named("duo-board"))
                    .onChanged { value in
                        guard model.canAnswer else { return }
                        draggedObject = index; dragLocation = value.location
                    }
                    .onEnded { value in
                        defer { draggedObject = nil }
                        guard model.canAnswer else { return }
                        if let pocket = (0..<3).first(where: { frames["pocket-\($0)"]?.contains(value.location) == true }),
                           model.deliver(index, to: pocket) { feedback() }
                    })
            }
    }

    @ViewBuilder private func courierPockets(compact: Bool) -> some View {
        if compact {
            HStack(spacing: 8) { courierPocketButtons(compact: true) }.frame(maxHeight: .infinity)
        } else {
            VStack(spacing: 16) { courierPocketButtons(compact: false) }.frame(maxHeight: .infinity)
        }
    }

    private func courierPocketButtons(compact: Bool) -> some View {
            ForEach(0..<3) { pocket in
                let occupant = model.showsSolution ? model.round.homes.firstIndex(of: pocket) : model.deliveries.first(where: { $0.value == pocket })?.key
                Button {
                    if let object = model.selectedObject, model.deliver(object, to: pocket) { feedback() }
                } label: {
                    Group {
                    if compact {
                        VStack(spacing: 4) {
                            Text("\(pocket + 1)").font(.caption.bold()).foregroundStyle(MemoryTheme.solar)
                            if let occupant { Text(model.round.objects[occupant].symbol).font(.system(size: 30)) }
                            else { Image(systemName: "tray").font(.title2).foregroundStyle(MemoryTheme.mist) }
                        }
                    } else {
                    HStack {
                        Text("\(pocket + 1)").font(.title2.bold()).foregroundStyle(MemoryTheme.solar)
                        Spacer()
                        if let occupant { Text(model.round.objects[occupant].symbol).font(.system(size: 38)) }
                        else { Image(systemName: "tray").font(.title).foregroundStyle(MemoryTheme.mist) }
                        Spacer()
                    }
                    }
                    }.padding(compact ? 8 : 14).frame(maxWidth: .infinity, minHeight: 76)
                        .background(MemoryTheme.aqua.opacity(0.08), in: RoundedRectangle(cornerRadius: 22))
                        .overlay(RoundedRectangle(cornerRadius: 22).stroke(MemoryTheme.aqua.opacity(0.4), style: StrokeStyle(lineWidth: 2, dash: [6])))
                }.buttonStyle(MemoryPressStyle()).disabled(!model.canAnswer)
                    .matchedGeometryEffect(id: "home-\(pocket)", in: boardMotion)
                    .duoFrame("pocket-\(pocket)")
                    .accessibilityLabel(DuoText.format("pocket", pocket + 1))
                    .accessibilityValue(occupant.map { model.round.objects[$0].name } ?? DuoText.text("empty"))
                    .accessibilityIdentifier("duo-pocket-\(pocket)")
                    .accessibilityHidden(model.needsRecovery)
            }
    }

    private func threadNodes(side: Int, diameter: CGFloat) -> some View {
        VStack(spacing: 10) {
            ForEach((0..<3).map { $0 * 2 + side }, id: \.self) { node in
                let path = model.showsSolution ? model.round.route : model.tracedNodes
                let order = path.firstIndex(of: node)
                Button { if model.trace(node) { feedback() } } label: {
                    VStack(spacing: 5) {
                        Text(String(UnicodeScalar(65 + node)!)).font(.system(.title, design: .rounded, weight: .black))
                        if let order { Text(DuoText.format("step", order + 1)).font(.caption.bold()) }
                    }.frame(width: diameter, height: diameter)
                        .background(order == nil ? MemoryTheme.inkSoft : MemoryTheme.violet, in: Circle())
                        .overlay(Circle().stroke(MemoryTheme.aqua.opacity(order == nil ? 0.25 : 0.9), lineWidth: 3))
                }.buttonStyle(MemoryPressStyle()).disabled(!model.canAnswer || model.answerIsComplete)
                    .duoFrame("node-\(node)")
                    .accessibilityLabel(DuoText.format("node", String(UnicodeScalar(65 + node)!)))
                    .accessibilityValue(order.map { DuoText.format("step", $0 + 1) } ?? "")
                    .accessibilityIdentifier("duo-node-\(node)")
                    .accessibilityHidden(model.needsRecovery)
                    .frame(maxHeight: .infinity)
            }
        }.frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var threadLines: some View {
        let nodes = model.showsSolution ? model.round.route : model.tracedNodes
        return Path { path in
            for (index, node) in nodes.enumerated() {
                guard let rect = frames["node-\(node)"] else { continue }
                let center = CGPoint(x: rect.midX, y: rect.midY)
                if index == 0 { path.move(to: center) } else { path.addLine(to: center) }
            }
        }.stroke(MemoryTheme.aqua.opacity(0.4), style: StrokeStyle(lineWidth: 4, lineCap: .round, dash: [8, 8]))
            .allowsHitTesting(false).accessibilityHidden(true)
    }

    private var traceGesture: some Gesture {
        DragGesture(minimumDistance: 6, coordinateSpace: .named("duo-board"))
            .onChanged { value in
                guard model.game.mechanic == .threads, model.canAnswer else { return }
                let centers = Dictionary(uniqueKeysWithValues: (0..<6).compactMap { node -> (Int, CGPoint)? in
                    frames["node-\(node)"].map { (node, CGPoint(x: $0.midX, y: $0.midY)) }
                })
                let radius = min(44, (frames["node-0"]?.width ?? 72) / 2 + 8)
                let crossed = DuoGestureRules.crossedNodes(from: previousTracePoint ?? value.startLocation, to: value.location, centers: centers, radius: radius)
                for node in crossed { if model.trace(node) { feedback() } }
                previousTracePoint = value.location
            }
            .onEnded { _ in previousTracePoint = nil }
    }

    private var catapultStage: some View {
        VStack(spacing: 18) {
            sequenceStrip(model.showsSolution ? model.round.gates.map { "\($0 + 1)" } : model.launchedGates.map { "\($0 + 1)" })
            HStack(spacing: 16) {
                ForEach(0..<3) { gate in
                    VStack(spacing: 6) {
                        Image(systemName: ["moon.fill", "star.fill", "sun.max.fill"][gate]).font(.title)
                        Text("\(gate + 1)").font(.title2.bold())
                    }.foregroundStyle(MemoryTheme.solar).frame(maxWidth: .infinity, minHeight: 70)
                        .background(MemoryTheme.solar.opacity(0.08), in: RoundedRectangle(cornerRadius: 22))
                        .duoFrame("gate-\(gate)").accessibilityLabel(DuoText.format("gate", gate + 1))
                }
            }
        }.frame(maxHeight: .infinity)
    }

    private var catapultControls: some View {
        VStack(spacing: 12) {
            Image(systemName: "sparkle").font(.system(size: 38, weight: .black)).foregroundStyle(MemoryTheme.ink)
                .frame(width: 76, height: 76).background(MemoryTheme.solar, in: Circle())
                .offset(x: pull.width * 0.25, y: pull.height * 0.25)
                .duoFrame("launcher").accessibilityLabel(DuoText.text("catapult.flick"))
                .accessibilityIdentifier("duo-launcher")
                .gesture(DragGesture(minimumDistance: 6)
                    .onChanged { if model.canAnswer && !model.answerIsComplete { pull = $0.translation } }
                    .onEnded { value in
                        pull = .zero
                        if let gate = DuoGestureRules.launchGate(translation: value.translation) { launch(gate) }
                    })
            HStack(spacing: 10) {
                ForEach(0..<3) { gate in
                    Button { selectedGate = gate } label: {
                        Text("\(gate + 1)").font(.headline).frame(maxWidth: .infinity, minHeight: 44)
                            .background(selectedGate == gate ? MemoryTheme.violet : .white.opacity(0.08), in: RoundedRectangle(cornerRadius: 14))
                    }
                    .accessibilityLabel(DuoText.format("gate", gate + 1))
                    .accessibilityAddTraits(selectedGate == gate ? [.isSelected] : [])
                    .accessibilityIdentifier("duo-gate-\(gate)")
                }
            }
            .disabled(!model.canAnswer || model.answerIsComplete)
            Button(DuoText.text("launch")) { launch(selectedGate) }
                .font(.headline).frame(maxWidth: .infinity, minHeight: 44)
                .background(MemoryTheme.aqua.opacity(0.2), in: RoundedRectangle(cornerRadius: 14))
                .accessibilityIdentifier("duo-launch")
            .disabled(!model.canAnswer || model.answerIsComplete)
        }.frame(maxHeight: .infinity)
    }

    private var drumStage: some View {
        VStack(spacing: 12) {
            sequenceStrip(model.showsSolution ? model.round.beats.map(\.symbol) : model.playedBeats.map(\.symbol))
            HStack(spacing: 30) {
                drumLamp("L", active: litBeat == .left || litBeat == .both || litBeat == .holdLeft)
                drumLamp("R", active: litBeat == .right || litBeat == .both)
            }.duoFrame("drum-stage")
            if model.showsSolution {
                Button { playSequence() } label: {
                    Label(DuoText.text("play.phrase"), systemImage: "play.fill").font(.headline).frame(minHeight: 44)
                }.disabled(playback != nil).accessibilityIdentifier("duo-play-phrase")
            }
        }.frame(maxHeight: .infinity)
    }

    private func drumLamp(_ label: String, active: Bool) -> some View {
        Text(label).font(.system(.title, design: .rounded, weight: .black))
            .frame(width: 70, height: 70)
            .foregroundStyle(active ? MemoryTheme.ink : MemoryTheme.aqua)
            .background(active ? MemoryTheme.aqua : MemoryTheme.aqua.opacity(0.1), in: Circle())
            .accessibilityHidden(true)
    }

    private var drumControls: some View {
        VStack(spacing: 10) {
            DuoDrumInput(isEnabled: model.canAnswer && !model.answerIsComplete, onBeat: playBeat)
                .frame(minHeight: 70, idealHeight: 100, maxHeight: 130).duoFrame("drum-pads")
                .accessibilityIdentifier("duo-drum-pads")
            ViewThatFits(in: .horizontal) {
                HStack(spacing: 8) { beatButtons }
                LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())]) { beatButtons }
            }
        }.frame(maxHeight: .infinity)
    }

    private var beatButtons: some View {
        ForEach(DuoBeat.allCases, id: \.rawValue) { beat in
            Button { playBeat(beat) } label: {
                Text(beat.label).font(.caption.bold()).padding(.horizontal, 10).frame(minHeight: 44)
                    .background(.white.opacity(0.08), in: RoundedRectangle(cornerRadius: 14))
            }.disabled(!model.canAnswer || model.answerIsComplete).accessibilityIdentifier("duo-beat-\(beat.rawValue)")
        }
    }

    private func sequenceStrip(_ values: [String]) -> some View {
        HStack(spacing: 10) {
            ForEach(0..<model.answerTotal, id: \.self) { index in
                Text(index < values.count ? values[index] : "·")
                    .font(.system(.headline, design: .monospaced, weight: .bold))
                    .frame(minWidth: 44, minHeight: 40)
                    .background(.white.opacity(0.08), in: RoundedRectangle(cornerRadius: 12))
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(DuoText.text(model.showsSolution ? "solution" : "your.answer"))
        .accessibilityValue(values.joined(separator: ", "))
        .accessibilityIdentifier(model.showsSolution ? "duo-solution" : "duo-answer")
    }

    private var footer: some View {
        VStack(spacing: 10) {
            if let score = model.score {
                VStack(spacing: 5) {
                    HStack {
                        Image(systemName: score.isPerfect ? "sparkles" : "arrow.trianglehead.clockwise")
                        Text(DuoText.format("score", score.correct, score.total)).accessibilityIdentifier("duo-score")
                    }
                    Text(DuoText.text("review.help")).font(.caption).foregroundStyle(MemoryTheme.mist)
                        .multilineTextAlignment(.center)
                }.font(.headline).foregroundStyle(MemoryTheme.aqua)
            } else {
                Text(model.phase == .study ? model.game.instructions : DuoText.text("recall.\(model.game.rawValue)"))
                    .font(.callout).foregroundStyle(MemoryTheme.mist).multilineTextAlignment(.center)
            }
            ViewThatFits(in: .horizontal) {
                HStack(spacing: 10) { footerActions }
                VStack(spacing: 8) { footerActions }
            }
        }.padding(.horizontal, 16).padding(.bottom, 12)
    }

    @ViewBuilder private var footerActions: some View {
        if model.phase == .recall {
                    Button(DuoText.text(model.game.mechanic == .courier ? "clear" : "undo")) { model.undo() }
                .buttonStyle(MemorySecondaryButtonStyle(dark: true)).disabled(!model.canAnswer || model.answerCount == 0)
                .accessibilityIdentifier("duo-undo")
                .accessibilityHidden(model.needsRecovery)
            Text("\(model.answerCount)/\(model.answerTotal)").font(.headline.monospacedDigit())
                .accessibilityIdentifier("duo-progress")
                .accessibilityHidden(model.needsRecovery)
            Button(DuoText.text("check")) { model.submit() }
                .buttonStyle(MemoryPrimaryButtonStyle()).disabled(!model.canAnswer || !model.answerIsComplete)
                .opacity(model.answerIsComplete ? 1 : 0.45).accessibilityIdentifier("duo-check")
                .accessibilityHidden(model.needsRecovery)
        } else {
            Button(DuoText.text(model.phase == .study ? "ready" : onReviewContinue == nil ? "next.round" : "continue.scan")) {
                if model.phase == .study { model.beginRecall() }
                else if let onReviewContinue { onReviewContinue() }
                else { model.nextRound() }
            }.buttonStyle(MemoryPrimaryButtonStyle()).disabled(!model.canPlay)
                .accessibilityIdentifier("duo-continue").accessibilityHidden(model.needsRecovery)
        }
    }

    private func launch(_ gate: Int) {
        guard model.launch(gate) else { return }
        feedback()
        animateFlight(from: frames["launcher"], to: frames["gate-\(gate)"])
    }

    private func playBeat(_ beat: DuoBeat) {
        guard model.play(beat) else { return }
        feedback(); sound(beat); litBeat = beat
        animateFlight(from: frames["drum-pads"], to: frames["drum-stage"])
    }

    private func sound(_ beat: DuoBeat) {
        tonePlayer.playChord(beat == .both ? [.low, .high] : beat == .right ? [.high] : [.low], duration: beat == .holdLeft ? 0.6 : 0.25)
    }

    private func playSequence() {
        guard model.canPlay, model.showsSolution else { return }
        playback?.cancel()
        playback = Task { @MainActor in
            for beat in model.round.beats {
                guard !Task.isCancelled, model.canPlay, model.showsSolution else { break }
                litBeat = beat; sound(beat)
                do { try await Task.sleep(for: .milliseconds(beat == .holdLeft ? 700 : 400)) } catch { break }
                litBeat = nil
                do { try await Task.sleep(for: .milliseconds(200)) } catch { break }
            }
            litBeat = nil; playback = nil
        }
    }

    private func animateFlight(from source: CGRect?, to target: CGRect?) {
        flightTask?.cancel()
        guard let source, let target else { return }
        flight = CGPoint(x: source.midX, y: source.midY)
        flightTask = Task { @MainActor in
            await Task.yield()
            guard !Task.isCancelled else { return }
            withAnimation(reduceMotion ? nil : .easeOut(duration: 0.4)) { flight = CGPoint(x: target.midX, y: target.midY) }
            do { try await Task.sleep(for: .milliseconds(500)) } catch { return }
            flight = nil; litBeat = nil
        }
    }

    private func feedback() { UIImpactFeedbackGenerator(style: .light).impactOccurred() }
    private func clearGestures() { draggedObject = nil; previousTracePoint = nil; pull = .zero }
    private func cancelTransientInput() {
        clearGestures(); playback?.cancel(); playback = nil; flightTask?.cancel(); flight = nil
        litBeat = nil; tonePlayer.stop()
    }
}

// Copyright (c) 2026 Jean-Baptiste Meyer
// SPDX-License-Identifier: MIT

import Foundation
import CoreGraphics
import Observation

enum AdaptiveGameAvailability { case folded, expanded }
enum DuoMechanic { case courier, threads, catapult, drums }

enum DuoBoardAxis: Equatable { case sideBySide, stacked }

/// Measures the playable surfaces after scan chrome and the footer have taken
/// their space. Never squeeze fixed targets into a smaller physical pane.
struct DuoBoardLayout: Equatable {
    let pose: DuoPose
    let axis: DuoBoardAxis
    let primary: CGRect
    let secondary: CGRect
    let canFit: Bool
    let nodeDiameter: CGFloat

    static func make(size: CGSize, division: CGRect?, pose: DuoPose, mechanic: DuoMechanic) -> Self {
        let axis: DuoBoardAxis = division.map { $0.width > $0.height ? .stacked : .sideBySide }
            ?? (pose == .tabletop ? .stacked : .sideBySide)
        let bounds = CGRect(origin: .zero, size: size)
        let length = axis == .sideBySide ? size.width : size.height
        let start = division.map { axis == .sideBySide ? $0.minX : $0.minY } ?? length / 2
        let end = division.map { axis == .sideBySide ? $0.maxX : $0.maxY } ?? length / 2
        let before = max(0, min(length, start - 8))
        let after = max(0, min(length, end + 8))
        let primary: CGRect
        let secondary: CGRect
        if axis == .sideBySide {
            primary = CGRect(x: 12, y: 0, width: max(0, before - 12), height: size.height)
            secondary = CGRect(x: after, y: 0, width: max(0, size.width - after - 12), height: size.height)
        } else {
            primary = CGRect(x: 12, y: 0, width: max(0, size.width - 24), height: before)
            secondary = CGRect(x: 12, y: after, width: max(0, size.width - 24), height: max(0, size.height - after))
        }
        let minimum: CGSize
        switch mechanic {
        case .courier: minimum = axis == .stacked ? CGSize(width: 260, height: 155) : CGSize(width: 160, height: 330)
        case .threads: minimum = CGSize(width: 130, height: 245)
        case .catapult: minimum = CGSize(width: 225, height: 275)
        case .drums: minimum = CGSize(width: 260, height: 250)
        }
        let fits = [primary, secondary].allSatisfy { $0.width >= minimum.width && $0.height >= minimum.height }
            && (division.map { bounds.intersects($0) } ?? true)
        let diameter = min(90, max(52, (min(primary.height, secondary.height) - 84) / 3))
        return Self(pose: pose, axis: axis, primary: primary, secondary: secondary, canFit: fits, nodeDiameter: diameter)
    }
}

enum AdaptiveDisplayMode: Equatable {
    case compact, folded, expanded

    var preferredGames: [DuoGame] {
        switch self {
        case .compact: []
        case .folded: DuoGame.foldedGames
        case .expanded: DuoGame.expandedGames
        }
    }
}

struct AdaptiveDisplayContext: Equatable {
    let mode: AdaptiveDisplayMode
    let pose: DuoPose
    let isExpanded: Bool

    static let compact = AdaptiveDisplayContext(mode: .compact, pose: .unavailable, isExpanded: false)
}

enum DuoGame: String, CaseIterable, Identifiable {
    // Partially folded: ten experiences that use two physical regions.
    case courier, threads, catapult, drums
    case mirrorMarket, constellation, signalVault, pulseRelay, colorBridge, lightPath
    // Flat Duo and iPad: roomier experiences that use the whole canvas.
    case panoramaPairs, orbitMap, soundBoard, cometField

    var id: String { rawValue }
    var title: String { DuoText.text("game.\(rawValue)") }
    var subtitle: String { DuoText.text("description.\(rawValue)") }
    var instructions: String { DuoText.text("instructions.\(rawValue)") }
    static let foldedGames: [DuoGame] = [.courier, .threads, .catapult, .drums, .mirrorMarket,
                                         .constellation, .signalVault, .pulseRelay, .colorBridge, .lightPath]
    static let expandedGames: [DuoGame] = [.panoramaPairs, .orbitMap, .soundBoard, .cometField]
    var availability: AdaptiveGameAvailability {
        Self.foldedGames.contains(self) ? .folded : .expanded
    }
    var mechanic: DuoMechanic {
        switch self {
        case .courier, .mirrorMarket, .colorBridge, .panoramaPairs: .courier
        case .threads, .constellation, .lightPath, .orbitMap: .threads
        case .catapult, .signalVault, .cometField: .catapult
        case .drums, .pulseRelay, .soundBoard: .drums
        }
    }
    var memoryCategory: MemoryCategory {
        switch self {
        case .courier, .mirrorMarket: .association
        case .threads, .signalVault, .cometField: .sequence
        case .catapult, .constellation, .orbitMap: .spatial
        case .drums, .pulseRelay, .soundBoard: .sound
        case .colorBridge, .lightPath, .panoramaPairs: .visual
        }
    }
    var icon: String {
        switch self {
        case .courier: "tray.and.arrow.down.fill"
        case .threads: "point.3.connected.trianglepath.dotted"
        case .catapult: "paperplane.fill"
        case .drums: "hand.tap.fill"
        case .mirrorMarket: "square.split.2x1.fill"
        case .constellation: "sparkles"
        case .signalVault: "antenna.radiowaves.left.and.right"
        case .pulseRelay: "waveform.path"
        case .colorBridge: "paintpalette.fill"
        case .lightPath: "flashlight.on.fill"
        case .panoramaPairs: "rectangle.split.3x1.fill"
        case .orbitMap: "circle.hexagongrid.fill"
        case .soundBoard: "waveform.badge.mic"
        case .cometField: "circle.grid.cross.fill"
        }
    }
}

enum DuoPose: String, CaseIterable {
    case unavailable, closed, flat, book, tabletop
    var title: String { DuoText.text("pose.\(rawValue)") }
}

enum DuoHingeState { case unknown, absent, closed, open, partial }

enum DuoPoseResolver {
    /// Use the actual division region, not the overall window's aspect ratio.
    /// A narrow multitasking window may not contain both sides of the fold.
    static func resolve(hinge: DuoHingeState, division: CGRect?, viewport: CGSize) -> DuoPose {
        if hinge == .absent { return .unavailable }
        if hinge == .closed { return .closed }
        if hinge == .open { return .flat }
        guard let fold = division, viewport.width > 0, viewport.height > 0 else {
            return hinge == .unknown ? .unavailable : .flat
        }
        let bounds = CGRect(origin: .zero, size: viewport)
        guard bounds.intersects(fold) else { return .unavailable }
        if fold.width > fold.height {
            guard fold.minY >= 130, viewport.height - fold.maxY >= 130,
                  fold.width >= viewport.width * 0.7 else { return .unavailable }
            return .tabletop
        }
        guard fold.minX >= 130, viewport.width - fold.maxX >= 130,
              fold.height >= viewport.height * 0.7 else { return .unavailable }
        return .book
    }
}

enum DuoBeat: String, CaseIterable {
    case left, both, right, holdLeft
    var label: String { DuoText.text("beat.\(rawValue)") }
    var symbol: String {
        switch self { case .left: "L"; case .right: "R"; case .both: "L + R"; case .holdLeft: "L —" }
    }
}

struct DuoObject: Equatable, Identifiable {
    let id: Int
    let symbol: String
    let nameKey: String
    var name: String { DuoText.text(nameKey) }
    static let pool: [DuoObject] = [
        .init(id: 0, symbol: "🍋", nameKey: "object.lemon"),
        .init(id: 1, symbol: "🦋", nameKey: "object.butterfly"),
        .init(id: 2, symbol: "🎸", nameKey: "object.guitar"),
        .init(id: 3, symbol: "🚀", nameKey: "object.rocket"),
        .init(id: 4, symbol: "🌵", nameKey: "object.cactus"),
        .init(id: 5, symbol: "🎈", nameKey: "object.balloon")
    ]
}

struct DuoRound: Equatable {
    let id: UUID
    let objects: [DuoObject]
    /// Each object index maps to one pocket index.
    let homes: [Int]
    /// Even nodes are on the left page; odd nodes are on the right.
    let route: [Int]
    let gates: [Int]
    let beats: [DuoBeat]

    static func make(avoiding previous: DuoRound? = nil) -> DuoRound {
        var candidate = random()
        // Every replay has fresh content for every game, not just a new UUID.
        for _ in 0..<100 {
            guard let previous,
                  (candidate.objects == previous.objects && candidate.homes == previous.homes)
                    || candidate.route == previous.route || candidate.gates == previous.gates
                    || candidate.beats == previous.beats else { break }
            candidate = random()
        }
        return candidate
    }

    private static func random() -> DuoRound {
        let left = [0, 2, 4].shuffled(), right = [1, 3, 5].shuffled()
        let route = zip(left, right).flatMap { [$0, $1] }
        return .init(id: UUID(), objects: Array(DuoObject.pool.shuffled().prefix(3)),
                     homes: [0, 1, 2].shuffled(), route: route,
                     gates: [0, 1, 2].shuffled(), beats: DuoBeat.allCases.shuffled())
    }

    #if DEBUG
    static let fixture = DuoRound(id: UUID(), objects: Array(DuoObject.pool.prefix(3)),
                                 homes: [1, 0, 2], route: [0, 3, 2, 5, 4, 1],
                                 gates: [2, 0, 1], beats: [.left, .both, .right, .holdLeft])
    #endif
}

struct DuoRoundScore: Equatable {
    let correct: Int
    let total: Int
    var isPerfect: Bool { correct == total }
}

enum DuoGestureRules {
    /// A directional flick snaps to a large gate. Motor precision is not scored.
    static func launchGate(translation: CGSize) -> Int? {
        guard translation.height <= -18 else { return nil }
        let slope = translation.width / abs(translation.height)
        return slope < -0.35 ? 0 : slope > 0.35 ? 2 : 1
    }

    /// Include nodes crossed between samples so a quick stroke cannot skip a node.
    static func crossedNodes(from start: CGPoint, to end: CGPoint, centers: [Int: CGPoint], radius: CGFloat) -> [Int] {
        let dx = end.x - start.x, dy = end.y - start.y
        let lengthSquared = dx * dx + dy * dy
        return centers.compactMap { key, center -> (Int, CGFloat)? in
            let t = lengthSquared > 0 ? max(0, min(1, ((center.x - start.x) * dx + (center.y - start.y) * dy) / lengthSquared)) : 0
            let distance = hypot(center.x - (start.x + t * dx), center.y - (start.y + t * dy))
            return distance <= radius ? (key, t) : nil
        }.sorted { $0.1 < $1.1 }.map(\.0)
    }
}

/// Independently tracks each contact so a chord is emitted once, after both
/// fingers lift. A cancelled gesture never contributes a partial answer.
struct DuoDrumTouchState<TouchID: Hashable> {
    private struct Contact { let side: Int; let started: TimeInterval }
    private var contacts: [TouchID: Contact] = [:]
    private var isChord = false
    var activeSides: Set<Int> { Set(contacts.values.map(\.side)) }

    mutating func begin(_ id: TouchID, side: Int, at time: TimeInterval) {
        guard (0...1).contains(side), !activeSides.contains(side) else { return }
        contacts[id] = Contact(side: side, started: time)
        if activeSides.count == 2 { isChord = true }
    }

    mutating func end(_ id: TouchID, at time: TimeInterval) -> DuoBeat? {
        guard let contact = contacts.removeValue(forKey: id) else { return nil }
        if isChord {
            guard contacts.isEmpty else { return nil }
            isChord = false
            return .both
        }
        return contact.side == 1 ? .right : time - contact.started >= 0.5 ? .holdLeft : .left
    }

    mutating func cancel() { contacts.removeAll(); isChord = false }
}

@MainActor @Observable
final class DuoArcadeModel {
    enum Phase { case study, recall, review }
    private(set) var game: DuoGame = .courier
    private(set) var round = DuoRound.make()
    private(set) var phase: Phase = .study
    private(set) var isInGame = false
    private(set) var pose: DuoPose = .unavailable
    private(set) var isExpandedLayout = false
    private(set) var isSceneActive = true
    private(set) var roundNumber = 1
    private(set) var deliveries: [Int: Int] = [:]
    private(set) var tracedNodes: [Int] = []
    private(set) var launchedGates: [Int] = []
    private(set) var playedBeats: [DuoBeat] = []
    private(set) var score: DuoRoundScore?
    private(set) var selectedObject: Int?
    private(set) var layoutAxis: DuoBoardAxis = .sideBySide
    private(set) var layoutCanFit = true
    private(set) var requiresResume = false
    private(set) var isRepositioning = false
    private(set) var memorizedAxis: DuoBoardAxis = .sideBySide
    private(set) var memorizedPose: DuoPose = .book

    var hasUsableDisplay: Bool {
        pose == .book || pose == .tabletop || pose == .flat || (isExpandedLayout && pose == .unavailable)
    }
    var surfaceIsCompatible: Bool {
        hasUsableDisplay && layoutCanFit
            && (phase != .recall || game.mechanic == .courier || layoutAxis == memorizedAxis)
    }
    var needsRecovery: Bool {
        isInGame && (requiresResume || !hasUsableDisplay || !isSceneActive
                     || (!isRepositioning && !surfaceIsCompatible))
    }
    var canResume: Bool { isInGame && surfaceIsCompatible && isSceneActive && requiresResume && !isRepositioning }

    var canPlay: Bool {
        isInGame && isSceneActive && surfaceIsCompatible && !requiresResume && !isRepositioning
    }
    var canAnswer: Bool { canPlay && phase == .recall }
    var showsSolution: Bool { phase != .recall }
    var answerCount: Int {
        switch game.mechanic {
        case .courier: deliveries.count
        case .threads: tracedNodes.count
        case .catapult: launchedGates.count
        case .drums: playedBeats.count
        }
    }
    var answerTotal: Int {
        switch game.mechanic {
        case .courier: round.objects.count
        case .threads: round.route.count
        case .catapult: round.gates.count
        case .drums: round.beats.count
        }
    }
    var answerIsComplete: Bool { answerCount == answerTotal }

    func updateContext(pose: DuoPose, isExpanded: Bool = false, isSceneActive: Bool) {
        if self.pose != pose { layoutAxis = pose == .tabletop ? .stacked : .sideBySide }
        self.pose = pose
        isExpandedLayout = isExpanded
        self.isSceneActive = isSceneActive
        pauseIfNeeded()
    }

    func updateLayout(axis: DuoBoardAxis, canFit: Bool) {
        layoutAxis = axis
        layoutCanFit = canFit
        // SwiftUI briefly proposes a zero-sized board during transitions.
        // Only a settled measurement should interrupt a playable round.
        let rearrangesRecall = canFit && phase == .recall && game.mechanic != .courier && axis != memorizedAxis
        if !isRepositioning || rearrangesRecall { pauseIfNeeded() }
    }

    func resume() {
        guard canResume else { return }
        requiresResume = false
    }

    func beginRepositioning() { isRepositioning = true; selectedObject = nil }
    func finishRepositioning() { isRepositioning = false; pauseIfNeeded() }

    private func pauseIfNeeded() {
        // A compatible surface returning never silently restarts input/audio.
        if isInGame && (!surfaceIsCompatible || !isSceneActive) { requiresResume = true; selectedObject = nil }
    }

    func start(_ game: DuoGame, round: DuoRound? = nil) {
        self.game = game
        isInGame = true
        requiresResume = false
        roundNumber = 1
        reset(round: round ?? .make(avoiding: self.round))
        pauseIfNeeded()
    }

    func returnToLobby() { isInGame = false }

    func beginRecall() {
        guard canPlay, phase == .study else { return }
        memorizedAxis = layoutAxis
        memorizedPose = pose == .tabletop ? .tabletop : isExpandedLayout ? .flat : .book
        phase = .recall
    }

    func nextRound() {
        guard canPlay, phase == .review else { return }
        roundNumber += 1
        reset(round: .make(avoiding: round))
    }

    func selectObject(_ index: Int) {
        guard canAnswer, game.mechanic == .courier, round.objects.indices.contains(index) else { return }
        selectedObject = index
    }

    @discardableResult
    func deliver(_ object: Int, to pocket: Int) -> Bool {
        guard canAnswer, game.mechanic == .courier, round.objects.indices.contains(object), (0..<3).contains(pocket) else { return false }
        // Moving to an occupied pocket swaps the two objects, so every mistake
        // remains editable before submitting the round.
        if let occupant = deliveries.first(where: { $0.value == pocket && $0.key != object })?.key {
            if let oldPocket = deliveries[object] { deliveries[occupant] = oldPocket }
            else { deliveries.removeValue(forKey: occupant) }
        }
        deliveries[object] = pocket
        selectedObject = nil
        return true
    }

    @discardableResult
    func trace(_ node: Int) -> Bool {
        guard canAnswer, game.mechanic == .threads, (0..<6).contains(node), tracedNodes.count < round.route.count,
              tracedNodes.last != node else { return false }
        tracedNodes.append(node)
        return true
    }

    @discardableResult
    func launch(_ gate: Int) -> Bool {
        guard canAnswer, game.mechanic == .catapult, (0..<3).contains(gate), launchedGates.count < round.gates.count else { return false }
        launchedGates.append(gate)
        return true
    }

    @discardableResult
    func play(_ beat: DuoBeat) -> Bool {
        guard canAnswer, game.mechanic == .drums, playedBeats.count < round.beats.count else { return false }
        playedBeats.append(beat)
        return true
    }

    func undo() {
        guard canAnswer else { return }
        switch game.mechanic {
        case .courier: deliveries = [:]; selectedObject = nil
        case .threads: if !tracedNodes.isEmpty { tracedNodes.removeLast() }
        case .catapult: if !launchedGates.isEmpty { launchedGates.removeLast() }
        case .drums: if !playedBeats.isEmpty { playedBeats.removeLast() }
        }
    }

    func submit() {
        guard canAnswer, answerIsComplete else { return }
        let correct: Int
        switch game.mechanic {
        case .courier: correct = round.homes.indices.filter { deliveries[$0] == round.homes[$0] }.count
        case .threads: correct = zip(tracedNodes, round.route).filter { $0 == $1 }.count
        case .catapult: correct = zip(launchedGates, round.gates).filter { $0 == $1 }.count
        case .drums: correct = zip(playedBeats, round.beats).filter { $0 == $1 }.count
        }
        score = .init(correct: correct, total: answerTotal)
        phase = .review
    }

    private func reset(round: DuoRound) {
        self.round = round
        phase = .study
        deliveries = [:]; tracedNodes = []; launchedGates = []; playedBeats = []
        score = nil; selectedObject = nil
    }
}

enum DuoText {
    static func text(_ key: String) -> String {
        let fallback = Bundle.main.path(forResource: "en", ofType: "lproj")
            .flatMap(Bundle.init(path:))?.localizedString(forKey: key, value: key, table: "DuoArcade") ?? key
        return Bundle.main.localizedString(forKey: key, value: fallback, table: "DuoArcade")
    }
    static func format(_ key: String, _ arguments: CVarArg...) -> String {
        String(format: text(key), locale: Locale.current, arguments: arguments)
    }
}

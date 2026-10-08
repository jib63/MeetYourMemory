// Copyright (c) 2026 Jean-Baptiste Meyer
// SPDX-License-Identifier: MIT

import CoreGraphics
import Testing
@testable import Meet_Your_Memory

@MainActor
struct DuoArcadeTests {
    @Test("The adaptive catalog contains ten folded and four expanded games")
    func adaptiveCatalog() {
        #expect(DuoGame.foldedGames.count == 10)
        #expect(DuoGame.expandedGames.count == 4)
        #expect(Set(DuoGame.foldedGames).isDisjoint(with: Set(DuoGame.expandedGames)))
        #expect(Set(DuoGame.foldedGames + DuoGame.expandedGames) == Set(DuoGame.allCases))
    }

    @Test("The scan changes only its next pick and prefers games for the current screen")
    func transparentScanSelection() {
        let game = MemoryGame()
        game.updateAdaptiveContext(.compact)
        game.startQuickScan()
        #expect(game.currentAdaptiveGame == nil)

        game.updateAdaptiveContext(.init(mode: .expanded, pose: .flat, isExpanded: true))
        game.advanceAfterCurrentStep()
        #expect(game.currentAdaptiveGame.map(DuoGame.expandedGames.contains) == true)

        game.updateAdaptiveContext(.init(mode: .folded, pose: .book, isExpanded: false))
        game.completeAdaptiveStep(.init(correct: 3, total: 3))
        #expect(game.currentAdaptiveGame.map(DuoGame.foldedGames.contains) == true)

        game.completeAdaptiveStep(.init(correct: 3, total: 3))
        #expect(game.currentAdaptiveGame == nil)
    }

    @Test("Spatial recall pauses on rearrangement and resumes with hidden answers intact")
    func activeRoundSurvivesPostureChanges() {
        let model = DuoArcadeModel()
        model.updateContext(pose: .book, isSceneActive: true)
        model.start(.threads, round: .fixture)
        model.beginRecall()
        #expect(model.trace(0))
        model.updateContext(pose: .flat, isExpanded: true, isSceneActive: true)
        #expect(model.canPlay) // The same two columns still fit.
        for pose in [DuoPose.tabletop, .closed, .unavailable] {
            model.updateContext(pose: pose, isExpanded: pose == .flat, isSceneActive: true)
            #expect(!model.canPlay)
            #expect(!model.trace(3))
            #expect(model.answerCount == 1)
            #expect(!model.showsSolution)
        }
        model.updateContext(pose: .book, isSceneActive: true)
        #expect(model.canResume && !model.canAnswer)
        model.resume()
        #expect(model.canAnswer && model.tracedNodes == [0])
    }

    private func ready(_ game: DuoGame) -> DuoArcadeModel {
        let model = DuoArcadeModel()
        let pose: DuoPose = game.availability == .folded ? .book : .flat
        model.updateContext(pose: pose, isExpanded: game.availability == .expanded, isSceneActive: true)
        model.start(game, round: .fixture)
        model.beginRecall()
        return model
    }

    @Test("Every adaptive game scores only after complete recall", arguments: DuoGame.allCases)
    func scoring(game: DuoGame) {
        let model = ready(game)
        model.submit()
        #expect(model.score == nil)
        #expect(!model.showsSolution)
        switch game.mechanic {
        case .courier: for (object, pocket) in model.round.homes.enumerated() { model.deliver(object, to: pocket) }
        case .threads: model.round.route.forEach { model.trace($0) }
        case .catapult: model.round.gates.forEach { model.launch($0) }
        case .drums: model.round.beats.forEach { model.play($0) }
        }
        #expect(model.score == nil)
        model.submit()
        #expect(model.score == .init(correct: model.answerTotal, total: model.answerTotal))
        #expect(model.phase == .review)
        let oldRound = model.round
        model.nextRound()
        #expect(model.roundNumber == 2)
        #expect(model.round.id != oldRound.id)
        #expect(model.answerCount == 0)
        #expect(model.phase == .study)
    }

    @Test("Posture and app interruptions preserve hidden recall", arguments: DuoGame.allCases)
    func interruption(game: DuoGame) {
        let model = ready(game)
        func input() {
            switch game.mechanic {
            case .courier: model.deliver(0, to: 1)
            case .threads: model.trace(0)
            case .catapult: model.launch(2)
            case .drums: model.play(.left)
            }
        }
        input()
        let round = model.round
        let unavailablePoses: [DuoPose] = [.unavailable, .closed]
        for pose in unavailablePoses {
            model.updateContext(pose: pose, isExpanded: false, isSceneActive: true)
            input(); model.beginRecall(); model.submit(); model.nextRound(); model.undo()
            #expect(model.answerCount == 1)
            #expect(model.round == round)
            #expect(model.phase == .recall)
            #expect(!model.showsSolution)
            #expect(!model.canPlay)
        }
        let activePose: DuoPose = game.availability == .folded ? .book : .flat
        model.updateContext(pose: activePose, isExpanded: game.availability == .expanded, isSceneActive: false)
        input()
        #expect(model.answerCount == 1)
        #expect(!model.canAnswer)
        model.updateContext(pose: activePose, isExpanded: game.availability == .expanded, isSceneActive: true)
        #expect(model.canResume && !model.canAnswer)
        model.resume()
        #expect(model.canAnswer)
        #expect(model.answerCount == 1)
    }

    @Test("A round cannot accept input during study or after checking")
    func phaseGating() {
        let model = DuoArcadeModel()
        model.updateContext(pose: .tabletop, isSceneActive: true)
        model.start(.drums, round: .fixture)
        #expect(!model.play(.left))
        model.beginRecall()
        model.round.beats.forEach { model.play($0) }
        #expect(!model.play(.left))
        model.submit()
        let result = model.score
        model.undo(); model.play(.right); model.submit()
        #expect(model.score == result)
        #expect(model.answerCount == 4)
    }

    @Test("Courier swaps occupied pockets and rejects invalid inputs")
    func courierCorrections() {
        let model = ready(.courier)
        #expect(!model.deliver(-1, to: 0))
        #expect(!model.deliver(0, to: 3))
        model.deliver(0, to: 0); model.deliver(1, to: 1)
        model.deliver(0, to: 1)
        #expect(model.deliveries == [0: 1, 1: 0])
        model.deliver(2, to: 0)
        #expect(model.deliveries == [0: 1, 2: 0])
        model.undo()
        #expect(model.deliveries.isEmpty)
    }

    @Test("Route sampling ignores repeated hits and allows undo")
    func threadCorrections() {
        let model = ready(.threads)
        #expect(model.trace(0))
        #expect(!model.trace(0))
        #expect(!model.trace(6))
        #expect(model.trace(3))
        model.undo()
        #expect(model.tracedNodes == [0])
        #expect(!model.launch(1))
        #expect(!model.play(.left))
    }

    @Test("Order matters, independently of tapping or gesture precision")
    func wrongOrder() {
        let model = ready(.catapult)
        [0, 2, 1].forEach { model.launch($0) }
        model.submit()
        #expect(model.score == .init(correct: 1, total: 3))
    }

    @Test("Fresh rounds retain balanced cross-fold challenges")
    func generation() {
        var previous = DuoRound.fixture
        for _ in 0..<80 {
            let round = DuoRound.make(avoiding: previous)
            #expect(Set(round.objects.map(\.id)).count == 3)
            #expect(Set(round.homes) == Set(0..<3))
            #expect(Set(round.gates) == Set(0..<3))
            #expect(Set(round.route) == Set(0..<6))
            #expect(round.route.enumerated().allSatisfy { $0.offset % 2 == $0.element % 2 })
            #expect(Set(round.beats) == Set(DuoBeat.allCases))
            #expect(round.route != previous.route && round.gates != previous.gates && round.beats != previous.beats)
            previous = round
        }
    }

    @Test("Pose comes from the fold, not the window shape")
    func poses() {
        let size = CGSize(width: 800, height: 900)
        let book = CGRect(x: 390, y: 0, width: 20, height: 900)
        let table = CGRect(x: 0, y: 440, width: 800, height: 20)
        #expect(DuoPoseResolver.resolve(hinge: .partial, division: book, viewport: size) == .book)
        #expect(DuoPoseResolver.resolve(hinge: .partial, division: table, viewport: size) == .tabletop)
        #expect(DuoPoseResolver.resolve(hinge: .open, division: book, viewport: size) == .flat)
        #expect(DuoPoseResolver.resolve(hinge: .closed, division: book, viewport: size) == .closed)
        #expect(DuoPoseResolver.resolve(hinge: .absent, division: book, viewport: size) == .unavailable)
        #expect(DuoPoseResolver.resolve(hinge: .partial, division: CGRect(x: 20, y: 0, width: 20, height: 900), viewport: size) == .unavailable)
        #expect(DuoPoseResolver.resolve(hinge: .unknown, division: nil, viewport: size) == .unavailable)
    }

    @Test("An active matching round can reflow across inner display configurations")
    func expandedAvailability() {
        let model = DuoArcadeModel()
        model.updateContext(pose: .flat, isExpanded: true, isSceneActive: true)
        model.start(.panoramaPairs, round: .fixture)
        model.beginRecall()
        model.deliver(0, to: 1)
        #expect(model.canPlay)
        model.updateContext(pose: .book, isExpanded: false, isSceneActive: true)
        #expect(model.canPlay)
        model.updateContext(pose: .tabletop, isSceneActive: true)
        #expect(model.canPlay && model.deliveries == [0: 1])
        model.updateContext(pose: .unavailable, isExpanded: true, isSceneActive: true)
        #expect(model.canPlay)
    }

    @Test("Insufficient board space and settling gestures never accept hidden input")
    func layoutRecovery() {
        let model = ready(.threads)
        model.trace(0)
        model.updateLayout(axis: .sideBySide, canFit: false)
        #expect(model.needsRecovery && !model.canResume)
        model.updateLayout(axis: .sideBySide, canFit: true)
        model.beginRepositioning()
        #expect(!model.canResume && !model.trace(3))
        model.finishRepositioning()
        model.resume()
        #expect(model.tracedNodes == [0] && model.canAnswer)
        model.beginRepositioning()
        model.updateLayout(axis: .stacked, canFit: true)
        #expect(model.needsRecovery && model.requiresResume && !model.showsSolution)
    }

    @Test("Transient zero-sized proposals do not pause a new round")
    func initialMeasurementSettles() {
        let model = DuoArcadeModel()
        model.updateContext(pose: .book, isSceneActive: true)
        model.start(.courier, round: .fixture)
        model.beginRepositioning()
        model.updateLayout(axis: .sideBySide, canFit: false)
        #expect(!model.canPlay && !model.requiresResume)
        model.updateLayout(axis: .sideBySide, canFit: true)
        model.finishRepositioning()
        #expect(model.canPlay && !model.needsRecovery)
        model.beginRepositioning()
        model.updateLayout(axis: .sideBySide, canFit: false)
        model.finishRepositioning()
        #expect(model.needsRecovery && model.requiresResume)
    }

    @Test("Study can adapt before recall locks the learned arrangement")
    func studyAdaptation() {
        let model = DuoArcadeModel()
        model.updateContext(pose: .book, isSceneActive: true)
        model.start(.threads, round: .fixture)
        model.updateContext(pose: .tabletop, isSceneActive: true)
        #expect(model.canPlay)
        model.beginRecall()
        model.updateContext(pose: .book, isSceneActive: true)
        #expect(!model.canPlay && !model.canResume && !model.showsSolution)
        model.updateContext(pose: .tabletop, isSceneActive: true)
        model.resume()
        #expect(model.canAnswer)
    }

    @Test("Replacement keeps the scan slot and excludes interrupted adaptive points")
    func replacementAccounting() {
        let scan = MemoryGame()
        scan.startAdaptiveUITest(.constellation)
        let slot = scan.currentIndex
        scan.updateAdaptiveContext(.compact)
        scan.replaceAdaptiveStep(for: .constellation)
        #expect(scan.currentIndex == slot)
        #expect(scan.currentAdaptiveGame == nil && scan.currentStep.category == .spatial)
        #expect(scan.correctScores.isEmpty && scan.possibleScores == [.spatial: 1])
        let replacement = scan.currentStep
        scan.replaceAdaptiveStep(for: .constellation)
        scan.completeAdaptiveStep(.init(correct: 6, total: 6), for: .constellation)
        #expect(scan.currentStep == replacement && scan.currentIndex == slot)

        scan.startAdaptiveUITest(.constellation)
        scan.updateAdaptiveContext(.init(mode: .expanded, pose: .flat, isExpanded: true))
        scan.replaceAdaptiveStep(for: .constellation)
        #expect(scan.currentIndex == 0 && scan.currentAdaptiveGame == nil && scan.currentStep.category == .spatial)
        #expect(scan.possibleScores == [.spatial: 1] && scan.correctScores.isEmpty)
    }

    @Test("Directional and rhythm games protect their learned arrangement", arguments: [DuoGame.catapult, .drums, .cometField, .soundBoard])
    func directionalRecovery(game: DuoGame) {
        let model = ready(game)
        model.updateContext(pose: .tabletop, isSceneActive: true)
        #expect(!model.canAnswer && !model.canResume)
        #expect(!model.launch(0) && !model.play(.left))
        #expect(!model.showsSolution && model.answerCount == 0)
        model.updateContext(pose: .flat, isExpanded: true, isSceneActive: true)
        model.resume()
        #expect(model.canAnswer)
    }

    @Test("Board measurement respects the actual fold and rejects crowded surfaces")
    func boardMeasurements() {
        let size = CGSize(width: 760, height: 660)
        let book = DuoBoardLayout.make(size: size, division: CGRect(x: 360, y: 0, width: 32, height: 660), pose: .book, mechanic: .threads)
        #expect(book.canFit && book.axis == .sideBySide)
        #expect(book.primary.maxX < 360 && book.secondary.minX > 392)
        let table = DuoBoardLayout.make(size: size, division: CGRect(x: 0, y: 290, width: 760, height: 26), pose: .tabletop, mechanic: .courier)
        #expect(table.canFit && table.axis == .stacked)
        #expect(table.primary.maxY < 290 && table.secondary.minY > 316)
        let crowded = DuoBoardLayout.make(size: CGSize(width: 350, height: 360), division: nil, pose: .tabletop, mechanic: .threads)
        #expect(!crowded.canFit)
        let outside = DuoBoardLayout.make(size: size, division: CGRect(x: 0, y: 680, width: 760, height: 30), pose: .tabletop, mechanic: .courier)
        #expect(!outside.canFit)
    }

    @Test("Flicks need upward intent and snap to generous gates")
    func flicks() {
        #expect(DuoGestureRules.launchGate(translation: CGSize(width: 90, height: -100)) == 2)
        #expect(DuoGestureRules.launchGate(translation: CGSize(width: -90, height: -100)) == 0)
        #expect(DuoGestureRules.launchGate(translation: CGSize(width: 20, height: -100)) == 1)
        #expect(DuoGestureRules.launchGate(translation: CGSize(width: 20, height: 100)) == nil)
        #expect(DuoGestureRules.launchGate(translation: CGSize(width: 0, height: -10)) == nil)
    }

    @Test("A fast stroke visits crossed nodes in spatial order")
    func fastTrace() {
        let nodes = [4: CGPoint(x: 40, y: 5), 1: CGPoint(x: 80, y: 0), 0: CGPoint(x: 30, y: 60)]
        #expect(DuoGestureRules.crossedNodes(from: .zero, to: CGPoint(x: 100, y: 0), centers: nodes, radius: 10) == [4, 1])
        #expect(DuoGestureRules.crossedNodes(from: CGPoint(x: 100, y: 0), to: .zero, centers: nodes, radius: 10) == [1, 4])
    }

    @Test("Drum taps, holds and chords retain independent finger timing")
    func drumTouches() {
        var state = DuoDrumTouchState<Int>()
        state.begin(1, side: 0, at: 0)
        #expect(state.end(1, at: 0.2) == .left)
        state.begin(1, side: 0, at: 1)
        #expect(state.end(1, at: 1.5) == .holdLeft)
        state.begin(1, side: 1, at: 2)
        #expect(state.end(1, at: 3) == .right)
        state.begin(1, side: 0, at: 4)
        state.begin(2, side: 1, at: 4.05)
        #expect(state.activeSides == [0, 1])
        #expect(state.end(2, at: 4.2) == nil)
        #expect(state.end(1, at: 4.8) == .both)
        #expect(state.end(1, at: 5) == nil)
    }

    @Test("Cancelled and duplicate drum contacts never submit phantom beats")
    func cancelledDrumTouches() {
        var state = DuoDrumTouchState<Int>()
        state.begin(1, side: 0, at: 0)
        state.begin(2, side: 0, at: 0.1)
        #expect(state.end(2, at: 0.2) == nil)
        state.begin(3, side: 1, at: 0.3)
        state.cancel()
        #expect(state.activeSides.isEmpty)
        #expect(state.end(1, at: 1) == nil)
        #expect(state.end(3, at: 1) == nil)
        state.begin(4, side: 0, at: 2)
        #expect(state.end(4, at: 2.2) == .left)
    }
}

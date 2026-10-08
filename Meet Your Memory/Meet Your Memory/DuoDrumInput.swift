// Copyright (c) 2026 Jean-Baptiste Meyer
// SPDX-License-Identifier: MIT

import SwiftUI
import UIKit

/// A small UIKit surface preserves independent touches for chords; SwiftUI's
/// single DragGesture cannot distinguish two fingers on the two drum pads.
struct DuoDrumInput: UIViewRepresentable {
    var isEnabled: Bool
    var onBeat: (DuoBeat) -> Void

    func makeUIView(context: Context) -> DuoDrumTouchView { DuoDrumTouchView() }
    func updateUIView(_ view: DuoDrumTouchView, context: Context) {
        view.onBeat = onBeat
        view.acceptsInput = isEnabled
    }
    static func dismantleUIView(_ view: DuoDrumTouchView, coordinator: ()) { view.cancelTouches() }
}

@MainActor
final class DuoDrumTouchView: UIView {
    var onBeat: (DuoBeat) -> Void = { _ in }
    var acceptsInput = false {
        didSet { if !acceptsInput { cancelTouches() } }
    }
    private var touchesState = DuoDrumTouchState<ObjectIdentifier>()
    private var previousSize = CGSize.zero
    private let labels = [UILabel(), UILabel()]

    override init(frame: CGRect) {
        super.init(frame: frame)
        isMultipleTouchEnabled = true
        // Equivalent, labeled SwiftUI buttons below handle VoiceOver and
        // keyboard/Switch Control without requiring timed or multi-touch input.
        accessibilityElementsHidden = true
        for (index, label) in labels.enumerated() {
            label.text = index == 0 ? "L" : "R"
            label.font = .systemFont(ofSize: 28, weight: .heavy)
            label.textAlignment = .center
            label.layer.cornerRadius = 24
            label.clipsToBounds = true
            addSubview(label)
        }
        updateColors()
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    override func layoutSubviews() {
        super.layoutSubviews()
        if previousSize != bounds.size { cancelTouches(); previousSize = bounds.size }
        let gap: CGFloat = 16
        let width = max(0, (bounds.width - gap) / 2)
        labels[0].frame = CGRect(x: 0, y: 0, width: width, height: bounds.height)
        labels[1].frame = CGRect(x: width + gap, y: 0, width: width, height: bounds.height)
    }

    override func touchesBegan(_ touches: Set<UITouch>, with event: UIEvent?) {
        guard acceptsInput else { return }
        for touch in touches {
            guard let side = labels.firstIndex(where: { $0.frame.contains(touch.location(in: self)) }) else { continue }
            touchesState.begin(ObjectIdentifier(touch), side: side, at: touch.timestamp)
        }
        updateColors()
    }

    override func touchesEnded(_ touches: Set<UITouch>, with event: UIEvent?) {
        guard acceptsInput else { cancelTouches(); return }
        var completed: [DuoBeat] = []
        for touch in touches {
            if let beat = touchesState.end(ObjectIdentifier(touch), at: touch.timestamp) { completed.append(beat) }
        }
        updateColors()
        for beat in completed { onBeat(beat) }
    }

    override func touchesCancelled(_ touches: Set<UITouch>, with event: UIEvent?) { cancelTouches() }

    func cancelTouches() {
        touchesState.cancel()
        updateColors()
    }

    private func updateColors() {
        let active = touchesState.activeSides
        for (index, label) in labels.enumerated() {
            label.backgroundColor = active.contains(index) ? UIColor(MemoryTheme.aqua) : UIColor(MemoryTheme.violet.opacity(0.35))
            label.textColor = active.contains(index) ? UIColor(MemoryTheme.ink) : .white
        }
    }
}

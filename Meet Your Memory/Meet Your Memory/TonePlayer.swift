// Copyright (c) 2026 Jean-Baptiste Meyer
// SPDX-License-Identifier: MIT

import AVFoundation

@MainActor
final class TonePlayer {
    private let engine = AVAudioEngine()
    private let player = AVAudioPlayerNode()
    private let sampleRate = 44_100.0

    init() {
        engine.attach(player)
        let format = AVAudioFormat(standardFormatWithSampleRate: sampleRate, channels: 1)!
        engine.connect(player, to: engine.mainMixerNode, format: format)
        try? AVAudioSession.sharedInstance().setCategory(.ambient, mode: .default)
        try? engine.start()
    }

    func play(_ tones: [MemoryTone]) {
        player.stop()
        if !engine.isRunning { try? engine.start() }

        for tone in tones {
            if let buffer = makeBuffer(frequency: tone.frequency) {
                player.scheduleBuffer(buffer)
            }
        }
        player.play()
    }

    private func makeBuffer(frequency: Double) -> AVAudioPCMBuffer? {
        let toneDuration = 0.34
        let silenceDuration = 0.12
        let frameCount = AVAudioFrameCount((toneDuration + silenceDuration) * sampleRate)
        guard
            let format = AVAudioFormat(standardFormatWithSampleRate: sampleRate, channels: 1),
            let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: frameCount),
            let samples = buffer.floatChannelData?[0]
        else { return nil }

        buffer.frameLength = frameCount
        let audibleFrames = Int(toneDuration * sampleRate)
        let fadeFrames = Int(0.025 * sampleRate)

        for frame in 0..<Int(frameCount) {
            guard frame < audibleFrames else {
                samples[frame] = 0
                continue
            }

            let fadeIn = min(1, Double(frame) / Double(max(fadeFrames, 1)))
            let fadeOut = min(1, Double(audibleFrames - frame) / Double(max(fadeFrames, 1)))
            let envelope = Float(min(fadeIn, fadeOut))
            let phase = 2 * Double.pi * frequency * Double(frame) / sampleRate
            samples[frame] = sin(Float(phase)) * 0.22 * envelope
        }

        return buffer
    }
}

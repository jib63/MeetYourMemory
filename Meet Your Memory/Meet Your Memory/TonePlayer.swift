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
            if let buffer = makeBuffer(frequencies: [tone.frequency]) {
                player.scheduleBuffer(buffer)
            }
        }
        player.play()
    }

    func playChord(_ tones: [MemoryTone], duration: TimeInterval = 0.34) {
        guard !tones.isEmpty else { return }
        player.stop()
        if !engine.isRunning { try? engine.start() }
        if let buffer = makeBuffer(frequencies: tones.map(\.frequency), toneDuration: duration) {
            player.scheduleBuffer(buffer)
            player.play()
        }
    }

    func stop() { player.stop() }

    private func makeBuffer(frequencies: [Double], toneDuration: TimeInterval = 0.34) -> AVAudioPCMBuffer? {
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
            let wave = frequencies.reduce(Float.zero) { result, frequency in
                result + sin(Float(2 * Double.pi * frequency * Double(frame) / sampleRate))
            } / Float(frequencies.count)
            samples[frame] = wave * 0.22 * envelope
        }

        return buffer
    }
}

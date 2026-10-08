#!/usr/bin/env swift
// Localized creative artwork typography. Native shaping and font fallback cover
// CJK, Thai and Devanagari; the existing screenshot renderer stays unchanged.
import AppKit
import Foundation

var args: [String: String] = [:]
let values = Array(CommandLine.arguments.dropFirst())
for index in stride(from: 0, to: values.count - 1, by: 2) {
    args[values[index]] = values[index + 1]
}
guard let text = args["--text"], let output = args["--output"],
      let width = Double(args["--width"] ?? ""),
      let height = Double(args["--height"] ?? ""), width > 24, height > 24 else {
    fputs("Missing text/output or invalid pixel canvas\n", stderr); exit(2)
}
let lines = text.components(separatedBy: "\n")
let maximum = Double(args["--font-size"] ?? "112") ?? 112
let requestedFamily = args["--font"] ?? "Georgia-Bold"
// Georgia's fallback metrics under-report Thai marks. Use a native Thai font
// for both measuring and painting so tone marks remain inside the safe canvas.
let isThai = text.unicodeScalars.contains { (0x0E00...0x0E7F).contains($0.value) }
let family = isThai ? (requestedFamily.contains("Bold") ? "Thonburi-Bold" : "Thonburi") : requestedFamily
let centered = (args["--align"] ?? "center") == "center"
let hex = args["--color"] ?? "10223D"
guard let rgb = UInt32(hex.replacingOccurrences(of: "#", with: ""), radix: 16) else {
    fputs("Invalid text color\n", stderr); exit(2)
}
let color = NSColor(srgbRed: Double((rgb >> 16) & 255) / 255,
                    green: Double((rgb >> 8) & 255) / 255,
                    blue: Double(rgb & 255) / 255, alpha: 1)
func attributes(_ size: Double) -> [NSAttributedString.Key: Any] {
    let font: NSFont
    if family == "system-rounded" {
        let base = NSFont.systemFont(ofSize: size, weight: .heavy)
        font = base.fontDescriptor.withDesign(.rounded).flatMap { NSFont(descriptor: $0, size: size) } ?? base
    } else {
        font = NSFont(name: family, size: size) ?? NSFont.systemFont(ofSize: size)
    }
    return [.font: font, .foregroundColor: color]
}
var size = maximum
var dimensions: [NSSize] = []
while size >= 16 {
    dimensions = lines.map { ($0 as NSString).size(withAttributes: attributes(size)) }
    if dimensions.allSatisfy({ $0.width <= width - 28 }) &&
       dimensions.reduce(0, { $0 + $1.height }) + Double(lines.count - 1) * size * 0.02 <= height - 20 {
        break
    }
    size -= 1
}
guard size >= 16 else { fputs("Text cannot fit canvas\n", stderr); exit(1) }
let total = dimensions.reduce(0, { $0 + $1.height }) + Double(lines.count - 1) * size * 0.02
guard let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(width), pixelsHigh: Int(height),
    bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
    colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0),
    let context = NSGraphicsContext(bitmapImageRep: bitmap) else { exit(1) }
NSGraphicsContext.saveGraphicsState()
context.cgContext.translateBy(x: 0, y: height)
context.cgContext.scaleBy(x: 1, y: -1)
NSGraphicsContext.current = NSGraphicsContext(cgContext: context.cgContext, flipped: true)
NSColor.clear.setFill()
NSRect(x: 0, y: 0, width: width, height: height).fill()
var y = (height - total) / 2
for (index, line) in lines.enumerated() {
    let x = centered ? (width - dimensions[index].width) / 2 : 14
    (line as NSString).draw(at: NSPoint(x: x, y: y), withAttributes: attributes(size))
    y += dimensions[index].height + size * 0.02
}
NSGraphicsContext.restoreGraphicsState()
guard let png = bitmap.representation(using: .png, properties: [:]) else { exit(1) }
do { try png.write(to: URL(fileURLWithPath: output), options: .atomic) }
catch { fputs("Failed to write text bitmap\n", stderr); exit(1) }
print("Text fit: font=\(family) size=\(size) lines=\(lines.count) canvas=\(Int(width))x\(Int(height))")

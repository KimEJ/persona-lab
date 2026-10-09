// Rebuild the SVG and macOS icon without third-party tools:
// xcrun swift -module-cache-path build/module-cache tools/generate_app_icon.swift
import AppKit
import Foundation

enum IconError: Error { case invalidSVG(String), invalidPath(String), imageEncoding }

let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
let markURL = root.appendingPathComponent("web/brand-mark.svg")
let iconURL = root.appendingPathComponent("macos/AppIcon.svg")
let iconsetURL = root.appendingPathComponent("build/Paneloom.iconset", isDirectory: true)
let icnsURL = root.appendingPathComponent("macos/AppIcon.icns")
let document = try XMLDocument(contentsOf: markURL)
guard let element = document.rootElement(), element.attribute(forName: "viewBox")?.stringValue == "0 0 200 200" else {
    throw IconError.invalidSVG("The brand mark must use the canonical 200 by 200 viewBox.")
}
let pathStrings = try document.nodes(forXPath: "//*[local-name()='path']").map { node -> String in
    guard let value = (node as? XMLElement)?.attribute(forName: "d")?.stringValue else { throw IconError.invalidSVG("Missing path geometry.") }
    return value
}
guard pathStrings.count == 2 else { throw IconError.invalidSVG("The mark must contain two plates.") }

// The canonical mark uses only absolute commands. Reject other syntax so an
// edited SVG cannot silently produce a different icon from the source mark.
func path(_ source: String) throws -> CGPath {
    let expression = try NSRegularExpression(pattern: "[MLHVCZ]|-?(?:[0-9]+(?:\\.[0-9]+)?|\\.[0-9]+)")
    let range = NSRange(source.startIndex..<source.endIndex, in: source)
    let matches = expression.matches(in: source, range: range)
    var tokens: [String] = []
    var end = source.startIndex
    for match in matches {
        guard let tokenRange = Range(match.range, in: source), source[end..<tokenRange.lowerBound].allSatisfy({ $0.isWhitespace || $0 == "," }) else { throw IconError.invalidPath(source) }
        tokens.append(String(source[tokenRange])); end = tokenRange.upperBound
    }
    guard source[end...].allSatisfy({ $0.isWhitespace || $0 == "," }) else { throw IconError.invalidPath(source) }
    let result = CGMutablePath()
    var index = 0
    var point = CGPoint.zero
    func number() throws -> CGFloat {
        guard index < tokens.count, let value = Double(tokens[index]), value.isFinite else { throw IconError.invalidPath(source) }
        index += 1; return CGFloat(value)
    }
    while index < tokens.count {
        let command = tokens[index]; index += 1
        switch command {
        case "M": point = try CGPoint(x: number(), y: number()); result.move(to: point)
        case "L": point = try CGPoint(x: number(), y: number()); result.addLine(to: point)
        case "H": point.x = try number(); result.addLine(to: point)
        case "V": point.y = try number(); result.addLine(to: point)
        case "C":
            let first = try CGPoint(x: number(), y: number())
            let second = try CGPoint(x: number(), y: number())
            point = try CGPoint(x: number(), y: number())
            result.addCurve(to: point, control1: first, control2: second)
        case "Z": result.closeSubpath()
        default: throw IconError.invalidPath(source)
        }
    }
    return result
}
let paths = try pathStrings.map(path)
let background = try path("M272 72 H752 C862.457 72 952 161.543 952 272 V752 C952 862.457 862.457 952 752 952 H272 C161.543 952 72 862.457 72 752 V272 C72 161.543 161.543 72 272 72 Z")
let svgPaths = pathStrings.map { "    <path d=\"\($0)\"/>" }.joined(separator: "\n")
let svg = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024">
  <title>Paneloom app icon</title>
  <path fill="#245C7A" d="M272 72 H752 C862.457 72 952 161.543 952 272 V752 C952 862.457 862.457 952 752 952 H272 C161.543 952 72 862.457 72 752 V272 C72 161.543 161.543 72 272 72 Z"/>
  <g fill="#FFFEFA" transform="translate(208 208) scale(3.04)">
\(svgPaths)
  </g>
</svg>

"""
try svg.write(to: iconURL, atomically: true, encoding: .utf8)
try FileManager.default.createDirectory(at: iconsetURL, withIntermediateDirectories: true)

func render(size: Int, destination: URL) throws {
    // Pin the raster color space as well as the numeric colors so the PNG,
    // SVG, and web palette share the same sRGB definition.
    guard let colorSpace = CGColorSpace(name: CGColorSpace.sRGB), let context = CGContext(data: nil, width: size, height: size, bitsPerComponent: 8, bytesPerRow: size * 4, space: colorSpace, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { throw IconError.imageEncoding }
    context.setAllowsAntialiasing(true)
    context.setShouldAntialias(true)
    context.translateBy(x: 0, y: CGFloat(size))
    context.scaleBy(x: CGFloat(size) / 1024, y: -CGFloat(size) / 1024)
    context.setFillColor(CGColor(srgbRed: 36.0 / 255, green: 92.0 / 255, blue: 122.0 / 255, alpha: 1))
    context.addPath(background); context.fillPath()
    context.translateBy(x: 208, y: 208); context.scaleBy(x: 3.04, y: 3.04)
    context.setFillColor(CGColor(srgbRed: 1, green: 254.0 / 255, blue: 250.0 / 255, alpha: 1))
    for plate in paths { context.addPath(plate); context.fillPath() }
    guard let image = context.makeImage(), let png = NSBitmapImageRep(cgImage: image).representation(using: .png, properties: [:]) else { throw IconError.imageEncoding }
    try png.write(to: destination, options: .atomic)
}
for size in [16, 32, 128, 256, 512] {
    try render(size: size, destination: iconsetURL.appendingPathComponent("icon_\(size)x\(size).png"))
    try render(size: size * 2, destination: iconsetURL.appendingPathComponent("icon_\(size)x\(size)@2x.png"))
}
let process = Process()
process.executableURL = URL(fileURLWithPath: "/usr/bin/iconutil")
process.arguments = ["-c", "icns", "-o", icnsURL.path, iconsetURL.path]
try process.run(); process.waitUntilExit()
guard process.terminationStatus == 0 else { throw IconError.imageEncoding }
print(icnsURL.path)

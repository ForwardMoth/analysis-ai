// Apple Vision OCR: prints recognized lines of each image as JSON {"path": [{"text","x","y","w","h"}]}.
// Coordinates are normalized, origin top-left, so lines can be sorted into reading order and indented by x.
import Foundation
import Vision
import AppKit

struct Line: Codable { let text: String; let x: Double; let y: Double; let w: Double; let h: Double }

func recognize(_ path: String) -> [Line] {
    guard let image = NSImage(contentsOfFile: path),
          let cg = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else { return [] }
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = false  // code is not prose: keep identifiers as they are
    request.recognitionLanguages = ["en-US", "ru-RU"]
    try? VNImageRequestHandler(cgImage: cg).perform([request])
    let observations = request.results ?? []
    return observations.compactMap { obs in
        guard let top = obs.topCandidates(1).first else { return nil }
        let b = obs.boundingBox
        return Line(text: top.string, x: b.minX, y: 1 - b.maxY, w: b.width, h: b.height)
    }
}

var output: [String: [Line]] = [:]
for path in CommandLine.arguments.dropFirst() { output[path] = recognize(path) }
let data = try JSONEncoder().encode(output)
FileHandle.standardOutput.write(data)

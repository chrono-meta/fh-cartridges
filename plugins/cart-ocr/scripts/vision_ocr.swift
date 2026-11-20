// Apple Vision text recognition (macOS only). Usage: swift vision_ocr.swift IMAGE [LANGS, default ko-KR,en-US]
// Prints {"engine":"apple-vision","lines":[{"text","conf","x","y","w","h"}]}; exit 2 with {"error":...} if unreadable.
import Foundation
import Vision
import AppKit
guard CommandLine.arguments.count == 2 || CommandLine.arguments.count == 3 else { print("{\"error\":\"usage: vision_ocr.swift IMAGE\"}"); exit(2) }
let path = CommandLine.arguments[1]
guard let img = NSImage(contentsOfFile: path),
      let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else { print("{\"error\":\"unreadable image\"}"); exit(2) }
let req = VNRecognizeTextRequest()
req.recognitionLevel = .accurate
req.usesLanguageCorrection = false   // a corrected word is a guess; keep what is printed
req.recognitionLanguages = CommandLine.arguments.count == 3 ? CommandLine.arguments[2].split(separator: ",").map(String.init) : ["ko-KR", "en-US"]
do { try VNImageRequestHandler(cgImage: cg).perform([req]) } catch { print("{\"error\":\"vision failed\"}"); exit(2) }
var out: [[String: Any]] = []
for o in req.results ?? [] {
  if let c = o.topCandidates(1).first {
    let b = o.boundingBox
    out.append(["text": c.string, "conf": c.confidence, "x": b.minX, "y": b.minY, "w": b.width, "h": b.height])
  }
}
let d = try! JSONSerialization.data(withJSONObject: ["engine": "apple-vision", "lines": out])
print(String(data: d, encoding: .utf8)!)

// Usage: faces <dir-of-jpgs> <out.json>
// Writes {"file.jpg": [[cx, cy, w, h], ...]} with normalized top-left-origin coords.
import Foundation
import Vision
import ImageIO

let dir = CommandLine.arguments[1]
let files = try FileManager.default.contentsOfDirectory(atPath: dir).filter { $0.hasSuffix(".jpg") }.sorted()
var out: [String: [[Double]]] = [:]
for f in files {
    let url = URL(fileURLWithPath: dir).appendingPathComponent(f)
    guard let src = CGImageSourceCreateWithURL(url as CFURL, nil),
          let img = CGImageSourceCreateImageAtIndex(src, 0, nil) else { continue }
    let req = VNDetectFaceRectanglesRequest()
    try? VNImageRequestHandler(cgImage: img).perform([req])
    out[f] = (req.results ?? []).map { r in
        let b = r.boundingBox
        return [Double(b.midX), Double(1 - b.midY), Double(b.width), Double(b.height)]
    }
}
let data = try JSONSerialization.data(withJSONObject: out)
try data.write(to: URL(fileURLWithPath: CommandLine.arguments[2]))
print("faces:", files.count, "frames")

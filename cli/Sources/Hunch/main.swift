import Foundation
import FoundationModels
import HunchLib

func findDatabase() -> String? {
    let candidates = [
        URL(fileURLWithPath: CommandLine.arguments[0])
            .deletingLastPathComponent()
            .appendingPathComponent("../share/hunch/tldr_bank.db")
            .standardized.path,
        NSHomeDirectory() + "/.local/share/hunch/tldr_bank.db",
        "/opt/homebrew/share/hunch/tldr_bank.db",
        "/usr/local/share/hunch/tldr_bank.db",
        FileManager.default.currentDirectoryPath + "/bank/tldr_bank.db",
        NSHomeDirectory() + "/.hunch/tldr_bank.db",
    ]
    for path in candidates {
        if FileManager.default.fileExists(atPath: path) {
            return path
        }
    }
    return nil
}

func parseFlag(_ args: inout [String], flag: String) -> String? {
    guard let idx = args.firstIndex(of: flag), idx + 1 < args.count else { return nil }
    let value = args[idx + 1]
    args.removeSubrange(idx...idx + 1)
    return value
}

@main
struct Hunch {
    static func main() async {
        var args = Array(CommandLine.arguments.dropFirst())

        guard !args.isEmpty else {
            printUsage()
            return
        }

        if args[0] == "--help" || args[0] == "-h" {
            printUsage()
            return
        }

        if args[0] == "--version" || args[0] == "-v" {
            print("hunch 0.1.0")
            return
        }

        // Parse options
        let temperature = parseFlag(&args, flag: "--temperature").flatMap(Double.init)
        let samples = parseFlag(&args, flag: "--samples").flatMap(Int.init) ?? 1
        let limit = parseFlag(&args, flag: "--limit").flatMap(Int.init) ?? 8

        // Parse mode
        var mode: Mode = .suggest
        if args.first == "--notfound" {
            mode = .notfound
            args.removeFirst()
        } else if args.first == "--explain" {
            mode = .explain
            args.removeFirst()
        }

        guard !args.isEmpty else {
            printUsage()
            return
        }

        let fullQuery = args.joined(separator: " ")

        // Search bank
        var examples: [BankResult] = []
        if let dbPath = findDatabase() {
            switch mode {
            case .suggest:
                examples = searchBank(dbPath: dbPath, query: fullQuery, limit: limit)
            case .notfound:
                examples = searchBankByCommand(dbPath: dbPath, command: fullQuery, limit: limit)
            case .explain:
                break
            }
        }

        let systemPrompt = buildSystemPrompt(mode: mode, examples: examples)

        do {
            let model = SystemLanguageModel(
                guardrails: .permissiveContentTransformations
            )

            // Build generation options
            var genOptions = GenerationOptions()
            if let t = temperature {
                genOptions.temperature = t
            }

            let session: LanguageModelSession
            if !systemPrompt.isEmpty {
                let segment = Transcript.TextSegment(content: systemPrompt)
                let instructions = Transcript.Instructions(
                    segments: [.text(segment)],
                    toolDefinitions: []
                )
                session = LanguageModelSession(
                    model: model,
                    transcript: Transcript(entries: [.instructions(instructions)])
                )
            } else {
                session = LanguageModelSession(model: model)
            }

            if samples <= 1 {
                let response = try await session.respond(to: fullQuery, options: genOptions)
                print(stripMarkdown(response.content))
            } else {
                // Self-consistency: run N times, pick majority
                var results: [String] = []
                for _ in 0..<samples {
                    let s = LanguageModelSession(
                        model: model,
                        transcript: session.transcript
                    )
                    let response = try await s.respond(to: fullQuery, options: genOptions)
                    results.append(stripMarkdown(response.content))
                }

                // Majority vote
                var counts: [String: Int] = [:]
                for r in results { counts[r, default: 0] += 1 }
                let best = counts.max(by: { $0.value < $1.value })?.key ?? results[0]
                print(best)
            }
        } catch {
            fputs("error: \(error.localizedDescription)\n", stderr)
            exit(1)
        }
    }

    static func printUsage() {
        let dbStatus = findDatabase() != nil ? "found" : "not found"
        let envTemp = ProcessInfo.processInfo.environment["HUNCH_TEMPERATURE"] ?? "not set"
        let envSamples = ProcessInfo.processInfo.environment["HUNCH_SAMPLES"] ?? "not set"

        let usage = """
        hunch — on-device LLM shell command generator

        Usage:
          hunch [options] <description>
          hunch --notfound <command>
          hunch --explain <details>

        Options:
          --temperature <0.0-1.0>   Model temperature (default: 0)
          --samples <n>             Run n times, pick majority answer (default: 1)
          --limit <n>               Number of examples to retrieve (default: 8)

        Environment variables (for zsh hooks):
          HUNCH_TEMPERATURE         Passed as --temperature (current: \(envTemp))
          HUNCH_SAMPLES             Passed as --samples (current: \(envSamples))

        Examples:
          hunch find files changed in the last hour
          hunch --temperature 0.3 --samples 3 show disk usage
          hunch --notfound ip a
          hunch --explain "Command: git push — Exit code: 128"

        Status:
          Database: \(dbStatus)

        Uses Apple's on-device 3B model with dynamic few-shot
        retrieval from 21k tldr examples for improved accuracy.

        No cloud, no API keys, no dependencies.
        """
        print(usage)
    }
}

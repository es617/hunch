import Foundation
import FoundationModels
import HunchLib

func findDatabase() -> String? {
    let candidates = [
        URL(fileURLWithPath: CommandLine.arguments[0])
            .deletingLastPathComponent()
            .appendingPathComponent("../share/hunch/tldr_bank.db")
            .standardized.path,
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

        var mode: Mode = .suggest
        if args[0] == "--notfound" {
            mode = .notfound
            args.removeFirst()
        } else if args[0] == "--explain" {
            mode = .explain
            args.removeFirst()
        }

        guard !args.isEmpty else {
            printUsage()
            return
        }

        let fullQuery = args.joined(separator: " ")

        var examples: [BankResult] = []
        if mode != .explain, let dbPath = findDatabase() {
            examples = searchBank(dbPath: dbPath, query: fullQuery)
        }

        let systemPrompt = buildSystemPrompt(mode: mode, examples: examples)

        do {
            let model = SystemLanguageModel(
                guardrails: .permissiveContentTransformations
            )

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

            let response = try await session.respond(to: fullQuery)
            let result = stripMarkdown(response.content)
            print(result)
        } catch {
            fputs("error: \(error.localizedDescription)\n", stderr)
            exit(1)
        }
    }

    static func printUsage() {
        let usage = """
        hunch — on-device LLM shell command generator

        Usage:
          hunch <description>              generate a command (uses tldr bank)
          hunch --notfound <command>       suggest correction for unknown command
          hunch --explain <details>        explain why a command failed

        Examples:
          hunch find files changed in the last hour
          hunch --notfound ip a
          hunch --explain "Command: git push — Exit code: 128"

        Uses Apple's on-device 3B model with dynamic few-shot
        retrieval from 21k tldr examples for improved accuracy.

        No cloud, no API keys, no dependencies.
        """
        print(usage)
    }
}

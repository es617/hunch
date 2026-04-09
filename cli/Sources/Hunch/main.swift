import Foundation
import FoundationModels
import HunchLib

// Guided generation strategies
@Generable
struct ShellCommand {
    @Guide(description: "A single shell command for zsh on macOS. No explanation, no markdown, no backticks.")
    var command: String
}

@Generable
struct ShellCommandCoT {
    @Guide(description: "Brief reasoning: which macOS command fits and why. Consider if the command exists on macOS (not Linux-only).")
    var reasoning: String

    @Guide(description: "A single shell command for zsh on macOS.")
    var command: String
}

@Generable
struct ShellCommandMulti {
    @Guide(description: "Best shell command for zsh on macOS.")
    var first: String

    @Guide(description: "Alternative shell command for the same task.")
    var second: String

    @Guide(description: "Another alternative shell command.")
    var third: String
}

@Generable
struct ShellCommandCoTMulti {
    @Guide(description: "Brief reasoning: which macOS command fits and why. Consider if the command exists on macOS (not Linux-only).")
    var reasoning: String

    @Guide(description: "Best shell command for zsh on macOS.")
    var first: String

    @Guide(description: "Alternative shell command for the same task.")
    var second: String

    @Guide(description: "Another alternative shell command.")
    var third: String
}

func majorityVote(_ candidates: [String]) -> String {
    var counts: [String: Int] = [:]
    for c in candidates { counts[c, default: 0] += 1 }
    return counts.max(by: { $0.value < $1.value })?.key ?? candidates[0]
}

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
            print("hunch 0.1.2")
            return
        }


        // Parse options
        let temperature = parseFlag(&args, flag: "--temperature").flatMap(Double.init)
        let samples = parseFlag(&args, flag: "--samples").flatMap(Int.init) ?? 1
        let limit = parseFlag(&args, flag: "--limit").flatMap(Int.init) ?? 8
        let guided = parseFlag(&args, flag: "--guided")

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

            // Build generation options only when temperature is set
            let genOptions: GenerationOptions? = temperature.map {
                var opts = GenerationOptions()
                opts.temperature = $0
                return opts
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

            if samples > 1 && temperature == nil {
                fputs("warning: --samples without --temperature is useless (model is deterministic at temp 0). Add --temperature 0.3\n", stderr)
            }

            if mode == .explain {
                let response: LanguageModelSession.Response<String>
                if let opts = genOptions {
                    response = try await session.respond(to: fullQuery, options: opts)
                } else {
                    response = try await session.respond(to: fullQuery)
                }
                print(response.content)
            } else if guided == nil {
                // Default: plain string output with stripMarkdown
                if samples <= 1 {
                    let response: LanguageModelSession.Response<String>
                    if let opts = genOptions {
                        response = try await session.respond(to: fullQuery, options: opts)
                    } else {
                        response = try await session.respond(to: fullQuery)
                    }
                    print(stripMarkdown(response.content))
                } else {
                    var results: [String] = []
                    for _ in 0..<samples {
                        let s = LanguageModelSession(model: model, transcript: session.transcript)
                        let response: LanguageModelSession.Response<String>
                        if let opts = genOptions {
                            response = try await s.respond(to: fullQuery, options: opts)
                        } else {
                            response = try await s.respond(to: fullQuery)
                        }
                        results.append(stripMarkdown(response.content))
                    }
                    print(majorityVote(results))
                }
            } else if guided == "plain" {
                // Guided: single command struct
                let response: LanguageModelSession.Response<ShellCommand>
                if let opts = genOptions {
                    response = try await session.respond(to: fullQuery, generating: ShellCommand.self, options: opts)
                } else {
                    response = try await session.respond(to: fullQuery, generating: ShellCommand.self)
                }
                print(response.content.command)
            } else if guided == "cot" {
                // Guided: chain of thought + command
                let response: LanguageModelSession.Response<ShellCommandCoT>
                if let opts = genOptions {
                    response = try await session.respond(to: fullQuery, generating: ShellCommandCoT.self, options: opts)
                } else {
                    response = try await session.respond(to: fullQuery, generating: ShellCommandCoT.self)
                }
                if ProcessInfo.processInfo.environment["HUNCH_DEBUG"] != nil {
                    fputs("reasoning: \(response.content.reasoning)\n", stderr)
                }
                print(response.content.command)
            } else if guided == "multi" {
                // Guided: 3 candidates, majority vote
                let response: LanguageModelSession.Response<ShellCommandMulti>
                if let opts = genOptions {
                    response = try await session.respond(to: fullQuery, generating: ShellCommandMulti.self, options: opts)
                } else {
                    response = try await session.respond(to: fullQuery, generating: ShellCommandMulti.self)
                }
                print(majorityVote([response.content.first, response.content.second, response.content.third]))
            } else if guided == "cotmulti" {
                // Guided: chain of thought + 3 candidates, majority vote
                let response: LanguageModelSession.Response<ShellCommandCoTMulti>
                if let opts = genOptions {
                    response = try await session.respond(to: fullQuery, generating: ShellCommandCoTMulti.self, options: opts)
                } else {
                    response = try await session.respond(to: fullQuery, generating: ShellCommandCoTMulti.self)
                }
                print(majorityVote([response.content.first, response.content.second, response.content.third]))
            } else {
                fputs("error: unknown --guided strategy '\(guided!)'. Use: plain, cot, multi, cotmulti\n", stderr)
                exit(1)
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

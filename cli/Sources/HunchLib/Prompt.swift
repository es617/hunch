import Foundation

public enum Mode: String, Sendable {
    case suggest
    case notfound
    case explain
}

public func buildSystemPrompt(mode: Mode, examples: [BankResult]) -> String {
    switch mode {
    case .suggest:
        var prompt = "Output a single shell command for zsh on macOS. No explanation, no markdown, no backticks. Just the command."
        if !examples.isEmpty {
            prompt += "\n\nExamples:"
            for ex in examples {
                prompt += "\nQ: \(ex.question)\nA: \(ex.answer)"
            }
        }
        return prompt

    case .notfound:
        var prompt = "This command was not found on macOS. If it is a typo, output the corrected command. If it is a Linux command, output the macOS equivalent. Just the command, no markdown, no backticks."
        if !examples.isEmpty {
            prompt += "\n\nExamples:"
            for ex in examples {
                prompt += "\nQ: \(ex.question)\nA: \(ex.answer)"
            }
        }
        return prompt

    case .explain:
        return "In one sentence, explain the likely cause of this shell command failure."
    }
}

public func stripMarkdown(_ text: String) -> String {
    var s = text
    s = s.replacingOccurrences(of: "```bash", with: "")
    s = s.replacingOccurrences(of: "```zsh", with: "")
    s = s.replacingOccurrences(of: "```shell", with: "")
    s = s.replacingOccurrences(of: "```", with: "")
    s = s.replacingOccurrences(of: "`", with: "")
    return s.trimmingCharacters(in: .whitespacesAndNewlines)
}

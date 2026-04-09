import Testing
import Foundation
@testable import HunchLib

// MARK: - Tokenizer Tests

@Test func tokenizeBasicQuery() {
    let tokens = tokenize("find files changed in the last hour")
    #expect(tokens == ["find", "files", "changed", "last", "hour"])
}

@Test func tokenizeRemovesStopWords() {
    let tokens = tokenize("show all the environment variables")
    #expect(tokens.contains("show"))
    #expect(!tokens.contains("all"))
    #expect(!tokens.contains("the"))
    #expect(tokens.contains("environment"))
    #expect(tokens.contains("variables"))
}

@Test func tokenizeEmptyInput() {
    #expect(tokenize("").isEmpty)
    #expect(tokenize("the a an in on to").isEmpty)
}

@Test func tokenizeSingleCharWordsDropped() {
    let tokens = tokenize("I want a file")
    #expect(!tokens.contains("I"))
    #expect(tokens.contains("want"))
    #expect(tokens.contains("file"))
}

@Test func tokenizeHandlesSpecialCharacters() {
    let tokens = tokenize("find *.png files (recursively)")
    #expect(tokens.contains("png"))
    #expect(tokens.contains("files"))
    #expect(tokens.contains("recursively"))
}

// MARK: - FTS Query Building Tests

@Test func buildFTSQueryBasic() {
    let query = buildFTSQuery(["files", "changed", "hour"])
    #expect(query == "\"files\" OR \"changed\" OR \"hour\"")
}

@Test func buildFTSQueryEscapesQuotes() {
    let query = buildFTSQuery(["he\"llo"])
    #expect(query == "\"he\"\"llo\"")
}

@Test func buildFTSQuerySingleWord() {
    let query = buildFTSQuery(["caffeinate"])
    #expect(query == "\"caffeinate\"")
}

// MARK: - Bank Search Tests

@Test func searchBankFindsRelevantResults() {
    let dbPath = testDatabasePath()
    let results = searchBank(dbPath: dbPath, query: "find files modified recently")
    #expect(!results.isEmpty)
    if let first = results.first {
        #expect(first.answer.contains("find"))
    }
}

@Test func searchBankReturnsEmptyForStopWordsOnly() {
    let dbPath = testDatabasePath()
    let results = searchBank(dbPath: dbPath, query: "the a an")
    #expect(results.isEmpty)
}

@Test func searchBankRespectsLimit() {
    let dbPath = testDatabasePath()
    let results = searchBank(dbPath: dbPath, query: "find files", limit: 2)
    #expect(results.count <= 2)
}

@Test func searchBankHandlesMissingDatabase() {
    let results = searchBank(dbPath: "/nonexistent/path.db", query: "test")
    #expect(results.isEmpty)
}

@Test func searchBankFindsMacOSCommands() {
    let dbPath = testDatabasePath()
    let results = searchBank(dbPath: dbPath, query: "clipboard copy")
    #expect(results.contains { $0.answer.contains("pbcopy") })
}

// MARK: - Prompt Building Tests

@Test func buildPromptSuggestNoExamples() {
    let prompt = buildSystemPrompt(mode: .suggest, examples: [])
    #expect(prompt.contains("single shell command"))
    #expect(!prompt.contains("Examples:"))
}

@Test func buildPromptSuggestWithExamples() {
    let examples = [
        BankResult(question: "show disk usage", answer: "df -h"),
        BankResult(question: "list files", answer: "ls"),
    ]
    let prompt = buildSystemPrompt(mode: .suggest, examples: examples)
    #expect(prompt.contains("prefer commands shown here:"))
    #expect(prompt.contains("Q: show disk usage"))
    #expect(prompt.contains("A: df -h"))
    #expect(prompt.contains("Q: list files"))
    #expect(prompt.contains("A: ls"))
}

@Test func buildPromptNotfound() {
    let prompt = buildSystemPrompt(mode: .notfound, examples: [])
    #expect(prompt.contains("not found on macOS"))
    #expect(prompt.contains("Linux"))
}

@Test func buildPromptExplainIgnoresExamples() {
    let examples = [BankResult(question: "test", answer: "test")]
    let prompt = buildSystemPrompt(mode: .explain, examples: examples)
    #expect(!prompt.contains("Examples:"))
    #expect(prompt.contains("explain"))
}

// MARK: - Markdown Stripping Tests

@Test func stripMarkdownRemovesFences() {
    #expect(stripMarkdown("```bash\nls -la\n```") == "ls -la")
    #expect(stripMarkdown("```zsh\nfind . -name '*.txt'\n```") == "find . -name '*.txt'")
    #expect(stripMarkdown("```shell\npwd\n```") == "pwd")
}

@Test func stripMarkdownRemovesInlineBackticks() {
    #expect(stripMarkdown("`ls -la`") == "ls -la")
    #expect(stripMarkdown("``ls``") == "ls")
}

@Test func stripMarkdownTrimsWhitespace() {
    #expect(stripMarkdown("  ls -la  \n") == "ls -la")
}

@Test func stripMarkdownPassthroughClean() {
    #expect(stripMarkdown("find . -mmin -60") == "find . -mmin -60")
}

// MARK: - Helpers

func testDatabasePath() -> String {
    Bundle.module.bundlePath + "/test_bank.db"
}

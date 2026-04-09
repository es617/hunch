import Foundation
import SQLite3

public struct BankResult: Equatable, Sendable {
    public let question: String
    public let answer: String

    public init(question: String, answer: String) {
        self.question = question
        self.answer = answer
    }
}

public let defaultStopWords: Set<String> = [
    "the", "a", "an", "in", "on", "to", "for", "of", "and", "or", "is", "it",
    "all", "my", "this", "that", "with", "from", "how", "do", "what"
]

public func tokenize(_ text: String, stopWords: Set<String> = defaultStopWords) -> [String] {
    text.lowercased()
        .components(separatedBy: CharacterSet.alphanumerics.inverted)
        .filter { $0.count > 1 && !stopWords.contains($0) }
}

public func buildFTSQuery(_ words: [String]) -> String {
    words
        .map { "\"\($0.replacingOccurrences(of: "\"", with: "\"\""))\"" }
        .joined(separator: " OR ")
}

public func searchBank(dbPath: String, query: String, limit: Int = 8) -> [BankResult] {
    var db: OpaquePointer?
    guard sqlite3_open_v2(dbPath, &db, SQLITE_OPEN_READONLY, nil) == SQLITE_OK else {
        return []
    }
    defer { sqlite3_close(db) }

    let words = tokenize(query)
    guard !words.isEmpty else { return [] }

    let ftsQuery = buildFTSQuery(words)
    let SQLITE_TRANSIENT = unsafeBitCast(-1, to: sqlite3_destructor_type.self)

    // Three-tier retrieval: override → tldr-osx → tldr-common
    var results: [BankResult] = []
    var seen = Set<String>()

    let tiers = ["override", "tldr-osx", "tldr-common"]
    for source in tiers {
        guard results.count < limit else { break }
        let sql = "SELECT question, answer FROM bank WHERE bank MATCH ? AND source = ? ORDER BY rank LIMIT ?"
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { continue }
        sqlite3_bind_text(stmt, 1, ftsQuery, -1, SQLITE_TRANSIENT)
        sqlite3_bind_text(stmt, 2, source, -1, SQLITE_TRANSIENT)
        sqlite3_bind_int(stmt, 3, Int32(limit - results.count))
        while sqlite3_step(stmt) == SQLITE_ROW && results.count < limit {
            guard let qPtr = sqlite3_column_text(stmt, 0),
                  let aPtr = sqlite3_column_text(stmt, 1) else { continue }
            let question = String(cString: qPtr)
            let answer = String(cString: aPtr)
            let key = "\(question)\t\(answer)"
            if !seen.contains(key) {
                seen.insert(key)
                results.append(BankResult(question: question, answer: answer))
            }
        }
        sqlite3_finalize(stmt)
    }

    // Fallback: if tiered search found nothing, search all sources
    if results.isEmpty {
        let sql = "SELECT question, answer FROM bank WHERE bank MATCH ? ORDER BY rank LIMIT ?"
        var stmt: OpaquePointer?
        if sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK {
            sqlite3_bind_text(stmt, 1, ftsQuery, -1, SQLITE_TRANSIENT)
            sqlite3_bind_int(stmt, 2, Int32(limit))
            while sqlite3_step(stmt) == SQLITE_ROW {
                guard let qPtr = sqlite3_column_text(stmt, 0),
                      let aPtr = sqlite3_column_text(stmt, 1) else { continue }
                results.append(BankResult(question: String(cString: qPtr), answer: String(cString: aPtr)))
            }
            sqlite3_finalize(stmt)
        }
    }

    return results
}

/// Check if a command name exists in the bank (any source).
public func commandExistsInBank(dbPath: String, command: String) -> Bool {
    var db: OpaquePointer?
    guard sqlite3_open_v2(dbPath, &db, SQLITE_OPEN_READONLY, nil) == SQLITE_OK else {
        return false
    }
    defer { sqlite3_close(db) }

    let sql = "SELECT 1 FROM bank WHERE cmd = ? LIMIT 1"
    var stmt: OpaquePointer?
    guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else {
        return false
    }
    defer { sqlite3_finalize(stmt) }

    let SQLITE_TRANSIENT = unsafeBitCast(-1, to: sqlite3_destructor_type.self)
    sqlite3_bind_text(stmt, 1, command, -1, SQLITE_TRANSIENT)
    return sqlite3_step(stmt) == SQLITE_ROW
}

/// Search bank by command name (for notfound mode).
/// Looks up examples for the command the user tried to run.
public func searchBankByCommand(dbPath: String, command: String, limit: Int = 8) -> [BankResult] {
    var db: OpaquePointer?
    guard sqlite3_open_v2(dbPath, &db, SQLITE_OPEN_READONLY, nil) == SQLITE_OK else {
        return []
    }
    defer { sqlite3_close(db) }

    // Extract the base command (first word)
    let baseCmd = command.split(separator: " ").first.map(String.init) ?? command

    // Search the cmd column specifically using FTS5 column filter
    let sql = "SELECT question, answer FROM bank WHERE bank MATCH ? ORDER BY rank LIMIT ?"

    var stmt: OpaquePointer?
    guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else {
        return []
    }
    defer { sqlite3_finalize(stmt) }

    let escaped = baseCmd.replacingOccurrences(of: "\"", with: "\"\"")
    let quoted = "cmd:\"\(escaped)\""
    let SQLITE_TRANSIENT = unsafeBitCast(-1, to: sqlite3_destructor_type.self)
    sqlite3_bind_text(stmt, 1, quoted, -1, SQLITE_TRANSIENT)
    sqlite3_bind_int(stmt, 2, Int32(limit))

    var results: [BankResult] = []
    while sqlite3_step(stmt) == SQLITE_ROW {
        guard let qPtr = sqlite3_column_text(stmt, 0),
              let aPtr = sqlite3_column_text(stmt, 1) else { continue }
        let question = String(cString: qPtr)
        let answer = String(cString: aPtr)
        results.append(BankResult(question: question, answer: answer))
    }
    return results
}

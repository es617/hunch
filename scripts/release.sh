#!/bin/bash
# Build and prepare a release archive.
# Run on macOS 26 (Tahoe) with Apple Silicon.
#
# Usage: ./scripts/release.sh 0.1.0

set -euo pipefail

VERSION="${1:?Usage: release.sh <version>}"

echo "Building hunch v${VERSION}..."
cd "$(dirname "$0")/.."

# Update version in source
sed -i '' "s/hunch [0-9]\.[0-9]\.[0-9]/hunch ${VERSION}/" cli/Sources/Hunch/main.swift

# Build
cd cli && swift build -c release && cd ..

# Run tests
cd cli && swift test && cd ..

# Package
mkdir -p dist
cp cli/.build/release/hunch dist/
cp bank/tldr_bank.db dist/
cp hooks/hunch.zsh dist/

cd dist
tar czf "../hunch-${VERSION}-arm64-macos.tar.gz" hunch tldr_bank.db hunch.zsh
cd ..
rm -rf dist

# Compute sha256
SHA=$(shasum -a 256 "hunch-${VERSION}-arm64-macos.tar.gz" | awk '{print $1}')
echo ""
echo "Archive: hunch-${VERSION}-arm64-macos.tar.gz"
echo "SHA256:  ${SHA}"
echo ""
echo "Update Formula/hunch.rb:"
echo "  url \"https://github.com/es617/hunch/releases/download/v${VERSION}/hunch-${VERSION}-arm64-macos.tar.gz\""
echo "  sha256 \"${SHA}\""
echo ""
echo "Then:"
echo "  git tag v${VERSION}"
echo "  git push origin v${VERSION}"
echo "  gh release create v${VERSION} hunch-${VERSION}-arm64-macos.tar.gz --title 'v${VERSION}' --draft"

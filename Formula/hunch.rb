class Hunch < Formula
  desc "On-device shell command generator using Apple's 3B model with tldr-based few-shot retrieval"
  homepage "https://github.com/es617/hunch"
  url "https://github.com/es617/hunch/releases/download/v0.1.1/hunch-0.1.1-arm64-macos.tar.gz"
  sha256 "f82ddcec7fde148374769e68f03a6087f3f8adc3be81f7431dbbf9b16323a8b3"
  license "MIT"

  depends_on :macos
  depends_on arch: :arm64

  def install
    bin.install "hunch"
    (share/"hunch").install "tldr_bank.db"
    (share/"hunch").install "hunch.zsh"
  end

  def caveats
    <<~EOS
      To enable shell hooks, add to ~/.zshrc:
        source #{share}/hunch/hunch.zsh

      Requires macOS 26 Tahoe with Apple Intelligence enabled.
    EOS
  end

  test do
    assert_match "hunch 0.1.1", shell_output("#{bin}/hunch --version")
  end
end

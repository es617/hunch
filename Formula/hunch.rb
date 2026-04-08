class Hunch < Formula
  desc "On-device shell command generator using Apple's 3B model with tldr-based few-shot retrieval"
  homepage "https://github.com/es617/hunch"
  url "https://github.com/es617/hunch/releases/download/v0.1.0/hunch-0.1.0-arm64-macos.tar.gz"
  sha256 "f93e147e5c8bfb829fd93528cedfb9bd068e7edf59d720edc9e3e6dccb3013e7"
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
    assert_match "hunch 0.1.0", shell_output("#{bin}/hunch --version")
  end
end

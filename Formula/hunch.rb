class Hunch < Formula
  desc "On-device shell command generator using Apple's 3B model with tldr-based few-shot retrieval"
  homepage "https://github.com/es617/hunch"
  url "https://github.com/es617/hunch/releases/download/v0.1.2/hunch-0.1.2-arm64-macos.tar.gz"
  sha256 "41c60665d452764e0c558e8707016f23b92f592a1bf0201017566781dda98be6"
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
    assert_match "hunch 0.1.2", shell_output("#{bin}/hunch --version")
  end
end

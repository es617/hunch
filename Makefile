PREFIX ?= $(HOME)/.local
BINDIR = $(PREFIX)/bin
SHAREDIR = $(PREFIX)/share/hunch

.PHONY: build test install uninstall hooks update-bank clean

build:
	cd cli && swift build -c release

test:
	cd cli && swift test

install: build
	install -d $(BINDIR) $(SHAREDIR)
	install -m 755 cli/.build/release/hunch $(BINDIR)/hunch
	install -m 644 bank/tldr_bank.db $(SHAREDIR)/tldr_bank.db
	install -m 644 hooks/hunch.zsh $(SHAREDIR)/hunch.zsh
	@echo ""
	@echo "Installed hunch to $(BINDIR)/hunch"
	@echo ""
	@case "$$PATH" in \
		*$(BINDIR)*) ;; \
		*) echo "Add to your PATH: export PATH=\"$(BINDIR):\$$PATH\"" ; echo "" ;; \
	esac
	@echo "Run 'make hooks' to add shell hooks to ~/.zshrc, or add manually:"
	@echo "  source $(SHAREDIR)/hunch.zsh"

hooks:
	@if grep -q 'hunch.zsh' ~/.zshrc 2>/dev/null; then \
		echo "hunch hooks already in ~/.zshrc"; \
	else \
		echo "" >> ~/.zshrc; \
		echo "# hunch — on-device LLM shell hooks" >> ~/.zshrc; \
		echo "source $(SHAREDIR)/hunch.zsh" >> ~/.zshrc; \
		echo "Added hunch hooks to ~/.zshrc. Open a new terminal to activate."; \
	fi

uninstall:
	rm -f $(BINDIR)/hunch
	rm -rf $(SHAREDIR)

update-bank:
	cd bank && python3 build_tldr_bank.py
	@echo "Bank updated. Run 'make install' to deploy."

clean:
	cd cli && swift package clean

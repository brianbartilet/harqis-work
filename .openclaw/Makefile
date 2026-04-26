.PHONY: help setup setup-sh setup-ps1 setup-bat clean verify

SYNC_REPO ?= $(CURDIR)/workspace
PROFILE ?= default

help:
	@echo "OpenClaw Environment Setup"
	@echo ""
	@echo "Available targets:"
	@echo "  make setup          - Run setup for current platform (auto-detect)"
	@echo "  make setup-sh       - Run Unix/Linux/macOS setup"
	@echo "  make setup-ps1      - Run Windows PowerShell setup"
	@echo "  make setup-bat      - Run Windows batch setup"
	@echo "  make verify         - Verify OpenClaw environment variables"
	@echo "  make clean          - Remove environment variable exports"
	@echo ""
	@echo "Options:"
	@echo "  SYNC_REPO=<path>    - Custom sync repository path (default: ./workspace)"
	@echo "  PROFILE=<name>      - OpenClaw profile name (default: default)"
	@echo ""
	@echo "Examples:"
	@echo "  make setup"
	@echo "  make setup SYNC_REPO=/mnt/openclaw PROFILE=work"
	@echo "  make verify"

setup:
	@echo "Detecting platform..."
	@uname -s | grep -q Darwin && echo "macOS detected" && $(MAKE) setup-sh || true
	@uname -s | grep -q Linux && echo "Linux detected" && $(MAKE) setup-sh || true
	@uname -s | grep -q MINGW && echo "Windows detected" && $(MAKE) setup-ps1 || true

setup-sh:
	@echo "Setting up OpenClaw environment (Unix/Linux/macOS)..."
	@chmod +x setup-env.sh
	@./setup-env.sh "$(SYNC_REPO)"

setup-ps1:
	@echo "Setting up OpenClaw environment (Windows PowerShell)..."
	@powershell -NoProfile -ExecutionPolicy Bypass -Command "& '$(CURDIR)\setup-env.ps1' -SyncRepo '$(SYNC_REPO)' -Profile '$(PROFILE)'"

setup-bat:
	@echo "Setting up OpenClaw environment (Windows batch)..."
	@cmd /c "setup-env.bat --sync-repo "$(SYNC_REPO)" --profile "$(PROFILE)""

verify:
	@echo "Verifying OpenClaw environment..."
	@echo ""
	@if command -v powershell > /dev/null; then \
		echo "OPENCLAW_CONFIG_PATH: $$OPENCLAW_CONFIG_PATH"; \
		echo "OPENCLAW_STATE_DIR: $$OPENCLAW_STATE_DIR"; \
		echo ""; \
		if [ -n "$$OPENCLAW_CONFIG_PATH" ] && [ -d "$$OPENCLAW_CONFIG_PATH" ]; then \
			echo "✓ Config directory exists"; \
		else \
			echo "✗ Config directory not found"; \
		fi; \
		if [ -n "$$OPENCLAW_STATE_DIR" ] && [ -d "$$OPENCLAW_STATE_DIR" ]; then \
			echo "✓ State directory exists"; \
		else \
			echo "✗ State directory not found"; \
		fi; \
	else \
		echo "Note: Run 'openclaw status' to verify OpenClaw is using the correct directories"; \
	fi

clean:
	@echo "Cleaning up OpenClaw environment..."
	@unset OPENCLAW_CONFIG_PATH
	@unset OPENCLAW_STATE_DIR
	@unset OPENCLAW_PROFILE
	@echo "Environment variables cleared for this session"
	@echo "Note: Run 'openclaw reset' to clear permanent configuration"

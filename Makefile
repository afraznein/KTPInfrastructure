# KTP Infrastructure Makefile
# Build and deployment automation for KTP game server stack
#
# Usage:
#   make build              - Build all components
#   make build-engine       - Build only KTPReHLDS
#   make build-amxx         - Build only KTPAMXX
#   make build-plugins      - Build only plugins
#   make deploy             - Deploy to all clusters
#   make deploy-atlanta     - Deploy to Atlanta cluster
#   make deploy-plugins     - Deploy only plugins to all clusters
#   make clean              - Remove build artifacts

# ============================================
# Configuration
# ============================================

# Version defaults to today's date
VERSION ?= $(shell date +%Y%m%d)

# Project root (parent of KTPInfrastructure)
KTP_PROJECT_ROOT ?= $(shell cd .. && pwd)

# Export for docker-compose
export VERSION
export KTP_PROJECT_ROOT

# Docker compose file location
COMPOSE_FILE := build/docker-compose.yml
COMPOSE := docker compose -f $(COMPOSE_FILE)

# Artifact output directory
ARTIFACTS_DIR := artifacts/$(VERSION)

# Python for deployment scripts
PYTHON := python3

# ============================================
# Build Targets
# ============================================

.PHONY: all build build-base build-engine build-amxx build-reapi build-curl build-plugins clean

all: build

# Build everything
build: build-base
	@echo "========================================"
	@echo "Building all KTP components (version: $(VERSION))"
	@echo "========================================"
	@echo ""
	@echo "Step 1: Building Docker images..."
	$(COMPOSE) build ktp-rehlds ktp-amxx ktp-reapi ktp-curl
	@echo ""
	@echo "Step 2: Building plugins (depends on amxx)..."
	$(COMPOSE) build ktp-plugins
	@echo ""
	@echo "Step 3: Extracting artifacts..."
	@$(MAKE) extract-artifacts
	@echo ""
	@echo "========================================"
	@echo "Build complete! Artifacts in: $(ARTIFACTS_DIR)"
	@echo "========================================"

# Build base image first
build-base:
	@echo "Building base image..."
	$(COMPOSE) build ktp-base

# Extract artifacts from built images
extract-artifacts:
	@echo "Extracting artifacts to $(ARTIFACTS_DIR)..."
	@mkdir -p $(ARTIFACTS_DIR)/engine $(ARTIFACTS_DIR)/ktpamx/dlls $(ARTIFACTS_DIR)/ktpamx/modules $(ARTIFACTS_DIR)/ktpamx/scripting $(ARTIFACTS_DIR)/plugins
	@# Extract from rehlds
	@docker create --name ktp-extract-rehlds ktp-rehlds:$(VERSION) 2>/dev/null || true
	@docker cp ktp-extract-rehlds:/output/engine/. $(ARTIFACTS_DIR)/engine/ 2>/dev/null || echo "  Warning: Could not extract engine artifacts"
	@docker rm ktp-extract-rehlds 2>/dev/null || true
	@# Extract from amxx
	@docker create --name ktp-extract-amxx ktp-amxx:$(VERSION) 2>/dev/null || true
	@docker cp ktp-extract-amxx:/output/ktpamx/. $(ARTIFACTS_DIR)/ktpamx/ 2>/dev/null || echo "  Warning: Could not extract amxx artifacts"
	@docker rm ktp-extract-amxx 2>/dev/null || true
	@# Extract from reapi
	@docker create --name ktp-extract-reapi ktp-reapi:$(VERSION) 2>/dev/null || true
	@docker cp ktp-extract-reapi:/output/ktpamx/modules/. $(ARTIFACTS_DIR)/ktpamx/modules/ 2>/dev/null || echo "  Warning: Could not extract reapi artifacts"
	@docker rm ktp-extract-reapi 2>/dev/null || true
	@# Extract from curl
	@docker create --name ktp-extract-curl ktp-curl:$(VERSION) 2>/dev/null || true
	@docker cp ktp-extract-curl:/output/ktpamx/modules/. $(ARTIFACTS_DIR)/ktpamx/modules/ 2>/dev/null || echo "  Warning: Could not extract curl artifacts"
	@docker rm ktp-extract-curl 2>/dev/null || true
	@# Extract from plugins
	@docker create --name ktp-extract-plugins ktp-plugins:$(VERSION) 2>/dev/null || true
	@docker cp ktp-extract-plugins:/output/plugins/. $(ARTIFACTS_DIR)/plugins/ 2>/dev/null || echo "  Warning: Could not extract plugin artifacts"
	@docker rm ktp-extract-plugins 2>/dev/null || true
	@echo "Artifacts extracted:"
	@ls -la $(ARTIFACTS_DIR)/engine/ 2>/dev/null || echo "  (no engine artifacts)"
	@ls -la $(ARTIFACTS_DIR)/ktpamx/dlls/ 2>/dev/null || echo "  (no amxx dlls)"
	@ls -la $(ARTIFACTS_DIR)/ktpamx/modules/ 2>/dev/null || echo "  (no modules)"
	@ls -la $(ARTIFACTS_DIR)/plugins/ 2>/dev/null || echo "  (no plugins)"

# Individual component builds
build-engine: build-base
	@echo "Building KTPReHLDS..."
	$(COMPOSE) build ktp-rehlds
	@mkdir -p $(ARTIFACTS_DIR)/engine
	@docker create --name ktp-extract-rehlds ktp-rehlds:$(VERSION) 2>/dev/null || true
	@docker cp ktp-extract-rehlds:/output/engine/. $(ARTIFACTS_DIR)/engine/
	@docker rm ktp-extract-rehlds 2>/dev/null || true
	@echo "Engine artifacts:"
	@ls -la $(ARTIFACTS_DIR)/engine/

build-amxx: build-base
	@echo "Building KTPAMXX..."
	$(COMPOSE) build ktp-amxx
	@mkdir -p $(ARTIFACTS_DIR)/ktpamx
	@docker create --name ktp-extract-amxx ktp-amxx:$(VERSION) 2>/dev/null || true
	@docker cp ktp-extract-amxx:/output/ktpamx/. $(ARTIFACTS_DIR)/ktpamx/
	@docker rm ktp-extract-amxx 2>/dev/null || true
	@echo "AMXX artifacts:"
	@ls -laR $(ARTIFACTS_DIR)/ktpamx/

build-reapi: build-base
	@echo "Building KTPReAPI..."
	$(COMPOSE) build ktp-reapi
	@mkdir -p $(ARTIFACTS_DIR)/ktpamx/modules
	@docker create --name ktp-extract-reapi ktp-reapi:$(VERSION) 2>/dev/null || true
	@docker cp ktp-extract-reapi:/output/ktpamx/modules/. $(ARTIFACTS_DIR)/ktpamx/modules/
	@docker rm ktp-extract-reapi 2>/dev/null || true
	@echo "ReAPI artifacts:"
	@ls -la $(ARTIFACTS_DIR)/ktpamx/modules/reapi*

build-curl: build-base
	@echo "Building KTPAmxxCurl..."
	$(COMPOSE) build ktp-curl
	@mkdir -p $(ARTIFACTS_DIR)/ktpamx/modules
	@docker create --name ktp-extract-curl ktp-curl:$(VERSION) 2>/dev/null || true
	@docker cp ktp-extract-curl:/output/ktpamx/modules/. $(ARTIFACTS_DIR)/ktpamx/modules/
	@docker rm ktp-extract-curl 2>/dev/null || true
	@echo "Curl artifacts:"
	@ls -la $(ARTIFACTS_DIR)/ktpamx/modules/amxxcurl*

build-plugins: build-base build-amxx
	@echo "Building plugins..."
	$(COMPOSE) build ktp-plugins
	@mkdir -p $(ARTIFACTS_DIR)/plugins
	@docker create --name ktp-extract-plugins ktp-plugins:$(VERSION) 2>/dev/null || true
	@docker cp ktp-extract-plugins:/output/plugins/. $(ARTIFACTS_DIR)/plugins/
	@docker rm ktp-extract-plugins 2>/dev/null || true
	@echo "Plugin artifacts:"
	@ls -la $(ARTIFACTS_DIR)/plugins/

# ============================================
# Deployment Targets
# ============================================

.PHONY: deploy deploy-atlanta deploy-dallas deploy-denver deploy-plugins configure-names

# Deploy to all clusters
deploy:
	@echo "Deploying version $(VERSION) to all clusters..."
	$(PYTHON) deploy/deploy.py --all --version $(VERSION)

# Deploy to specific cluster
deploy-atlanta:
	$(PYTHON) deploy/deploy.py --cluster atlanta --version $(VERSION)

deploy-dallas:
	$(PYTHON) deploy/deploy.py --cluster dallas --version $(VERSION)

deploy-denver:
	$(PYTHON) deploy/deploy.py --cluster denver --version $(VERSION)

# Deploy only plugins
deploy-plugins:
	$(PYTHON) deploy/deploy.py --all --component plugins --version $(VERSION)

deploy-plugins-atlanta:
	$(PYTHON) deploy/deploy.py --cluster atlanta --component plugins --version $(VERSION)

deploy-plugins-dallas:
	$(PYTHON) deploy/deploy.py --cluster dallas --component plugins --version $(VERSION)

# Configure server names (LinuxGSM hostname/servername)
configure-names:
	$(PYTHON) deploy/deploy.py --all --component plugins --configure-names --version $(VERSION)

configure-names-atlanta:
	$(PYTHON) deploy/deploy.py --cluster atlanta --component plugins --configure-names --version $(VERSION)

configure-names-dallas:
	$(PYTHON) deploy/deploy.py --cluster dallas --component plugins --configure-names --version $(VERSION)

# ============================================
# Utility Targets
# ============================================

.PHONY: clean clean-images clean-containers list-artifacts package-dod-base

# Package base DoD files (maps, configs, models - excludes built plugins/modules)
# Source: KTP DoD Server test installation
DOD_BASE_SOURCE ?= $(KTP_PROJECT_ROOT)/KTP DoD Server/serverfiles/dod
DOD_BASE_OUTPUT := $(ARTIFACTS_DIR)/dod-base-files.tar.gz

package-dod-base:
	@echo "Packaging base DoD files..."
	@mkdir -p $(ARTIFACTS_DIR)
	@bash scripts/package-dod-base.sh "$(DOD_BASE_SOURCE)" "$(DOD_BASE_OUTPUT)"
	@echo "Package created: $(DOD_BASE_OUTPUT)"

# Remove artifacts
clean:
	@echo "Cleaning artifacts..."
	rm -rf artifacts/

# Remove Docker images
clean-images: clean
	@echo "Removing Docker images..."
	-docker rmi ktp-base:latest 2>/dev/null
	-docker rmi ktp-rehlds:$(VERSION) 2>/dev/null
	-docker rmi ktp-amxx:$(VERSION) 2>/dev/null
	-docker rmi ktp-reapi:$(VERSION) 2>/dev/null
	-docker rmi ktp-curl:$(VERSION) 2>/dev/null
	-docker rmi ktp-plugins:$(VERSION) 2>/dev/null

# Clean up any leftover extraction containers
clean-containers:
	@echo "Cleaning extraction containers..."
	-docker rm ktp-extract-rehlds ktp-extract-amxx ktp-extract-reapi ktp-extract-curl ktp-extract-plugins 2>/dev/null

# List available artifact versions
list-artifacts:
	@echo "Available artifact versions:"
	@ls -d artifacts/*/ 2>/dev/null | xargs -n1 basename || echo "  (none)"

# ============================================
# Help
# ============================================

.PHONY: help

help:
	@echo "KTP Infrastructure Build System"
	@echo ""
	@echo "Build targets:"
	@echo "  make build           - Build all components"
	@echo "  make build-engine    - Build KTPReHLDS only"
	@echo "  make build-amxx      - Build KTPAMXX only"
	@echo "  make build-reapi     - Build KTPReAPI only"
	@echo "  make build-curl      - Build KTPAmxxCurl only"
	@echo "  make build-plugins   - Build all plugins"
	@echo ""
	@echo "Deploy targets:"
	@echo "  make deploy          - Deploy to all clusters"
	@echo "  make deploy-atlanta  - Deploy to Atlanta cluster"
	@echo "  make deploy-dallas   - Deploy to Dallas cluster"
	@echo "  make deploy-denver   - Deploy to Denver (test) cluster"
	@echo "  make deploy-plugins  - Deploy only plugins to all"
	@echo "  make configure-names - Configure server names (all clusters)"
	@echo ""
	@echo "Utility:"
	@echo "  make package-dod-base- Package base DoD files (maps, configs)"
	@echo "  make clean           - Remove build artifacts"
	@echo "  make clean-images    - Remove Docker images"
	@echo "  make clean-containers- Remove temp containers"
	@echo "  make list-artifacts  - List available versions"
	@echo ""
	@echo "Environment variables:"
	@echo "  VERSION              - Build version (default: YYYYMMDD)"
	@echo "  KTP_PROJECT_ROOT     - Path to KTP projects"

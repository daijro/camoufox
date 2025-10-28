include scripts/upstream.sh
export

cf_source_dir := camoufox-$(version)-$(release)
ff_source_tarball := firefox-$(version).source.tar.xz
ff_repo := git@github.com:mozilla-firefox/firefox.git

debs := python3 python3-dev python3-pip p7zip-full golang-go msitools wget aria2
rpms := python3 python3-devel p7zip golang msitools wget aria2
pacman := python python-pip p7zip go msitools wget aria2

.PHONY: build-launcher check-arch revert revert-checkpoint retag-baseline copy-additions edits run setup-local-dev bootstrap mozbootstrap dir \
        package-linux package-macos package-windows vcredist_arch patch unpatch \
        workspace check-arg edit-cfg ff-dbg tests tests-parallel update-ubo-assets tagged-checkpoint \
        git-fetch git-dir git-bootstrap check-not-git \
		lint lint-scripts lint-tests lint-lib \

help:
	@echo "Available targets:"
	@echo ""
	@echo "Tarball Workflow (original):"
	@echo "  fetch           - Fetch Firefox source tarball"
	@echo "  setup           - Setup Camoufox & local git repo for development"
	@echo "  dir             - Prepare source & apply patches"
	@echo "  bootstrap       - Set up build environment"
	@echo ""
	@echo "Git Workflow (preserves Firefox history, recommended for development):"
	@echo "  git-fetch       - Clone Firefox source from Mozilla (blobless clone)"
	@echo "  git-dir         - Setup git source & apply patches"
	@echo "  git-bootstrap   - Set up build environment"
	@echo ""
	@echo "Development:"
	@echo "  revert          - Reset to 'unpatched' tag (vanilla Firefox + additions)"
	@echo "  revert-checkpoint - Reset to 'checkpoint' tag (return to saved checkpoint)"
	@echo "  copy-additions  - Copy additions/ and settings/ to source (fast, no git operations)"
	@echo "  retag-baseline  - Rebuild 'unpatched' tag with latest additions/ changes (git only)"
	@echo "  tagged-checkpoint - Save current state with reusable 'checkpoint' tag"
	@echo "  edits           - Camoufox developer UI"
	@echo "  edit-cfg        - Edit camoufox.cfg"
	@echo "  workspace       - Sets the workspace to a patch, assuming its applied"
	@echo "  patch           - Apply a patch"
	@echo "  unpatch         - Remove a patch"
	@echo ""
	@echo "Building:"
	@echo "  build           - Build Camoufox"
	@echo "  set-target      - Change the build target with BUILD_TARGET"
	@echo "  package-linux   - Package Camoufox for Linux"
	@echo "  package-macos   - Package Camoufox for macOS"
	@echo "  package-windows - Package Camoufox for Windows"
	@echo "  run             - Run Camoufox"
	@echo ""
	@echo "Other:"
	@echo "  mozbootstrap    - Sets up mach"
	@echo "  build-launcher  - Build launcher"
	@echo "  clean           - Remove build artifacts"
	@echo "  distclean       - Remove everything including downloads"
	@echo "  setup-local-dev - Set up build directory for local Python library testing"
	@echo "  ff-dbg          - Setup vanilla Firefox with minimal patches"
	@echo "  tests           - Runs the Playwright tests"
	@echo "  tests-parallel  - Runs the Playwright tests in parallel (use workers=N to specify worker count)"
	@echo "  update-ubo-assets - Update the uBOAssets.json file"

_ARGS := $(wordlist 2,$(words $(MAKECMDGOALS)),$(MAKECMDGOALS))
$(eval $(_ARGS):;@:)

fetch:
	# Fetching private patches...
	@if [ -d "patches/private" ]; then \
		echo "Found patches/private. Skipping private patches fetch..."; \
	else \
		if [ -z "$$CAMOUFOX_PASSWD" ]; then \
			echo "CAMOUFOX_PASSWD environment variable not set. Skipping private patches..."; \
		else \
			echo "Fetching private patches..."; \
			mkdir -p patches/closedsrc; \
			if ! aria2c --dry-run "https://camoufox.com/pipeline/rev-$(closedsrc_rev).7z" 2>/dev/null; then \
				echo "No private patches found for this version"; \
				exit 1; \
			else \
				aria2c -o rev-$(closedsrc_rev).7z "https://camoufox.com/pipeline/rev-$(closedsrc_rev).7z" && \
				7z x -p"$$CAMOUFOX_PASSWD" rev-$(closedsrc_rev).7z -o./firefox/patches/closedsrc && \
				rm rev-$(closedsrc_rev).7z; \
			fi; \
		fi; \
	fi
	# Fetching the Firefox source tarball...
	aria2c -x16 -s16 -k1M -o $(ff_source_tarball) "https://archive.mozilla.org/pub/firefox/releases/$(version)/source/firefox-$(version).source.tar.xz"; \

setup-minimal:
	# Note: Only docker containers are intended to run this directly.
	# Run this before `make dir` or `make build` to avoid setting up a local git repo.
	if [ ! -f $(ff_source_tarball) ]; then \
		make fetch; \
	fi
	# Create new cf_source_dir
	rm -rf $(cf_source_dir)
	mkdir -p $(cf_source_dir)
	tar -xJf $(ff_source_tarball) -C $(cf_source_dir) --strip-components=1
	# Copy settings & additions
	cd $(cf_source_dir) && bash ../scripts/copy-additions.sh $(version) $(release)

setup: setup-minimal
	# Initialize local git repo for development
	cd $(cf_source_dir) && \
		git init -b main && \
		git add -f -A && \
		git commit -m "Initial commit" && \
		git tag -a unpatched -m "Initial commit"

ff-dbg: setup
	# Only apply patches to help debug vanilla Firefox
	make patch ./firefox/patches/chromeutil.patch
	make patch ./firefox/patches/browser-init.patch
	echo "LOCAL_INCLUDES += ['/camoucfg']" >> $(cf_source_dir)/dom/base/moz.build
	touch $(cf_source_dir)/_READY
	make checkpoint
	make build

revert:
	cd $(cf_source_dir) && git reset --hard unpatched && rm -f _READY browser/app/camoufox.exe.manifest

revert-checkpoint:
	cd $(cf_source_dir) && git reset --hard checkpoint && rm -f _READY browser/app/camoufox.exe.manifest

copy-additions:
	@echo "Copying additions/ and settings/ to source tree..."
	cd $(cf_source_dir) && bash ../scripts/copy-additions.sh $(version) $(release)
	@echo "✓ Files copied. Run 'make build' for incremental rebuild."

retag-baseline:
	@echo "Rebuilding 'unpatched' baseline with latest additions..."
	@cd $(cf_source_dir) && \
		if ! git rev-parse --verify unpatched^ >/dev/null 2>&1; then \
			echo "ERROR: Cannot find parent of 'unpatched' tag."; \
			echo "This target requires a Firefox git repository with history,"; \
			echo "not a tarball-based setup. Your setup is incompatible."; \
			exit 1; \
		fi
	cd $(cf_source_dir) && \
		git reset --hard unpatched^ && \
		git clean -dxf
	$(MAKE) copy-additions
	cd $(cf_source_dir) && \
		git add -A && \
		git commit -m "Add Camoufox additions (Firefox $(version) compatibility)" && \
		git tag -f -a unpatched -m "Initial commit with additions"
	@echo "✓ Baseline refreshed. 'unpatched' tag updated with latest additions."

dir:
	@if [ ! -d $(cf_source_dir) ]; then \
		make setup; \
	fi
	python3 scripts/patch.py $(version) $(release)
	touch $(cf_source_dir)/_READY

set-target:
	python3 scripts/patch.py $(version) $(release) --mozconfig-only

mozbootstrap:
	cd $(cf_source_dir) && MOZBUILD_STATE_PATH=$$HOME/.mozbuild ./mach --no-interactive bootstrap --application-choice=browser

bootstrap: dir
	(sudo apt-get -y install $(debs) || sudo dnf -y install $(rpms) || sudo pacman -Sy $(pacman))
	make mozbootstrap

# ============================================================================
# Git-based workflow (preserves Firefox git history)
# ============================================================================

# Safety check: prevent tarball workflow from destroying git repos
check-not-git:
	@if [ -d $(cf_source_dir)/.git ] && cd $(cf_source_dir) && git remote -v | grep -q "mozilla"; then \
		echo ""; \
		echo "ERROR: Git-based Firefox repo detected!"; \
		echo "This target will DESTROY your git history."; \
		echo ""; \
		echo "Use git workflow instead:"; \
		echo "  make git-dir       # Setup git-based source"; \
		echo "  make git-bootstrap # Bootstrap build system"; \
		echo ""; \
		exit 1; \
	fi

# Clone Firefox source from Mozilla
git-fetch:
	@if [ -d $(cf_source_dir) ]; then \
		echo "$(cf_source_dir) already exists. Skipping clone."; \
		echo "To re-clone, run: rm -rf $(cf_source_dir)"; \
		exit 0; \
	fi
	@echo "Cloning Firefox source (commit $(ff_commit))..."
	@echo "Using blobless clone for faster download..."
	git clone --filter=blob:none $(ff_repo) $(cf_source_dir)
	cd $(cf_source_dir) && git checkout $(ff_commit)
	@echo "✓ Firefox source ready at $(cf_source_dir)"

# Setup git-based source and apply patches
git-dir:
	@if [ ! -d $(cf_source_dir) ]; then \
		echo "Firefox source not found. Run 'make git-fetch' first."; \
		exit 1; \
	fi
	@if [ ! -d $(cf_source_dir)/.git ]; then \
		echo "ERROR: $(cf_source_dir) is not a git repo."; \
		echo "Use 'make dir' for tarball workflow."; \
		exit 1; \
	fi
	@if [ -f $(cf_source_dir)/_READY ]; then \
		echo "Already setup (found _READY). Run 'make revert' to reset."; \
		exit 0; \
	fi
	@echo "Setting up git-based Firefox source..."
	$(MAKE) copy-additions
	cd $(cf_source_dir) && \
		git add -A && \
		git commit -m "Add Camoufox additions (Firefox $(version) compatibility)" && \
		git tag -f -a unpatched -m "Initial commit with additions"
	python3 scripts/patch.py $(version) $(release)
	touch $(cf_source_dir)/_READY
	@echo "✓ Setup complete! Run 'make git-bootstrap' next."

# Bootstrap for git workflow
git-bootstrap:
	@if [ ! -f $(cf_source_dir)/_READY ]; then \
		echo "ERROR: Run 'make git-dir' first"; \
		exit 1; \
	fi
	(sudo apt-get -y install $(debs) || sudo dnf -y install $(rpms) || sudo pacman -Sy $(pacman))
	make mozbootstrap
	@echo "✓ Bootstrap complete!"
	@echo "Now build with: python3 multibuild.py --target linux --arch x86_64"

# Protect dangerous tarball targets
setup-minimal: check-not-git
setup: check-not-git
distclean: check-not-git

diff:
	@cd $(cf_source_dir) && git diff $(_ARGS)

checkpoint:
	cd $(cf_source_dir) && git commit -m "Checkpoint" -a -uno

tagged-checkpoint:
	cd $(cf_source_dir) && git commit -m "Checkpoint" -a -uno && git tag -f checkpoint

clean:
	cd $(cf_source_dir) && git clean -fdx && ./mach clobber
	make revert

distclean:
	rm -rf $(cf_source_dir) $(ff_source_tarball)

build: unbusy
	@if [ ! -f $(cf_source_dir)/_READY ]; then \
		make dir; \
	fi
	cd $(cf_source_dir) && ./mach build $(_ARGS)

edits:
	python3 ./scripts/developer.py $(version) $(release)

check-arch:
	@if ! echo "x86_64 i686 arm64" | grep -qw "$(arch)"; then \
		echo "Error: Invalid arch value. Must be x86_64, i686, or arm64."; \
		exit 1; \
	fi

package-linux:
	python3 scripts/package.py linux \
		--includes \
			firefox/settings/chrome.css \
			firefox/settings/properties.json \
			firefox/bundle/fontconfigs \
		--version $(version) \
		--release $(release) \
		--arch $(arch) \
		--fonts windows macos linux

package-macos:
	python3 scripts/package.py macos \
		--includes \
			firefox/settings/chrome.css \
			firefox/settings/properties.json \
		--version $(version) \
		--release $(release) \
		--arch $(arch) \
		--fonts windows linux

package-windows:
	python3 scripts/package.py windows \
		--includes \
			firefox/settings/chrome.css \
			firefox/settings/properties.json \
			~/.mozbuild/vs/VC/Redist/MSVC/14.38.33135/$(vcredist_arch)/Microsoft.VC143.CRT/*.dll \
		--version $(version) \
		--release $(release) \
		--arch $(arch) \
		--fonts macos linux

run:
	cd $(cf_source_dir) \
	&& rm -rf ~/.camoufox obj-x86_64-pc-linux-gnu/tmp/profile-default \
	&& CAMOU_CONFIG=$${CAMOU_CONFIG:-'{}'} \
	&& if [ "$$CAMOU_CONFIG" = "{}" ]; then \
		CAMOU_CONFIG='{"debug": true}'; \
	else \
		CAMOU_CONFIG="$${CAMOU_CONFIG%?}, \"debug\": true}"; \
	fi \
	&& ./mach run $(args)

setup-local-dev:
	@echo "Setting up local development environment..."
	@if [ ! -d $(cf_source_dir)/obj-x86_64-pc-linux-gnu/dist/bin ]; then \
		echo "Error: Build directory not found. Run 'make build' first."; \
		exit 1; \
	fi
	@echo "Creating symlinks for bundled resources..."
	cd $(cf_source_dir)/obj-x86_64-pc-linux-gnu/dist/bin && \
		ln -sf ../../../../bundle/fontconfigs fontconfigs && \
		cd fonts && \
		ln -sf ../../../../../bundle/fonts/linux linux && \
		ln -sf ../../../../../bundle/fonts/windows windows && \
		ln -sf ../../../../../bundle/fonts/macos macos
	@echo "Creating version.json..."
	@echo '{"version":"$(version)","release":"$(release)"}' > $(cf_source_dir)/obj-x86_64-pc-linux-gnu/dist/bin/version.json
	@echo "Setting up cache symlink..."
	@mkdir -p ~/.cache
	@if [ -L ~/.cache/camoufox ] || [ -e ~/.cache/camoufox ]; then \
		echo "~/.cache/camoufox already exists (skipping)"; \
	else \
		ln -s $(PWD)/$(cf_source_dir)/obj-x86_64-pc-linux-gnu/dist/bin ~/.cache/camoufox && \
		echo "Created ~/.cache/camoufox symlink"; \
	fi
	@echo "✓ Local dev setup complete! You can now use the Camoufox Python library with your local build."

edit-cfg:
	@if [ ! -f $(cf_source_dir)/obj-x86_64-pc-linux-gnu/dist/bin/camoufox.cfg ]; then \
		echo "Error: camoufox.cfg not found. Apply config.patch first."; \
		exit 1; \
	fi
	$(EDITOR) $(cf_source_dir)/obj-x86_64-pc-linux-gnu/dist/bin/camoufox.cfg

check-arg:
	@if [ -z "$(_ARGS)" ]; then \
		echo "Error: No file specified. Usage: make <command> ./firefox/patches/file.patch"; \
		exit 1; \
	fi

grep:
	grep "$(_ARGS)" -r ./firefox/patches/*.patch

patch:
	@make check-arg $(_ARGS);
	cd $(cf_source_dir) && patch -p1 -i ../$(_ARGS)

unpatch:
	@make check-arg $(_ARGS);
	cd $(cf_source_dir) && patch -p1 -R -i ../$(_ARGS)

workspace:
	@make check-arg $(_ARGS);
	@if (cd $(cf_source_dir) && patch -p1 -R --dry-run --force -i ../$(_ARGS)) > /dev/null 2>&1; then \
		echo "Patch is already applied. Unapplying..."; \
		make unpatch $(_ARGS); \
	else \
		echo "Patch is not applied. Proceeding with application..."; \
	fi
	make checkpoint || true
	make patch $(_ARGS)

tests:
	cd ./tests && \
	bash run-tests.sh \
		--executable-path ../$(cf_source_dir)/obj-x86_64-pc-linux-gnu/dist/bin/camoufox-bin \
		$(if $(filter true,$(headful)),--headful,)

tests-parallel:
	cd ./tests && \
	PYTEST_WORKERS=$(if $(workers),$(workers),auto) bash run-tests.sh \
		--executable-path ../$(cf_source_dir)/obj-x86_64-pc-linux-gnu/dist/bin/camoufox-bin \
		$(if $(filter true,$(headful)),--headful,)

unbusy:
	rm -rf $(cf_source_dir)/obj-x86_64-pc-linux-gnu/dist/bin/camoufox-bin \
		$(cf_source_dir)/obj-x86_64-pc-linux-gnu/dist/bin/camoufox \
		$(cf_source_dir)/obj-x86_64-pc-linux-gnu/dist/bin/launch

path:
	@realpath $(cf_source_dir)/obj-x86_64-pc-linux-gnu/dist/bin/camoufox-bin

update-ubo-assets:
	bash ./scripts/update-ubo-assets.sh

upload:
	# ===============================
	# This is only for internal use. You can ignore this.
	# ===============================

	@test -f .passwd || { echo "Error: .passwd file not found"; exit 1; }
	@mkdir -p ../camoufox-web/internal
	@rm -rf ../camoufox-web/pipeline/rev-$(closedsrc_rev).7z
	7z a "-p$$(cat ./.passwd)" -mhe=on ../camoufox-web/pipeline/rev-$(closedsrc_rev).7z "./firefox/patches/private/*.patch"

vcredist_arch := $(shell echo $(arch) | sed 's/x86_64/x64/' | sed 's/i686/x86/')

lint-scripts:
	cd ./scripts && uv run ruff check .
	cd ./scripts && uv run mypy .

lint-tests:
	cd ./tests && uv run ruff check .

lint-lib:
	cd ./pythonlib && uv run ruff check .

lint: lint-scripts lint-tests lint-lib

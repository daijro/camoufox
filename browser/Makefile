include upstream.sh
export

cf_source_dir := camoufox-$(version)-$(release)
ff_source_tarball := firefox-$(version).source.tar.xz

.PHONY: help fetch setup-minimal setup ff-dbg revert fetch-fonts fonts-extract fonts-check \
        fonts-clean dir set-target mozbootstrap setup-macos-sdk bootstrap diff first-checkpoint \
        checkpoint clean distclean build package-linux package-macos package-windows run edit-cfg \
        check-arg grep patch unpatch workspace tests stage-fonts unbusy path update-ubo-assets \
        generate-assets-car

help:
	@echo "Available targets:"
	@echo "  fetch               - Fetch the Firefox source code"
	@echo "  setup-minimal       - Extract Firefox and copy additions, without a git repo (Docker)"
	@echo "  setup               - Setup Camoufox & local git repo for development"
	@echo "  bootstrap           - Install host dependencies and set up mach"
	@echo "  mozbootstrap        - Sets up mach"
	@echo "  dir                 - Prepare Camoufox source directory with BUILD_TARGET"
	@echo "  revert              - Kill all working changes"
	@echo "  clean               - Remove build artifacts"
	@echo "  distclean           - Remove everything including downloads"
	@echo "  build               - Build Camoufox"
	@echo "  set-target          - Change the build target with BUILD_TARGET"
	@echo "  setup-macos-sdk     - Download the macOS SDK for cross-compilation"
	@echo "  fetch-fonts         - Download and verify the font bundle"
	@echo "  fonts-extract       - Unpack the font bundle to bundle/fonts/"
	@echo "  fonts-check         - Verify the font bundle against its pin"
	@echo "  fonts-clean         - Remove the downloaded and extracted font bundle"
	@echo "  stage-fonts         - Stage the font bundle into an unpackaged build"
	@echo "  package-linux       - Package Camoufox for Linux"
	@echo "  package-macos       - Package Camoufox for macOS"
	@echo "  package-windows     - Package Camoufox for Windows"
	@echo "  run                 - Run Camoufox"
	@echo "  path                - Print the path of the built camoufox-bin"
	@echo "  edit-cfg            - Edit camoufox.cfg"
	@echo "  ff-dbg              - Setup vanilla Firefox with minimal patches"
	@echo "  patch               - Apply a patch"
	@echo "  unpatch             - Remove a patch"
	@echo "  workspace           - Sets the workspace to a patch, assuming its applied"
	@echo "  first-checkpoint    - Commit the tree and tag it as the base for diff"
	@echo "  checkpoint          - Commit tracked changes in the tree"
	@echo "  diff                - Diff the tree against first-checkpoint"
	@echo "  grep                - Search the patches for a string"
	@echo "  tests               - Runs the Playwright tests"
	@echo "  update-ubo-assets   - Update the uBOAssets.json file"
	@echo "  generate-assets-car - Regenerate the macOS Assets.car icon catalog"

_ARGS := $(wordlist 2,$(words $(MAKECMDGOALS)),$(MAKECMDGOALS))
$(eval $(_ARGS):;@:)

fetch:
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
	make patch ./patches/chromeutil.patch
	make patch ./patches/browser-init.patch
	echo "LOCAL_INCLUDES += ['/camoucfg']" >> $(cf_source_dir)/dom/base/moz.build
	touch $(cf_source_dir)/_READY
	make checkpoint
	make build

revert:
	cd $(cf_source_dir) && git reset --hard unpatched

# The font bundle is a release asset, not repo content (see
# scripts/fetch-fonts.py for why). fetch-fonts downloads and verifies the
# archive; fonts-extract unpacks it to bundle/fonts/, which every font tool and
# `make package-*` needs. Both are no-ops once satisfied, so they are cheap to
# depend on.
fetch-fonts:
	python3 scripts/fetch-fonts.py

fonts-extract:
	python3 scripts/fetch-fonts.py --extract

fonts-check:
	python3 scripts/fetch-fonts.py --check

fonts-clean:
	python3 scripts/fetch-fonts.py --clean

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

setup-macos-sdk:
	@if [ "$$(uname -s)" != "Darwin" ] && [ ! -f "$$HOME/.mozbuild/MacOSX26.5.sdk/SDKSettings.plist" ]; then \
		echo "Downloading macOS 26.5 SDK..."; \
		cd $(cf_source_dir) && env -u MOZ_AUTOMATION ./mach --no-interactive python --virtualenv build \
			taskcluster/scripts/misc/unpack-sdk.py \
			https://swcdn.apple.com/content/downloads/09/08/047-91568-A_Y1CFZWQCD4/4xekpyz43i26dbp4enxfro8eb1q7wiujh5/CLTools_macOSNMOS_SDK.pkg \
			5db8b5a06a489a7d3ec587ebb7e01be55163128029923fc24edcad47faecd67830193c0d91e2643ee0e92f2ccca37adf20e4c42cf8de5784666f8663638b5cc5 \
			Library/Developer/CommandLineTools/SDKs/MacOSX26.5.sdk \
			"$$HOME/.mozbuild/MacOSX26.5.sdk"; \
	fi

bootstrap: dir
	bash scripts/install-deps.sh
	make mozbootstrap

diff:
	@cd $(cf_source_dir) && git diff first-checkpoint $(_ARGS)

first-checkpoint:
	cd $(cf_source_dir) && \
		git tag -d first-checkpoint || true && \
		git add -A && \
		git reset -q _READY || true && \
		git commit -m "Checkpoint" -uno && \
		git tag -a first-checkpoint -m "Checkpoint"

checkpoint:
	cd $(cf_source_dir) && git commit -m "Checkpoint" -uno

clean:
	@if [ -e "$(cf_source_dir)/.git" ]; then \
		cd "$(cf_source_dir)" && ./mach clobber && git clean -fdx; \
		$(MAKE) revert; \
	else \
		echo "No git repo found in $(cf_source_dir); re-extracting Firefox source..."; \
		rm -rf "$(cf_source_dir)"; \
		$(MAKE) setup-minimal; \
	fi

distclean:
	rm -rf $(cf_source_dir) $(ff_source_tarball)

build: unbusy
	@if [ ! -f $(cf_source_dir)/_READY ]; then \
		make dir; \
	fi
	cd $(cf_source_dir) && ./mach build $(_ARGS)

package-linux: fonts-extract
	python3 scripts/package.py linux \
		--includes \
			settings/chrome.css \
			settings/properties.json \
			bundle/fontconfig \
		--version $(version) \
		--release $(release) \
		--arch $(arch) \
		--fonts windows macos linux

package-macos: fonts-extract
	python3 scripts/package.py macos \
		--includes \
			settings/chrome.css \
			settings/properties.json \
		--version $(version) \
		--release $(release) \
		--arch $(arch) \
		--fonts windows macos linux

package-windows: fonts-extract
	python3 scripts/package.py windows \
		--includes \
			settings/chrome.css \
			settings/properties.json \
			~/.mozbuild/vs/VC/Redist/MSVC/*/$(vcredist_arch)/Microsoft.VC*.CRT/*.dll \
		--version $(version) \
		--release $(release) \
		--arch $(arch) \
		--fonts windows macos linux

run:
	cd $(cf_source_dir) \
	&& rm -rf ~/.camoufox obj-x86_64-pc-linux-gnu/tmp/profile-default \
	&& CAMOU_CONFIG=$${CAMOU_CONFIG:-'{}'} \
	&& CAMOU_CONFIG="$${CAMOU_CONFIG%?}, \"debug\": true}" ./mach run $(args)

edit-cfg:
	@if [ ! -f $(cf_source_dir)/obj-x86_64-pc-linux-gnu/dist/bin/camoufox.cfg ]; then \
		echo "Error: camoufox.cfg not found. Apply config.patch first."; \
		exit 1; \
	fi
	$(EDITOR) $(cf_source_dir)/obj-x86_64-pc-linux-gnu/dist/bin/camoufox.cfg

check-arg:
	@if [ -z "$(_ARGS)" ]; then \
		echo "Error: No file specified. Usage: make <command> ./patches/file.patch"; \
		exit 1; \
	fi

grep:
	grep "$(_ARGS)" -r ./patches/*.patch

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
	make first-checkpoint || true
	make patch $(_ARGS)

# The Playwright suite: upstream playwright-python at the tag ci/versions.py
# resolves for this browser, fetched fresh, plus tests/playwright/camoufox/. The
# ci package runs from the repo root. The first run builds a virtualenv under
# .ci-work/ and is slow; later runs reuse it.
tests:
	cd .. && python3 -m ci.run_playwright \
		--binary browser/$(cf_source_dir)/obj-x86_64-pc-linux-gnu/dist/bin/camoufox-bin \
		$(if $(filter true,$(headful)),--headful,)

# Lets tests/playwright/patches/*.py run against an unpackaged build. A fresh
# checkout has no bundle/fonts/, and fonts-extract is a no-op once it does.
stage-fonts: fonts-extract
	bash scripts/stage-fonts.sh $(version) $(release)

unbusy:
	rm -rf $(cf_source_dir)/obj-x86_64-pc-linux-gnu/dist/bin/camoufox-bin \
		$(cf_source_dir)/obj-x86_64-pc-linux-gnu/dist/bin/camoufox

path:
	@realpath $(cf_source_dir)/obj-x86_64-pc-linux-gnu/dist/bin/camoufox-bin

update-ubo-assets:
	bash ./scripts/update-ubo-assets.sh

generate-assets-car:
	bash ./scripts/generate-assets-car.sh

vcredist_arch := $(shell echo $(arch) | sed 's/x86_64/x64/' | sed 's/i686/x86/')

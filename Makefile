include upstream.sh
export

cf_source_dir := camoufox-$(version)-$(release)
ff_source_tarball := firefox-$(version).source.tar.xz

debs := python3 python3-dev python3-pip p7zip-full golang-go msitools wget aria2c
rpms := python3 python3-devel p7zip golang msitools wget aria2c
pacman := python python-pip p7zip go msitools wget aria2c

.PHONY: help fetch setup setup-minimal clean distclean build package build-launcher check-arch revert edits run bootstrap mozbootstrap dir package-common package-linux package-macos package-windows

help:
	@echo "Available targets:"
	@echo "  fetch           - Fetch the Firefox source code"
	@echo "  setup           - Setup Camoufox & local git repo for development"
	@echo "  bootstrap       - Set up build environment"
	@echo "  mozbootstrap    - Sets up mach"
	@echo "  dir             - Prepare Camoufox source directory with BUILD_TARGET"
	@echo "  revert          - Kill all working changes"
	@echo "  edits           - Camoufox developer UI"
	@echo "  build-launcher  - Build launcher"
	@echo "  clean           - Remove build artifacts"
	@echo "  distclean       - Remove everything including downloads"
	@echo "  build           - Build Camoufox"
	@echo "  package-linux   - Package Camoufox for Linux"
	@echo "  package-macos   - Package Camoufox for macOS"
	@echo "  package-windows - Package Camoufox for Windows"
	@echo "  run             - Run Camoufox"

fetch:
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

revert:
	cd $(cf_source_dir) && git reset --hard unpatched

dir:
	@if [ ! -d $(cf_source_dir) ]; then \
		make setup; \
	fi
	make clean
	python3 scripts/patch.py $(version) $(release)
	touch $(cf_source_dir)/_READY

mozbootstrap:
	cd $(cf_source_dir) && MOZBUILD_STATE_PATH=$$HOME/.mozbuild ./mach --no-interactive bootstrap --application-choice=browser

bootstrap: dir
	(sudo apt-get -y install $(debs) || sudo dnf -y install $(rpms) || sudo pacman -Sy $(pacman))
	make mozbootstrap

diff:
	cd $(cf_source_dir) && git diff

checkpoint:
	cd $(cf_source_dir) && git commit -m "Checkpoint" -a

clean:
	cd $(cf_source_dir) && git clean -fdx && ./mach clobber
	make revert

distclean:
	rm -rf $(cf_source_dir) $(ff_source_tarball)

build:
	@if [ ! -f $(cf_source_dir)/_READY ]; then \
		make dir; \
	fi
	cd $(cf_source_dir) && ./mach build

edits:
	python ./scripts/developer.py

check-arch:
	@if [ "$(arch)" != "x64" ] && [ "$(arch)" != "x86" ] && [ "$(arch)" != "arm64" ]; then \
		echo "Error: Invalid arch value. Must be x64, x86, or arm64."; \
		exit 1; \
	fi

build-launcher: check-arch
	cd launcher && ./build.sh $(arch) $(os)

package-common: check-arch
	cd $(cf_source_dir) && cat browser/locales/shipped-locales | xargs ./mach package-multi-locale --locales
	cp -v $(cf_source_dir)/obj-*/dist/camoufox-$(version)-$(release).*.* .

package-linux: package-common
	make build-launcher arch=$(arch) os=linux;
	python3 scripts/package.py linux \
		--includes \
			settings/chrome.css \
			bundle/fontconfigs \
		--version $(version) \
		--release $(release) \
		--arch $(arch) \
		--fonts windows macos linux

package-macos: package-common
	make build-launcher arch=$(arch) os=macos;
	python3 scripts/package.py macos \
		--includes \
			settings/chrome.css \
		--version $(version) \
		--release $(release) \
		--arch $(arch) \
		--fonts windows linux

package-windows: package-common
	make build-launcher arch=$(arch) os=windows;
	python3 scripts/package.py windows \
		--includes \
			settings/chrome.css \
			~/.mozbuild/vs/VC/Redist/MSVC/14.38.33135/$(arch)/Microsoft.VC143.CRT/*.dll \
		--version $(version) \
		--release $(release) \
		--arch $(arch) \
		--fonts macos linux

run:
	cd $(cf_source_dir) && rm -rf ~/.camoufox && ./mach run

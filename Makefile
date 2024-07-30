include upstream.sh
export

cf_source_dir := camoufox-$(version)-$(release)

debs := python3 python3-dev python3-pip p7zip-full golang-go msitools wget
rpms := python3 python3-devel p7zip golang msitools wget
pacman := python python-pip p7zip go msitools wget

.PHONY: help fetch clean distclean build package build-launcher check-arch revert edits run bootstrap mozbootstrap dir package-common package-linux package-macos package-windows

help:
	@echo "Available targets:"
	@echo "  fetch           - Clone Firefox source code"
	@echo "  bootstrap       - Set up build environment"
	@echo "  mozbootstrap    - Sets up mach"
	@echo "  dir             - Prepare Camoufox source directory"
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
	git clone --depth 1 --branch $(BASE_BRANCH) --single-branch $(REMOTE_URL) $(cf_source_dir)
	cd $(cf_source_dir) && git fetch --depth 1 origin $(BASE_REVISION)
	make revert

revert:
	cd $(cf_source_dir) && git reset --hard $(BASE_REVISION)
	python3 scripts/init-patch.py $(version) $(release)

dir:
	@if [ ! -d $(cf_source_dir) ]; then \
		make fetch; \
	fi
	make clean
	python3 scripts/patch.py $(version) $(release)

mozbootstrap:
	cd $(cf_source_dir) && MOZBUILD_STATE_PATH=$$HOME/.mozbuild ./mach --no-interactive bootstrap --application-choice=browser

bootstrap: dir
	(sudo apt-get -y install $(debs) || sudo dnf -y install $(rpms) || sudo pacman -Sy $(pacman))
	make mozbootstrap

clean:
	cd $(cf_source_dir) && git clean -fdx && ./mach clobber
	make revert

distclean: clean
	rm -rf $(cf_source_dir)

build:
	@if [ ! -d $(cf_source_dir) ]; then \
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

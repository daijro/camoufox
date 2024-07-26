include upstream.sh
export

ff_source_dir := firefox-$(version)
lw_source_dir := camoufox-$(version)-$(release)

debs := python3 python3-dev python3-pip p7zip-full golang-go
rpms := python3 python3-devel p7zip golang
pacman := python python-pip p7zip go

.PHONY: help fetch clean distclean build package build-launcher check-arch edits run bootstrap dir package-common package-linux package-macos package-windows

help:
	@echo "Available targets:"
	@echo "  fetch           - Clone Firefox source code"
	@echo "  bootstrap       - Set up build environment"
	@echo "  dir             - Prepare Camoufox source directory"
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
	git clone --depth 1 --branch $(BASE_BRANCH) --single-branch $(REMOTE_URL) $(ff_source_dir)
	cd $(ff_source_dir) && git fetch --depth 1 origin $(BASE_REVISION) && git checkout $(BASE_REVISION)

dir:
	@if [ ! -d $(ff_source_dir) ]; then \
		make fetch; \
	fi
	rm -rf $(lw_source_dir)
	cp -r $(ff_source_dir) $(lw_source_dir)
	python3 scripts/patch.py $(version) $(release)

bootstrap: dir
	(sudo apt-get -y install $(debs) || sudo dnf -y install $(rpms) || sudo pacman -Sy $(pacman))
	cd $(lw_source_dir) && MOZBUILD_STATE_PATH=$$HOME/.mozbuild ./mach --no-interactive bootstrap --application-choice=browser

clean:
	rm -rf $(lw_source_dir)

distclean: clean
	rm -rf $(ff_source_dir)

build:
	@if [ ! -d $(lw_source_dir) ]; then \
		make dir; \
	fi
	cd $(lw_source_dir) && ./mach build

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
	cd $(lw_source_dir) && cat browser/locales/shipped-locales | xargs ./mach package-multi-locale --locales
	cp -v $(lw_source_dir)/obj-*/dist/camoufox-$(version)-$(release).*.* .

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
	cd $(lw_source_dir) && rm -rf ~/.camoufox && ./mach run

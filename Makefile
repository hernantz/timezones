PYTHON ?= python3
BUILD ?= builddir
ENTRY ?= src.app

setup:
	meson setup $(BUILD)

build:
	meson compile -C $(BUILD)

run: build
	@glib-compile-schemas data --targetdir=$(BUILD)
	@export PYTHONPATH="$$(pwd)"; \
	export GSETTINGS_SCHEMA_DIR="$$(pwd)/$(BUILD)"; \
	export TIMEZONES_BUILD_DIR="$(BUILD)"; \
	export TIMEZONES_LOCALEDIR="$$(pwd)/$(BUILD)/po"; \
	export TIMEZONES_DEV=1; \
	$(PYTHON) -m $(ENTRY)

install: build
	meson install -C $(BUILD)

clean:
	rm -rf $(BUILD)

test:
	$(PYTHON) -m unittest discover -s tests -t .

# Regenerate po/timezones.pot from the sources, then merge it into every
# po/<lang>.po, so translators start from the current strings.
pot: build
	meson compile -C $(BUILD) timezones-pot
	meson compile -C $(BUILD) timezones-update-po

# src/VERSION is the source of truth (meson and src/const.py both read it);
# the rpm spec cannot read a file at parse time, so it is rewritten here.
SPEC = packaging/rpm/timezones.spec
PKGBUILD = packaging/arch/PKGBUILD
# Flathub and software centres show the newest <release> here as the version.
METAINFO = data/appdata/io.github.hernantz.timezones.metainfo.xml
PACKAGER = $(shell git config user.name) <$(shell git config user.email)>
NOTES_TODO = TODO: release notes

version:
	@cat src/VERSION

# Edits the files only; the notes still need writing, then `make tag`.
release:
	@test -n "$(VERSION)" || { echo "usage: make release VERSION=x.y.z"; exit 1; }
	@echo "$(VERSION)" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$$' || \
		{ echo "VERSION must look like x.y.z, got '$(VERSION)'"; exit 1; }
	@! git rev-parse -q --verify "refs/tags/v$(VERSION)" >/dev/null || \
		{ echo "tag v$(VERSION) already exists"; exit 1; }
	@! grep -q 'release version="$(VERSION)"' $(METAINFO) || \
		{ echo "$(VERSION) is already listed in $(METAINFO)"; exit 1; }
	@echo "$(VERSION)" > src/VERSION
	@sed -i -e 's/^Version:.*/Version:        $(VERSION)/' \
		-e 's/^Release:.*/Release:        1%{?dist}/' \
		-e 's|^%changelog$$|&\n* '"$$(LC_ALL=C date '+%a %b %d %Y')"' $(PACKAGER) - $(VERSION)-1\n- Release $(VERSION).\n|' \
		$(SPEC)
	@sed -i -e 's/^pkgver=.*/pkgver=$(VERSION)/' -e 's/^pkgrel=.*/pkgrel=1/' $(PKGBUILD)
	@sed -i 's|^  <releases>$$|&\n    <release version="$(VERSION)" date="'"$$(date +%F)"'">\n      <description>\n        <p>$(NOTES_TODO)</p>\n      </description>\n    </release>|' \
		$(METAINFO)
	@grep -n '^Version:' $(SPEC)
	@echo "src/VERSION -> $(VERSION)"
	@echo "write the notes in $(METAINFO) (and the spec %changelog), review, then: make tag"

# Commits the release files and tags them; pushing is left to you, since a
# pushed tag is what COPR and Flathub build from.
tag:
	@v=$$(cat src/VERSION); \
	! git rev-parse -q --verify "refs/tags/v$$v" >/dev/null || \
		{ echo "tag v$$v already exists"; exit 1; }; \
	grep -q "release version=\"$$v\"" $(METAINFO) || \
		{ echo "no <release> for $$v in $(METAINFO); run make release first"; exit 1; }; \
	! grep -q '$(NOTES_TODO)' $(METAINFO) || \
		{ echo "write the release notes in $(METAINFO) first"; exit 1; }; \
	other=$$(git status --porcelain | grep -v -E ' (src/VERSION|$(SPEC)|$(PKGBUILD)|$(METAINFO)|po/[^/]+\.po)$$'); \
	test -z "$$other" || { echo "uncommitted changes outside the release files:"; echo "$$other"; exit 1; }; \
	{ git diff --quiet HEAD || git commit -q -am "Release $$v"; } && \
	git tag -a "v$$v" -m "Release $$v" && \
	echo "tagged v$$v at $$(git rev-parse HEAD)" && \
	echo "next: git push --follow-tags (CI publishes the Flatpak repo, the GitHub Release, COPR and the AUR)"

# packaging/flatpak builds the working tree; Flathub only accepts a pinned
# source, so its manifest is this one with the app pointed at the release tag.
# The output goes in the flathub/io.github.hernantz.timezones repository.
FLATPAK_MANIFEST = packaging/flatpak/io.github.hernantz.timezones.json
FLATHUB_MANIFEST = build-flathub/io.github.hernantz.timezones.json
GIT_URL = https://github.com/hernantz/timezones.git

flathub:
	@v=$$(cat src/VERSION); \
	commit=$$(git rev-list -n 1 "v$$v" 2>/dev/null) || \
		{ echo "no tag v$$v; run make release and make tag first"; exit 1; }; \
	mkdir -p $(dir $(FLATHUB_MANIFEST)) && \
	jq --arg url "$(GIT_URL)" --arg tag "v$$v" --arg commit "$$commit" \
		'(.modules[] | select(.name == "timezones") | .sources) = [{type: "git", url: $$url, tag: $$tag, commit: $$commit}]' \
		$(FLATPAK_MANIFEST) > $(FLATHUB_MANIFEST) && \
	echo "$(FLATHUB_MANIFEST): v$$v at $$commit"

# Our own Flatpak repository, served from GitHub Pages; CI publishes $(SITE).
# Users add it with the .flatpakref; the runtime still comes from Flathub.
FLATPAK_URL = https://hernantz.github.io/timezones
FLATPAK_BRANCH = stable
FLATHUB_REPO = https://dl.flathub.org/repo/flathub.flatpakrepo
# The repository's public key, committed; CI signs with the matching secret key.
REPO_KEY = packaging/flatpak/repo.gpg
SITE = build-site
GPG_KEY ?=
GPG_HOMEDIR ?=
GPG_ARGS = $(if $(GPG_KEY),--gpg-sign=$(GPG_KEY)) $(if $(GPG_HOMEDIR),--gpg-homedir=$(GPG_HOMEDIR))
APP_ID = io.github.hernantz.timezones

flatpak-repo:
	@test -n "$(GPG_KEY)" || { echo "usage: make flatpak-repo GPG_KEY=<key id>"; exit 1; }
	@test -f $(REPO_KEY) || { echo "missing $(REPO_KEY), the public key users verify with"; exit 1; }
	rm -rf $(SITE) && mkdir -p $(SITE)
	flatpak-builder --force-clean --disable-rofiles-fuse --default-branch=$(FLATPAK_BRANCH) \
		--repo=$(SITE)/repo $(GPG_ARGS) build-flatpak $(FLATPAK_MANIFEST)
	flatpak build-update-repo --generate-static-deltas --prune --title=Timezones \
		--default-branch=$(FLATPAK_BRANCH) $(GPG_ARGS) $(SITE)/repo
	@key=$$(base64 -w0 $(REPO_KEY)); \
	printf '%s\n' '[Flatpak Repo]' 'Title=Timezones' 'Url=$(FLATPAK_URL)/repo/' \
		'Homepage=https://github.com/hernantz/timezones' "GPGKey=$$key" \
		> $(SITE)/timezones.flatpakrepo; \
	printf '%s\n' '[Flatpak Ref]' 'Name=$(APP_ID)' 'Branch=$(FLATPAK_BRANCH)' 'Title=Timezones' \
		'Url=$(FLATPAK_URL)/repo/' 'SuggestRemoteName=timezones' 'IsRuntime=false' \
		'RuntimeRepo=$(FLATHUB_REPO)' "GPGKey=$$key" \
		> $(SITE)/$(APP_ID).flatpakref
	@sed -e 's|@URL@|$(FLATPAK_URL)|g' -e 's|@APP_ID@|$(APP_ID)|g' \
		packaging/flatpak/index.html > $(SITE)/index.html
	@echo "$(SITE): repo, .flatpakrepo, .flatpakref and index.html"

# A single-file installer for GitHub Releases. It carries the repo's key and
# URL, so an install from it keeps updating from $(FLATPAK_URL).
bundle:
	@test -d $(SITE)/repo || { echo "no $(SITE)/repo; run make flatpak-repo first"; exit 1; }
	flatpak build-bundle --runtime-repo=$(FLATHUB_REPO) --repo-url=$(FLATPAK_URL)/repo/ \
		--gpg-keys=$(REPO_KEY) $(SITE)/repo timezones-$$(cat src/VERSION).flatpak \
		$(APP_ID) $(FLATPAK_BRANCH)
	@echo "timezones-$$(cat src/VERSION).flatpak"

# FlatPark never builds apps: it unpacks a prebuilt tree, published here as a
# release asset, into /app/extra at install time. The tree is built for that
# final location (the launcher, locale dir and libgweather's data paths are all
# absolute), from the same modules as the Flatpak manifest.
FLATPARK_PREFIX = /app/extra/timezones
FLATPARK_ARCH ?= $(shell flatpak --default-arch)
FLATPARK_PAYLOAD = timezones-$$(cat src/VERSION)-flatpark-$(FLATPARK_ARCH).tar.xz

flatpark-payload:
	@mkdir -p build-flatpark
	jq --arg p "$(FLATPARK_PREFIX)" --arg root "$(CURDIR)" -f packaging/flatpark/payload.jq \
		$(FLATPAK_MANIFEST) > build-flatpark/payload.json
	flatpak-builder --force-clean --disable-rofiles-fuse --build-only \
		--state-dir=.flatpak-builder build-flatpark/build build-flatpark/payload.json
	tar -C build-flatpark/build/files/extra/timezones --owner=0 --group=0 \
		--exclude=./include --exclude=./lib/pkgconfig --exclude=./share/gir-1.0 \
		-cJf $(FLATPARK_PAYLOAD) .
	@echo $(FLATPARK_PAYLOAD)

# The folder to submit as registry/$(APP_ID) in a flatpark/flatpark PR, pinned
# to the tree as published on the release (PAYLOAD_URL can point elsewhere to
# test). The desktop entry, metainfo and icon are taken from that same tree.
FLATPARK_DIR = build-flatpark/registry/$(APP_ID)
PAYLOAD_URL ?= https://github.com/hernantz/timezones/releases/download/v$$(cat src/VERSION)/$(FLATPARK_PAYLOAD)

flatpark-registry:
	@mkdir -p build-flatpark && rm -rf $(FLATPARK_DIR) build-flatpark/published && \
	curl -fsSL -o build-flatpark/published.tar.xz "$(PAYLOAD_URL)" && \
	mkdir -p $(FLATPARK_DIR) build-flatpark/published && \
	tar -xJf build-flatpark/published.tar.xz -C build-flatpark/published \
		./share/applications/$(APP_ID).desktop ./share/metainfo/$(APP_ID).metainfo.xml \
		./share/icons/hicolor/scalable/apps/$(APP_ID).svg && \
	find build-flatpark/published -type f -exec cp {} $(FLATPARK_DIR)/ \; && \
	cp packaging/flatpark/flatpark.yml packaging/flatpark/apply_extra.sh \
		packaging/flatpark/timezones-wrapper packaging/flatpark/resolve-update.sh $(FLATPARK_DIR)/ && \
	sed -e "s|@URL@|$(PAYLOAD_URL)|" \
		-e "s|@SHA256@|$$(sha256sum build-flatpark/published.tar.xz | cut -d' ' -f1)|" \
		-e "s|@SIZE@|$$(stat -c %s build-flatpark/published.tar.xz)|" \
		packaging/flatpark/$(APP_ID).yml > $(FLATPARK_DIR)/$(APP_ID).yml && \
	echo "$(FLATPARK_DIR)"

.PHONY: setup build run install clean test pot version release tag flathub flatpak-repo bundle flatpark-payload flatpark-registry

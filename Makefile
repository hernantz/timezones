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
	other=$$(git status --porcelain | grep -v -E ' (src/VERSION|$(SPEC)|$(METAINFO))$$'); \
	test -z "$$other" || { echo "uncommitted changes outside the release files:"; echo "$$other"; exit 1; }; \
	{ git diff --quiet HEAD || git commit -q -am "Release $$v"; } && \
	git tag -a "v$$v" -m "Release $$v" && \
	echo "tagged v$$v at $$(git rev-parse HEAD)" && \
	echo "next: git push --follow-tags, build in COPR, make flathub"

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

.PHONY: setup build run install clean test pot version release tag flathub

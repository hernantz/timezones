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
	export TIMEZONES_DEV=1; \
	$(PYTHON) -m $(ENTRY)

install: build
	meson install -C $(BUILD)

clean:
	rm -rf $(BUILD)

# src/VERSION is the source of truth (meson and src/const.py both read it);
# the rpm spec cannot read a file at parse time, so it is rewritten here.
SPEC = packaging/rpm/timezones.spec

version:
	@cat src/VERSION

release:
	@test -n "$(VERSION)" || { echo "usage: make release VERSION=x.y.z"; exit 1; }
	@echo "$(VERSION)" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$$' || \
		{ echo "VERSION must look like x.y.z, got '$(VERSION)'"; exit 1; }
	@echo "$(VERSION)" > src/VERSION
	@sed -i -e 's/^Version:.*/Version:        $(VERSION)/' \
		-e 's/^Release:.*/Release:        1%{?dist}/' $(SPEC)
	@grep -n '^Version:' $(SPEC)
	@echo "src/VERSION -> $(VERSION)"
	@echo "review, then: git commit -am 'Release $(VERSION)' && git tag v$(VERSION)"

.PHONY: setup build run install clean version release

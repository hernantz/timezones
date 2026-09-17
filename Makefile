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

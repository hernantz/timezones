PYTHON ?= python3
BUILD ?= builddir
ENTRY ?= src.app

setup:
	meson setup $(BUILD)

build:
	meson compile -C $(BUILD)

run: build
	@export PYTHONPATH="$$(pwd)"; \
	export GSETTINGS_SCHEMA_DIR="$$(pwd)/$(BUILD)"; \
	$(PYTHON) -m $(ENTRY)

install: build
	meson install -C $(BUILD)

clean:
	rm -rf $(BUILD)

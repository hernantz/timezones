project('timezones', version: '0.1.0')

python_mod = import('python')
python = python_mod.find_installation('python3')

gnome = import('gnome')

pkgdatadir = join_paths(get_option('prefix'), get_option('datadir'), meson.project_name())

# Install Python sources
install_data(
  'app.py',
  install_dir: pkgdatadir
)

install_data(
  'src/__init__.py',
  'src/main_window.py',
  'src/model.py',
  'src/persistence.py',
  'src/tzinfo_helpers.py',
  'src/timeline.py',
  'src/cursor_overlay.py',
  'src/row.py',
  'src/add_dialog.py',
  'src/preferences.py',
  'src/date_popover.py',
  install_dir: join_paths(pkgdatadir, 'src')
)

# Compile and install GResource bundle
gnome.compile_resources(
  'com.hernantz.timezones',
  'data/resources/gresource.xml',
  gresource_bundle: true,
  install: true,
  install_dir: pkgdatadir,
  source_dir: 'data/resources'
)

# Install and compile GSettings schema
install_data(
  'data/com.hernantz.timezones.gschema.xml',
  install_dir: join_paths(get_option('datadir'), 'glib-2.0', 'schemas')
)

gnome.post_install(glib_compile_schemas: true, gtk_update_icon_cache: true, update_desktop_database: true)

# Configure and install launcher
conf = configuration_data()
conf.set('PYTHON', python.full_path())
conf.set('pkgdatadir', pkgdatadir)

timezones_script = configure_file(
  input: 'bin/timezones.in',
  output: 'timezones',
  configuration: conf
)

install_data(
  timezones_script,
  install_dir: get_option('bindir'),
  install_mode: 'rwxr-xr-x'
)

# Install the application icon, desktop entry and metainfo. The desktop file and
# metainfo are named after the application id so the shell can match a running
# window (its Wayland app_id) to this entry, and so pick up Icon= below.
install_data(
  'data/icons/hicolor/scalable/apps/com.hernantz.timezones.svg',
  install_dir: join_paths(get_option('datadir'), 'icons', 'hicolor', 'scalable', 'apps')
)

install_data(
  'data/com.hernantz.timezones.desktop',
  install_dir: join_paths(get_option('datadir'), 'applications')
)

install_data(
  'data/appdata/com.hernantz.timezones.metainfo.xml',
  install_dir: join_paths(get_option('datadir'), 'metainfo')
)

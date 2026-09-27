# The version lives in src/VERSION, beside the code that reads it (src/const.py);
# it is installed with the package so both the source tree and an install agree.
project('timezones', version: files('src/VERSION'), license: 'GPL-3.0-or-later')

# The desktop entry, GSettings schema, icon and resource bundle are all named
# after the application id; src/const.py holds the same value for the Python side.
app_id = 'io.github.hernantz.timezones'

python_mod = import('python')
python = python_mod.find_installation('python3')

gnome = import('gnome')
i18n = import('i18n')

pkgdatadir = join_paths(get_option('prefix'), get_option('datadir'), meson.project_name())
localedir = join_paths(get_option('prefix'), get_option('localedir'))

# Translations: the catalog is named after the project ('timezones'), which is
# also the gettext domain src/i18n.py binds.
subdir('po')

# Install Python sources
install_data(
  'app.py',
  install_dir: pkgdatadir
)

install_data(
  'src/__init__.py',
  'src/app.py',
  'src/const.py',
  'src/i18n.py',
  'src/VERSION',
  'src/main_window.py',
  'src/model.py',
  'src/persistence.py',
  'src/tzinfo_helpers.py',
  'src/timeline.py',
  'src/row.py',
  'src/add_dialog.py',
  'src/preferences.py',
  'src/date_popover.py',
  'src/share.py',
  install_dir: join_paths(pkgdatadir, 'src')
)

# Compile and install GResource bundle
gnome.compile_resources(
  app_id,
  'data/resources/gresource.xml',
  gresource_bundle: true,
  install: true,
  install_dir: pkgdatadir,
  source_dir: 'data/resources'
)

# Install and compile GSettings schema
install_data(
  'data' / app_id + '.gschema.xml',
  install_dir: join_paths(get_option('datadir'), 'glib-2.0', 'schemas')
)

gnome.post_install(glib_compile_schemas: true, gtk_update_icon_cache: true, update_desktop_database: true)

# Configure and install launcher
conf = configuration_data()
conf.set('PYTHON', python.full_path())
conf.set('pkgdatadir', pkgdatadir)
conf.set('localedir', localedir)

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
  'data/icons/hicolor/scalable/apps' / app_id + '.svg',
  install_dir: join_paths(get_option('datadir'), 'icons', 'hicolor', 'scalable', 'apps')
)

#
# Both go through the translations on the way: merge_file writes each language's
# strings into the installed copy, which is how the shell and software centres
# find a translated name and description.
i18n.merge_file(
  input: 'data' / app_id + '.desktop',
  output: app_id + '.desktop',
  type: 'desktop',
  po_dir: 'po',
  install: true,
  install_dir: join_paths(get_option('datadir'), 'applications')
)

i18n.merge_file(
  input: 'data/appdata' / app_id + '.metainfo.xml',
  output: app_id + '.metainfo.xml',
  po_dir: 'po',
  install: true,
  install_dir: join_paths(get_option('datadir'), 'metainfo')
)

# The GPL asks that the licence travel with the program; this is also where
# Flatpak and distribution packaging expect to find it.
install_data(
  'COPYING',
  install_dir: join_paths(get_option('datadir'), 'licenses', app_id)
)

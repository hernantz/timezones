Name:           timezones
Version:        1.0.0
Release:        1%{?dist}
Summary:        World time clocks with native GTK4 UI
License:        GPL-3.0-or-later
URL:            https://github.com/hernantz/timezones
# GitHub's tarball for the v<version> tag; it unpacks to timezones-<version>.
Source0:        %{url}/archive/v%{version}/%{name}-%{version}.tar.gz

# Pure Python: nothing is compiled, so one package serves every architecture.
BuildArch:      noarch

BuildRequires:  meson
BuildRequires:  ninja-build
BuildRequires:  python3
BuildRequires:  python3-devel
BuildRequires:  python3-gobject
BuildRequires:  libadwaita-devel >= 1.7
BuildRequires:  gtk4-devel
BuildRequires:  glib2-devel
BuildRequires:  pkgconfig
BuildRequires:  desktop-file-utils
BuildRequires:  appstream
BuildRequires:  gettext

Requires:       python3
Requires:       python3-gobject
Requires:       adwaita-icon-theme
Requires:       gtk4
Requires:       libadwaita >= 1.7

# zoneinfo is stdlib since 3.9, so no Python timezone package is needed. It
# reads the IANA database from disk rather than bundling one, and the app reads
# zone.tab/iso3166.tab from that same directory for the country of each zone.
# Both come from tzdata; named explicitly because this package now depends on
# those two files being present, not merely on the compiled zones.
Requires:       tzdata

# The cities beyond the one each zone is named for (Seattle, Houston), and their
# translated names: the add dialog searches libgweather's location database,
# the one GNOME Clocks uses, and saved rows store their city in its format.
# Pulls in gweather-locations, whose catalog also translates the zone cities.
Requires:       libgweather4 >= 4.0

# Translated country names, read as a plain gettext catalog; without it the
# app still works, only with the English names.
Recommends:     iso-codes

%description
World time clocks with native GTK4 UI.

%prep
%autosetup -n %{name}-%{version}

%build
%meson
%meson_build

%install
%meson_install
# The sources live in /usr/share/timezones, outside site-packages, where the
# automatic byte-compilation does not reach.
%py_byte_compile %{python3} %{buildroot}%{_datadir}/%{name}/
%find_lang %{name}

%check
desktop-file-validate %{buildroot}%{_datadir}/applications/io.github.hernantz.timezones.desktop
appstreamcli validate --no-net %{buildroot}%{_metainfodir}/io.github.hernantz.timezones.metainfo.xml

%files -f %{name}.lang
# meson installs the licence itself, under the application id.
%license %{_datadir}/licenses/io.github.hernantz.timezones/
%doc README*

%{_bindir}/timezones
%{_datadir}/%{name}/
%{_datadir}/applications/io.github.hernantz.timezones.desktop
%{_metainfodir}/io.github.hernantz.timezones.metainfo.xml
%{_datadir}/glib-2.0/schemas/io.github.hernantz.timezones.gschema.xml
%{_datadir}/icons/hicolor/scalable/apps/io.github.hernantz.timezones.svg

%changelog
* Tue Oct 06 2026 Hernan Lozano <hernantz@gmail.com> - 1.0.0-1
- First release.

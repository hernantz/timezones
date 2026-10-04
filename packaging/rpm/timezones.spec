spec

Name:           timezones
Version:        0.1.0
Release:        1%{?dist}
Summary:        World time clocks with native GTK4 UI
License:        GPL-3.0-or-later
URL:            https://github.com/hernantz/timezones
Source0:        %{name}-%{version}.tar.gz

BuildRequires:  gcc
BuildRequires:  meson
BuildRequires:  ninja-build
BuildRequires:  python3
BuildRequires:  python3-devel
BuildRequires:  python3-pygobject
BuildRequires:  libadwaita-devel >= 1.7
BuildRequires:  gtk4-devel
BuildRequires:  pkgconfig
BuildRequires:  desktop-file-utils
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
%meson_configure \
  -Dpython.bytecompile=true

%meson_build

%install
%meson_install
%find_lang %{name}

%check
desktop-file-validate %{buildroot}%{_datadir}/applications/io.github.hernantz.timezones.desktop

%files -f %{name}.lang
%license LICENSE*
%doc README* 

%{_bindir}/timezones
%{_datadir}/applications/io.github.hernantz.timezones.desktop
%{_datadir}/metainfo/*

%{python3_sitearch}/timezones/*
%{_datadir}/glib-2.0/schemas/io.github.hernantz.timezones.gschema.xml

%{_datadir}/icons/hicolor/scalable/apps/io.github.hernantz.timezones.svg

%changelog

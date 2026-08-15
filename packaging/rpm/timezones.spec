spec

Name:           timezones
Version:        0.1.0
Release:        1%{?dist}
Summary:        World time clocks with native GTK4 UI
License:        GPL-3.0-or-later
URL:            https://example.invalid
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

# Install desktop file
install -Dm0644 %{_datadir}/applications/timezones.desktop \
  %{buildroot}%{_datadir}/applications/timezones.desktop

# Install metainfo if you add it (optional)
# install -Dm0644 %{buildroot}%{_metainfodir}/timezones.appdata.xml %{buildroot}%{_metainfodir}/timezones.appdata.xml

# Install icons (if you add them)
# Example: place files in data/icons/hicolor/... and have meson install them,
# or add explicit installs here.

%files
%license LICENSE*
%doc README* 

%{_bindir}/timezones
%{_datadir}/applications/timezones.desktop
%{_datadir}/metainfo/*

%{python3_sitearch}/timezones/*
%{_datadir}/glib-2.0/schemas/com.hernantz.timezones.gschema.xml

%{_datadir}/icons/*

%changelog

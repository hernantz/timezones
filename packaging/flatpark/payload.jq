# The Flatpak manifest, rebuilt for FlatPark's payload: every module installs
# under $p (the tree's final place in /app/extra) and finds the others there;
# the app is built from $root, the checkout, since this file is written
# elsewhere. Dev files are left out when the tree is packed, not by cleanup.
.["build-options"] = {
  prefix: $p,
  env: {
    # gweather-locations is data only, so its .pc file is under share/.
    PKG_CONFIG_PATH: ($p + "/lib/pkgconfig:" + $p + "/share/pkgconfig"),
    XDG_DATA_DIRS: ($p + "/share:/usr/share"),
    GI_TYPELIB_PATH: ($p + "/lib/girepository-1.0"),
    LD_LIBRARY_PATH: ($p + "/lib")
  }
}
| del(.cleanup)
| .modules |= map(
    del(.cleanup)
    | if .name == "timezones"
      then .sources = [{
        type: "dir",
        path: $root,
        skip: ["builddir", "build-flatpak", "build-flatpark", "build-flathub", "build-site", ".flatpak-builder"]
      }]
      else . end
  )

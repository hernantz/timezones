# Not the 'glib' preset: it extracts every comment above a string, and the
# comments in this codebase explain the code, not the text. Only the ones
# starting "Translators:" are meant for the people translating it.
i18n.gettext(
  meson.project_name(),
  args: [
    '--from-code=UTF-8',
    '--add-comments=Translators',
    '--keyword=_',
    '--keyword=N_',
    '--keyword=C_:1c,2',
    '--keyword=ngettext:1,2',
  ],
)

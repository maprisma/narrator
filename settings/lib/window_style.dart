// Maprisma app windows: Solid, Transparent, Glassy or Follow desktop.
//
// One file for all Maprisma apps: ~/.config/maprisma/windows.json
//   {"style": "solid" | "transparent" | "glassy" | "follow", "theme_blur": true | false}
// Maprisma Settings and Maprisma Theme write "style" (Settings › Window › App windows);
// Maprisma Theme writes "theme_blur" when it turns the desktop's blur on or off (KDE, COSMIC).
// Every app keeps an identical copy of this file (there is no shared package).
//
// Follow desktop: on Omarchy, Omarchy's window style (its toggle files, as
// `omarchy-hyprland-window-transparency` reads them); elsewhere Glassy while
// Maprisma Theme has the desktop's blur on, else Solid.
// The compositor blurs behind a see-through window where it does so
// (Hyprland with blur on, KWin's and COSMIC's blur).
import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';

const windowStyles = ['solid', 'transparent', 'glassy', 'follow'];
const glassyAlpha = 0.6, transparentAlpha = 0.9;
const _maxBytes = 4096;

String _home(Map<String, String> env) => env['HOME'] ?? '';
String _configHome(Map<String, String> env) =>
    (env['XDG_CONFIG_HOME'] ?? '').startsWith('/') ? env['XDG_CONFIG_HOME']! : '${_home(env)}/.config';
String _stateHome(Map<String, String> env) =>
    (env['XDG_STATE_HOME'] ?? '').startsWith('/') ? env['XDG_STATE_HOME']! : '${_home(env)}/.local/state';

String windowsFilePath([Map<String, String>? env]) => '${_configHome(env ?? Platform.environment)}/maprisma/windows.json';

/// The file's settings; {} when it is missing, not a regular file, too big or not JSON.
Map<String, dynamic> readWindowsFile([Map<String, String>? env]) {
  final path = windowsFilePath(env);
  try {
    if (FileSystemEntity.typeSync(path, followLinks: false) != FileSystemEntityType.file) return {};
    final file = File(path).openSync();
    try {
      final bytes = file.readSync(_maxBytes + 1);
      if (bytes.length > _maxBytes) return {};
      final value = jsonDecode(utf8.decode(bytes, allowMalformed: true));
      return value is Map<String, dynamic> ? value : {};
    } finally {
      file.closeSync();
    }
  } on Object {
    return {};
  }
}

/// The chosen style (Solid when unset or unknown).
String chosenWindowStyle([Map<String, String>? env]) {
  final style = readWindowsFile(env)['style'];
  return windowStyles.contains(style) ? style as String : 'solid';
}

/// Solid, Transparent or Glassy: Follow desktop resolved.
String resolvedWindowStyle([Map<String, String>? env]) {
  env ??= Platform.environment;
  final settings = readWindowsFile(env);
  final style = windowStyles.contains(settings['style']) ? settings['style'] as String : 'solid';
  if (style != 'follow') return style;
  final omarchy = '${_stateHome(env)}/omarchy';
  if (FileSystemEntity.typeSync(omarchy) == FileSystemEntityType.directory) {
    final toggles = '$omarchy/toggles/hypr';
    if (FileSystemEntity.typeSync('$toggles/window-opaque.lua') != FileSystemEntityType.notFound) return 'solid';
    if (FileSystemEntity.typeSync('$toggles/window-glassy.lua') != FileSystemEntityType.notFound) return 'glassy';
    return 'transparent';
  }
  return settings['theme_blur'] == true ? 'glassy' : 'solid';
}

double windowAlpha(String resolved) => switch (resolved) {
      'glassy' => glassyAlpha,
      'transparent' => transparentAlpha,
      _ => 1.0,
    };

/// Writes one key, keeping the others; the folder is created, the file replaced atomically.
Future<void> writeWindowsSetting(String key, Object value, [Map<String, String>? env]) async {
  final path = windowsFilePath(env);
  final dir = Directory(File(path).parent.path);
  await dir.create(recursive: true);
  final settings = readWindowsFile(env)..[key] = value;
  final tmp = File('$path.$pid.tmp');
  await tmp.writeAsString('${const JsonEncoder.withIndent('  ').convert(settings)}\n', flush: true);
  await tmp.rename(path);
}

/// The window's background alpha, checked every few seconds (and on [refresh]).
class WindowStyleWatcher extends ValueNotifier<double> {
  WindowStyleWatcher({Duration every = const Duration(seconds: 3), this.env})
      : super(windowAlpha(resolvedWindowStyle(env))) {
    _timer = Timer.periodic(every, (_) => refresh());
    _all.add(this);
  }
  static final _all = <WindowStyleWatcher>{};

  /// After a change in this app: every window follows at once.
  static void refreshAll() {
    for (final w in _all) {
      w.refresh();
    }
  }
  final Map<String, String>? env;
  late final Timer _timer;

  void refresh() => value = windowAlpha(resolvedWindowStyle(env));

  @override
  void dispose() {
    _all.remove(this);
    _timer.cancel();
    super.dispose();
  }
}

/// The theme with a see-through window: the background at [alpha], cards and side panels
/// (the surface containers) a little more solid; menus, dropdowns and dialogs stay solid so
/// what floats over the page stays readable.
ThemeData withWindowAlpha(ThemeData theme, double alpha) {
  if (alpha >= 1) return theme;
  final s = theme.colorScheme;
  final cardAlpha = (1 + alpha) / 2;
  Color see(Color c, double a) => c.withValues(alpha: c.a * a);
  final solidMenu = theme.menuTheme.style?.backgroundColor ?? WidgetStatePropertyAll(s.surfaceContainer);
  return theme.copyWith(
    scaffoldBackgroundColor: see(theme.scaffoldBackgroundColor, alpha),
    canvasColor: see(theme.canvasColor, alpha),
    colorScheme: s.copyWith(
      surfaceContainerLowest: see(s.surfaceContainerLowest, cardAlpha),
      surfaceContainerLow: see(s.surfaceContainerLow, cardAlpha),
      surfaceContainer: see(s.surfaceContainer, cardAlpha),
    ),
    cardTheme: theme.cardTheme.copyWith(color: see(theme.cardTheme.color ?? s.surfaceContainerLow, cardAlpha)),
    dialogTheme: theme.dialogTheme.copyWith(backgroundColor: theme.dialogTheme.backgroundColor ?? s.surfaceContainerHigh),
    popupMenuTheme: theme.popupMenuTheme.copyWith(color: theme.popupMenuTheme.color ?? s.surfaceContainer),
    menuTheme: MenuThemeData(style: (theme.menuTheme.style ?? const MenuStyle()).copyWith(backgroundColor: solidMenu)),
    dropdownMenuTheme: theme.dropdownMenuTheme.copyWith(
      menuStyle: (theme.dropdownMenuTheme.menuStyle ?? const MenuStyle()).copyWith(backgroundColor: solidMenu),
    ),
  );
}

/// Settings › Window › App windows: the choices, in the app's language.
List<(String, String)> windowStyleChoices(String Function(String) tr) => [
      ('solid', tr('Solid')),
      ('transparent', tr('Transparent')),
      ('glassy', tr('Glassy (blurred)')),
      ('follow', tr('Follow the desktop')),
    ];

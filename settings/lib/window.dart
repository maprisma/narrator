// Closing and the window's size (Maprisma layout rules, "Closing and toggling"). Shared copy in
// maprisma-narrator/settings and maprisma-video-translator/app; change both.
//
// Esc closes the innermost thing first: drop-down menus and dialogs (the screenshot note is one)
// close themselves while they are open; only then [EscapeCloses] closes the window, the same way as its close button (the GTK runner's
// gtk_window_close, so the app's own exit handling runs).
//
// The window's size: saved {width, height} 0.5 s after the last resize (not while maximised,
// fullscreen or tiled), restored on the next start before the window is shown, at least
// [AppWindow.minimum] and at most the screen's work area; missing or broken: the default size.

import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math' as math;

import 'package:flutter/services.dart';
import 'package:flutter/widgets.dart';

/// Drop-down menus open right now (ChoiceButton counts them): while one is open, its own Esc
/// closes it and [EscapeCloses] lets the key pass.
final openMenus = ValueNotifier<int>(0);

/// Esc with nothing open on the page: [onClose]. Wraps the main page (MaterialApp.home). It
/// listens to the key itself rather than through DismissIntent, which a page route or a Scaffold
/// would take first (with an action that does nothing). Its focus scope keeps the keyboard focus
/// inside it (also after a text field lets go of it). Dialogs are routes of their own, so their
/// Esc never comes here; an open drop-down (see [openMenus]) closes first.
class EscapeCloses extends StatelessWidget {
  const EscapeCloses({super.key, required this.onClose, required this.child});

  final VoidCallback onClose;
  final Widget child;

  @override
  Widget build(BuildContext context) => FocusScope(
    autofocus: true,
    onKeyEvent: (node, event) {
      if (event is! KeyDownEvent || event.logicalKey != LogicalKeyboardKey.escape) return KeyEventResult.ignored;
      if (openMenus.value > 0) return KeyEventResult.ignored;
      onClose();
      return KeyEventResult.handled;
    },
    child: child,
  );
}

/// The GTK runner's window: close it, and keep its size between starts.
class AppWindow {
  AppWindow({
    required this.channel,
    required this.file,
    required this.defaultSize,
    this.minimum = const Size(420, 360),
    this.delay = const Duration(milliseconds: 500),
    this.notUsers = hyprlandSizeNotUsers,
  });

  final MethodChannel channel;

  /// Where the size is kept (the app's own config folder).
  final File Function() file;

  /// Whether the present size is the compositor's (Hyprland: tiled or fullscreen), asked just
  /// before saving.
  final Future<bool> Function() notUsers;
  final Size defaultSize;
  final Size minimum;
  final Duration delay;

  Size? _last;
  Timer? _pending;

  /// Closes the window as its close button does. Without the runner (tests) it does nothing.
  Future<void> close() async {
    try {
      await channel.invokeMethod<void>('close');
    } on MissingPluginException {
      // Not running under the GTK runner.
    } on PlatformException {
      // No window (yet).
    }
  }

  /// {width, height} as positive finite numbers, else null.
  static Size? parseSize(Object? json) {
    if (json is! Map) return null;
    final width = json['width'];
    final height = json['height'];
    if (width is! num || height is! num) return null;
    final w = width.toDouble();
    final h = height.toDouble();
    if (!w.isFinite || !h.isFinite || w <= 0 || h <= 0) return null;
    return Size(w, h);
  }

  /// The size to open with: [saved] (or [fallback]) at least [minimum], at most [screen].
  static Size fit(Size? saved, {required Size fallback, required Size minimum, Size? screen}) {
    final size = saved ?? fallback;
    var width = math.max(size.width, minimum.width);
    var height = math.max(size.height, minimum.height);
    if (screen != null) {
      width = math.min(width, screen.width);
      height = math.min(height, screen.height);
    }
    return Size(width.roundToDouble(), height.roundToDouble());
  }

  Size? readSaved() {
    try {
      return parseSize(jsonDecode(file().readAsStringSync()));
    } on Object {
      return null; // missing or broken: the default size
    }
  }

  /// Before the first frame: the saved size (fitted to the screen) for the window, and from now
  /// on the runner's resize reports.
  Future<void> restore() async {
    channel.setMethodCallHandler((call) async {
      if (call.method == 'resized') resized(call.arguments);
    });
    Size? screen;
    try {
      screen = parseSize(await channel.invokeMethod<Object?>('screen'));
    } on Object {
      screen = null;
    }
    final size = fit(readSaved(), fallback: defaultSize, minimum: minimum, screen: screen);
    _last = size;
    try {
      await channel.invokeMethod<void>('resize', {'width': size.width.toInt(), 'height': size.height.toInt()});
    } on Object {
      // Not running under the GTK runner: nothing to size.
    }
  }

  /// The runner's report after a resize: {width, height, maximized, fullscreen, tiled}.
  void resized(Object? report) {
    final map = report is Map ? report : const {};
    final size = parseSize(map);
    if (size == null || map['maximized'] == true || map['fullscreen'] == true || map['tiled'] == true) {
      _pending?.cancel();
      return;
    }
    final rounded = Size(size.width.roundToDouble(), size.height.roundToDouble());
    _pending?.cancel();
    if (rounded == _last) return;
    _pending = Timer(delay, () => unawaited(_saveIfUsers(rounded)));
  }

  Future<void> _saveIfUsers(Size size) async {
    if (await notUsers()) return;
    save(size);
  }

  /// Writes the size (atomically, next to the app's other settings).
  void save(Size size) {
    try {
      final target = file();
      target.parent.createSync(recursive: true);
      final temporary = File('${target.path}.tmp');
      temporary.writeAsStringSync(jsonEncode({'width': size.width.round(), 'height': size.height.round()}));
      temporary.renameSync(target.path);
      _last = size;
    } on Object {
      // Read-only config: the next start uses the default size.
    }
  }

  void dispose() => _pending?.cancel();
}

/// Hyprland marks every window as tiled, floating ones too, so the runner can't tell whether a
/// size is the user's: there `hyprctl -j clients` decides. True when this process's window is
/// tiled or fullscreen (not a size to keep); false on other desktops or when it can't be told.
/// Shared in every Maprisma Flutter app's size code (Uwe, 2026-11-14).
Future<bool> hyprlandSizeNotUsers({
  Map<String, String>? environment,
  int? processId,
  Future<ProcessResult> Function()? clients,
}) async {
  final env = environment ?? Platform.environment;
  if (!_hyprlandDesktop(env)) return false;
  try {
    final result = await (clients ?? () => Process.run('hyprctl', ['-j', 'clients']))()
        .timeout(const Duration(seconds: 2));
    if (result.exitCode != 0) return false;
    return hyprNotUsers(result.stdout.toString(), processId ?? pid) ?? false;
  } on Object {
    return false;
  }
}

/// From `hyprctl -j clients`: whether [processId]'s window is tiled or fullscreen; null when the
/// list has no window of it.
bool? hyprNotUsers(String clientsJson, int processId) {
  Object? list;
  try {
    list = jsonDecode(clientsJson);
  } on FormatException {
    return null;
  }
  if (list is! List) return null;
  for (final client in list) {
    if (client is Map && client['pid'] == processId) {
      final fullscreen = client['fullscreen'];
      return client['floating'] != true || (fullscreen is num && fullscreen != 0) || fullscreen == true;
    }
  }
  return null;
}

/// MAPRISMA_DESKTOP, else XDG_CURRENT_DESKTOP; Hyprland's instance signature only when neither
/// is set (a stale one stays in the systemd user environment after a Hyprland session).
bool _hyprlandDesktop(Map<String, String> env) {
  final forced = (env['MAPRISMA_DESKTOP'] ?? '').trim().toLowerCase();
  if (forced.isNotEmpty) return forced == 'hyprland';
  final names = (env['XDG_CURRENT_DESKTOP'] ?? '')
      .toLowerCase()
      .split(':')
      .map((n) => n.trim())
      .where((n) => n.isNotEmpty)
      .toList();
  if (names.isNotEmpty) return names.contains('hyprland');
  return (env['HYPRLAND_INSTANCE_SIGNATURE'] ?? '').isNotEmpty;
}

/// Maprisma Tiling (the KWin script) sizes the windows it tiles itself, and no tiled state reaches
/// GTK (it only moves the frame), so the runner's "free" can't see it: on Plasma with the script
/// on, only an app it always floats (its `floatingClasses`, by default the Launcher) keeps a size.
/// [environment] and [systemData] are for tests.
bool tiledByMaprismaTiling(String appId, {Map<String, String>? environment, String systemData = '/usr/share'}) {
  final env = environment ?? Platform.environment;
  final names = (env['XDG_CURRENT_DESKTOP'] ?? '').toUpperCase().split(':');
  if (!names.contains('KDE')) return false;
  final home = env['HOME'] ?? '/';
  String xdg(String key, String fallback) {
    final v = env[key] ?? '';
    return v.startsWith('/') ? v : '$home/$fallback';
  }

  String text;
  try {
    final file = File('${xdg('XDG_CONFIG_HOME', '.config')}/kwinrc');
    text = file.lengthSync() > 1024 * 1024 ? '' : file.readAsStringSync();
  } on Object {
    text = '';
  }
  String? value(String group, String key) {
    String? current, found;
    for (final raw in text.split('\n')) {
      final line = raw.trim();
      if (line.startsWith('[') && line.endsWith(']')) {
        current = line.substring(1, line.length - 1);
      } else if (current == group) {
        final eq = line.indexOf('=');
        if (eq > 0 && line.substring(0, eq).trim() == key) found = line.substring(eq + 1).trim();
      }
    }
    return found;
  }

  final enabled = value('Plugins', 'maprisma-tilingEnabled');
  if (enabled == 'false') return false;
  // Not switched either way: on by default once installed.
  if (enabled != 'true' &&
      !Directory('${xdg('XDG_DATA_HOME', '.local/share')}/kwin/scripts/maprisma-tiling').existsSync() &&
      !Directory('$systemData/kwin/scripts/maprisma-tiling').existsSync()) {
    return false;
  }
  final floating = (value('Script-maprisma-tiling', 'floatingClasses') ?? 'com.maprisma.Launcher')
      .split(',')
      .map((c) => c.trim().toLowerCase());
  return !floating.contains(appId.toLowerCase());
}

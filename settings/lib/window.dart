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
//
// Hyprland: the window's place too ({x, y} in the same file, [WindowPlaceKeeper]): asked every
// 2 s while shown, saved when it moved, and the window is moved back each time it shows.

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
      // the place (Hyprland) stays in the file
      final place = readPlace();
      temporary.writeAsStringSync(jsonEncode({
        'width': size.width.round(),
        'height': size.height.round(),
        if (place != null) 'x': place.$1,
        if (place != null) 'y': place.$2,
      }));
      temporary.renameSync(target.path);
      _last = size;
    } on Object {
      // Read-only config: the next start uses the default size.
    }
  }

  /// Hyprland: the saved place ({x, y} next to the size), or null.
  (int, int)? readPlace() {
    try {
      return parsePlace(jsonDecode(file().readAsStringSync()));
    } on Object {
      return null;
    }
  }

  /// {x, y} as whole numbers (Hyprland's layout pixels, may be negative, |v| ≤ 100000), else null.
  static (int, int)? parsePlace(Object? json) {
    if (json is! Map) return null;
    final x = json['x'], y = json['y'];
    if (x is! int || y is! int || x.abs() > 100000 || y.abs() > 100000) return null;
    return (x, y);
  }

  /// Writes the place (atomically), keeping the saved size.
  void savePlace(int x, int y) {
    try {
      final target = file();
      target.parent.createSync(recursive: true);
      Object? old;
      try {
        old = jsonDecode(target.readAsStringSync());
      } on Object {
        old = null;
      }
      final size = parseSize(old);
      final temporary = File('${target.path}.tmp');
      temporary.writeAsStringSync(jsonEncode({
        if (size != null) 'width': size.width.round(),
        if (size != null) 'height': size.height.round(),
        'x': x,
        'y': y,
      }));
      temporary.renameSync(target.path);
    } on Object {
      // Read-only config: the window opens where the compositor puts it.
    }
  }

  void dispose() => _pending?.cancel();
}

/// From `hyprctl -j clients`: where [processId]'s window is, when it floats and isn't fullscreen
/// (a tiled or fullscreen place is not the user's); null otherwise.
(int, int)? hyprPosition(String clientsJson, int processId) {
  if (hyprNotUsers(clientsJson, processId) != false) return null;
  for (final client in jsonDecode(clientsJson) as List) {
    if (client is Map && client['pid'] == processId) {
      final at = client['at'];
      if (at is List && at.length == 2 && at[0] is int && at[1] is int) return (at[0] as int, at[1] as int);
    }
  }
  return null;
}

/// From `hyprctl -j monitors`: whether a window at [position] (its top left) with [size] keeps
/// at least 48 px on a screen, so a place on a screen that is gone isn't used.
bool onAMonitor(String monitorsJson, (int, int) position, (int, int) size) {
  Object? list;
  try {
    list = jsonDecode(monitorsJson);
  } on FormatException {
    return false;
  }
  if (list is! List) return false;
  final (x, y) = position;
  for (final m in list) {
    if (m is! Map) continue;
    final scale = (m['scale'] is num && (m['scale'] as num) > 0) ? (m['scale'] as num).toDouble() : 1.0;
    final mx = m['x'], my = m['y'], mw = m['width'], mh = m['height'];
    if (mx is! num || my is! num || mw is! num || mh is! num) continue;
    final w = mw / scale, h = mh / scale;
    if (x + size.$1 - 48 >= mx && x + 48 <= mx + w && y >= my && y + 48 <= my + h) return true;
  }
  return false;
}

/// Hyprland: the window opens where the user left it (Uwe, 2026-11-14, every Maprisma window;
/// the same keeper as in the other Maprisma apps' window_size.dart). A Wayland window can't place
/// itself or hear that it was moved, and the runner hides it before Dart could ask, so while it
/// is shown [every] few seconds hyprctl says where it is (saved when that changed), and each time
/// it is shown again it is moved back there. Elsewhere, and in tests, it does nothing. [run] and
/// [environment] are for tests.
final class WindowPlaceKeeper {
  WindowPlaceKeeper({
    required (int, int)? saved,
    required this.save,
    this.every = const Duration(seconds: 2),
    Map<String, String>? environment,
    Future<ProcessResult> Function(List<String> args)? run,
    int? processId,
  }) : _saved = saved, // ignore: prefer_initializing_formals
       _env = environment ?? Platform.environment,
       _run = run ?? ((args) => Process.run('hyprctl', args)),
       _pid = processId ?? pid;

  final void Function(int x, int y) save;
  final Duration every;
  final Map<String, String> _env;
  final Future<ProcessResult> Function(List<String> args) _run;
  final int _pid;
  (int, int)? _saved;
  Timer? _timer;
  bool _shown = true;

  /// Hyprland only, and never in widget tests (they must not ask or move the real windows).
  bool get active => _env['FLUTTER_TEST'] != 'true' && _hyprlandDesktop(_env);

  Future<String?> _ask(List<String> args) async {
    try {
      final r = await _run(args).timeout(const Duration(seconds: 2));
      return r.exitCode == 0 ? r.stdout.toString() : null;
    } on Object {
      return null;
    }
  }

  /// At start: back to the saved place, then sampling while shown.
  void start() {
    if (!active) return;
    unawaited(restore());
    _timer = Timer.periodic(every, (_) {
      if (_shown) unawaited(sample());
    });
  }

  /// From didChangeAppLifecycleState: hidden stops the sampling; shown again moves it back.
  void lifecycle(AppLifecycleState state) {
    if (!active) return;
    final shown = state != AppLifecycleState.hidden && state != AppLifecycleState.paused;
    if (shown && !_shown) unawaited(restore());
    _shown = shown;
  }

  /// Saves where the window is now when that changed (floating, not fullscreen).
  Future<void> sample() async {
    final clients = await _ask(['-j', 'clients']);
    if (clients == null) return;
    final at = hyprPosition(clients, _pid);
    if (at == null || at == _saved) return;
    _saved = at;
    save(at.$1, at.$2);
  }

  /// Once Hyprland lists the window (asked every 50 ms for up to 3 s), it is moved to the saved
  /// place when that is still on a screen.
  Future<void> restore() async {
    final place = _saved;
    if (place == null) return;
    for (var i = 0; i < 60; i++) {
      await Future<void>.delayed(const Duration(milliseconds: 50));
      final clients = await _ask(['-j', 'clients']);
      if (clients == null) return;
      if (hyprNotUsers(clients, _pid) == null) continue; // not mapped yet
      if (hyprNotUsers(clients, _pid) == true) return; // tiled or fullscreen: Hyprland's place
      final size = _sizeOf(clients);
      if (hyprPosition(clients, _pid) == place || size == null) return;
      final monitors = await _ask(['-j', 'monitors']);
      if (monitors != null && onAMonitor(monitors, place, size)) {
        await _ask(['eval', "hl.dispatch(hl.dsp.window.move({ x = ${place.$1}, y = ${place.$2}, window = 'pid:$_pid' }))"]);
      }
      return;
    }
  }

  (int, int)? _sizeOf(String clientsJson) {
    for (final client in jsonDecode(clientsJson) as List) {
      if (client is Map && client['pid'] == _pid && client['size'] is List) {
        final s = client['size'] as List;
        if (s.length == 2 && s[0] is int && s[1] is int) return (s[0] as int, s[1] as int);
      }
    }
    return null;
  }

  void dispose() => _timer?.cancel();
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

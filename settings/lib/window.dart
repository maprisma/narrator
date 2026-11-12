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
  });

  final MethodChannel channel;

  /// Where the size is kept (the app's own config folder).
  final File Function() file;
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
    _pending = Timer(delay, () => save(rounded));
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

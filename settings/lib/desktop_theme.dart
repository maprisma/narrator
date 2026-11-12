// The GTK runner's side of the look: the XDG portal's accent-color (the accent on desktops
// whose palette desktop_look.dart does not read), and the runner's GTK header bar painted in the
// page's colours, so it is never a white bar on a dark window. The theme itself is app_theme.dart.

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'app_theme.dart';

class DesktopTheme {
  DesktopTheme({MethodChannel? channel}) : _channel = channel ?? const MethodChannel('maprisma_narrator/theme');

  final MethodChannel _channel;
  final accent = ValueNotifier<Color?>(null);
  String? _sentHeader;

  /// Asks the runner for the accent and listens for changes. Without the runner (tests) it does nothing.
  Future<void> start() async {
    _channel.setMethodCallHandler((call) async {
      if (call.method == 'accentChanged') accent.value = parseAccent(call.arguments);
    });
    try {
      accent.value = parseAccent(await _channel.invokeMethod<Object?>('getAccent'));
    } on MissingPluginException {
      // Not running under the GTK runner.
    } on PlatformException {
      // No portal: keep the fallback.
    }
  }

  /// The portal gives (r, g, b) in 0..1; values outside that range mean "no accent set".
  static Color? parseAccent(Object? value) {
    if (value is! List || value.length != 3) return null;
    final rgb = value.map((v) => v is num ? v.toDouble() : -1.0).toList();
    if (rgb.any((v) => v < 0 || v > 1)) return null;
    return Color.from(alpha: 1, red: rgb[0], green: rgb[1], blue: rgb[2]);
  }

  /// Paints the GTK header bar (and the window behind the Flutter view) like the page.
  void syncHeader(ThemeData theme) {
    final scheme = theme.colorScheme;
    final header = {
      'background': colorHex(scheme.surfaceContainer),
      'foreground': colorHex(scheme.onSurface),
      'border': colorHex(scheme.outlineVariant),
      'surface': colorHex(scheme.surface),
      'dark': theme.brightness == Brightness.dark,
    };
    final key = header.toString();
    if (key == _sentHeader) return;
    _sentHeader = key;
    _channel.invokeMethod<void>('setHeaderColors', header).catchError((_) {});
  }
}

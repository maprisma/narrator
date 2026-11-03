// Follows the desktop's look: light/dark comes from Flutter (the XDG portal's color-scheme), the
// accent color from the portal's accent-color (COSMIC, GNOME, KDE, ...), read by the GTK runner.
// The runner's GTK header bar is painted in the same colors, so it is never a white bar on a
// dark window.

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

const fallbackAccent = Color(0xFF3584E4);

class DesktopTheme {
  DesktopTheme({MethodChannel? channel}) : _channel = channel ?? const MethodChannel('screen_narrator/theme');

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

  static ThemeData theme(Brightness brightness, Color? accent) {
    final scheme = ColorScheme.fromSeed(
      seedColor: accent ?? fallbackAccent,
      brightness: brightness,
      // Keeps primary close to the desktop accent instead of a muted tone of it.
      dynamicSchemeVariant: accent == null ? DynamicSchemeVariant.tonalSpot : DynamicSchemeVariant.fidelity,
    );
    return ThemeData(
      useMaterial3: true,
      colorScheme: scheme,
      visualDensity: VisualDensity.compact,
      materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
      cardTheme: const CardThemeData(elevation: 0),
      // Material's default snack bar is the inverse surface: a white bar in a dark window.
      snackBarTheme: SnackBarThemeData(
        backgroundColor: scheme.surfaceContainerHighest,
        contentTextStyle: TextStyle(color: scheme.onSurface),
        actionTextColor: scheme.primary,
        closeIconColor: scheme.onSurfaceVariant,
        elevation: 0,
        shape: Border(top: BorderSide(color: scheme.outlineVariant)),
      ),
    );
  }

  static String _hex(Color c) => '#${(c.toARGB32() & 0xFFFFFF).toRadixString(16).padLeft(6, '0')}';

  /// Paints the GTK header bar (and the window behind the Flutter view) like the page.
  void syncHeader(ThemeData theme) {
    final scheme = theme.colorScheme;
    final header = {
      'background': _hex(scheme.surfaceContainer),
      'foreground': _hex(scheme.onSurface),
      'border': _hex(scheme.outlineVariant),
      'surface': _hex(scheme.surface),
      'dark': theme.brightness == Brightness.dark,
    };
    final key = header.toString();
    if (key == _sentHeader) return;
    _sentHeader = key;
    _channel.invokeMethod<void>('setHeaderColors', header).catchError((_) {});
  }
}

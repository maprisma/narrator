// Maprisma Narrator settings for the COSMIC desktop: a Flutter port of the GNOME extension's
// settings window. It talks only to the backend's bridge.py.

import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:maprisma_ui/window_style.dart';

import 'app_theme.dart';
import 'bridge.dart';
import 'desktop_look.dart';
import 'desktop_theme.dart';
import 'i18n.dart';
import 'look.dart';
import 'skin.dart';
import 'settings_page.dart';
import 'shot.dart';
import 'window.dart';

/// The settings window (GTK runner): Esc closes it, its size is kept next to the settings.
final appWindow = AppWindow(
  channel: const MethodChannel('maprisma_narrator/window'),
  file: () => File('${languageSettingsFile().parent.path}/window.json'),
  defaultSize: const Size(640, 820),
  // Maprisma Tiling on KDE sizes the window without GTK knowing; Hyprland: only floating counts.
  notUsers: () async =>
      tiledByMaprismaTiling('com.maprisma.Narrator') ||
      await hyprlandSizeNotUsers(),
);

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  // The desktop's palette before the first frame: no flash of Material's colours.
  final watcher = DesktopLookWatcher();
  desktopLook.value = await watcher.read();
  // The saved size before the window shows (it shows with the first frame).
  await appWindow.restore();
  runApp(SettingsApp(bridge: Bridge(), lookWatcher: watcher));
}

class SettingsApp extends StatefulWidget {
  const SettingsApp({
    super.key,
    required this.bridge,
    this.desktopTheme,
    this.lookWatcher,
    this.onClose,
  });

  final Bridge bridge;
  final DesktopTheme? desktopTheme;

  /// Re-reads the desktop's look every 5 s and when the window gets the focus; null (tests):
  /// [desktopLook] stays as it is set.
  final DesktopLookWatcher? lookWatcher;

  /// Esc with nothing open: closes the window like its close button (reading goes on: the
  /// reader is its own service). Null: [appWindow]'s close.
  final VoidCallback? onClose;

  @override
  State<SettingsApp> createState() => _SettingsAppState();
}

class _SettingsAppState extends State<SettingsApp> with WidgetsBindingObserver {
  late final DesktopTheme _desktop = widget.desktopTheme ?? DesktopTheme();
  Timer? _lookTimer;

  /// Maprisma Settings › App windows: see-through windows for all Maprisma apps (window_style.dart).
  WindowStyleWatcher? _windowStyle;

  /// Hyprland: the window's place, kept next to its size and put back each time it shows
  /// (window.dart); null in tests.
  WindowPlaceKeeper? _windowPlace;

  @override
  void initState() {
    super.initState();
    _desktop.start();
    if (widget.lookWatcher != null) {
      WidgetsBinding.instance.addObserver(this);
      _lookTimer = Timer.periodic(
        DesktopLookWatcher.filesEvery,
        (_) => _reloadLook(),
      );
      _windowStyle = WindowStyleWatcher();
      _windowPlace = WindowPlaceKeeper(
        saved: appWindow.readPlace(),
        save: appWindow.savePlace,
      )..start();
    }
  }

  @override
  void dispose() {
    _lookTimer?.cancel();
    _windowStyle?.dispose();
    _windowPlace?.dispose();
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    _windowPlace?.lifecycle(state);
    if (state == AppLifecycleState.resumed) _reloadLook();
  }

  Future<void> _reloadLook() async {
    final fresh = await widget.lookWatcher!.read();
    // Only a change rebuilds the window.
    if (mounted && fresh != desktopLook.value) desktopLook.value = fresh;
  }

  @override
  Widget build(BuildContext context) {
    final style = _windowStyle;
    if (style == null) return _app(1);
    return ValueListenableBuilder<double>(
      valueListenable: style,
      builder: (context, alpha, _) => _app(alpha),
    );
  }

  Widget _app(double alpha) {
    return ValueListenableBuilder<String>(
      valueListenable: interfaceLanguage,
      builder: (context, language, _) => ValueListenableBuilder<LookSettings>(
        valueListenable: look,
        builder: (context, settings, _) => ValueListenableBuilder<DesktopLook>(
          valueListenable: desktopLook,
          builder: (context, desktop, _) => ValueListenableBuilder<Color?>(
            valueListenable: _desktop.accent,
            builder: (context, accent, _) {
              // The portal's accent only where the desktop's palette has none.
              final colors = {
                if (accent != null) 'accent': colorHex(accent),
                ...desktop.colors,
              };
              final radius = cornerRadius(settings.corners, desktop.rounding);
              return MaterialApp(
                title: tr('Maprisma Narrator'),
                debugShowCheckedModeBanner: false,
                navigatorKey: shotNavigator,
                scaffoldMessengerKey: shotMessenger,
                themeMode: settings.skin == 'native'
                    ? appThemeMode(colors)
                    : ThemeMode.dark,
                theme: withWindowAlpha(
                  applySkinToTheme(
                    appTheme(
                      Brightness.light,
                      colors,
                      radius,
                      fonts: desktop.fonts,
                    ),
                    settings.skin,
                    radius: radius,
                  ),
                  alpha,
                ),
                darkTheme: withWindowAlpha(
                  applySkinToTheme(
                    appTheme(
                      Brightness.dark,
                      colors,
                      radius,
                      fonts: desktop.fonts,
                    ),
                    settings.skin,
                    radius: radius,
                  ),
                  alpha,
                ),
                builder: (context, child) {
                  _desktop.syncHeader(Theme.of(context));
                  return ShotScope(child: child!);
                },
                home: EscapeCloses(
                  onClose: widget.onClose ?? appWindow.close,
                  child: SettingsPage(bridge: widget.bridge),
                ),
              );
            },
          ),
        ),
      ),
    );
  }
}

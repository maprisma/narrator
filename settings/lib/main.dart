// Maprisma Narrator settings for the COSMIC desktop: a Flutter port of the GNOME extension's
// settings window. It talks only to the backend's bridge.py.

import 'dart:async';

import 'package:flutter/material.dart';

import 'app_theme.dart';
import 'bridge.dart';
import 'desktop_look.dart';
import 'desktop_theme.dart';
import 'i18n.dart';
import 'look.dart';
import 'settings_page.dart';
import 'shot.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  // The desktop's palette before the first frame: no flash of Material's colours.
  final watcher = DesktopLookWatcher();
  desktopLook.value = await watcher.read();
  runApp(SettingsApp(bridge: Bridge(), lookWatcher: watcher));
}

class SettingsApp extends StatefulWidget {
  const SettingsApp({super.key, required this.bridge, this.desktopTheme, this.lookWatcher});

  final Bridge bridge;
  final DesktopTheme? desktopTheme;

  /// Re-reads the desktop's look every 5 s and when the window gets the focus; null (tests):
  /// [desktopLook] stays as it is set.
  final DesktopLookWatcher? lookWatcher;

  @override
  State<SettingsApp> createState() => _SettingsAppState();
}

class _SettingsAppState extends State<SettingsApp> with WidgetsBindingObserver {
  late final DesktopTheme _desktop = widget.desktopTheme ?? DesktopTheme();
  Timer? _lookTimer;

  @override
  void initState() {
    super.initState();
    _desktop.start();
    if (widget.lookWatcher != null) {
      WidgetsBinding.instance.addObserver(this);
      _lookTimer = Timer.periodic(DesktopLookWatcher.filesEvery, (_) => _reloadLook());
    }
  }

  @override
  void dispose() {
    _lookTimer?.cancel();
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) _reloadLook();
  }

  Future<void> _reloadLook() async {
    final fresh = await widget.lookWatcher!.read();
    // Only a change rebuilds the window.
    if (mounted && fresh != desktopLook.value) desktopLook.value = fresh;
  }

  @override
  Widget build(BuildContext context) {
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
                themeMode: appThemeMode(colors),
                theme: appTheme(Brightness.light, colors, radius),
                darkTheme: appTheme(Brightness.dark, colors, radius),
                builder: (context, child) {
                  _desktop.syncHeader(Theme.of(context));
                  return ShotScope(child: child!);
                },
                home: SettingsPage(bridge: widget.bridge),
              );
            },
          ),
        ),
      ),
    );
  }
}

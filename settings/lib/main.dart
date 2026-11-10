// Maprisma Narrator settings for the COSMIC desktop: a Flutter port of the GNOME extension's
// settings window. It talks only to the backend's bridge.py.

import 'i18n.dart';
import 'package:flutter/material.dart';

import 'bridge.dart';
import 'desktop_theme.dart';
import 'look.dart';
import 'settings_page.dart';
import 'shot.dart';

void main() {
  runApp(SettingsApp(bridge: Bridge()));
}

class SettingsApp extends StatefulWidget {
  const SettingsApp({super.key, required this.bridge, this.desktopTheme});

  final Bridge bridge;
  final DesktopTheme? desktopTheme;

  @override
  State<SettingsApp> createState() => _SettingsAppState();
}

class _SettingsAppState extends State<SettingsApp> {
  late final DesktopTheme _desktop = widget.desktopTheme ?? DesktopTheme();

  @override
  void initState() {
    super.initState();
    _desktop.start();
  }

  @override
  Widget build(BuildContext context) {
    return ValueListenableBuilder<String>(
      valueListenable: interfaceLanguage,
      builder: (context, language, _) => ValueListenableBuilder<LookSettings>(
        valueListenable: look,
        builder: (context, settings, _) => ValueListenableBuilder<Color?>(
          valueListenable: _desktop.accent,
          builder: (context, accent, _) => MaterialApp(
            title: tr('Maprisma Narrator'),
            debugShowCheckedModeBanner: false,
            navigatorKey: shotNavigator,
            scaffoldMessengerKey: shotMessenger,
            themeMode: ThemeMode.system,
            theme: DesktopTheme.theme(Brightness.light, accent,
                radius: cornerRadius(settings.corners, desktopRadius(Brightness.light))),
            darkTheme: DesktopTheme.theme(Brightness.dark, accent,
                radius: cornerRadius(settings.corners, desktopRadius(Brightness.dark))),
            builder: (context, child) {
              _desktop.syncHeader(Theme.of(context));
              return ShotScope(child: child!);
            },
            home: SettingsPage(bridge: widget.bridge),
          ),
        ),
      ),
    );
  }
}

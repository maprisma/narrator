// Screen Narrator settings for the COSMIC desktop: a Flutter port of the GNOME extension's
// settings window. It talks only to the backend's bridge.py.

import 'package:flutter/material.dart';

import 'bridge.dart';
import 'settings_page.dart';

void main() {
  runApp(SettingsApp(bridge: Bridge()));
}

class SettingsApp extends StatelessWidget {
  const SettingsApp({super.key, required this.bridge});

  final Bridge bridge;

  static ThemeData _theme(Brightness brightness) => ThemeData(
        useMaterial3: true,
        brightness: brightness,
        colorSchemeSeed: const Color(0xFF3584E4),
        visualDensity: VisualDensity.compact,
        materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
        cardTheme: const CardThemeData(elevation: 0),
      );

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Screen Narrator',
      debugShowCheckedModeBanner: false,
      themeMode: ThemeMode.system,
      theme: _theme(Brightness.light),
      darkTheme: _theme(Brightness.dark),
      home: SettingsPage(bridge: bridge),
    );
  }
}

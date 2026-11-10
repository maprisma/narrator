// Settings › Corners and F12 saves a screenshot: stored next to the interface language, read by
// the panel applet too. Corners in AI Playground's sizes: cards, dialogs, pop-up menus [radius];
// buttons, choice boxes, fields [control] (at most 8); check boxes and small parts [small] (at
// most 4); pills [pill] (round, or square with Square).

import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:flutter/material.dart';

import 'i18n.dart';
import 'private_files.dart';

/// The app's folder in the pictures folder, and its pictures' name.
const screenshotApp = 'Maprisma Narrator';
const screenshotSlug = 'maprisma-narrator';

/// The settings file the look is stored in (tests point it elsewhere).
File Function() lookSettingsFile = languageSettingsFile;

const cornerChoices = ['desktop', 'slight', 'rounded', 'square'];

@immutable
class LookSettings {
  const LookSettings({this.screenshotKey = true, this.corners = 'desktop'});
  final bool screenshotKey;
  final String corners;

  /// From the settings file's JSON: a missing or unknown value is the default.
  factory LookSettings.fromJson(Object? json) {
    final map = json is Map ? json : const {};
    final key = map['screenshot_key'];
    final corners = map['corners'];
    return LookSettings(
      screenshotKey: key is bool ? key : true,
      corners: cornerChoices.contains(corners) ? corners as String : 'desktop',
    );
  }

  @override
  bool operator ==(Object other) =>
      other is LookSettings && other.screenshotKey == screenshotKey && other.corners == corners;
  @override
  int get hashCode => Object.hash(screenshotKey, corners);
}

LookSettings readLook([File? file]) {
  try {
    return LookSettings.fromJson(jsonDecode((file ?? lookSettingsFile()).readAsStringSync()));
  } on Object {
    return const LookSettings(); // missing or malformed: the defaults
  }
}

final look = ValueNotifier<LookSettings>(readLook());

/// Saves one look value, keeping every other key of the settings file.
void saveLook({bool? screenshotKey, String? corners, File? file}) {
  if (corners != null && !cornerChoices.contains(corners)) return;
  final target = file ?? lookSettingsFile();
  Map<String, dynamic> settings = {};
  try {
    settings = (jsonDecode(target.readAsStringSync()) as Map).cast<String, dynamic>();
  } on Object {
    /* first save */
  }
  if (screenshotKey != null) settings['screenshot_key'] = screenshotKey;
  if (corners != null) settings['corners'] = corners;
  target.parent.createSync(recursive: true);
  final temporary = File('${target.path}.tmp');
  temporary.writeAsStringSync(jsonEncode(settings));
  temporary.renameSync(target.path);
  look.value = LookSettings.fromJson(settings);
}

/// radius_m[0] of a COSMIC theme's corner_radii file (RON), or null.
double? parseRadiusM(String text) {
  final match = RegExp(r'radius_m\s*:\s*\(\s*(-?[0-9]+(?:\.[0-9]+)?)').firstMatch(text);
  final value = match == null ? null : double.tryParse(match[1]!);
  return value == null || value < 0 || value > 1000 ? null : value;
}

/// The COSMIC theme's corner radius for light or dark, as the Maprisma COSMIC apps show it in
/// "Like the desktop (N px)": its medium radius (16 Round, 8 Slightly round, 2 Square); 16, as
/// libcosmic's default theme, without one (KDE).
double desktopRadius(Brightness brightness, [Map<String, String>? environment]) {
  final env = environment ?? Platform.environment;
  final configured = env['XDG_CONFIG_HOME'];
  final config = configured != null && configured.startsWith('/') ? configured : '${env['HOME'] ?? ''}/.config';
  final mode = brightness == Brightness.dark ? 'Dark' : 'Light';
  return parseRadiusM(readRegularNoFollow('$config/cosmic/com.system76.CosmicTheme.$mode/v1/corner_radii')) ?? 16;
}

/// "slight" 6, "rounded" 12, "square" 0; null for "desktop": Material's own corners, untouched.
double? cornerRadius(String setting) => switch (setting) {
  'slight' => 6,
  'rounded' => 12,
  'square' => 0,
  _ => null,
};

@immutable
class Corners {
  const Corners(this.radius);
  final double radius;
  double get control => min(radius, 8);
  double get small => min(radius, 4);
  double get pill => radius > 0 ? 999 : 0;
}

String cornerLabel(String choice, double desktop) => switch (choice) {
  'slight' => trf('Slightly rounded ({0} px)', [6]),
  'rounded' => trf('Rounded ({0} px)', [12]),
  'square' => tr('Square'),
  _ => trf('Like the desktop ({0} px)', [desktop.round()]),
};

/// [theme] with the corners of [corners] on its cards, dialogs, menus, buttons and check boxes.
/// (The window's text fields are drawn without a frame, so they have no corners.)
ThemeData withCorners(ThemeData theme, Corners corners) {
  RoundedRectangleBorder round(double r) => RoundedRectangleBorder(borderRadius: BorderRadius.circular(r));
  final control = round(corners.control);
  final buttons = ButtonStyle(shape: WidgetStatePropertyAll(control));
  final menu = MenuStyle(shape: WidgetStatePropertyAll(round(corners.radius)));
  return theme.copyWith(
    cardTheme: theme.cardTheme.copyWith(shape: round(corners.radius)),
    dialogTheme: theme.dialogTheme.copyWith(shape: round(corners.radius)),
    popupMenuTheme: theme.popupMenuTheme.copyWith(shape: round(corners.radius)),
    menuTheme: MenuThemeData(style: menu),
    dropdownMenuTheme: DropdownMenuThemeData(menuStyle: menu),
    filledButtonTheme: FilledButtonThemeData(style: buttons),
    outlinedButtonTheme: OutlinedButtonThemeData(style: buttons),
    textButtonTheme: TextButtonThemeData(style: buttons),
    elevatedButtonTheme: ElevatedButtonThemeData(style: buttons),
    iconButtonTheme: IconButtonThemeData(style: buttons),
    checkboxTheme: theme.checkboxTheme.copyWith(shape: round(corners.small)),
    chipTheme: theme.chipTheme.copyWith(shape: round(corners.pill)),
    extensions: [CornerSizes(corners.radius)],
  );
}

/// The sizes in a widget's theme: `Theme.of(context).extension<CornerSizes>()`.
class CornerSizes extends ThemeExtension<CornerSizes> {
  const CornerSizes(this.radius);
  final double radius;
  Corners get sizes => Corners(radius);
  @override
  CornerSizes copyWith({double? radius}) => CornerSizes(radius ?? this.radius);
  @override
  CornerSizes lerp(CornerSizes? other, double t) => other ?? this;
}

Corners cornersOf(BuildContext context) => Theme.of(context).extension<CornerSizes>()?.sizes ?? const Corners(12);

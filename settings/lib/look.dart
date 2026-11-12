// Settings › Corners and F12 saves a screenshot: stored next to the interface language, read by
// the panel applet too. The corner sizes and the theme are in app_theme.dart.

import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';

import 'desktop_look.dart';
import 'i18n.dart';

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

/// The desktop's palette and corners in effect (desktop_look.dart), kept fresh by the app's root;
/// empty in tests.
final desktopLook = ValueNotifier<DesktopLook>(const DesktopLook());

String cornerLabel(String choice, int? desktop) => switch (choice) {
  'slight' => trf('Slightly rounded ({0} px)', [6]),
  'rounded' => trf('Rounded ({0} px)', [12]),
  'square' => tr('Square'),
  _ => trf('Like the desktop ({0} px)', [desktop ?? 12]),
};

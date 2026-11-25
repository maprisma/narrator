// Settings › App skin, Corners and F12 saves a screenshot: stored next to the interface
// language and read by the panel applet too.

import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';

import 'desktop_look.dart';
import 'i18n.dart';
import 'skin.dart';

/// The app's folder in the pictures folder, and its pictures' name.
const screenshotApp = 'Maprisma Narrator';
const screenshotSlug = 'maprisma-narrator';

/// The settings file the look is stored in (tests point it elsewhere).
File Function() lookSettingsFile = languageSettingsFile;

const cornerChoices = ['desktop', 'slight', 'rounded', 'square'];

@immutable
class LookSettings {
  const LookSettings({
    this.screenshotKey = true,
    this.corners = 'desktop',
    this.skin = 'native',
  });
  final bool screenshotKey;
  final String corners;
  final String skin;

  /// From the settings file's JSON: a missing or unknown value is the default.
  factory LookSettings.fromJson(Object? json) {
    final map = json is Map ? json : const {};
    final key = map['screenshot_key'];
    final corners = map['corners'];
    return LookSettings(
      screenshotKey: key is bool ? key : true,
      corners: cornerChoices.contains(corners) ? corners as String : 'desktop',
      skin: normalizeSkin(
        map[skinKey] is String ? map[skinKey] as String : null,
      ),
    );
  }

  @override
  bool operator ==(Object other) =>
      other is LookSettings &&
      other.screenshotKey == screenshotKey &&
      other.corners == corners &&
      other.skin == skin;
  @override
  int get hashCode => Object.hash(screenshotKey, corners, skin);
}

LookSettings readLook([File? file]) {
  try {
    return LookSettings.fromJson(
      jsonDecode((file ?? lookSettingsFile()).readAsStringSync()),
    );
  } on Object {
    return const LookSettings(); // missing or malformed: the defaults
  }
}

final look = ValueNotifier<LookSettings>(readLook());

/// Saves one look value, keeping every other key of the settings file.
void saveLook({
  bool? screenshotKey,
  String? corners,
  String? skin,
  File? file,
}) {
  if (corners != null && !cornerChoices.contains(corners)) return;
  if (skin != null && !appSkins.contains(skin)) return;
  final target = file ?? lookSettingsFile();
  Map<String, dynamic> settings = {};
  try {
    settings = (jsonDecode(target.readAsStringSync()) as Map)
        .cast<String, dynamic>();
  } on Object {
    /* first save */
  }
  if (screenshotKey != null) settings['screenshot_key'] = screenshotKey;
  if (corners != null) {
    if (corners == 'desktop') {
      settings.remove('corners');
    } else {
      settings['corners'] = corners;
    }
  }
  if (skin != null) {
    if (skin == 'native') {
      settings.remove(skinKey);
    } else {
      settings[skinKey] = skin;
    }
  }
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

import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';

import 'translations.g.dart';

const languageNames = {
  'en': 'English',
  'de': 'Deutsch',
  'fr': 'Français',
  'es': 'Español',
  'it': 'Italiano',
  'pt': 'Português',
  'nl': 'Nederlands',
  'pl': 'Polski',
};
String systemLanguage(Map<String, String> env) {
  final locale =
      [
        env['LC_ALL'],
        env['LC_MESSAGES'],
        env['LANG'],
      ].whereType<String>().where((s) => s.isNotEmpty).firstOrNull ??
      '';
  final code = locale.split(RegExp(r'[_ .@-]')).first.toLowerCase();
  return languageNames.containsKey(code) ? code : 'en';
}

File languageSettingsFile([Map<String, String>? environment]) {
  final env = environment ?? Platform.environment;
  final configured = env['XDG_CONFIG_HOME'];
  final config = configured != null && configured.isNotEmpty
      ? configured
      : '${env['HOME'] ?? ''}/.config';
  return File('$config/maprisma-narrator/settings.json');
}

String readLanguage({File? settingsFile}) {
  try {
    final value = jsonDecode(
      (settingsFile ?? languageSettingsFile()).readAsStringSync(),
    )['interface_language'];
    if (languageNames.containsKey(value)) return value as String;
  } catch (_) {
    /* A missing or malformed settings file follows the system. */
  }
  return 'auto';
}

final interfaceLanguage = ValueNotifier<String>(readLanguage());
String get activeLanguage => interfaceLanguage.value == 'auto'
    ? systemLanguage(Platform.environment)
    : interfaceLanguage.value;
void setInterfaceLanguage(String value, {File? settingsFile}) {
  if (value != 'auto' && !languageNames.containsKey(value)) return;
  final file = settingsFile ?? languageSettingsFile();
  Map<String, dynamic> settings = {};
  try {
    settings = (jsonDecode(file.readAsStringSync()) as Map)
        .cast<String, dynamic>();
  } catch (_) {
    /* First save. */
  }
  settings['interface_language'] = value;
  file.parent.createSync(recursive: true);
  final temporary = File('${file.path}.tmp');
  temporary.writeAsStringSync(jsonEncode(settings));
  temporary.renameSync(file.path);
  interfaceLanguage.value = value;
}

String tr(String text) => translations[activeLanguage]?[text] ?? text;
String trf(String text, List<Object?> values) =>
    tr(text).replaceAllMapped(RegExp(r'\{(\d+)\}'), (m) {
      final i = int.parse(m[1]!);
      return i < values.length ? '${values[i]}' : m[0]!;
    });

// Presentation adapter for shared reader messages; substituted values stay data.
String message(String text) {
  if (text.startsWith('There is no ') &&
      text.endsWith(' voice yet.') &&
      text.length >= 23) {
    return trf('There is no {0} voice yet.', [
      text.substring(12, text.length - 11),
    ]);
  }
  if (text.startsWith('Text recognition for ') &&
      text.endsWith(' is not installed yet.') &&
      text.length >= 43) {
    return trf('Text recognition for {0} is not installed yet.', [
      text.substring(21, text.length - 22),
    ]);
  }
  if (text.startsWith('Install ') &&
      text.endsWith(' text recognition') &&
      text.length >= 25) {
    return trf('Install {0} text recognition', [
      text.substring(8, text.length - 17),
    ]);
  }
  if (text.startsWith('The translation server (') &&
      text.endsWith(') is not running.') &&
      text.length >= 41) {
    return trf('The translation server ({0}) is not running.', [
      text.substring(24, text.length - 17),
    ]);
  }
  if (text.startsWith('Voice test failed: ')) {
    return trf('Voice test failed: {0}', [text.substring(19)]);
  }
  if (text.startsWith('Translation works: ')) {
    return trf('Translation works: {0}', [text.substring(19)]);
  }
  if (text.startsWith('Translation test failed: ')) {
    return trf('Translation test failed: {0}', [text.substring(25)]);
  }
  if (text.startsWith('Kokoro installed for ')) {
    return trf('Kokoro installed for {0}', [text.substring(21)]);
  }
  if (text.startsWith('Install ') && text.endsWith(')')) {
    final at = text.indexOf(' voice (', 8);
    if (at > 0) {
      return trf('Install {0} voice ({1})', [
        text.substring(8, at),
        text.substring(at + 8, text.length - 1),
      ]);
    }
  }
  return tr(text);
}

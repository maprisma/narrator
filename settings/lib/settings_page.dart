// The settings window: what needs setting up, then Reading, Voice, Qwen voice, Speech server
// and Translation (port of the GNOME extension's prefs.js). Every change goes to the reader at
// once through the bridge; the state is polled every 1.5 s while the window is open.

import 'i18n.dart';
import 'dart:async';
import 'dart:io';

import 'package:file_selector/file_selector.dart';
import 'package:flutter/material.dart';

import 'app_look.dart';
import 'bridge.dart';
import 'look.dart';
import 'widgets.dart';

const servers = [
  ('llama.cpp', 'http://127.0.0.1:8080/v1'),
  ('LM Studio', 'http://127.0.0.1:1234/v1'),
  ('Ollama', 'http://127.0.0.1:11434/v1'),
];
String get offline => tr('Offline translator (NLLB-200)');
// Qwen speaks with a llama.cpp TTS runner, two model files and a recording of the speaker.
List<(String, String, String)> get qwenFiles => [
  ('qwen_runner', tr('Speech runner'), tr('The llama.cpp TTS program (llama-tts)')),
  ('qwen_model', tr('Voice model'), tr('The Qwen3-TTS 1.7B model (.gguf)')),
  ('qwen_projection', tr('Audio model'), tr('Its matching audio projection (mmproj-….gguf)')),
  ('qwen_speaker', tr('Speaker recording'), tr('A clear recording of the voice to speak with (.wav)')),
];
const qwenLanguages = ['zh', 'en', 'ja', 'ko', 'de', 'fr', 'ru', 'pt', 'es', 'it'];
List<(String, String, String)> get readingSwitches => [
  ('follow', tr('Read new pages'), tr('Also pages you turn yourself; off reads one page')),
  ('highlight', tr('Highlight the passage being read'), ''),
  ('pdf_page_area', tr('Read only the page in PDF viewers'), tr('Document Viewer and Papers: no toolbar, sidebar or page numbers')),
  ('kindle_crop', tr('Skip the Kindle toolbar and progress bar'), ''),
  ('auto_page_turn', tr('Turn Kindle and PDF pages after reading'), tr('Stops at the end of the document')),
];

/// A number as JavaScript prints it (800, not 800.0).
String jsNumber(Object? value) {
  if (value is num && value == value.roundToDouble() && value.isFinite) return value.toInt().toString();
  return '$value';
}

List<Option> options(Object? list) => [
      if (list is List)
        for (final o in list.whereType<Map>()) ('${o['value']}', '${o['label']}'),
    ];

class SettingsPage extends StatefulWidget {
  const SettingsPage({super.key, required this.bridge});

  final Bridge bridge;

  @override
  State<SettingsPage> createState() => _SettingsPageState();
}

class _SettingsPageState extends State<SettingsPage> {
  Json _state = {};
  Timer? _timer;
  bool _polling = false;

  String? _installLanguage;
  bool _serverFilled = false;
  bool _translatorRememberFilled = false;
  bool _remember = false;
  bool _translatorRemember = false;
  String? _testedToken;

  final _endpoint = TextEditingController();
  final _model = TextEditingController();
  final _voiceId = TextEditingController();
  final _token = TextEditingController();
  final _translatorToken = TextEditingController();
  final _qwenPaths = {for (final (key, _, _) in qwenFiles) key: TextEditingController()};

  @override
  void initState() {
    super.initState();
    for (final c in [_endpoint, _model, _voiceId, _token, _translatorToken, ..._qwenPaths.values]) {
      c.addListener(_changed);
    }
    _refresh();
    _timer = Timer.periodic(const Duration(milliseconds: 1500), (_) => _refresh());
  }

  @override
  void dispose() {
    _timer?.cancel();
    for (final c in [_endpoint, _model, _voiceId, _token, _translatorToken, ..._qwenPaths.values]) {
      c.dispose();
    }
    super.dispose();
  }

  void _changed() {
    if (mounted) setState(() {});
  }

  Json get _settings => (_state['settings'] as Map?)?.cast<String, dynamic>() ?? {};

  Future<void> _send(Json payload) async {
    final state = await widget.bridge.request(payload);
    if (!mounted) return;
    if (state['error'] != null) {
      ScaffoldMessenger.of(context)
        ..hideCurrentSnackBar()
        ..showSnackBar(SnackBar(content: Text(message('${state['error']}')), duration: const Duration(seconds: 6)));
    } else {
      _update(state);
    }
  }

  void _configure(Json settings) => _send({'command': 'configure', 'settings': settings});

  Future<void> _refresh() async {
    // A status poll still waiting in the queue is enough; do not stack more behind it.
    if (_polling) return;
    _polling = true;
    final state = await widget.bridge.request({'command': 'status'});
    _polling = false;
    if (mounted && state['error'] == null) _update(state);
  }

  void _update(Json state) {
    setState(() {
      _state = state;
      final settings = _settings;
      if (!_translatorRememberFilled && state['settings'] != null) {
        _translatorRememberFilled = true;
        _translatorRemember = truthy(settings['remember_translator_token']);
      }
      if (!_serverFilled && state['settings'] != null) {
        // The fields start from the server in use (or the last one tried) and are then the user's.
        _serverFilled = true;
        for (final (key, _, _) in qwenFiles) {
          if (truthy(settings[key])) _qwenPaths[key]!.text = '${settings[key]}';
        }
        _endpoint.text = settings['online_endpoint'] as String? ?? 'https://api.openai.com/v1';
        _model.text = settings['online_model'] as String? ?? '';
        _voiceId.text = settings['online_voice'] as String? ?? 'alloy';
        _remember = truthy(settings['remember_token']);
      }
    });
  }

  String? _speechLanguage() {
    final settings = _settings;
    return truthy(settings['translate_to']) ? '${settings['translate_to']}' : settings['language'] as String?;
  }

  Json _qwenCandidate() => {
        'provider': 'Local',
        'voice': 'qwen-custom',
        for (final entry in _qwenPaths.entries)
          if (entry.value.text.trim().isNotEmpty) entry.key: entry.value.text.trim(),
      };

  Json _candidate() => {
        'provider': 'Online',
        'online_endpoint': _endpoint.text.trim(),
        'online_model': _model.text.trim(),
        'online_voice': _voiceId.text.trim(),
      };

  String? _tokenOrNull() => _token.text.isEmpty ? null : _token.text;

  bool _matchesVerified(Json candidate) {
    final verified = (_state['verified_provider'] as Map?) ?? {};
    return candidate.entries.every((e) => verified[e.key] == e.value);
  }

  Future<void> _chooseFile(String key, String title) async {
    final current = _qwenPaths[key]!.text.trim();
    final file = await openFile(
      confirmButtonText: tr('Open'),
      initialDirectory: current.isEmpty ? null : File(current).parent.path,
    );
    if (file != null) _qwenPaths[key]!.text = file.path;
  }

  void _applyTranslatorToken() {
    _send({
      'command': 'configure-translator-token',
      'token': _translatorToken.text,
      'remember_token': _translatorRemember,
    });
    _translatorToken.text = '';
  }

  /// Settings › Corners and F12 saves a screenshot (look.dart; the applet reads them too).
  List<Widget> _lookRows(BuildContext context) {
    final desktop = desktopLook.value.rounding;
    void save(void Function() write) {
      try {
        write();
        setState(() {});
      } on FileSystemException catch (error) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error.osError?.message ?? error.message)));
      }
    }

    return [
      PrefRow(title: tr('Corners'), suffixes: [
        ChoiceButton(
          title: tr('Corners'),
          options: [for (final choice in cornerChoices) (choice, cornerLabel(choice, desktop))],
          value: look.value.corners,
          onPick: (value) => save(() => saveLook(corners: value)),
        ),
      ]),
      SwitchPrefRow(
        title: tr('F12 saves a screenshot'),
        value: look.value.screenshotKey,
        onChanged: (on) => save(() => saveLook(screenshotKey: on)),
      ),
    ];
  }

  @override
  Widget build(BuildContext context) {
    final state = _state;
    final settings = _settings;
    final ready = state['backend_ready'] == true && !truthy(state['setup_busy']);
    final languages = options(state['languages']);

    return Scaffold(
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.symmetric(vertical: AppSpace.lg),
          children: [
            Center(
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 720),
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: AppSpace.lg),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      PrefGroup(title: tr('Language'), children: [
                        PrefRow(title: tr('Language'), suffixes: [
                          ChoiceButton(
                            title: tr('Language'),
                            options: [
                              ('auto', trf('System ({0})', [languageNames[systemLanguage(Platform.environment)]])),
                              ...languageNames.entries.map((e) => (e.key, e.value)),
                            ],
                            value: interfaceLanguage.value,
                            onPick: (value) {
                              try {
                                setInterfaceLanguage(value);
                                setState(() {});
                              } on FileSystemException {
                                ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(tr('Could not save the language setting.'))));
                              }
                            },
                          ),
                        ]),
                        ..._lookRows(context),
                      ]),
                      _statusGroup(state),
                      _readingGroup(state, settings, languages, ready),
                      _voiceGroup(state, settings, languages, ready),
                      _qwenGroup(state, settings, languages, ready),
                      _serverGroup(state, settings, ready),
                      _translationGroup(state, settings, languages, ready),
                    ],
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _statusGroup(Json state) {
    final step = nextStep(state);
    final window = state['window'];
    final notices = state['notices'];
    final notice = notices is List && notices.isNotEmpty ? notices.last as Map? : null;
    final ready = state['backend_ready'] == true && !truthy(state['setup_busy']);
    final reading = truthy(state['enabled']);
    final paused = truthy(state['paused']);
    final canStart = ready && !reading && state['can_start'] != false && step == null;
    return PrefGroup(children: [
      PrefRow(
        title: message(state['status'] as String? ?? tr('Maprisma Narrator')),
        subtitle: step?.text == null ? (truthy(window) ? trf('Reading: {0}', [window]) : '') : message(step!.text!),
        suffixes: [
          if (truthy(state['setup_busy']))
            const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)),
          if (step != null && step.label.isNotEmpty && step.payload != null)
            FilledButton(onPressed: () => _send(step.payload!), child: Text(message(step.label))),
          if (step == null && ready) ...[
            if (!reading)
              FilledButton(
                onPressed: canStart ? () => _send({'command': 'on'}) : null,
                child: Text(tr('Start')),
              ),
            if (reading) ...[
              OutlinedButton(
                onPressed: () => _send({'command': 'pause'}),
                child: Text(paused ? tr('Resume') : tr('Pause')),
              ),
              OutlinedButton(
                onPressed: () => _send({'command': 'off'}),
                child: Text(tr('Stop')),
              ),
            ],
          ],
        ],
      ),
      if (step == null && ready && reading)
        PrefRow(
          title: tr('Book'),
          subtitle: tr('Re-read this page or switch to the focused window'),
          suffixes: [
            OutlinedButton(
              onPressed: () => _send({'command': 'reread'}),
              child: Text(tr('Read again')),
            ),
            OutlinedButton(
              onPressed: () => _send({'command': 'read'}),
              child: Text(tr('Read active window')),
            ),
          ],
        ),
      if (notice != null)
        PrefRow(title: tr('Last problem'), subtitle: '${tr('${notice['title']}')}: ${message('${notice['text']}')}', error: true),
    ]);
  }

  Widget _readingGroup(Json state, Json settings, List<Option> languages, bool ready) {
    final custom = state['custom_area'];
    final kindle = settings['kindle_area'];
    final area = truthy(custom)
        ? trf('Selected area ({0}×{1} px)', [jsNumber((custom as List)[2]), jsNumber(custom[3])])
        : truthy(kindle)
            ? trf('Kindle ({0}% × {1}%)', [(((kindle as List)[2] as num) * 100).round(), ((kindle[3] as num) * 100).round()])
            : tr('The whole active window');
    return PrefGroup(title: tr('Reading'), children: [
      PrefRow(
        title: tr('Text language'),
        subtitle: tr('The language of the text on screen'),
        enabled: ready,
        suffixes: [
          ChoiceButton(
            title: tr('Text language'),
            options: languages,
            value: settings['language'] as String?,
            searchable: true,
            onPick: (language) => _configure({'language': language}),
          ),
        ],
      ),
      PrefRow(
        title: tr('Reading speed'),
        enabled: ready,
        suffixes: [
          SpinField(
            value: ((settings['speed'] as num?) ?? 1).toDouble(),
            lower: 0.6,
            upper: 2,
            step: 0.05,
            digits: 2,
            onChanged: (v) => _configure({'speed': (v * 100).round() / 100}),
          ),
        ],
      ),
      for (final (key, title, subtitle) in readingSwitches)
        SwitchPrefRow(
          title: tr(title),
          subtitle: tr(subtitle),
          enabled: ready,
          value: settings[key] is bool ? settings[key] as bool : truthy(settings[key] ?? true),
          onChanged: (value) => _configure({key: value}),
        ),
      PrefRow(
        title: tr('Reading area'),
        subtitle: area,
        enabled: ready,
        suffixes: [
          if (truthy(custom) || truthy(kindle))
            TextButton(onPressed: () => _send({'command': 'clear-area'}), child: Text(tr('Reset'))),
          OutlinedButton(onPressed: () => _send({'command': 'select-area'}), child: Text(tr('Select…'))),
        ],
      ),
    ]);
  }

  Widget _voiceGroup(Json state, Json settings, List<Option> languages, bool ready) {
    final online = settings['provider'] == 'Online';
    final voices = options(state['voices']);
    final spoken = _speechLanguage();
    final kokoro = (state['kokoro_languages'] as Map?) ?? {};
    final updates = (state['kokoro_updates'] as Map?) ?? {};
    final update = (updates[spoken] as Map?) ?? {};
    final installing = truthy(state['installing_kokoro']);
    final checking = truthy(state['kokoro_checking']);
    final providerStatus = state['provider_status'];
    final kokoroSubtitle = checking
        ? tr('Checking the official Kokoro model sources…')
        : installing
            ? (truthy(providerStatus) ? message('$providerStatus') : tr('Updating the Kokoro model…'))
            : (truthy(update['message'])
                ? message('${update['message']}')
                : tr('Looks for newer verified models of this language\'s Kokoro voice'));
    return PrefGroup(title: tr('Voice'), children: [
      PrefRow(
        title: tr('Voice'),
        subtitle: online
            ? tr('A speech server is in use; choosing a voice here switches back')
            : voices.isNotEmpty
                ? ''
                : tr('No voice is installed for this language yet'),
        enabled: ready,
        suffixes: [
          TextButton(onPressed: () => _send({'command': 'test-voice'}), child: Text(tr('Test'))),
          ChoiceButton(
            title: tr('Voice'),
            options: voices,
            value: online ? null : settings['voice'] as String?,
            onPick: (voice) => _configure({'provider': 'Local', 'voice': voice}),
          ),
        ],
      ),
      PrefRow(
        title: tr('Audio output'),
        enabled: ready,
        suffixes: [
          ChoiceButton(
            title: tr('Audio output'),
            options: [for (final o in options(state['audio_outputs'])) (o.$1, o.$1 == 'auto' ? tr('System default') : o.$2)],
            value: settings['audio_output'] as String?,
            onPick: (value) => _configure({'audio_output': value}),
          ),
        ],
      ),
      // Kokoro (or Piper where Kokoro has no voice) for any language, with its text recognition.
      PrefRow(
        title: tr('Install a voice'),
        subtitle: tr('With text recognition for the language'),
        enabled: !truthy(state['setup_busy']),
        suffixes: [
          ChoiceButton(
            title: tr('Install a voice'),
            options: languages,
            value: _installLanguage ?? settings['language'] as String?,
            searchable: true,
            onPick: (value) => setState(() => _installLanguage = value),
          ),
          OutlinedButton(
            onPressed: () {
              final language = _installLanguage ?? settings['language'];
              if (truthy(language)) _send({'command': 'setup', 'language': language});
            },
            child: Text(tr('Install')),
          ),
        ],
      ),
      // Newer Kokoro models for the spoken language: checked on request, never installed on their own.
      if (kokoro.containsKey(spoken))
        PrefRow(
          title: tr('Kokoro model updates'),
          subtitle: kokoroSubtitle,
          enabled: ready,
          suffixes: [
            if (!installing)
              TextButton(
                onPressed: !checking && !truthy(state['enabled'])
                    ? () => _send({'command': 'check-kokoro-updates', 'language': _speechLanguage()})
                    : null,
                child: Text(tr('Check')),
              ),
            if (update['available'] == true && !installing)
              FilledButton(
                onPressed: () => _send({'command': 'update-kokoro', 'language': _speechLanguage()}),
                child: Text(tr('Update')),
              ),
            if (installing)
              OutlinedButton(
                onPressed: () => _send({'command': 'cancel-kokoro-install'}),
                child: Text(tr('Cancel')),
              ),
          ],
        ),
    ]);
  }

  // A Qwen voice: like a speech server it is tested first, then used.
  Widget _qwenGroup(Json state, Json settings, List<Option> languages, bool ready) {
    final spoken = _speechLanguage();
    final candidate = _qwenCandidate();
    final canUse = qwenFiles.every((f) => candidate.containsKey(f.$1)) && _matchesVerified(candidate);
    final spokenLabel = languages.where((o) => o.$1 == spoken).firstOrNull?.$2 ?? spoken;
    final providerStatus = state['provider_status'];
    final testSubtitle = !qwenLanguages.contains(spoken)
        ? trf('Qwen does not speak {0}', [spokenLabel])
        : truthy(state['testing_voice'])
            ? tr('Testing the voice…')
            : (truthy(providerStatus) ? message('$providerStatus') : '');
    return PrefGroup(
      title: tr('Qwen voice'),
      description: tr('Qwen3-TTS through llama.cpp speaks with the voice of any recording you choose. It needs the files below; nothing is downloaded for it.'),
      children: [
        for (final (key, title, help) in qwenFiles) _qwenFileRow(key, title, help, ready),
        PrefRow(
          title: tr('Test the voice, then use it'),
          subtitle: testSubtitle,
          enabled: ready,
          suffixes: [
            OutlinedButton(
              onPressed: () => _send({'command': 'test-provider', 'settings': _qwenCandidate()}),
              child: Text(tr('Test')),
            ),
            FilledButton(
              onPressed: canUse ? () => _send({'command': 'use-provider', 'settings': _qwenCandidate()}) : null,
              child: Text(tr('Use')),
            ),
          ],
        ),
      ],
    );
  }

  Widget _qwenFileRow(String key, String title, String help, bool ready) {
    final path = _qwenPaths[key]!.text.trim();
    final missing = path.isNotEmpty && !FileSystemEntity.isFileSync(path) ? tr(' · not found') : '';
    final subtitle = path.isNotEmpty ? '${path.split('/').last}$missing' : tr(help);
    final theme = Theme.of(context);
    return Sensitive(
      enabled: ready,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(AppSpace.md, AppSpace.xs, AppSpace.md, AppSpace.sm),
        child: Row(
          children: [
            Expanded(
              child: TextField(
                controller: _qwenPaths[key],
                autocorrect: false,
                decoration: InputDecoration(
                  labelText: tr(title),
                  helperText: subtitle,
                  helperStyle: missing.isNotEmpty ? theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.error) : null,
                  border: InputBorder.none,
                  isDense: true,
                ),
              ),
            ),
            const SizedBox(width: AppSpace.sm),
            OutlinedButton(onPressed: () => _chooseFile(key, title), child: Text(tr('Choose…'))),
          ],
        ),
      ),
    );
  }

  // An OpenAI-compatible speech server instead of the voices on this computer. It is tested
  // first (a sample sentence through the audio output), then used.
  Widget _serverGroup(Json state, Json settings, bool ready) {
    final online = settings['provider'] == 'Online';
    final speechModels = [
      if (state['online_models'] is List)
        for (final m in state['online_models'] as List) ('$m', '$m'),
    ];
    final candidate = _candidate();
    final complete = candidate['online_endpoint'] != '' && candidate['online_model'] != '' && candidate['online_voice'] != '';
    final canUse = complete && _token.text == (_testedToken ?? '') && _matchesVerified(candidate);
    final keyReady = truthy(state['key_ready']);
    final providerStatus = state['provider_status'];
    return PrefGroup(
      title: tr('Speech server'),
      description: tr('An OpenAI-compatible server with /v1/audio/speech and WAV output. A remote server receives the text being read and may charge for speech; a server on this computer keeps it here.'),
      children: [
        PrefRow(
          title: tr('In use'),
          subtitle: online
              ? trf('Speech server · {0} · {1} / {2}', [settings['online_endpoint'], settings['online_model'], settings['online_voice']])
              : tr('Voices on this computer (Kokoro or Piper)'),
          enabled: ready,
          suffixes: [
            if (online)
              OutlinedButton(
                onPressed: () => _configure({'provider': 'Local'}),
                child: Text(tr('Use voices on this computer')),
              ),
          ],
        ),
        EntryPrefRow(
          title: tr('Server address (https://…/v1, or http://localhost)'),
          controller: _endpoint,
          enabled: ready,
        ),
        EntryPrefRow(
          title: tr('Speech model'),
          controller: _model,
          enabled: ready,
          suffixes: [
            TextButton(
              onPressed: () => _send({
                'command': 'online-models',
                'endpoint': _endpoint.text.trim(),
                'token': _tokenOrNull(),
              }),
              child: Text(tr('Find models')),
            ),
          ],
        ),
        if (speechModels.isNotEmpty)
          PrefRow(
            title: tr('Models on the server'),
            subtitle: tr('Chat models cannot speak: choose a speech model'),
            suffixes: [
              ChoiceButton(
                title: tr('Models on the server'),
                options: speechModels,
                value: _model.text.trim(),
                searchable: true,
                onPick: (model) => _model.text = model,
              ),
            ],
          ),
        EntryPrefRow(title: tr('Voice'), controller: _voiceId, enabled: ready),
        EntryPrefRow(
          title: keyReady && _endpoint.text.trim() == settings['online_endpoint']
              ? tr('API key / token (the saved one is used; type to replace it)')
              : tr('API key / token, if the server needs one'),
          controller: _token,
          password: true,
          enabled: ready,
        ),
        SwitchPrefRow(
          title: tr('Remember the token on this device'),
          subtitle: tr('Saved in an owner-only plain-text file'),
          value: _remember,
          enabled: ready,
          onChanged: (value) => setState(() => _remember = value),
        ),
        PrefRow(
          title: tr('Test the voice, then use the server'),
          subtitle: truthy(state['models_loading'])
              ? tr('Asking the server for its models…')
              : truthy(state['testing_voice'])
                  ? tr('Testing the voice…')
                  : (truthy(providerStatus) ? message('$providerStatus') : ''),
          enabled: ready,
          suffixes: [
            OutlinedButton(
              onPressed: () {
                setState(() => _testedToken = _token.text);
                _send({'command': 'test-provider', 'settings': _candidate(), 'token': _tokenOrNull()});
              },
              child: Text(tr('Test')),
            ),
            FilledButton(
              onPressed: canUse
                  ? () => _send({
                        'command': 'use-provider',
                        'settings': _candidate(),
                        'token': _tokenOrNull(),
                        'remember_token': _remember,
                      })
                  : null,
              child: Text(tr('Use')),
            ),
          ],
        ),
        if (keyReady)
          PrefRow(
            title: tr('Saved token of the server in use'),
            suffixes: [
              TextButton(
                onPressed: () => _send({'command': 'configure-token', 'token': '', 'remember_token': false}),
                child: Text(tr('Clear')),
              ),
            ],
          ),
      ],
    );
  }

  Widget _translationGroup(Json state, Json settings, List<Option> languages, bool ready) {
    final target = settings['translate_to'] as String? ?? '';
    final translating = target.isNotEmpty;
    final endpoint = settings['translator_endpoint'] as String? ?? servers.first.$2;
    final serverOptions = <Option>[
      for (final (name, url) in servers) (url, '$name (${url.replaceFirst(RegExp(r'^https?://'), '')})'),
      if (!servers.any((s) => s.$2 == endpoint)) (endpoint, endpoint),
      ('nllb', offline),
    ];
    final offlineSelected = settings['translator'] == 'nllb';
    final models = <String>{
      if (state['translator_models'] is List)
        for (final m in state['translator_models'] as List)
          if (truthy(m)) '$m',
      if (truthy(settings['translator_model'])) '${settings['translator_model']}',
    }.toList();
    final installingTranslator = truthy(state['installing_translator']);
    final server = translating && !offlineSelected;
    final translatorKeyReady = truthy(state['translator_key_ready']);
    return PrefGroup(
      title: tr('Translation'),
      description: tr('Read the text in one language and hear it in another'),
      children: [
        PrefRow(
          title: tr('Speak in'),
          enabled: ready,
          suffixes: [
            ChoiceButton(
              title: tr('Speak in'),
              options: [
                ('', tr('Off · read in the text language')),
                ...languages.where((o) => o.$1 != settings['language']),
              ],
              value: target,
              searchable: true,
              onPick: (value) => _configure({'translate_to': value}),
            ),
          ],
        ),
        if (translating)
          PrefRow(
            title: tr('Translator'),
            enabled: ready,
            suffixes: [
              ChoiceButton(
                title: tr('Translator'),
                options: serverOptions,
                value: offlineSelected ? 'nllb' : endpoint,
                onPick: (value) => value == 'nllb'
                    ? _configure({'translator': 'nllb'})
                    : _configure({'translator': 'llm', 'translator_endpoint': value, 'translator_model': ''}),
              ),
            ],
          ),
        if (translating && !offlineSelected)
          PrefRow(
            title: tr('Model'),
            subtitle: tr('A chat or instruct model of the server'),
            enabled: ready,
            suffixes: [
              TextButton(onPressed: () => _send({'command': 'translator-models'}), child: Text(tr('Refresh'))),
              ChoiceButton(
                title: tr('Model'),
                options: [for (final m in models) (m, m)],
                value: settings['translator_model'] as String?,
                onPick: (value) => _configure({'translator_model': value}),
              ),
            ],
          ),
        if (translating && offlineSelected && (!truthy(state['nllb_ready']) || installingTranslator))
          PrefRow(
            title: tr('Offline translator'),
            subtitle: tr('NLLB-200 1.3B, about 1.4 GB, non-commercial use only (CC-BY-NC 4.0)'),
            suffixes: [
              OutlinedButton(
                onPressed: () => _send({
                  'command': truthy(_state['installing_translator']) ? 'cancel-translator-install' : 'install-translator',
                }),
                child: Text(installingTranslator ? tr('Cancel') : tr('Install')),
              ),
            ],
          ),
        if (server)
          EntryPrefRow(
            title: translatorKeyReady
                ? tr('API key / token (one is in use; enter a new one to replace it)')
                : tr('API key / token, only for servers that need one'),
            controller: _translatorToken,
            password: true,
            enabled: ready,
            onSubmitted: (_) => _applyTranslatorToken(),
            suffixes: [
              if (_translatorToken.text.isNotEmpty)
                IconButton(
                  tooltip: tr('Apply'),
                  icon: const Icon(Icons.check),
                  onPressed: _applyTranslatorToken,
                ),
            ],
          ),
        if (server)
          SwitchPrefRow(
            title: tr('Remember the token on this device'),
            subtitle: tr('Saved in an owner-only plain-text file, for this server only'),
            value: _translatorRemember,
            enabled: ready,
            onChanged: (value) => setState(() => _translatorRemember = value),
          ),
        if (server && translatorKeyReady)
          PrefRow(
            title: tr('Token in use for the translation server'),
            suffixes: [
              TextButton(
                onPressed: () =>
                    _send({'command': 'configure-translator-token', 'token': '', 'remember_token': false}),
                child: Text(tr('Clear')),
              ),
            ],
          ),
        if (translating)
          PrefRow(
            title: tr('Test translation'),
            subtitle: message(state['translation_status'] as String? ?? ''),
            enabled: ready,
            suffixes: [
              OutlinedButton(onPressed: () => _send({'command': 'test-translation'}), child: Text(tr('Test'))),
            ],
          ),
      ],
    );
  }
}

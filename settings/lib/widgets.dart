// Building blocks shaped like libadwaita preference groups and rows.

import 'package:flutter/material.dart';

import 'app_look.dart';
import 'i18n.dart';

/// A titled card of rows, like Adw.PreferencesGroup.
class PrefGroup extends StatelessWidget {
  const PrefGroup({super.key, this.title, this.description, required this.children});

  final String? title;
  final String? description;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final rows = <Widget>[];
    for (final child in children) {
      if (rows.isNotEmpty) rows.add(const Divider(height: 1));
      rows.add(child);
    }
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpace.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (title != null)
            Padding(
              padding: const EdgeInsets.fromLTRB(AppSpace.xs, 0, AppSpace.xs, AppSpace.xs),
              child: Text(title!, style: theme.textTheme.titleSmall),
            ),
          if (description != null)
            Padding(
              padding: const EdgeInsets.fromLTRB(AppSpace.xs, 0, AppSpace.xs, AppSpace.sm),
              child: Text(description!,
                  style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.onSurfaceVariant)),
            ),
          Card(
            margin: EdgeInsets.zero,
            clipBehavior: Clip.antiAlias,
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: rows),
          ),
        ],
      ),
    );
  }
}

/// Greys out and blocks a row, like GTK's `sensitive = false`.
class Sensitive extends StatelessWidget {
  const Sensitive({super.key, required this.enabled, required this.child});

  final bool enabled;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    if (enabled) return child;
    return ExcludeFocus(
      child: IgnorePointer(child: Opacity(opacity: 0.5, child: child)),
    );
  }
}

/// A row with a title, an optional subtitle and suffix widgets, like Adw.ActionRow.
class PrefRow extends StatelessWidget {
  const PrefRow({
    super.key,
    required this.title,
    this.subtitle,
    this.suffixes = const [],
    this.error = false,
    this.enabled = true,
  });

  final String title;
  final String? subtitle;
  final List<Widget> suffixes;
  final bool error;
  final bool enabled;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final color = error ? theme.colorScheme.error : null;
    return Sensitive(
      enabled: enabled,
      child: ConstrainedBox(
        constraints: const BoxConstraints(minHeight: 52),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: AppSpace.md, vertical: AppSpace.sm),
          child: Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(title, style: theme.textTheme.bodyMedium?.copyWith(color: color)),
                    if (subtitle != null && subtitle!.isNotEmpty)
                      Text(subtitle!,
                          style: theme.textTheme.bodySmall?.copyWith(color: color ?? theme.colorScheme.onSurfaceVariant)),
                  ],
                ),
              ),
              for (final suffix in suffixes)
                Padding(padding: const EdgeInsets.only(left: AppSpace.sm), child: suffix),
            ],
          ),
        ),
      ),
    );
  }
}

/// A row with a switch, like Adw.SwitchRow.
class SwitchPrefRow extends StatelessWidget {
  const SwitchPrefRow({
    super.key,
    required this.title,
    this.subtitle,
    required this.value,
    required this.onChanged,
    this.enabled = true,
  });

  final String title;
  final String? subtitle;
  final bool value;
  final ValueChanged<bool> onChanged;
  final bool enabled;

  @override
  Widget build(BuildContext context) => Sensitive(
        enabled: enabled,
        child: InkWell(
          onTap: () => onChanged(!value),
          child: PrefRow(title: title, subtitle: subtitle, suffixes: [Switch(value: value, onChanged: onChanged)]),
        ),
      );
}

/// A text entry row with a floating title, like Adw.EntryRow / Adw.PasswordEntryRow.
class EntryPrefRow extends StatefulWidget {
  const EntryPrefRow({
    super.key,
    required this.title,
    required this.controller,
    this.password = false,
    this.suffixes = const [],
    this.onSubmitted,
    this.enabled = true,
  });

  final String title;
  final TextEditingController controller;
  final bool password;
  final List<Widget> suffixes;
  final ValueChanged<String>? onSubmitted;
  final bool enabled;

  @override
  State<EntryPrefRow> createState() => _EntryPrefRowState();
}

class _EntryPrefRowState extends State<EntryPrefRow> {
  bool _peek = false;

  @override
  Widget build(BuildContext context) {
    return Sensitive(
      enabled: widget.enabled,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: AppSpace.md, vertical: AppSpace.xs),
        child: Row(
          children: [
            Expanded(
              child: TextField(
                controller: widget.controller,
                obscureText: widget.password && !_peek,
                enableSuggestions: !widget.password,
                autocorrect: false,
                onSubmitted: widget.onSubmitted,
                decoration: InputDecoration(
                  labelText: widget.title,
                  border: InputBorder.none,
                  isDense: true,
                ),
              ),
            ),
            if (widget.password)
              IconButton(
                tooltip: _peek ? tr('Hide text') : tr('Show text'),
                icon: Icon(_peek ? Icons.visibility_off_outlined : Icons.visibility_outlined, size: 20),
                onPressed: () => setState(() => _peek = !_peek),
              ),
            for (final suffix in widget.suffixes)
              Padding(padding: const EdgeInsets.only(left: AppSpace.sm), child: suffix),
          ],
        ),
      ),
    );
  }
}

typedef Option = (String value, String label);

/// A choice among (value, label) options that can change while the window is open, like the
/// prefs.js Choice. It reports a pick only when it differs from the current value.
class ChoiceButton extends StatelessWidget {
  const ChoiceButton({
    super.key,
    required this.options,
    required this.value,
    required this.onPick,
    this.searchable = false,
    this.title = '',
  });

  final List<Option> options;
  final String? value;
  final ValueChanged<String> onPick;
  final bool searchable;
  final String title;

  static const double width = 240;

  void _pick(String? picked) {
    if (picked != null && picked != value) onPick(picked);
  }

  @override
  Widget build(BuildContext context) {
    final current = options.where((o) => o.$1 == value).firstOrNull;
    Widget face(VoidCallback? onPressed) => SizedBox(
          width: width,
          child: OutlinedButton(
            onPressed: options.isEmpty ? null : onPressed,
            style: OutlinedButton.styleFrom(
              padding: const EdgeInsets.symmetric(horizontal: AppSpace.md),
              alignment: Alignment.centerLeft,
            ),
            child: Row(
              children: [
                Expanded(child: Text(current?.$2 ?? '', overflow: TextOverflow.ellipsis)),
                const Icon(Icons.arrow_drop_down, size: 20),
              ],
            ),
          ),
        );
    if (searchable) {
      return face(() async {
        _pick(await showDialog<String>(
          context: context,
          builder: (_) => _SearchDialog(title: title, options: options, value: value),
        ));
      });
    }
    return MenuAnchor(
      menuChildren: [
        for (final option in options)
          MenuItemButton(
            onPressed: () => _pick(option.$1),
            leadingIcon: Icon(option.$1 == value ? Icons.check : null, size: 18),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Text(option.$2, overflow: TextOverflow.ellipsis),
            ),
          ),
      ],
      builder: (context, controller, _) =>
          face(() => controller.isOpen ? controller.close() : controller.open()),
    );
  }
}

class _SearchDialog extends StatefulWidget {
  const _SearchDialog({required this.title, required this.options, required this.value});

  final String title;
  final List<Option> options;
  final String? value;

  @override
  State<_SearchDialog> createState() => _SearchDialogState();
}

class _SearchDialogState extends State<_SearchDialog> {
  String _query = '';

  @override
  Widget build(BuildContext context) {
    final query = _query.toLowerCase();
    final shown = widget.options.where((o) => o.$2.toLowerCase().contains(query)).toList();
    return AlertDialog(
      title: Text(widget.title),
      contentPadding: const EdgeInsets.fromLTRB(AppSpace.lg, AppSpace.md, AppSpace.lg, 0),
      content: SizedBox(
        width: 420,
        height: 420,
        child: Column(
          children: [
            TextField(
              autofocus: true,
              decoration: const InputDecoration(prefixIcon: Icon(Icons.search), isDense: true),
              onChanged: (text) => setState(() => _query = text),
              onSubmitted: (_) {
                if (shown.isNotEmpty) Navigator.pop(context, shown.first.$1);
              },
            ),
            const SizedBox(height: AppSpace.sm),
            Expanded(
              child: ListView.builder(
                itemCount: shown.length,
                itemBuilder: (context, index) {
                  final option = shown[index];
                  return ListTile(
                    dense: true,
                    title: Text(option.$2),
                    selected: option.$1 == widget.value,
                    trailing: option.$1 == widget.value ? const Icon(Icons.check, size: 18) : null,
                    onTap: () => Navigator.pop(context, option.$1),
                  );
                },
              ),
            ),
          ],
        ),
      ),
      actions: [TextButton(onPressed: () => Navigator.pop(context), child: Text(tr('Cancel')))],
    );
  }
}

/// A number with − and + buttons and a typed value, like Adw.SpinRow.
class SpinField extends StatefulWidget {
  const SpinField({
    super.key,
    required this.value,
    required this.lower,
    required this.upper,
    required this.step,
    required this.digits,
    required this.onChanged,
  });

  final double value;
  final double lower;
  final double upper;
  final double step;
  final int digits;
  final ValueChanged<double> onChanged;

  @override
  State<SpinField> createState() => _SpinFieldState();
}

class _SpinFieldState extends State<SpinField> {
  late final TextEditingController _text = TextEditingController(text: _format(widget.value));
  final FocusNode _focus = FocusNode();

  String _format(double v) => v.toStringAsFixed(widget.digits);

  @override
  void initState() {
    super.initState();
    _focus.addListener(() {
      if (!_focus.hasFocus) _commit(_text.text);
    });
  }

  @override
  void didUpdateWidget(SpinField old) {
    super.didUpdateWidget(old);
    if (!_focus.hasFocus) _text.text = _format(widget.value);
  }

  @override
  void dispose() {
    _text.dispose();
    _focus.dispose();
    super.dispose();
  }

  void _set(double v) {
    final clamped = v.clamp(widget.lower, widget.upper).toDouble();
    _text.text = _format(clamped);
    if ((clamped - widget.value).abs() > 1e-9) widget.onChanged(clamped);
  }

  void _commit(String text) {
    final parsed = double.tryParse(text.trim().replaceAll(',', '.'));
    if (parsed == null) {
      _text.text = _format(widget.value);
    } else {
      _set(parsed);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        IconButton.outlined(
          tooltip: tr('Decrease'),
          icon: const Icon(Icons.remove, size: 18),
          onPressed: widget.value > widget.lower ? () => _set(widget.value - widget.step) : null,
        ),
        SizedBox(
          width: 64,
          child: TextField(
            controller: _text,
            focusNode: _focus,
            textAlign: TextAlign.center,
            decoration: const InputDecoration(isDense: true, border: InputBorder.none),
            onSubmitted: _commit,
          ),
        ),
        IconButton.outlined(
          tooltip: tr('Increase'),
          icon: const Icon(Icons.add, size: 18),
          onPressed: widget.value < widget.upper ? () => _set(widget.value + widget.step) : null,
        ),
      ],
    );
  }
}

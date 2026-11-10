//! Shared UI localization. Catalogs are compiled in; the reader runtime is independent.
use serde_json::Value;
use std::sync::LazyLock;
static CATALOGS: LazyLock<Value> = LazyLock::new(|| {
    serde_json::from_str(include_str!("compiled.json")).expect("generated translations")
});
const CODES: &[&str] = &["en", "de", "fr", "es", "it", "pt", "nl", "pl"];
pub fn system_language(env: impl Fn(&str) -> Option<String>) -> String {
    let locale = ["LC_ALL", "LC_MESSAGES", "LANG"]
        .iter()
        .find_map(|k| env(k).filter(|v| !v.is_empty()))
        .unwrap_or_default();
    let code = locale
        .split(['_', '.', '-', '@'])
        .next()
        .unwrap_or("")
        .to_lowercase();
    if CODES.contains(&code.as_str()) {
        code
    } else {
        "en".into()
    }
}
pub fn language() -> String {
    let config = std::env::var_os("XDG_CONFIG_HOME")
        .filter(|v| !v.is_empty())
        .map(std::path::PathBuf::from)
        .unwrap_or_else(|| {
            std::path::PathBuf::from(std::env::var_os("HOME").unwrap_or_default()).join(".config")
        });
    let choice = std::fs::read_to_string(config.join("maprisma-narrator/settings.json"))
        .ok()
        .and_then(|s| serde_json::from_str::<Value>(&s).ok())
        .and_then(|v| v["interface_language"].as_str().map(str::to_owned));
    match choice {
        Some(c) if CODES.contains(&c.as_str()) => c,
        _ => system_language(|k| std::env::var(k).ok()),
    }
}
pub fn tr(text: &str) -> &str {
    CATALOGS
        .get(language())
        .and_then(|c| c.get(text))
        .and_then(Value::as_str)
        .unwrap_or(text)
}
pub fn trf(text: &str, values: &[&str]) -> String {
    let text = tr(text);
    // Substitute once: a value containing another placeholder remains data.
    let mut result = String::new();
    let mut rest = text;
    while let Some(at) = rest.find('{') {
        result.push_str(&rest[..at]);
        rest = &rest[at..];
        if let Some(end) = rest.find('}') {
            if let Ok(i) = rest[1..end].parse::<usize>() {
                if let Some(value) = values.get(i) {
                    result.push_str(value);
                    rest = &rest[end + 1..];
                    continue;
                }
            }
        }
        result.push('{');
        rest = &rest[1..];
    }
    result.push_str(rest);
    result
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn locale_precedence() {
        for code in CODES {
            assert_eq!(system_language(|_| Some(format!("{code}_XX.UTF-8"))), *code);
        }
        for (all, messages, lang, want) in [
            ("de_DE.UTF-8", "fr", "pl", "de"),
            ("", "fr_FR.UTF-8", "pl", "fr"),
            ("", "", "pt_BR.UTF-8", "pt"),
            ("xx_YY", "de", "pl", "en"),
            ("C.UTF-8", "de", "pl", "en"),
            ("", "", "", "en"),
        ] {
            assert_eq!(
                system_language(|k| Some(
                    match k {
                        "LC_ALL" => all,
                        "LC_MESSAGES" => messages,
                        _ => lang,
                    }
                    .into()
                )),
                want
            );
        }
    }
    #[test]
    fn reader_messages_preserve_values() {
        assert_eq!(
            message("There is no English voice yet."),
            trf("There is no {0} voice yet.", &["English"])
        );
        assert_eq!(
            message("Install English voice (80 MB)"),
            trf("Install {0} voice ({1})", &["English", "80 MB"])
        );
        assert_eq!(message("Model XYZ"), "Model XYZ");
        let template = "{0}/{1}";
        assert_eq!(trf(template, &["{1}", "value"]), "{1}/value");
    }
}

/// Presentation adapter for the shared reader protocol. Captured values stay data.
pub fn message(text: &str) -> String {
    if let Some(value) = text
        .strip_prefix("There is no ")
        .and_then(|s| s.strip_suffix(" voice yet."))
    {
        return trf("There is no {0} voice yet.", &[value]);
    }
    if let Some(value) = text
        .strip_prefix("Text recognition for ")
        .and_then(|s| s.strip_suffix(" is not installed yet."))
    {
        return trf("Text recognition for {0} is not installed yet.", &[value]);
    }
    if let Some(value) = text
        .strip_prefix("Install ")
        .and_then(|s| s.strip_suffix(" text recognition"))
    {
        return trf("Install {0} text recognition", &[value]);
    }
    if let Some(value) = text
        .strip_prefix("The translation server (")
        .and_then(|s| s.strip_suffix(") is not running."))
    {
        return trf("The translation server ({0}) is not running.", &[value]);
    }
    if let Some(value) = text.strip_prefix("Voice test failed: ") {
        return trf("Voice test failed: {0}", &[value]);
    }
    if let Some(value) = text.strip_prefix("Translation works: ") {
        return trf("Translation works: {0}", &[value]);
    }
    if let Some(value) = text.strip_prefix("Translation test failed: ") {
        return trf("Translation test failed: {0}", &[value]);
    }
    if let Some(value) = text.strip_prefix("Kokoro installed for ") {
        return trf("Kokoro installed for {0}", &[value]);
    }
    if let Some(value) = text
        .strip_prefix("Install ")
        .and_then(|s| s.strip_suffix(')'))
    {
        if let Some((language, size)) = value.split_once(" voice (") {
            return trf("Install {0} voice ({1})", &[language, size]);
        }
    }
    tr(text).to_owned()
}

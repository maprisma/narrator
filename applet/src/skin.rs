use crate::tr;
use cosmic::iced::Color;
use maprisma_kit::look;

pub const SKIN_KEY: &str = "skin";
pub const SKINS: [&str; 6] = ["native", "synthwave", "cozy", "terminal", "disco", "zen"];

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct SkinStyle {
    pub accent: Color,
    pub border_tint: Color,
    pub bg_tint: Color,
    pub window_bg: [u8; 3],
    pub foreground: [u8; 3],
    pub border_width: f32,
}

impl SkinStyle {
    pub fn palette(&self) -> look::Palette {
        let rgb = |c: Color| {
            [
                (c.r * 255.0).round() as u8,
                (c.g * 255.0).round() as u8,
                (c.b * 255.0).round() as u8,
            ]
        };
        look::Palette {
            accent: Some(rgb(self.accent)),
            background: Some(self.window_bg),
            foreground: Some(self.foreground),
            ..Default::default()
        }
    }
}

pub fn normalize_skin(skin: &str) -> &'static str {
    SKINS
        .iter()
        .find(|s| **s == skin)
        .copied()
        .unwrap_or("native")
}

pub fn skin_style(skin: &str) -> Option<SkinStyle> {
    let (accent, border, bg, window_bg, foreground, border_width) = match normalize_skin(skin) {
        "synthwave" => (
            [0xff, 0x2e, 0x93],
            [0x00, 0xe5, 0xff],
            [0x3a, 0x12, 0x59],
            [0x13, 0x09, 0x24],
            [0xf4, 0xea, 0xff],
            1.5,
        ),
        "cozy" => (
            [0xf0, 0x9a, 0x36],
            [0xe0, 0x82, 0x2a],
            [0x59, 0x30, 0x12],
            [0x21, 0x15, 0x0e],
            [0xf5, 0xe8, 0xd6],
            1.25,
        ),
        "terminal" => (
            [0x2c, 0xe8, 0x68],
            [0x22, 0xc5, 0x5e],
            [0x0d, 0x38, 0x1a],
            [0x09, 0x13, 0x0b],
            [0xd2, 0xfc, 0xe0],
            1.25,
        ),
        "disco" => (
            [0xd9, 0x46, 0xef],
            [0xfa, 0xcc, 0x15],
            [0x4c, 0x16, 0x66],
            [0x1c, 0x0c, 0x2b],
            [0xf8, 0xec, 0xff],
            1.5,
        ),
        "zen" => (
            [0x52, 0xb7, 0x98],
            [0x64, 0xc2, 0xa4],
            [0x1e, 0x38, 0x32],
            [0x14, 0x1d, 0x1c],
            [0xe2, 0xf0, 0xec],
            1.0,
        ),
        _ => return None,
    };
    let color = |[r, g, b]: [u8; 3]| Color::from_rgb8(r, g, b);
    Some(SkinStyle {
        accent: color(accent),
        border_tint: color(border),
        bg_tint: color(bg),
        window_bg,
        foreground,
        border_width,
    })
}

pub fn skin_label(skin: &str) -> String {
    tr(match normalize_skin(skin) {
        "synthwave" => "Synthwave",
        "cozy" => "Cozy",
        "terminal" => "Terminal",
        "disco" => "Disco",
        "zen" => "Zen",
        _ => "Native",
    })
    .to_owned()
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn palettes_and_normalization() {
        assert_eq!(normalize_skin("unknown"), "native");
        assert!(skin_style("native").is_none());
        let expected = [
            (
                "synthwave",
                [0xff, 0x2e, 0x93],
                [0x00, 0xe5, 0xff],
                [0x3a, 0x12, 0x59],
                [0x13, 0x09, 0x24],
                [0xf4, 0xea, 0xff],
                1.5,
            ),
            (
                "cozy",
                [0xf0, 0x9a, 0x36],
                [0xe0, 0x82, 0x2a],
                [0x59, 0x30, 0x12],
                [0x21, 0x15, 0x0e],
                [0xf5, 0xe8, 0xd6],
                1.25,
            ),
            (
                "terminal",
                [0x2c, 0xe8, 0x68],
                [0x22, 0xc5, 0x5e],
                [0x0d, 0x38, 0x1a],
                [0x09, 0x13, 0x0b],
                [0xd2, 0xfc, 0xe0],
                1.25,
            ),
            (
                "disco",
                [0xd9, 0x46, 0xef],
                [0xfa, 0xcc, 0x15],
                [0x4c, 0x16, 0x66],
                [0x1c, 0x0c, 0x2b],
                [0xf8, 0xec, 0xff],
                1.5,
            ),
            (
                "zen",
                [0x52, 0xb7, 0x98],
                [0x64, 0xc2, 0xa4],
                [0x1e, 0x38, 0x32],
                [0x14, 0x1d, 0x1c],
                [0xe2, 0xf0, 0xec],
                1.0,
            ),
        ];
        for (skin, accent, border, bg, window, foreground, width) in expected {
            let st = skin_style(skin).unwrap();
            assert_eq!(normalize_skin(skin), skin);
            assert_eq!(st.accent, Color::from_rgb8(accent[0], accent[1], accent[2]));
            assert_eq!(
                st.border_tint,
                Color::from_rgb8(border[0], border[1], border[2])
            );
            assert_eq!(st.bg_tint, Color::from_rgb8(bg[0], bg[1], bg[2]));
            assert_eq!(st.window_bg, window);
            assert_eq!(st.foreground, foreground);
            assert_eq!(st.border_width, width);
            assert_eq!(st.palette().accent, Some(accent));
            assert_eq!(st.palette().background, Some(st.window_bg));
            assert_eq!(st.palette().foreground, Some(st.foreground));
            assert!(!skin_label(skin).is_empty());
        }
    }
}

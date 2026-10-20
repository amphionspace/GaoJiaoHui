# Journey fonts

- `zcool-xiaowei.woff2`: ZCOOL XiaoWei, from [Google Fonts](https://github.com/google/fonts/tree/main/ofl/zcoolxiaowei). License: `zcool-OFL.txt`.
- `fraunces-italic.woff2`: Fraunces italic. License: `fraunces-OFL.txt`.
- `noto-serif-sc-hui.woff2`: Noto Serif SC Regular, U+56DE only, obtained from the [Google Fonts CSS API](https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@400&text=%E5%9B%9E) and converted to WOFF2 with fontTools. License: `noto-serif-sc-OFL.txt`.

## Current typography

`noto-serif-sc.woff2` (400) and `noto-serif-sc-semibold.woff2` (600) are the complete Noto Serif SC fonts, downloaded from the official Google Fonts CSS API and compressed with fontTools. Both use `noto-serif-sc-OFL.txt`.

The journey now uses Noto Serif SC throughout the headings, letter and receipt. The older XiaoWei font and single-character patch are retained as historical assets but are no longer loaded. This replaces the faulty outlines across the whole font, including U+56DE and U+5DF1, rather than patching individual characters. No external font request is needed at runtime.

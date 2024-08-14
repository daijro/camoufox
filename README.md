<img src="https://i.imgur.com/8nXwzrW.png" align="center">

<h1 align="center">Camoufox</h1>

<h4 align="center">A stealthy, minimalistic, custom build of Firefox for web scraping 🦊</h4>

<p align="center">                                      
Camoufox aims to be a minimalistic browser for robust fingerprint injection & anti-bot evasion.
    
</p>

---

> [!WARNING]
> Camoufox is still under active development! Built releases aren't yet avaliable for production.

## Features

- Fingerprint injection (override properties of `navigator`, `window`, `screen`, etc) ✅
- Patches to avoid bot detection ✅
- Custom Playwright Juggler implementation for the latest Firefox ✅
- Font spoofing & anti-fingerprinting ✅
- Patches from LibreWolf & Ghostery to remove Mozilla services ✅
- Optimized for memory and speed ✅
- Stays up to date with the latest Firefox version 🕓

### Why Firefox instead of Chromium?

Camoufox is built on top of Firefox/Juggler instead of Chromium because:

- CDP is more widely used and known, so it's a more common target for bot detection
- Juggler operates on a lower level than CDP, and has less JS leaks
- WAFs are less likely to associate Firefox with automation

### What's planned?

- Continue research on potential leaks
- Built in TLS fingerprinting protection using [Hazetunnel](https://github.com/daijro/hazetunnel)
- Create integration tests
- Chromium port (long-term)

<hr width=50>

## Fingerprint Injection

Camoufox overrides Javascript properties on the lowest level possible, allowing values to be spoofed across all scopes.

To spoof fingerprint properties, pass a JSON containing properties to spoof:

```bash
$ ./launch --config '{"property": "value"}' [...other Firefox arguments]
```

The following attributes can be spoofed:

<details>
<summary>
Navigator 
</summary>

Navigator (the most important attributes) can be fully spoof other Firefox fingerprints, and it is **completely safe**! However, there are some issues when spoofing Chrome (leaks noted).

| Property                       | Notes |
| ------------------------------ | ----- |
| navigator.userAgent            | ✅    |
| navigator.doNotTrack           | ✅    |
| navigator.appCodeName          | ✅    |
| navigator.appName              | ✅    |
| navigator.appVersion           | ✅    |
| navigator.oscpu                | ✅    |
| navigator.language             | ✅    |
| navigator.languages            | ✅    |
| navigator.platform             | ✅    |
| navigator.hardwareConcurrency  | ✅    |
| navigator.product              | ✅    |
| navigator.productSub           | ✅    |
| navigator.maxTouchPoints       | ✅    |
| navigator.cookieEnabled        | ✅    |
| navigator.globalPrivacyControl | ✅    |
| navigator.appVersion           | ✅    |
| navigator.buildID              | ✅    |
| navigator.doNotTrack           | ✅    |

Camoufox will automatically add the following default fonts associated your spoofed User-Agent OS (the value passed in `navigator.userAgent`).

**Notes**:

- **navigator.webdriver** is set to false at all times.
- When spoofing Chrome fingerprints, the following may leak:
  - navigator.userAgentData missing.
  - navigator.deviceMemory missing.

</details>

<details>
<summary>
Fonts
</summary>

### Adding Fonts

Fonts can be passed to be used in Camoufox through the `fonts` config property.

By default, Camoufox is bundled with the default Windows 11 22H2 fonts, macOS Sonma fonts, and Linux fonts used in the TOR bundle.

Camoufox will automatically add the default fonts associated your spoofed User-Agent OS (the value passed in `navigator.userAgent`):

- **Mac OS fonts** (from macOS Sonma):

  ```bash
  [".Al Bayan PUA", ".Al Nile PUA", ".Al Tarikh PUA", ".Apple Color Emoji UI", ".Apple SD Gothic NeoI", ".Aqua Kana", ".Aqua Kana Bold", ".Aqua かな", ".Aqua かな ボールド", ".Arial Hebrew Desk Interface", ".Baghdad PUA", ".Beirut PUA", ".Damascus PUA", ".DecoType Naskh PUA", ".Diwan Kufi PUA", ".Farah PUA", ".Geeza Pro Interface", ".Geeza Pro PUA", ".Helvetica LT MM", ".Hiragino Kaku Gothic Interface", ".Hiragino Sans GB Interface", ".Keyboard", ".KufiStandardGK PUA", ".LastResort", ".Lucida Grande UI", ".Muna PUA", ".Nadeem PUA", ".New York", ".Noto Nastaliq Urdu UI", ".PingFang HK", ".PingFang SC", ".PingFang TC", ".SF Arabic", ".SF Arabic Rounded", ".SF Compact", ".SF Compact Rounded", ".SF NS", ".SF NS Mono", ".SF NS Rounded", ".Sana PUA", ".Savoye LET CC.", ".ThonburiUI", ".ThonburiUIWatch", ".苹方-港", ".苹方-简", ".苹方-繁", ".蘋方-港", ".蘋方-簡", ".蘋方-繁", "Academy Engraved LET", "Al Bayan", "Al Nile", "Al Tarikh", "American Typewriter", "Andale Mono", "Apple Braille", "Apple Chancery", "Apple Color Emoji", "Apple SD Gothic Neo", "Apple SD 산돌고딕 Neo", "Apple Symbols", "AppleGothic", "AppleMyungjo", "Arial", "Arial Black", "Arial Hebrew", "Arial Hebrew Scholar", "Arial Narrow", "Arial Rounded MT Bold", "Arial Unicode MS", "Athelas", "Avenir", "Avenir Black", "Avenir Black Oblique", "Avenir Book", "Avenir Heavy", "Avenir Light", "Avenir Medium", "Avenir Next", "Avenir Next Condensed", "Avenir Next Condensed Demi Bold", "Avenir Next Condensed Heavy", "Avenir Next Condensed Medium", "Avenir Next Condensed Ultra Light", "Avenir Next Demi Bold", "Avenir Next Heavy", "Avenir Next Medium", "Avenir Next Ultra Light", "Ayuthaya", "Baghdad", "Bangla MN", "Bangla Sangam MN", "Baskerville", "Beirut", "Big Caslon", "Bodoni 72", "Bodoni 72 Oldstyle", "Bodoni 72 Smallcaps", "Bodoni Ornaments", "Bradley Hand", "Brush Script MT", "Chalkboard", "Chalkboard SE", "Chalkduster", "Charter", "Charter Black", "Cochin", "Comic Sans MS", "Copperplate", "Corsiva Hebrew", "Courier", "Courier New", "Czcionka systemowa", "DIN Alternate", "DIN Condensed", "Damascus", "DecoType Naskh", "Devanagari MT", "Devanagari Sangam MN", "Didot", "Diwan Kufi", "Diwan Thuluth", "Euphemia UCAS", "Farah", "Farisi", "Font Sistem", "Font de sistem", "Font di sistema", "Font sustava", "Fonte do Sistema", "Futura", "GB18030 Bitmap", "Galvji", "Geeza Pro", "Geneva", "Georgia", "Gill Sans", "Grantha Sangam MN", "Gujarati MT", "Gujarati Sangam MN", "Gurmukhi MN", "Gurmukhi MT", "Gurmukhi Sangam MN", "Heiti SC", "Heiti TC", "Heiti-간체", "Heiti-번체", "Helvetica", "Helvetica Neue", "Herculanum", "Hiragino Kaku Gothic Pro", "Hiragino Kaku Gothic Pro W3", "Hiragino Kaku Gothic Pro W6", "Hiragino Kaku Gothic ProN", "Hiragino Kaku Gothic ProN W3", "Hiragino Kaku Gothic ProN W6", "Hiragino Kaku Gothic Std", "Hiragino Kaku Gothic Std W8", "Hiragino Kaku Gothic StdN", "Hiragino Kaku Gothic StdN W8", "Hiragino Maru Gothic Pro", "Hiragino Maru Gothic Pro W4", "Hiragino Maru Gothic ProN", "Hiragino Maru Gothic ProN W4", "Hiragino Mincho Pro", "Hiragino Mincho Pro W3", "Hiragino Mincho Pro W6", "Hiragino Mincho ProN", "Hiragino Mincho ProN W3", "Hiragino Mincho ProN W6", "Hiragino Sans", "Hiragino Sans GB", "Hiragino Sans GB W3", "Hiragino Sans GB W6", "Hiragino Sans W0", "Hiragino Sans W1", "Hiragino Sans W2", "Hiragino Sans W3", "Hiragino Sans W4", "Hiragino Sans W5", "Hiragino Sans W6", "Hiragino Sans W7", "Hiragino Sans W8", "Hiragino Sans W9", "Hoefler Text", "Hoefler Text Ornaments", "ITF Devanagari", "ITF Devanagari Marathi", "Impact", "InaiMathi", "Iowan Old Style", "Iowan Old Style Black", "Järjestelmäfontti", "Kailasa", "Kannada MN", "Kannada Sangam MN", "Kefa", "Khmer MN", "Khmer Sangam MN", "Kohinoor Bangla", "Kohinoor Devanagari", "Kohinoor Gujarati", "Kohinoor Telugu", "Kokonor", "Krungthep", "KufiStandardGK", "Lao MN", "Lao Sangam MN", "Lucida Grande", "Luminari", "Malayalam MN", "Malayalam Sangam MN", "Marion", "Marker Felt", "Menlo", "Microsoft Sans Serif", "Mishafi", "Mishafi Gold", "Monaco", "Mshtakan", "Mukta Mahee", "MuktaMahee Bold", "MuktaMahee ExtraBold", "MuktaMahee ExtraLight", "MuktaMahee Light", "MuktaMahee Medium", "MuktaMahee Regular", "MuktaMahee SemiBold", "Muna", "Myanmar MN", "Myanmar Sangam MN", "Nadeem", "New Peninim MT", "Noteworthy", "Noto Nastaliq Urdu", "Noto Sans Adlam", "Noto Sans Armenian", "Noto Sans Armenian Blk", "Noto Sans Armenian ExtBd", "Noto Sans Armenian ExtLt", "Noto Sans Armenian Light", "Noto Sans Armenian Med", "Noto Sans Armenian SemBd", "Noto Sans Armenian Thin", "Noto Sans Avestan", "Noto Sans Bamum", "Noto Sans Bassa Vah", "Noto Sans Batak", "Noto Sans Bhaiksuki", "Noto Sans Brahmi", "Noto Sans Buginese", "Noto Sans Buhid", "Noto Sans CanAborig", "Noto Sans Canadian Aboriginal", "Noto Sans Carian", "Noto Sans CaucAlban", "Noto Sans Caucasian Albanian", "Noto Sans Chakma", "Noto Sans Cham", "Noto Sans Coptic", "Noto Sans Cuneiform", "Noto Sans Cypriot", "Noto Sans Duployan", "Noto Sans EgyptHiero", "Noto Sans Egyptian Hieroglyphs", "Noto Sans Elbasan", "Noto Sans Glagolitic", "Noto Sans Gothic", "Noto Sans Gunjala Gondi", "Noto Sans Hanifi Rohingya", "Noto Sans HanifiRohg", "Noto Sans Hanunoo", "Noto Sans Hatran", "Noto Sans ImpAramaic", "Noto Sans Imperial Aramaic", "Noto Sans InsPahlavi", "Noto Sans InsParthi", "Noto Sans Inscriptional Pahlavi", "Noto Sans Inscriptional Parthian", "Noto Sans Javanese", "Noto Sans Kaithi", "Noto Sans Kannada", "Noto Sans Kannada Black", "Noto Sans Kannada ExtraBold", "Noto Sans Kannada ExtraLight", "Noto Sans Kannada Light", "Noto Sans Kannada Medium", "Noto Sans Kannada SemiBold", "Noto Sans Kannada Thin", "Noto Sans Kayah Li", "Noto Sans Kharoshthi", "Noto Sans Khojki", "Noto Sans Khudawadi", "Noto Sans Lepcha", "Noto Sans Limbu", "Noto Sans Linear A", "Noto Sans Linear B", "Noto Sans Lisu", "Noto Sans Lycian", "Noto Sans Lydian", "Noto Sans Mahajani", "Noto Sans Mandaic", "Noto Sans Manichaean", "Noto Sans Marchen", "Noto Sans Masaram Gondi", "Noto Sans Meetei Mayek", "Noto Sans Mende Kikakui", "Noto Sans Meroitic", "Noto Sans Miao", "Noto Sans Modi", "Noto Sans Mongolian", "Noto Sans Mro", "Noto Sans Multani", "Noto Sans Myanmar", "Noto Sans Myanmar Blk", "Noto Sans Myanmar ExtBd", "Noto Sans Myanmar ExtLt", "Noto Sans Myanmar Light", "Noto Sans Myanmar Med", "Noto Sans Myanmar SemBd", "Noto Sans Myanmar Thin", "Noto Sans NKo", "Noto Sans Nabataean", "Noto Sans New Tai Lue", "Noto Sans Newa", "Noto Sans Ol Chiki", "Noto Sans Old Hungarian", "Noto Sans Old Italic", "Noto Sans Old North Arabian", "Noto Sans Old Permic", "Noto Sans Old Persian", "Noto Sans Old South Arabian", "Noto Sans Old Turkic", "Noto Sans OldHung", "Noto Sans OldNorArab", "Noto Sans OldSouArab", "Noto Sans Oriya", "Noto Sans Osage", "Noto Sans Osmanya", "Noto Sans Pahawh Hmong", "Noto Sans Palmyrene", "Noto Sans Pau Cin Hau", "Noto Sans PhagsPa", "Noto Sans Phoenician", "Noto Sans PsaPahlavi", "Noto Sans Psalter Pahlavi", "Noto Sans Rejang", "Noto Sans Samaritan", "Noto Sans Saurashtra", "Noto Sans Sharada", "Noto Sans Siddham", "Noto Sans Sora Sompeng", "Noto Sans SoraSomp", "Noto Sans Sundanese", "Noto Sans Syloti Nagri", "Noto Sans Syriac", "Noto Sans Tagalog", "Noto Sans Tagbanwa", "Noto Sans Tai Le", "Noto Sans Tai Tham", "Noto Sans Tai Viet", "Noto Sans Takri", "Noto Sans Thaana", "Noto Sans Tifinagh", "Noto Sans Tirhuta", "Noto Sans Ugaritic", "Noto Sans Vai", "Noto Sans Wancho", "Noto Sans Warang Citi", "Noto Sans Yi", "Noto Sans Zawgyi", "Noto Sans Zawgyi Blk", "Noto Sans Zawgyi ExtBd", "Noto Sans Zawgyi ExtLt", "Noto Sans Zawgyi Light", "Noto Sans Zawgyi Med", "Noto Sans Zawgyi SemBd", "Noto Sans Zawgyi Thin", "Noto Serif Ahom", "Noto Serif Balinese", "Noto Serif Hmong Nyiakeng", "Noto Serif Myanmar", "Noto Serif Myanmar Blk", "Noto Serif Myanmar ExtBd", "Noto Serif Myanmar ExtLt", "Noto Serif Myanmar Light", "Noto Serif Myanmar Med", "Noto Serif Myanmar SemBd", "Noto Serif Myanmar Thin", "Noto Serif Yezidi", "Optima", "Oriya MN", "Oriya Sangam MN", "PT Mono", "PT Sans", "PT Sans Caption", "PT Sans Narrow", "PT Serif", "PT Serif Caption", "Palatino", "Papyrus", "Party LET", "Phosphate", "Phông chữ Hệ thống", "PingFang HK", "PingFang SC", "PingFang TC", "Plantagenet Cherokee", "Police système", "Raanana", "Rendszerbetűtípus", "Rockwell", "STIX Two Math", "STIX Two Text", "STIXGeneral", "STIXIntegralsD", "STIXIntegralsSm", "STIXIntegralsUp", "STIXIntegralsUpD", "STIXIntegralsUpSm", "STIXNonUnicode", "STIXSizeFiveSym", "STIXSizeFourSym", "STIXSizeOneSym", "STIXSizeThreeSym", "STIXSizeTwoSym", "STIXVariants", "STSong", "Sana", "Sathu", "Savoye LET", "Seravek", "Seravek ExtraLight", "Seravek Light", "Seravek Medium", "Shree Devanagari 714", "SignPainter", "SignPainter-HouseScript", "Silom", "Sinhala MN", "Sinhala Sangam MN", "Sistem Fontu", "Skia", "Snell Roundhand", "Songti SC", "Songti TC", "Sukhumvit Set", "Superclarendon", "Symbol", "Systeemlettertype", "System Font", "Systemschrift", "Systemskrift", "Systemtypsnitt", "Systémové písmo", "Tahoma", "Tamil MN", "Tamil Sangam MN", "Telugu MN", "Telugu Sangam MN", "Thonburi", "Times", "Times New Roman", "Tipo de letra del sistema", "Tipo de letra do sistema", "Tipus de lletra del sistema", "Trattatello", "Trebuchet MS", "Verdana", "Waseem", "Webdings", "Wingdings", "Wingdings 2", "Wingdings 3", "Zapf Dingbats", "Zapfino", "Γραμματοσειρά συστήματος", "Системний шрифт", "Системный шрифт", "גופן מערכת", "البيان", "التاريخ", "النيل", "بغداد", "بيروت", "جيزة", "خط النظام", "دمشق", "ديوان ثلث", "ديوان كوفي", "صنعاء", "فارسي", "فرح", "كوفي", "منى", "مِصحفي", "مِصحفي ذهبي", "نديم", "نسخ", "وسيم", "आई॰टी॰एफ़॰ देवनागरी", "आई॰टी॰एफ़॰ देवनागरी मराठी", "कोहिनूर देवनागरी", "देवनागरी एम॰टी॰", "देवनागरी संगम एम॰एन॰", "श्री देवनागरी ७१४", "แบบอักษรระบบ", "⹁煵愠芩苈", "システムフォント", "ヒラギノ丸ゴ Pro", "ヒラギノ丸ゴ Pro W4", "ヒラギノ丸ゴ ProN", "ヒラギノ丸ゴ ProN W4", "ヒラギノ明朝 Pro", "ヒラギノ明朝 Pro W3", "ヒラギノ明朝 Pro W6", "ヒラギノ明朝 ProN", "ヒラギノ明朝 ProN W3", "ヒラギノ明朝 ProN W6", "ヒラギノ角ゴ Pro", "ヒラギノ角ゴ Pro W3", "ヒラギノ角ゴ Pro W6", "ヒラギノ角ゴ ProN", "ヒラギノ角ゴ ProN W3", "ヒラギノ角ゴ ProN W6", "ヒラギノ角ゴ Std", "ヒラギノ角ゴ Std W8", "ヒラギノ角ゴ StdN", "ヒラギノ角ゴ StdN W8", "ヒラギノ角ゴ 簡体中文", "ヒラギノ角ゴ 簡体中文 W3", "ヒラギノ角ゴ 簡体中文 W6", "ヒラギノ角ゴシック", "ヒラギノ角ゴシック W0", "ヒラギノ角ゴシック W1", "ヒラギノ角ゴシック W2", "ヒラギノ角ゴシック W3", "ヒラギノ角ゴシック W4", "ヒラギノ角ゴシック W5", "ヒラギノ角ゴシック W6", "ヒラギノ角 ゴシック W7", "ヒラギノ角ゴシック W8", "ヒラギノ角ゴシック W9", "冬青黑体简体中文", "冬青黑体简体中文 W3", "冬青黑体简体中文 W6", "冬青黑體簡體中文", "冬青黑體簡體中文 W3", "冬青黑體簡體中文 W6", "宋体-简", "宋体-繁", "宋體-簡", "宋體-繁", "系統字體", "系统字体", "苹方-港", "苹方-简", "苹方-繁", "荱莉荍荭詰荓⁐牯", "荱莉荍荭詰荓⁓瑤", "荱莉荍荭詰荓荖荢荎", "荱莉荍荭諛荓⁐牯", "荱莉荍荭难銩⁐牯", "蘋方-港", "蘋方-簡", "蘋方-繁", "黑体-简", "黑体-繁", "黑體-簡", "黑體-繁", "黒体-簡", "黒体-繁", "시스템 서체"]
  ```

- **Windows fonts** (from Windows 11 22H2):

  ```bash
  ["Arial", "Arial Black", "Bahnschrift", "Calibri", "Calibri Light", "Cambria", "Cambria Math", "Candara", "Candara Light", "Comic Sans MS", "Consolas", "Constantia", "Corbel", "Corbel Light", "Courier New", "Ebrima", "Franklin Gothic Medium", "Gabriola", "Gadugi", "Georgia", "HoloLens MDL2 Assets", "Impact", "Ink Free", "Javanese Text", "Leelawadee UI", "Leelawadee UI Semilight", "Lucida Console", "Lucida Sans Unicode", "MS Gothic", "MS PGothic", "MS UI Gothic", "MV Boli", "Malgun Gothic", "Malgun Gothic Semilight", "Marlett", "Microsoft Himalaya", "Microsoft JhengHei", "Microsoft JhengHei Light", "Microsoft JhengHei UI", "Microsoft JhengHei UI Light", "Microsoft New Tai Lue", "Microsoft PhagsPa", "Microsoft Sans Serif", "Microsoft Tai Le", "Microsoft YaHei", "Microsoft YaHei Light", "Microsoft YaHei UI", "Microsoft YaHei UI Light", "Microsoft Yi Baiti", "MingLiU-ExtB", "MingLiU_HKSCS-ExtB", "Mongolian Baiti", "Myanmar Text", "NSimSun", "Nirmala UI", "Nirmala UI Semilight", "PMingLiU-ExtB", "Palatino Linotype", "Segoe Fluent Icons", "Segoe MDL2 Assets", "Segoe Print", "Segoe Script", "Segoe UI", "Segoe UI Black", "Segoe UI Emoji", "Segoe UI Historic", "Segoe UI Light", "Segoe UI Semibold", "Segoe UI Semilight", "Segoe UI Symbol", "Segoe UI Variable", "SimSun", "SimSun-ExtB", "Sitka", "Sitka Text", "Sylfaen", "Symbol", "Tahoma", "Times New Roman", "Trebuchet MS", "Twemoji Mozilla", "Verdana", "Webdings", "Wingdings", "Yu Gothic", "Yu Gothic Light", "Yu Gothic Medium", "Yu Gothic UI", "Yu Gothic UI Light", "Yu Gothic UI Semibold", "Yu Gothic UI Semilight", "宋体", "微軟正黑體", "微軟正黑體 Light", "微软雅黑", "微软雅黑 Light", "新宋体", "新細明體-ExtB", "游ゴシック", "游ゴシック Light", "游ゴシック Medium", "細明體-ExtB", "細明體_HKSCS-ExtB", "맑은 고딕", "맑은 고딕 Semilight", "ＭＳ ゴシック", "ＭＳ Ｐゴシック"]
  ```

- **Linux fonts** (from TOR Browser):

  ```bash
  ["Arimo", "Cousine", "Noto Naskh Arabic", "Noto Sans Adlam", "Noto Sans Armenian", "Noto Sans Balinese", "Noto Sans Bamum", "Noto Sans Bassa Vah", "Noto Sans Batak", "Noto Sans Bengali", "Noto Sans Buginese", "Noto Sans Buhid", "Noto Sans Canadian Aboriginal", "Noto Sans Chakma", "Noto Sans Cham", "Noto Sans Cherokee", "Noto Sans Coptic", "Noto Sans Deseret", "Noto Sans Devanagari", "Noto Sans Elbasan", "Noto Sans Ethiopic", "Noto Sans Georgian", "Noto Sans Grantha", "Noto Sans Gujarati", "Noto Sans Gunjala Gondi", "Noto Sans Gurmukhi", "Noto Sans Hanifi Rohingya", "Noto Sans Hanunoo", "Noto Sans Hebrew", "Noto Sans JP", "Noto Sans Javanese", "Noto Sans KR", "Noto Sans Kannada", "Noto Sans Kayah Li", "Noto Sans Khmer", "Noto Sans Khojki", "Noto Sans Khudawadi", "Noto Sans Lao", "Noto Sans Lepcha", "Noto Sans Limbu", "Noto Sans Lisu", "Noto Sans Mahajani", "Noto Sans Malayalam", "Noto Sans Mandaic", "Noto Sans Masaram Gondi", "Noto Sans Medefaidrin", "Noto Sans Meetei Mayek", "Noto Sans Mende Kikakui", "Noto Sans Miao", "Noto Sans Modi", "Noto Sans Mongolian", "Noto Sans Mro", "Noto Sans Multani", "Noto Sans Myanmar", "Noto Sans NKo", "Noto Sans New Tai Lue", "Noto Sans Newa", "Noto Sans Ol Chiki", "Noto Sans Oriya", "Noto Sans Osage", "Noto Sans Osmanya", "Noto Sans Pahawh Hmong", "Noto Sans Pau Cin Hau", "Noto Sans Rejang", "Noto Sans Runic", "Noto Sans SC", "Noto Sans Samaritan", "Noto Sans Saurashtra", "Noto Sans Sharada", "Noto Sans Shavian", "Noto Sans Sinhala", "Noto Sans Sora Sompeng", "Noto Sans Soyombo", "Noto Sans Sundanese", "Noto Sans Syloti Nagri", "Noto Sans Symbols", "Noto Sans Symbols 2", "Noto Sans Syriac", "Noto Sans TC", "Noto Sans Tagalog", "Noto Sans Tagbanwa", "Noto Sans Tai Le", "Noto Sans Tai Tham", "Noto Sans Tai Viet", "Noto Sans Takri", "Noto Sans Tamil", "Noto Sans Telugu", "Noto Sans Thaana", "Noto Sans Thai", "Noto Sans Tifinagh", "Noto Sans Tifinagh APT", "Noto Sans Tifinagh Adrar", "Noto Sans Tifinagh Agraw Imazighen", "Noto Sans Tifinagh Ahaggar", "Noto Sans Tifinagh Air", "Noto Sans Tifinagh Azawagh", "Noto Sans Tifinagh Ghat", "Noto Sans Tifinagh Hawad", "Noto Sans Tifinagh Rhissa Ixa", "Noto Sans Tifinagh SIL", "Noto Sans Tifinagh Tawellemmet", "Noto Sans Tirhuta", "Noto Sans Vai", "Noto Sans Wancho", "Noto Sans Warang Citi", "Noto Sans Yi", "Noto Sans Zanabazar Square", "Noto Serif Armenian", "Noto Serif Balinese", "Noto Serif Bengali", "Noto Serif Devanagari", "Noto Serif Dogra", "Noto Serif Ethiopic", "Noto Serif Georgian", "Noto Serif Grantha", "Noto Serif Gujarati", "Noto Serif Gurmukhi", "Noto Serif Hebrew", "Noto Serif Kannada", "Noto Serif Khmer", "Noto Serif Khojki", "Noto Serif Lao", "Noto Serif Malayalam", "Noto Serif Myanmar", "Noto Serif NP Hmong", "Noto Serif Sinhala", "Noto Serif Tamil", "Noto Serif Telugu", "Noto Serif Thai", "Noto Serif Tibetan", "Noto Serif Yezidi", "STIX Two Math", "Tinos", "Twemoji Mozilla"]
  ```

Other fonts can be added by copying them into the `fonts/` directory in Camoufox, or by installing them on your system.

**Note**: It is highly recommended that you randomly pass custom fonts to the `fonts` config property to avoid font fingerprinting!

### Font Metrics

Camoufox has a built in mechanism to prevent fingerprinting by font metrics & unicode glyphs:

<img src="https://i.imgur.com/X9hLKhO.gif">

This works by shifting the spacing of each letter by a random value between 0-0.1px.

</details>

<details>
<summary>
Screen
</summary>

| Property           | Status |
| ------------------ | ------ |
| screen.availHeight | ✅     |
| screen.availWidth  | ✅     |
| screen.availTop    | ✅     |
| screen.availLeft   | ✅     |
| screen.colorDepth  | ✅     |
| screen.height      | ✅     |
| screen.width       | ✅     |
| screen.pixelDepth  | ✅     |
| screen.pageXOffset | ✅     |
| screen.pageYOffset | ✅     |

</details>

<details>
<summary>
Window
</summary>

| Property                | Status                      |
| ----------------------- | --------------------------- |
| window.scrollMinX       | ✅                          |
| window.scrollMinY       | ✅                          |
| window.scrollMaxX       | ✅                          |
| window.scrollMaxY       | ✅                          |
| window.innerHeight      | ✅                          |
| window.outerHeight      | ✅                          |
| window.outerWidth       | ✅                          |
| window.innerWidth       | ✅                          |
| window.screenX          | ✅                          |
| window.screenY          | ✅                          |
| window.history.length   | ✅                          |
| window.devicePixelRatio | Works, but not recommended! |

**Notes:**

- Setting the outer window viewport will cause some cosmetic defects to the Camoufox window if the user attempts to manually resize it. Under no circumstances will Camoufox allow the outer window viewport to be resized.

</details>

<details>
<summary>
Document
</summary>

Spoofing document.body has been implemented, but it is more advicable to set `window.innerWidth` and `window.innerHeight` instead.

| Property                   | Status |
| -------------------------- | ------ |
| document.body.clientWidth  | ✅     |
| document.body.clientHeight | ✅     |
| document.body.clientTop    | ✅     |
| document.body.clientLeft   | ✅     |

</details>

<details>
<summary>
HTTP Headers
</summary>

Camoufox can override the following network headers:

| Property                | Status |
| ----------------------- | ------ |
| headers.User-Agent      | ✅     |
| headers.Accept-Language | ✅     |
| headers.Accept-Encoding | ✅     |

**Notes:**

- If `headers.User-Agent` is not set, it will fall back to `navigator.userAgent`.

</details>

<details>

<summary>
Addons
</summary>

Addons can be loaded with the `--addons` flag.

Example:

```bash
./launcher --addons '["/path/to/addon", "/path/to/addon2"]'
```

Camoufox will automatically download and use the latest uBlock Origin with custom privacy/adblock filters, and B.P.C. by default to help with scraping.

You can also exclude default addons with the `--exclude-addons` flag:

```bash
./launcher --exclude-addons '["uBO", "BPC"]'
```

</details>

</details>

<details>
<summary>
Miscellaneous (WebGl spoofing, battery status, etc)
</summary>

| Property                | Status | Notes                                                                                                                                          |
| ----------------------- | ------ | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| pdfViewer               | ✅     | Sets navigator.pdfViewerEnabled. Please keep this on though, many websites will flag a lack of pdfViewer as a headless browser.                |
| webGl:renderer          | ✅     | Spoofs the name of the unmasked WebGL renderer. Can cause leaks, use at your own caution! Also note, webGl is disabled in Camoufox by default. |
| webGl:vendor            | ✅     | Spoofs the name of the unmasked WebGL vendor. Can cause leaks, use at your own caution! Also note, webGl is disabled in Camoufox by default.   |
| battery:charging        | ✅     | Spoofs the battery charging status.                                                                                                            |
| battery:chargingTime    | ✅     | Spoofs the battery charging time.                                                                                                              |
| battery:dischargingTime | ✅     | Spoofs the battery discharging time.                                                                                                           |
| battery:level           | ✅     | Spoofs the battery level.                                                                                                                      |

**Notes:**

- For screen properties, using Page.setViewportSize() may be more effective.

</details>

<hr width=50>

## Patches

### What changes were made?

#### Fingerprint spoofing

- Navigator properties spoofing (device, browser, locale, etc.)
- Support for emulating screen size, resolution, etc.
- WebGL unmasked renderer spoofing (WIP)
- Battery API spoofing
- Support for spoofing both inner and outer window viewport sizes
- Network headers (Accept-Languages and User-Agent) are spoofed to match the navigator properties
- etc.

#### Anti font fingerprinting

- Automatically uses the correct system fonts for your User Agent
- Bundled with Windows, Mac, and Linux system fonts
- Prevents font metrics fingerprinting by randomly offsetting letter spacing

#### Playwright support

- Custom implementation of Playwright for the latest Firefox
- Various config patches to evade bot detection
- Removed leaking Playwright patches:
  - Fixes `content-document-global-created` observer leak
  - Fixes `navigator.webdriver` detection
  - Removed potentially leaking anti-zoom/meta viewport handling patches
  - Re-enable fission content isolation
  - Re-enable PDF.js

#### Debloat/Optimizations

- Stripped out/disabled _many, many_ Mozilla services. Runs faster than the original Mozilla Firefox, and uses less memory (200mb)
- Includes the debloat config from PeskyFox & LibreWolf, and others
- Speed optimizations from FastFox, and other network optimizations
- Minimalistic theming
- etc.

#### Addons

- Firefox addons can be loaded with the `--addons` flag
- Added uBlock Origin with custom privacy filters
- Added B.P.C.
- Addons are not allowed to open tabs
- Addons are automatically enabled in Private Browsing mode
- Addons are automatically pinned to the toolbar

## Stealth Performance

### Tests

Camoufox performs well against every major WAF I've tested. (Test sites from [Botright](https://github.com/Vinyzu/botright/?tab=readme-ov-file#browser-stealth))

| Test                                                                                               | Status                                            |
| -------------------------------------------------------------------------------------------------- | ------------------------------------------------- |
| **reCaptcha Score**                                                                                | ✔️                                                |
| ‣ [nopecha.com](https://nopecha.com/demo/recaptcha)                                                | ✔️ (v2-Hardest is unstable on Chrome fingerprint) |
| ‣ [recaptcha-demo.appspot.com](https://recaptcha-demo.appspot.com/recaptcha-v3-request-scores.php) | ✔️ 0.9                                            |
| ‣ [berstend.github.io](https://berstend.github.io/static/recaptcha/v3-programmatic.html)           | ✔️ 0.9                                            |
| [**CreepJS**](https://abrahamjuliot.github.io/creepjs/)                                            | ✔️ 71.5% (56% with Chrome fingerprint)            |
| **DataDome**                                                                                       | ✔️                                                |
| ‣ [antoinevastel.com](https://antoinevastel.com/bots/datadome)                                     | ✔️                                                |
| ‣ [datadome.co](https://datadome.co/bot-tester/)                                                   | ✔️                                                |
| **Imperva**                                                                                        | ✔️                                                |
| ‣ [ticketmaster.es](https://www.ticketmaster.es/)                                                  | ✔️                                                |
| **Kasada**                                                                                         | ✔️                                                |
| ‣ [canadagoose.com](https://www.canadagoose.com/)                                                  | ✔️                                                |
| **Cloudflare**                                                                                     | ✔️                                                |
| ‣ [Turnstile](https://nopecha.com/demo/turnstile)                                                  | ✔️                                                |
| ‣ [Interstitial](https://nopecha.com/demo/cloudflare)                                              | ✔️ Unstable on Chrome fingerprints                |
| **Font Fingerprinting**                                                                            | ✔️                                                |
| ‣ [Browserleaks Fonts](https://browserleaks.net/fonts)                                             | ✔️                                                |
| ‣ [CreepJS TextMetrics](https://abrahamjuliot.github.io/creepjs/tests/fonts.html)                  | ✔️                                                |
| [**SannySoft**](https://bot.sannysoft.com/)                                                        | ✔️                                                |
| [**Incolumitas**](https://bot.incolumitas.com/)                                                    | ✔️ 0.8-1.0                                        |
| [**Fingerprint.com**](https://fingerprint.com/products/bot-detection/)                             | ✔️                                                |
| [**IpHey**](https://iphey.com/)                                                                    | ✔️                                                |
| [**BrowserScan**](https://browserscan.net/)                                                        | ✔️                                                |
| [**Bet365**](https://www.bet365.com/#/AC/B1/C1/D1002/E79147586/G40/)                               | ✔️                                                |

Camoufox does **not** fully support injecting Chromium fingerprints. Some WAFs (such as [Interstitial](https://nopecha.com/demo/cloudflare)) look for the Gecko webdriver underneath.

---

## Build System

### Overview

Here is a diagram of the build system, and its associated make commands:

```mermaid
graph TD
    FFSRC[Firefox Source] -->|make fetch| REPO

    subgraph REPO[Camoufox Repository]
        PATCHES[Fingerprint masking patches]
        ADDONS[uBlock & B.P.C.]
        DEBLOAT[Debloat/optimizations]
        SYSTEM_FONTS[Win, Mac, Linux fonts]
        JUGGLER[Patched Juggler]
    end

    subgraph Local
    REPO -->|make dir| PATCH[Patched Source]
    PATCH -->|make build| BUILD[Built]
    BUILD -->|make package-linux| LINUX[Linux Portable]
    BUILD -->|make package-windows| WIN[Windows Portable]
    BUILD -->|make package-macos| MAC[macOS Portable]
    end
```

This was originally forked from the LibreWolf build system.

## Build CLI

> [!WARNING]
> Camoufox's build system is designed to be used in Linux. WSL will not work!

First, clone this repository with Git:

```bash
git clone --depth 1 https://gitlab.com/daijro/camoufox
cd camoufox
```

Next, build the Camoufox source code with the following command:

```bash
make dir
```

After that, you have to bootstrap your system to be able to build Camoufox. You only have to do this one time. It is done by running the following command:

```bash
make bootstrap
```

Finally you can build and package Camoufox the following command:

```bash
python3 multibuild.py --target linux windows macos --arch x86_64 arm64 i686
```

<details>
<summary>
CLI Parameters
</summary>

```bash
Options:
  -h, --help            show this help message and exit
  --target {linux,windows,macos} [{linux,windows,macos} ...]
                        Target platforms to build
  --arch {x86_64,arm64,i686} [{x86_64,arm64,i686} ...]
                        Target architectures to build for each platform
  --bootstrap           Bootstrap the build system
  --clean               Clean the build directory before starting

Example:
$ python3 multibuild.py --target linux windows macos --arch x86_64 arm64
```

</details>

### Using Docker

Camoufox can be built through Docker on all platforms.

1. Create the Docker image containing Firefox's source code:

```bash
docker build -t camoufox-builder .
```

2. Build Camoufox patches to a target platform and architecture:

```bash
docker run -v "$(pwd)/dist:/app/dist" camoufox-builder --target <os> --arch <arch>
```

<details>
<summary>
How can I use my local ~/.mozbuild directory?
</summary>

If you want to use the host's .mozbuild directory, you can use the following command instead to run the docker:

```bash
docker run \
  -v "$HOME/.mozbuild":/root/.mozbuild:rw,z \
  -v "$(pwd)/dist:/app/dist" \
  camoufox-builder \
  --target <os> \
  --arch <arch>
```

</details>

<details>
<summary>
Docker CLI Parameters
</summary>

```bash
Options:
  -h, --help            show this help message and exit
  --target {linux,windows,macos} [{linux,windows,macos} ...]
                        Target platforms to build
  --arch {x86_64,arm64,i686} [{x86_64,arm64,i686} ...]
                        Target architectures to build for each platform
  --bootstrap           Bootstrap the build system
  --clean               Clean the build directory before starting

Example:
$ docker run -v "$(pwd)/dist:/app/dist" camoufox-builder --target windows macos linux --arch x86_64 arm64 i686
```

</details>

Build artifacts will now appear written under the `dist/` folder.

---

## Development Tools

This repo comes with a developer UI under scripts/developer.py:

```
make edits
```

Patches can be edited, created, removed, and managed through here.

<img src="https://i.imgur.com/BYAN5J0.png">

### How to make a patch

1. In the developer UI, click **Reset workspace**.
2. Make changes in the `camoufox-*/` folder as needed. You can test your changes with `make build` and `make run`.
3. After you're done making changes, click **Write workspace to patch** and save the patch file.

### How to work on an existing patch

1. In the developer UI, click **Edit a patch**.
2. Select the patch you'd like to edit. Your workspace will be reset to the state of the selected patch.
3. After you're done making changes, hit **Write workspace to patch** and overwrite the existing patch file.

---

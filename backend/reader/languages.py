"""Reading languages: OCR data, verified local voices and test sentences.

Piper voices are pinned to one rhasspy/piper-voices revision; the SHA256 values
come from that revision's Hugging Face LFS metadata. Kokoro reads German with the
Martin model and its other listed languages with the standard v1.0 model."""

import os

PIPER_REVISION = 'c10ece1aade47bb51c153c893d14e5bf8e5b7117'

# code: (English name, native name, Tesseract language, test sentence)
LANGUAGES = {
    'ar': ('Arabic', 'العربية', 'ara', 'مرحبا، هذا اختبار.'),
    'bg': ('Bulgarian', 'Български', 'bul', 'Здравейте, това е тест.'),
    'bn': ('Bengali', 'বাংলা', 'ben', 'নমস্কার, এটি একটি পরীক্ষা।'),
    'ca': ('Catalan', 'Català', 'cat', 'Hola, això és una prova.'),
    'cs': ('Czech', 'Čeština', 'ces', 'Dobrý den, toto je test.'),
    'cy': ('Welsh', 'Cymraeg', 'cym', 'Helo, prawf yw hwn.'),
    'da': ('Danish', 'Dansk', 'dan', 'Hej, dette er en test.'),
    'de': ('German', 'Deutsch', 'deu', 'Hallo! Diese Stimme liest deinen Text vor.'),
    'el': ('Greek', 'Ελληνικά', 'ell', 'Γεια σας, αυτό είναι ένα τεστ.'),
    'en': ('English', 'English', 'eng', 'Hello! This voice will read your text aloud.'),
    'es': ('Spanish', 'Español', 'spa', 'Hola, esto es una prueba.'),
    'et': ('Estonian', 'Eesti', 'est', 'Tere, see on test.'),
    'eu': ('Basque', 'Euskara', 'eus', 'Kaixo, hau proba bat da.'),
    'fa': ('Persian', 'فارسی', 'fas', 'سلام، این یک آزمایش است.'),
    'fi': ('Finnish', 'Suomi', 'fin', 'Hei, tämä on testi.'),
    'fr': ('French', 'Français', 'fra', 'Bonjour, ceci est un test.'),
    'he': ('Hebrew', 'עברית', 'heb', 'שלום, זו בדיקה.'),
    'hi': ('Hindi', 'हिन्दी', 'hin', 'नमस्ते, यह एक परीक्षण है।'),
    'hu': ('Hungarian', 'Magyar', 'hun', 'Helló, ez egy teszt.'),
    'hy': ('Armenian', 'Հայերեն', 'hye', 'Բարև, սա փորձարկում է։'),
    'id': ('Indonesian', 'Bahasa Indonesia', 'ind', 'Halo, ini adalah tes.'),
    'is': ('Icelandic', 'Íslenska', 'isl', 'Halló, þetta er próf.'),
    'ja': ('Japanese', '日本語', 'jpn', 'こんにちは。この声があなたの文章を読み上げます。'),
    'it': ('Italian', 'Italiano', 'ita', 'Ciao, questa è una prova.'),
    'ka': ('Georgian', 'ქართული', 'kat', 'გამარჯობა, ეს ტესტია.'),
    'kk': ('Kazakh', 'Қазақша', 'kaz', 'Сәлеметсіз бе, бұл сынақ.'),
    'ko': ('Korean', '한국어', 'kor', '안녕하세요, 이것은 테스트입니다.'),
    'ku': ('Kurdish (Kurmanji)', 'Kurmancî', 'kmr', 'Silav, ev ceribandinek e.'),
    'lb': ('Luxembourgish', 'Lëtzebuergesch', 'ltz', 'Moien, dëst ass en Test.'),
    'lv': ('Latvian', 'Latviešu', 'lav', 'Sveiki, šis ir tests.'),
    'ml': ('Malayalam', 'മലയാളം', 'mal', 'നമസ്കാരം, ഇതൊരു പരീക്ഷണമാണ്.'),
    'mr': ('Marathi', 'मराठी', 'mar', 'नमस्कार, ही एक चाचणी आहे.'),
    'ne': ('Nepali', 'नेपाली', 'nep', 'नमस्ते, यो एउटा परीक्षण हो।'),
    'nl': ('Dutch', 'Nederlands', 'nld', 'Hallo, dit is een test.'),
    'no': ('Norwegian', 'Norsk', 'nor', 'Hei, dette er en test.'),
    'pl': ('Polish', 'Polski', 'pol', 'Cześć, to jest test.'),
    'pt': ('Portuguese', 'Português', 'por', 'Olá, isto é um teste.'),
    'ro': ('Romanian', 'Română', 'ron', 'Bună, acesta este un test.'),
    'ru': ('Russian', 'Русский', 'rus', 'Здравствуйте, это тест.'),
    'sk': ('Slovak', 'Slovenčina', 'slk', 'Dobrý deň, toto je test.'),
    'sl': ('Slovenian', 'Slovenščina', 'slv', 'Pozdravljeni, to je test.'),
    'sq': ('Albanian', 'Shqip', 'sqi', 'Përshëndetje, ky është një test.'),
    'sr': ('Serbian', 'Srpski', 'srp', 'Zdravo, ovo je test.'),
    'sv': ('Swedish', 'Svenska', 'swe', 'Hej, det här är ett test.'),
    'sw': ('Swahili', 'Kiswahili', 'swa', 'Habari, hili ni jaribio.'),
    'te': ('Telugu', 'తెలుగు', 'tel', 'నమస్కారం, ఇది ఒక పరీక్ష.'),
    'tr': ('Turkish', 'Türkçe', 'tur', 'Merhaba, bu bir testtir.'),
    'uk': ('Ukrainian', 'Українська', 'ukr', 'Вітаю, це тест.'),
    'ur': ('Urdu', 'اردو', 'urd', 'ہیلو، یہ ایک ٹیسٹ ہے۔'),
    'vi': ('Vietnamese', 'Tiếng Việt', 'vie', 'Xin chào, đây là một bài kiểm tra.'),
    'zh': ('Chinese', '中文', 'chi_sim', '你好，这是一个测试。'),
}

# code: (Kokoro model family, phonemizer language, [(voice, label)])
KOKORO = {
    'de': ('de', 'de', [('martin', 'Martin · male')]),
    'en': ('en', 'en-us', [('af_heart', 'Heart · female'), ('af_nicole', 'Nicole · female'), ('am_adam', 'Adam · male'),
                          ('bf_emma', 'Emma · female · British'), ('bm_george', 'George · male · British')]),
    'es': ('en', 'es', [('ef_dora', 'Dora · female'), ('em_alex', 'Alex · male')]),
    'fr': ('en', 'fr-fr', [('ff_siwis', 'Siwis · female')]),
    'it': ('en', 'it', [('if_sara', 'Sara · female'), ('im_nicola', 'Nicola · male')]),
    'ja': ('en', 'ja', [('jf_alpha', 'Alpha · female'), ('jm_kumo', 'Kumo · male')]),
    'pt': ('en', 'pt-br', [('pf_dora', 'Dora · female'), ('pm_alex', 'Alex · male')]),
    'hi': ('en', 'hi', [('hf_alpha', 'Alpha · female'), ('hm_omega', 'Omega · male')]),
    'zh': ('en', 'cmn', [('zf_xiaobei', 'Xiaobei · female'), ('zm_yunjian', 'Yunjian · male')]),
}

# code: (folder, model file, model SHA256, config SHA256, size in MB)
# Piper 1.8 cannot run the Japanese, Thai or Lithuanian voices (non-espeak
# phonemizers). Japanese is spoken by Kokoro with the misaki pronunciation pack
# below (espeak cannot read kanji); Thai and Lithuanian are not offered.
PIPER = {
    'ar': ('ar/ar_JO/kareem/medium/', 'ar_JO-kareem-medium.onnx',
           '9e95cab07b679da603bba17c4dec7ab3111320571964ee95c0379603c086491e',
           'ea6d9b9d9076dbdb6bf5c98c6a141ef154959d2359709b37855727964e7d6c4d', 60),
    'bg': ('bg/bg_BG/dimitar/medium/', 'bg_BG-dimitar-medium.onnx',
           '4972fe764468e8501416407ad81662de94cc6c9cdc680fcf807daef04e319f13',
           'ec9a9abdd17384d3db225e83085b2f68b790b112f058417c3a8a2ac58b79e7f0', 60),
    'bn': ('bn/bn_BD/google/medium/', 'bn_BD-google-medium.onnx',
           'f2e7518ed5534a755024a48c71b80bf617efaf12570bbdf3ce255a9526a8afd3',
           'bc7e5e39e2a874bdad186620576ce18089b5a06c5645e258bcea3d56fdb11c0a', 73),
    'ca': ('ca/ca_ES/upc_ona/medium/', 'ca_ES-upc_ona-medium.onnx',
           'fdb652db8c11a4475527346cf3241cb064d1ba393cf370f3f2ec09a872d118fd',
           '7f76acc9c06f4eda9e6aef2997b75782d97855aab48d4b401eb956a6e655eddc', 60),
    'cs': ('cs/cs_CZ/jirka/medium/', 'cs_CZ-jirka-medium.onnx',
           'cbd5c900acacc8e8cbecd64347abb8de39c00a9d3104bed06fee92e4f319efc8',
           'fb38b1799b7354808227c065efa97b1ffa2b0cde59505babb56a36d35af9c637', 60),
    'cy': ('cy/cy_GB/bu_tts/medium/', 'cy_GB-bu_tts-medium.onnx',
           '411b513cd35975b4248cbaa8e3e5a9d9a3b8db6b77680b821e37b75d984be329',
           'c318e3b8700b8eb4ed5deb276872b036dcb67e2882cc8dfb2d59d4a64018b285', 73),
    'da': ('da/da_DK/talesyntese/medium/', 'da_DK-talesyntese-medium.onnx',
           'b9271efd25f7b8494bbd28d48dd675c8c119daa284f3ee488008935f515f1241',
           '89fe13bd251406cc0088570d103ea7ac35823211d8466faf913268ab8506f41b', 60),
    'de': ('de/de_DE/thorsten/high/', 'de_DE-thorsten-high.onnx',
           '9df1c43c61149ef9b39e618e2b861fbe41e1fcea9390b2dac62e8761573ea4f1',
           '6de734444e4c3f9e33b7ebe2746dbc19b71e85f613e79c65acf623200b99a76a', 109),
    'el': ('el/el_GR/joy/medium/', 'el_GR-joy-medium.onnx',
           '31b1d51dc72dd43a5429b67798e27599f8cdcfce8a80265bc6f50d932bf144bc',
           '451a8885a0ea72e4432fffe22e65a75bbd2e65f6757273d1a5a9ed8a3419852e', 61),
    'en': ('en/en_US/lessac/high/', 'en_US-lessac-high.onnx',
           '4cabf7c3a638017137f34a1516522032d4fe3f38228a843cc9b764ddcbcd9e09',
           'db42b97d9859f257bc1561b8ed980e7fb2398402050a74ddd6cbec931a92412f', 109),
    'es': ('es/es_ES/davefx/medium/', 'es_ES-davefx-medium.onnx',
           '6658b03b1a6c316ee4c265a9896abc1393353c2d9e1bca7d66c2c442e222a917',
           '0e0dda87c732f6f38771ff274a6380d9252f327dca77aa2963d5fbdf9ec54842', 60),
    'et': ('et/et_EE/news/medium/', 'et_EE-news-medium.onnx',
           'ddd679e874e0f6ec4e8f76c99cef77d490341b001aa6e839415028be5d04f9bf',
           '2f56bbaf9cd2c44bf4b1e02fb36cfd31876f7ed3f78ca199f2aca6727e96441a', 73),
    'eu': ('eu/eu_ES/antton/medium/', 'eu_ES-antton-medium.onnx',
           'dc8305fda17b22e922f011cd7450c50c76b2f2630c2cfa5c35564326daef1454',
           'bc26d21295427594330bb8ea579c8b922d1d1f9dde1b51dc9949fbf3f559dcea', 61),
    'fa': ('fa/fa_IR/amir/medium/', 'fa_IR-amir-medium.onnx',
           'fb815380d969ea372b0b21b0de14421f58fe481047e153e69685d079b6e1a9d1',
           '75f918a3bf0f57a9179abe725af529f2a5c79d6c899e2a84aec76c685d5dfb9a', 61),
    'fi': ('fi/fi_FI/harri/medium/', 'fi_FI-harri-medium.onnx',
           'a44167faa34caed940e4fcad139fcc35922266b2593bcebe77701774c0fb2389',
           '3f9c9f76f74adf1fbe7279e41eea17d6610757e45effd6808bbea6be74b8916d', 60),
    'fr': ('fr/fr_FR/siwis/medium/', 'fr_FR-siwis-medium.onnx',
           '641d1ab097da2b81128c076810edb052b385decc8be3381814802a64a73baf99',
           '39479916c2db192b5ac9764daddd0c744d83e023ad890c6976c0633ae4df8959', 60),
    'he': ('he/he_IL/saspeech/medium/', 'he_IL-saspeech-medium.onnx',
           '3dc067debc9e782a8a0d095dbb58786648743d406366dcc2aa81009660873b4d',
           'e9800a282a6cf2e44b3ad97f640b38e35ed246dfe070458d13bfcf206befc5bf', 60),
    'hi': ('hi/hi_IN/pratham/medium/', 'hi_IN-pratham-medium.onnx',
           '169964b0871667f6793416d4b35e97357a68ba1ad01df8580c28048989ee7693',
           'b68edd2cd7950dd436314013b7cd12e9699e5a3f6fe5af5af94294cf6aa7b9fd', 61),
    'hu': ('hu/hu_HU/anna/medium/', 'hu_HU-anna-medium.onnx',
           '968c0c3a66cb667811242cc88653bff9247395fc7a0517fbeef7d8c08cdae62a',
           'ccf967d8db8018c9d8ffdb0edc8814ffcb6b75273bb0d84337317240f710283a', 60),
    'hy': ('hy/hy_AM/gor/medium/', 'hy_AM-gor-medium.onnx',
           '1c91fc33fecbbfc6b7921f9d11fd7487a859053a3a1987147f5c361155b89e7c',
           '01a8458d4ff226fac1b7dc7b1f619851fdbc8a9bd09d6a604e65e304c9600c2e', 61),
    'id': ('id/id_ID/news_tts/medium/', 'id_ID-news_tts-medium.onnx',
           'ed8f02aa593f7af6b19acbdb8142e0da0dd72f46194eb33d38e0eb10a52597e8',
           '1ef677072668a5e172e0759b1d3871f129009d1167f093325a17607f7add5ad7', 60),
    'is': ('is/is_IS/bui/medium/', 'is_IS-bui-medium.onnx',
           '3a645b2d2850e4098f01f3765cece931836c03741e01a5cc514d09d39d37c05c',
           '3cae728572fbb397713d047f2299247bb76b62639d9dfdcd65b26c578b8aba45', 73),
    'it': ('it/it_IT/paola/medium/', 'it_IT-paola-medium.onnx',
           '6fc918b5a0ea6137382833dddfa567bffbe6a5060c02043c87192ee59c04210c',
           'aea19c0a7fce29fbc359b93f10e7902854401e4c95ae2ea328ae516b15d296cf', 61),
    'ka': ('ka/ka_GE/natia/medium/', 'ka_GE-natia-medium.onnx',
           '04bdacf188fa24499885f9109b395fe8561a05ec2cd90d55453ec5beed7af460',
           '906436d0f8de79fcd65576470b10c7ea937c750f9b6b6dafc72a27cebd4a88f6', 60),
    'kk': ('kk/kk_KZ/issai/high/', 'kk_KZ-issai-high.onnx',
           '4dee767c893e8535da821447d12cb030e3569e11254c14030a1da5d8b2222c16',
           'eb145ac8712b87beda9f0266e95b98cad76acce89d4626cd8b1408234e9842f0', 122),
    'ko': ('ko/ko_KR/kss/medium/', 'ko_KR-kss-medium.onnx',
           '624fd774e26895f24bebae1bd9a3379e3394baeade4b584924f83e414096e2c9',
           '153b5619d0580f824a59108d83ca19434de410eb8e4fe80325b58684fdc8a1df', 60),
    'ku': ('ku/ku_TR/berfin_renas/medium/', 'ku_TR-berfin_renas-medium.onnx',
           'bc0b2cf086f9a33ca1d7ca2ca80b6f35f8917d0c89afe4a645c5b9d56ac355c4',
           '66d0da87aa8e572c7e6ee67647aa6af6008e85e38819679f17dc9b86e3affca8', 73),
    'lb': ('lb/lb_LU/marylux/medium/', 'lb_LU-marylux-medium.onnx',
           '4147ecacdd98932951d0f956555542de358d3ccff708d4996e305c3ce287097a',
           'e5c5dec5433d33ff573e76fa567e80dcf636d05de5dcc817b273963f0733d742', 60),
    'lv': ('lv/lv_LV/aivars/medium/', 'lv_LV-aivars-medium.onnx',
           '9d855a47c22e2b94795be9e0eb9e8c4c02ce251dc89461dede94de20ff08bd8e',
           '08ae2c297be8aa04f15f3f97b7ffeae0146b30b0bd8f7baebcdc46bc2c2f33dc', 61),
    'ml': ('ml/ml_IN/arjun/medium/', 'ml_IN-arjun-medium.onnx',
           'e881130516a874306972a07dcf262e6900140430c5658131121744a80ef3f11b',
           '2804f070954e56545e88101b70331d444402187899d0a6ff03e5d44bee813245', 60),
    'mr': ('mr/mr_IN/google/medium/', 'mr_IN-google-medium.onnx',
           'e1200d474a74ebd6d1737be2c7affe56f1f9efc18915d4595d7f5c2b15cf06f4',
           '11055302ee1e3c9902e5e96c03cbfc0a9eec29b1b06b91ef52a3c66e9873edbb', 73),
    'ne': ('ne/ne_NP/chitwan/medium/', 'ne_NP-chitwan-medium.onnx',
           'f7ba6b0927688f92717e93ca52bc06f5783ce8edc765d5f85365acef1d41822c',
           '18d523b03b201422d14e2892cc750a81208d2e45158a9c6a7e4e06a500930dee', 60),
    'nl': ('nl/nl_NL/mls/medium/', 'nl_NL-mls-medium.onnx',
           '88312e0fbf505b87caf2373d94c1384892e86b1bf2ee482cf65dc8ba179cc7d3',
           '6ddb215d38f1392ab935ad45441b82ada1eeae0452a2d6849ed71ea4f2e0aa63', 73),
    'no': ('no/no_NO/nvcc/medium/', 'no_NO-nvcc-medium.onnx',
           '3f51702946d9544898440a1a66906155661a9d680ee103130ff68f73360b512e',
           '98410e911e5a9076ac4677a79b08b20f98c54f550c4388e29978f6bafa32b83d', 73),
    'pl': ('pl/pl_PL/bass/high/', 'pl_PL-bass-high.onnx',
           '73b8408967c58118700f21eb2413cd8b666c7844c6136cf674bf5dd56bde72c2',
           '7bb41aa14fee87a31cc32264119c09e3553335196d3db15b39b1c18790e13c59', 109),
    'pt': ('pt/pt_BR/faber/medium/', 'pt_BR-faber-medium.onnx',
           '858555e3a064209c57088fe6bd70c4c3dc54d03eaa00c45d5ecaf43a33f95aa7',
           '7e694de195ae3fc36dd732c445eb04fb49b649854893cb5506b978f0d50a1d6f', 60),
    'ro': ('ro/ro_RO/mihai/medium/', 'ro_RO-mihai-medium.onnx',
           'e0608bbbd53c80267c09ece681b09f5199f54e792356684c8073738e5f15d29f',
           '8cc0c9f077dc0cec3c25a6a055ec8046db8e40a2510591582f2c9c869f4bc47e', 60),
    'ru': ('ru/ru_RU/denis/medium/', 'ru_RU-denis-medium.onnx',
           '15fab56e11a097858ee115545d0f697fc2a316c41a291a5362349fb870411b0a',
           '831c860dac0b5073eaa81610a0a638ec23d90a6cf8e5f871b4485c2cec3767c8', 60),
    'sk': ('sk/sk_SK/lili/medium/', 'sk_SK-lili-medium.onnx',
           'd8e21603e0165252849efe0bcb3fbffd1b3193c36bd1f556e1106911e8015526',
           'b7c474eba411913f9feb65b9da322463e8698e7b200d2b757f6e684802951333', 60),
    'sl': ('sl/sl_SI/artur/medium/', 'sl_SI-artur-medium.onnx',
           '9222ed93ef425524ad4be0b083369af8ea8db18455576a6016b154192f4ed38c',
           '741283430f1fa2be5c61717c6f1fe795a7b9f537491927340dd12f90f3b3cc04', 60),
    'sq': ('sq/sq_AL/edon/medium/', 'sq_AL-edon-medium.onnx',
           '5d0ae8af36a00ac6813517b2af47bc4cda42e88ece04f6076ae3b0f5479c57c8',
           'e9ee77beea52d8042bca589448bb48033ac0f7c1d86daee84ad1d5692d1270f7', 61),
    'sr': ('sr/sr_RS/serbski_institut/medium/', 'sr_RS-serbski_institut-medium.onnx',
           'd7003890cf596e653f660a4fd97fd17f57f1eceb6d9727abad9cd76d2fda0d80',
           '39ad6531b46ac629c0bed10aa9205dd2431e2dab3808b8535808711db87c2bc0', 73),
    'sv': ('sv/sv_SE/alma/medium/', 'sv_SE-alma-medium.onnx',
           'f75455eb6afeb1db9e2905d5bd7e4115afcd3710e0d399b6a40981766d32fedc',
           '6924380892f769afa92fc6b28ff91d558690d7fb4e3ef8cbf821cefadc8f38fe', 60),
    'sw': ('sw/sw_CD/lanfrica/medium/', 'sw_CD-lanfrica-medium.onnx',
           '1f195ed12ca5e7875114618e5f00207af364602e21ca78c8a6d3d7674f9259fa',
           '5bd6f6ad659aa8f1f89f414e23a3df84fc753eb9c066e91fe86729da2ad4c1fc', 60),
    'te': ('te/te_IN/maya/medium/', 'te_IN-maya-medium.onnx',
           'c3518ad4e3ca8ea6059c1e002f3772068f634960f58b237a96ff629db1c6200e',
           'c07074aadf0a33e230647611af9041e1fb6609b995d017ee95009586a491508f', 60),
    'tr': ('tr/tr_TR/dfki/medium/', 'tr_TR-dfki-medium.onnx',
           '2844717f524ab965d3fe86e60562cbb601d3e456836efcc2196cc3a14112a8fb',
           '13ebd7810f1b61b5027583cf3131a0a233b6ea81c38f2200ebc4ff41c3cca039', 60),
    'uk': ('uk/uk_UA/mykyta/high/', 'uk_UA-mykyta-high.onnx',
           '081d253cd246d7d4d698c6dd147b74cad498dafd213527887a3a490519138243',
           'b5db6b4efb02d4a0e8f128253fd64e82dfa72d1105e9060b0c6fd9610eec6a4f', 109),
    'ur': ('ur/ur_PK/aegis_female/medium/', 'ur_PK-aegis_female-medium.onnx',
           '3ec306035cfd0bbc22342fee5890450708a16dd231809522731678aa583c961f',
           'a8385c217a7e276acf5234bf01dbd0adb007a57c32ffbcc57d2db7eac3979bb6', 61),
    'vi': ('vi/vi_VN/vais1000/medium/', 'vi_VN-vais1000-medium.onnx',
           'ec7c89e2c85f4d1edc24b6120c18aaf1bda614f06b511567eb9c7c0de15e2dab',
           'fafb9da1354ed4b77c31af228ed41fb41cd825c14cffa105454b25e6ae751ee0', 60),
    'zh': ('zh/zh_CN/huayan/medium/', 'zh_CN-huayan-medium.onnx',
           '9929917bf8cabb26fd528ea44d3a6699c11e87317a14765312420be230be0f3d',
           'd521dc45504a8ccc99e325822b35946dd701840bfb07e3dbb31a40929ed6a82b', 60),
}


# Languages the Qwen3-TTS 12 Hz models speak.
QWEN_LANGUAGES = ('zh', 'en', 'ja', 'ko', 'de', 'fr', 'ru', 'pt', 'es', 'it')

# Japanese needs its own grapheme-to-phoneme step; installed only with a Japanese Kokoro voice.
JAPANESE_PACKAGES = ['misaki[ja]==0.7.4', 'fugashi==1.5.2', 'unidic-lite==1.0.8', 'jaconv==0.5.0', 'mojimoji==0.0.13']
JAPANESE_MODULES = ('misaki', 'fugashi', 'unidic_lite', 'jaconv', 'mojimoji')

# code: FLORES-200 language token of the offline NLLB-200 translator
NLLB = dict(ar='arb_Arab', bg='bul_Cyrl', bn='ben_Beng', ca='cat_Latn', cs='ces_Latn', cy='cym_Latn', da='dan_Latn', de='deu_Latn',
            el='ell_Grek', en='eng_Latn', es='spa_Latn', et='est_Latn', eu='eus_Latn', fa='pes_Arab', fi='fin_Latn', fr='fra_Latn',
            he='heb_Hebr', hi='hin_Deva', hu='hun_Latn', hy='hye_Armn', id='ind_Latn', it='ita_Latn', ja='jpn_Jpan',
            ka='kat_Geor', kk='kaz_Cyrl', ko='kor_Hang', ku='kmr_Latn', lb='ltz_Latn', lv='lvs_Latn', ml='mal_Mlym', mr='mar_Deva',
            ne='npi_Deva', nl='nld_Latn', no='nob_Latn', pl='pol_Latn', pt='por_Latn', ro='ron_Latn', ru='rus_Cyrl', sk='slk_Latn',
            sl='slv_Latn', sq='als_Latn', sr='srp_Cyrl', sv='swe_Latn', sw='swh_Latn', te='tel_Telu', tr='tur_Latn', uk='ukr_Cyrl',
            ur='urd_Arab', vi='vie_Latn', zh='zho_Hans')
NLLB['is'] = 'isl_Latn'  # 'is' is a Python keyword, so it cannot be a dict() argument.


def default_language():
    """The desktop locale's language when supported, otherwise English."""
    for key in ('LC_ALL', 'LC_MESSAGES', 'LANG'):
        code = os.environ.get(key, '').split('_')[0].split('.')[0].lower()
        if code in ('nb', 'nn'):
            code = 'no'
        if valid(code):
            return code
    return 'en'


def valid(code):
    return isinstance(code, str) and code in LANGUAGES


def name(code):
    return LANGUAGES[code][0] if valid(code) else str(code)


def label(code):
    english, native = LANGUAGES[code][:2]
    return english if english == native else english + ' · ' + native


def ocr_language(code):
    return LANGUAGES[code][2] if valid(code) else 'eng'


def sample(code):
    return LANGUAGES[code][3] if valid(code) else LANGUAGES['en'][3]


def kokoro_family(code):
    """German uses the Martin model; every other Kokoro language the standard model."""
    return KOKORO[code][0]


def kokoro_phonemes(code, voice=''):
    if code == 'en' and voice.startswith('b'):
        return 'en-gb'
    return KOKORO[code][1] if code in KOKORO else 'en-us'


def kokoro_voice_language(voice):
    for code, (_, _, voices) in KOKORO.items():
        if any(voice == item[0] for item in voices):
            return code
    return None


def options():
    """Languages for the popup, with the local engines that can be installed."""
    return [dict(value=code, label=label(code), kokoro=code in KOKORO, piper=code in PIPER,
                 piper_mb=PIPER[code][4] if code in PIPER else 0)
            for code in sorted(LANGUAGES, key=lambda c: name(c))]

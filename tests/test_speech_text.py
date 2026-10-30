import pytest

from signaltrail.speech_text import spoken_numbers


@pytest.mark.parametrize(('text', 'language', 'expected'), [
    ('3.75%—4%', 'zh-CN', '百分之三点七五至百分之四'),
    ('3.75%—4%', 'en', 'three point seven five percent to four percent'),
    ('2026-10-29', 'zh-CN', '二零二六年十月二十九日'),
    ('2026-10-29', 'en', 'October twenty nine, two zero two six'),
    ('1,234', 'zh-CN', '一千二百三十四'),
    ('1,234', 'en', 'one thousand two hundred thirty four'),
    ('2026年涨25基点，CPU不变。', 'zh-CN', '二零二六年涨二十五基点，CPU不变。'),
    ('13:05', 'zh-CN', '十三点零五分'),
    ('13:05', 'en', 'thirteen oh five'),
    ('-0.025%', 'zh-CN', '负百分之零点零二五'),
    ('-0.025%', 'en', 'minus zero point zero two five percent'),
    ('100010001', 'zh-CN', '一亿零一万零一'),
    ('10010', 'zh-CN', '一万零一十'),
    ('RTX4090 CPU GPT-4', 'en', 'RTX four zero nine zero CPU GPT dash four'),
    ('0007', 'zh-CN', '零零零七'),
    ('3.75%-4%', 'zh-CN', '百分之三点七五至百分之四'),
    ('-3--1', 'en', 'minus three to minus one'),
    ('CVE-2026-97229', 'zh-CN', 'CVE杠二零二六杠九七二二九'),
    ('CVE-2026-97229', 'en', 'CVE dash two zero two six dash nine seven two two nine'),
])
def test_standard_numbers_preserve_values(text, language, expected):
    assert spoken_numbers(text, language) == expected


def test_invalid_calendar_date_requires_explicit_reading():
    with pytest.raises(ValueError):
        spoken_numbers('2026-02-31', 'zh-CN')


@pytest.mark.parametrize('text', ['$3.75', '1e-5', '12:30:15'])
def test_unsupported_numeric_formats_request_explicit_spoken_words(text):
    with pytest.raises(ValueError, match='Spell out'):
        spoken_numbers(text, 'en')

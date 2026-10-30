"""为本地新闻口播展开标准中英文数字，保留原始新闻文本。"""

from __future__ import annotations

import re
from datetime import date

_ZH = "零一二三四五六七八九"
_EN = [
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
]
_TENS = [
    "zero",
    "ten",
    "twenty",
    "thirty",
    "forty",
    "fifty",
    "sixty",
    "seventy",
    "eighty",
    "ninety",
]
_SCALES = ("", "thousand", "million", "billion", "trillion", "quadrillion", "quintillion")
_MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]
_NUMBER = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+"
_SPOKEN = re.compile(
    r"(?P<date>\d{4}-\d{2}-\d{2})(?!\d)|(?P<year>\d{4})年|"
    r"(?P<time>\d{1,2}:\d{2})(?![\d:])|(?P<number>[+\-−]?(?:" + _NUMBER + r")[%％]?)"
)


def _zh_integer(number: int) -> str:
    """处理：以万、亿、万亿分组展开中文整数，并补齐组内及组间的零。
    输入：非负整数；超出万亿分组范围时保留为逐位数字。
    输出：不省略任何数字位的中文读法。
    """
    if number == 0:
        return _ZH[0]
    if number >= 10**16:
        return "".join(_ZH[int(c)] for c in str(number))
    groups = []
    while number:
        groups.append(number % 10000)
        number //= 10000
    result, gap = "", False
    for index in range(len(groups) - 1, -1, -1):
        group = groups[index]
        if not group:
            gap = bool(result)
            continue
        if result and (gap or group < 1000):
            result += "零"
        part, zero = "", False
        for digit, unit in zip(f"{group:04d}", ("千", "百", "十", ""), strict=True):
            value = int(digit)
            if value:
                if zero:
                    part += "零"
                part += _ZH[value] + unit
                zero = False
            elif part:
                zero = True
        result += part + ("", "万", "亿", "万亿")[index]
        gap = False
    return result[1:] if result.startswith("一十") else result


def _en_integer(number: int) -> str:
    """处理：以千为组展开英文整数，使用标准英文数词。
    输入：非负整数；超过现有量级词表时逐位读取。
    输出：英文整数读法，不作数量级推断或舍入。
    """
    if number < 20:
        return _EN[number]
    if number < 100:
        return _TENS[number // 10] + (" " + _EN[number % 10] if number % 10 else "")
    if number < 1000:
        return (
            _EN[number // 100]
            + " hundred"
            + (" " + _en_integer(number % 100) if number % 100 else "")
        )
    original = number
    groups, index = [], 0
    while number:
        if index == len(_SCALES):
            return " ".join(_EN[int(c)] for c in str(original))
        group = number % 1000
        if group:
            groups.append(_en_integer(group) + " " + _SCALES[index])
        number //= 1000
        index += 1
    return " ".join(reversed(groups)).strip()


def spoken_numbers(text: str, language: str) -> str:
    """处理：将新闻标题或讲解中的标准数字转成中英文朗读文本。
    输入：原文及 zh-CN/en；支持整数、小数、百分比、ISO 日期、年和时刻。
    输出：保留数值的朗读副本；型号中的数字逐位读，原文由调用方另行保存。
    """
    if language not in {"zh-CN", "en"}:
        raise ValueError("Number pronunciation supports zh-CN or en")
    if re.search(r"[$€£¥￥‰]|\d(?:\.\d+)?[eE][+\-]?\d|\d+:\d+:\d+", text):
        raise ValueError(
            "Spell out currency, per-mille, scientific notation or HH:MM:SS for speech")
    chinese = language == "zh-CN"
    joiner = "" if chinese else " "
    integer = _zh_integer if chinese else _en_integer

    def digits(value: str) -> str:
        """处理：逐位展开年份、小数尾数或型号数字。
        输入：仅含数字的字符串；保留其中的零。
        输出：所选语言的逐位数词。
        """
        return joiner.join((_ZH[int(c)] if chinese else _EN[int(c)]) for c in value)

    protected = []

    def protect(match: re.Match) -> str:
        """处理：暂存日期或展开多段编号，避免连接号被当作区间。
        输入：匹配到的 ISO 日期或带数字段的字母编号。
        输出：临时占位符，完成区间替换后恢复对应内容。
        """
        value = match.group()
        if re.match(r"[A-Za-z]", value):
            chunks = value.split("-")
            dash = "杠" if chinese else " dash "
            value = chunks[0] + dash + dash.join(digits(chunk) for chunk in chunks[1:])
        protected.append(value)
        return chr(0xE000 + len(protected) - 1)

    ranged = re.sub(r"[A-Za-z][A-Za-z0-9_]*(?:-\d+){2,}|\d{4}-\d{2}-\d{2}(?!\d)",
                    protect, text)
    ranged = re.sub(r"(?<=[\d%％])\s*[—–-]\s*(?=[+\-−]?\d)",
                    "至" if chinese else " to ", ranged)
    for index, value in enumerate(protected):
        ranged = ranged.replace(chr(0xE000 + index), value)

    def expand(match: re.Match) -> str:
        """处理：按已识别的日期、时间或数值类别生成等值读法。
        输入：原文中一个完整数字表达及其邻接字符。
        输出：保留单位和词界的朗读替换。
        """
        value = match.group()
        if match.group("date"):
            year, month, day = map(int, value.split("-"))
            date(year, month, day)
            return (
                digits(f"{year:04d}") + "年" + integer(month) + "月" + integer(day) + "日"
                if chinese
                else _MONTHS[month - 1] + " " + integer(day) + ", " + digits(f"{year:04d}")
            )
        if match.group("year"):
            return digits(match.group("year")) + ("年" if chinese else " year")
        if match.group("time"):
            hour, minute = map(int, value.split(":"))
            if hour > 23 or minute > 59:
                raise ValueError("Invalid HH:MM for speech: " + value)
            if chinese:
                return (
                    integer(hour)
                    + "点"
                    + ("零" if 0 < minute < 10 else "")
                    + integer(minute)
                    + "分"
                )
            return integer(hour) + " " + ("oh " if minute < 10 else "") + integer(minute)
        percent = value.endswith(("%", "％"))
        if percent:
            value = value[:-1]
        signed = value[:1] in "+-−"
        sign = value[0] if signed else ""
        if signed:
            value = value[1:]
        before = ranged[match.start() - 1 : match.start()] if match.start() else ""
        after = ranged[match.end() : match.end() + 1]
        model = bool(re.match(r"[A-Za-z_]", before) or re.match(r"[A-Za-z_]", after))
        value = value.replace(",", "")
        whole, dot, fraction = value.partition(".")
        reading = (
            digits(whole)
            if model or (len(whole) > 1 and whole.startswith("0"))
            else integer(int(whole or "0"))
        )
        if dot:
            reading += ("点" if chinese else " point ") + digits(fraction)
        if percent:
            reading = "百分之" + reading if chinese else reading + " percent"
        if sign:
            if model and before:
                reading = ("杠" if chinese else "dash ") + reading
            else:
                reading = (
                    {"+": "正", "-": "负", "−": "负"}[sign]
                    if chinese
                    else "plus "
                    if sign == "+"
                    else "minus "
                ) + reading
        # 英文数词须与原文单词保持词界，避免数字展开后粘成未知词。
        if not chinese:
            reading = (" " if before and before.isalpha() else "") + reading
            if after and after.isalpha():
                reading += " "
        return reading

    return _SPOKEN.sub(expand, ranged)

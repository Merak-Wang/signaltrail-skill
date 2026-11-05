from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from urllib.parse import parse_qs, parse_qsl, unquote, urljoin, urlsplit

_RESIZE_QUERY_HOSTS = {
    "images.ctfassets.net", "image.cnbcfm.com", "i.guim.co.uk", "www.twz.com",
    "i.abcnewsfe.com", "dam.mediacorp.sg", "www.bbc.com", "ichef.bbci.co.uk",
}
_SIZE_QUERY_KEYS = {"w", "width", "h", "height", "dpr"}
_RESIZE_QUERY_KEYS = _SIZE_QUERY_KEYS | {"q", "quality", "fm", "format", "auto", "fit"}

_PLACEHOLDER_MARKERS = (
    "placeholder",
    "default-image",
    "default_image",
    "defaultimage",
    "image-not-found",
    "image_not_found",
    "missing-image",
    "missing_image",
    "no-image",
    "no_image",
    "noimage",
)
_PLACEHOLDER_FILENAMES = {
    "blank.gif",
    "blank.png",
    "spacer.gif",
    "spacer.png",
    "transparent.gif",
    "transparent.png",
}


def is_placeholder_image_url(value: object) -> bool:
    """处理：判断地址是否明显指向占位图而非内容图片。
    输入：
    - ``value``：待解析或规范化的单个输入值；非法值按函数契约返回空值或报错。
    输出：布尔判断；True 表示满足处理说明中的条件，False 表示不满足且不产生该结果。
    """
    text = str(value or "").strip()
    if not text:
        return False
    parsed = urlsplit(text)
    path = unquote(parsed.path).replace("\\", "/").casefold()
    filename = path.rsplit("/", 1)[-1]
    return filename in _PLACEHOLDER_FILENAMES or any(
        marker in path for marker in _PLACEHOLDER_MARKERS
    )


def is_editorial_template(image: dict) -> bool:
    """处理：识别已核实的站点推广、二维码与品牌模板。
    输入：图片地址及原文替代文本、图注。
    输出：广告模板返回真，新闻正文图继续进入候选排序。
    """
    parsed = urlsplit(str(image.get("url") or image.get("resolved_url") or ""))
    path = unquote(parsed.path).casefold()
    label = str(image.get("alt") or "") + " " + str(image.get("caption") or "")
    return bool(
        re.search(r"(?:qrcode|qr[-_]code|download[-_]app|app[-_]download|/emoji/)", path)
        or re.search(
            r"(?:扫码|二维码).{0,12}(?:关注|下载|订阅|app)"
            r"|下载.{0,8}app|关注.{0,6}公众号",
            label,
            re.I,
        )
        or re.search(r"/(?:logo|site[-_]logo|favicon)\.(?:png|svg|ico)$", path)
        or (
            (parsed.hostname or "").endswith("tmtpost.com")
            and ("/tkrss/" in path or "/change_logo" in path or "/new_logo/" in path)
        )
        or (
            (parsed.hostname or "").endswith("pansci.asia")
            and any(marker in path for marker in ("【廣告】", "新書上市", "大橫幅"))
        )
        or parsed.hostname == "www.yicai.com"
        and re.fullmatch(r"/img/article_(?:lock|float)_[a-z]+\.[a-z0-9]+\.png", parsed.path, re.I)
    )


def filter_editorial_templates(images: list[dict]) -> list[dict]:
    """处理：过滤明确的推广资源及成组栏目横幅。
    输入：同一新闻的图片候选及其尺寸、图注。
    输出：保留正文图片，成组出现的栏目横幅不进入下载或渲染。
    """

    def section_banner(image: dict) -> bool:
        """处理：匹配已核实的栏目横幅资源特征。
        输入：单张图片的来源 URL、尺寸和图注。
        输出：满足栏目资源特征时返回真。
        """
        parsed = urlsplit(str(image.get("url") or image.get("resolved_url") or ""))
        width = str(image.get("width") or image.get("declared_width") or "")
        height = str(image.get("height") or image.get("declared_height") or "")
        return (
            parsed.hostname == "imgcdn.yicai.com"
            and parsed.path.startswith("/uppics/images/2019/10/")
            and width == "500"
            and height == "87"
            and not image.get("alt")
            and not image.get("caption")
        )

    banners = {
        str(image.get("url") or image.get("resolved_url"))
        for image in images
        if section_banner(image)
    }
    return [
        image
        for image in images
        if not is_editorial_template(image) and not (len(banners) >= 2 and section_banner(image))
    ]


def normalize_image_candidates(
    values: Iterable[object],
    base_url: str = "",
) -> list[str]:
    """处理：解析、过滤并稳定去重不可信图片候选。
    输入：
    - ``values``：待规范化、匹配或渲染的一组输入值。
    - ``base_url``：解析相对链接时使用的最终页面或 Feed 基准 URL。
    输出：“解析、过滤并稳定去重不可信图片候选”得到的字符串列表；
      顺序保持确定并可供下一步骤逐项处理。
    """
    candidates: list[str] = []
    seen: set[str] = set()
    for value in values:
        raw = str(value or "").strip()
        if not raw:
            continue
        resolved = urljoin(base_url, raw)
        parsed = urlsplit(resolved)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or is_placeholder_image_url(resolved)
            or is_editorial_template({"url": resolved})
            or resolved in seen
        ):
            continue
        seen.add(resolved)
        candidates.append(resolved)
    return candidates


def image_variant_key(url: str) -> tuple:
    """处理：仅依据明确的原图路径和发布者尺寸变换归并同照片版本。
    输入：原图片 URL；签名、未知参数和显式编辑裁切继续参与身份。
    输出：同原图自动缩放或已知缩略图共享的键，其他地址保持独立。
    """
    parsed = urlsplit(url)
    host = (parsed.hostname or "").casefold()
    path = parsed.path
    query = tuple(parse_qsl(parsed.query, keep_blank_values=True))
    if path == "/_next/image":
        parameters = dict(query)
        original = urljoin(url, parameters.get("url", ""))
        original_parts = urlsplit(original)
        if (original_parts.scheme in {"http", "https"} and original_parts.path != "/_next/image"
                and not (parameters.keys() - {"url", "w", "q"})):
            return image_variant_key(original)
    if host == "blog.cloudflare.com" and path == "/_image":
        parameters = dict(query)
        original = parameters.get("href", "")
        original_parts = urlsplit(original)
        if (original_parts.scheme in {"http", "https"} and original_parts.path != "/_image"
                and parameters.get("position", "center") == "center"
                and not (parameters.keys() - {"href", "w", "h", "q", "f", "fit", "position"})):
            return image_variant_key(original)
    if host == "static.dw.com":
        match = re.fullmatch(r"/image/(\d+)_\d+\.(?:jpe?g|webp|png)", path, re.I)
        if match:
            return "dw-photo", host, match[1], query
    if host == "global.unitednations.entermediadb.net":
        match = re.fullmatch(r"(.+\.(?:jpe?g|png))/image\d+x\d+(?:cropped)?\.(?:jpe?g|png)", path)
        if match:
            return "un-photo", host, match[1], query
    if host == "cdn.defenseone.com":
        match = re.fullmatch(r"(.+/)(?:large|open-graph|thumb|\d+x\d+)\.jpg", path)
        if match:
            return "defense-photo", host, match[1], query
    if "/wp-content/uploads/" in path:
        match = re.fullmatch(r"(.+?)(?:-\d+x\d+)?\.(jpe?g|png|webp)", path, re.I)
        if match:
            return "wordpress-photo", host, match[1], match[2].lower(), query
    if host == "dam.mediacorp.sg" and "/image/upload/" in path:
        parts = path.split("/")
        for position, part in enumerate(parts):
            transforms = part.split(",")
            if any(re.match(r"(?:w|h|dpr)_\d", value) for value in transforms):
                if any(re.match(r"(?:x|y|a)_|c_crop|g_custom", value) for value in transforms):
                    return "url", url
                parts[position] = ""
        return "cloudinary-photo", host, "/".join(part for part in parts if part), query
    parameters = dict(query)
    if (host in _RESIZE_QUERY_HOSTS and _SIZE_QUERY_KEYS & parameters.keys()
            and not {"rect", "crop", "x", "y", "focal", "fp-x", "fp-y"} & parameters.keys()):
        width = _image_dimension(parameters.get("w") or parameters.get("width"))
        height = _image_dimension(parameters.get("h") or parameters.get("height"))
        # 普通尺寸查询只合并等比版本，保留不同构图与所有非尺寸参数。
        ratio = round(width / height, 2) if width and height else None
        return ("query-resize", host, path, ratio,
                tuple((key, value) for key, value in query if key not in _RESIZE_QUERY_KEYS))
    return "url", url


def _image_dimension(value: object) -> float:
    """处理：读取候选已声明的正数像素或密度，忽略百分比和未知值。
    输入：图片尺寸或 srcset 描述符的数值。
    输出：可比较的正数，未声明时为零。
    """
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return 0
    return number if number > 0 and math.isfinite(number) else 0


def _image_pixels(image: dict) -> float:
    """处理：先用实际宽高排序，再使用响应式声明和明确的 URL 尺寸。
    输入：图片元数据；未知 large/thumb 名称不冒充已知高分辨率。
    输出：像素面积或宽度平方，WordPress 未缩放原图排在未下载派生图之前。
    """
    width, height = _image_dimension(image.get("width")), _image_dimension(image.get("height"))
    if width and height:
        return width * height
    parsed = urlsplit(str(image.get("url") or image.get("resolved_url") or ""))
    dimensions = re.search(r"(?:image|-|/)(\d+)x(\d+)(?:cropped)?\.[a-z]+$", parsed.path, re.I)
    if dimensions:
        return float(dimensions[1]) * float(dimensions[2])
    if "/wp-content/uploads/" in parsed.path:
        return math.inf
    query = parse_qs(parsed.query)
    width = _image_dimension((query.get("width") or query.get("w") or [0])[0])
    height = _image_dimension((query.get("height") or query.get("h") or [0])[0])
    density = _image_dimension((query.get("dpr") or [1])[0]) or 1
    width = _image_dimension(image.get("pixel_width")) or width * density
    height *= density
    if width:
        return width * (height or width)
    width = _image_dimension(image.get("declared_width"))
    height = _image_dimension(image.get("declared_height"))
    density = _image_dimension(image.get("pixel_density")) or 1
    return (width * (height or width) or density) * density


def image_variant_groups(images: list[dict]) -> list[list[dict]]:
    """处理：按原图稳定分组，组内优先实际或声明分辨率较高的候选。
    输入：采集、下载或旧 deck 的图片详情；明确 srcset 组可补充同图关系。
    输出：每组保留全部地址供失败回退，组间原始新闻图片顺序保持稳定。
    """
    groups = {}
    for image in images:
        url = str(image.get("url") or image.get("resolved_url") or image.get("source_url") or "")
        key = image_variant_key(url)
        if key[0] == "url" and image.get("responsive_group"):
            key = "responsive", image["responsive_group"]
        groups.setdefault(key, []).append(image)
    return [sorted(group, key=_image_pixels, reverse=True) for group in groups.values()]


def _available_image_rank(image: dict, data_dir: Path | None) -> tuple[bool, float]:
    """处理：最终展示先选实际可读的本地图，再比较分辨率。
    输入：候选元数据与可选数据根；远程未知原图仅参与下载排序。
    输出：可用性和像素排序键，不发起网络请求。
    """
    value = image.get("local_path")
    available = bool(value)
    if value and data_dir:
        try:
            path = (data_dir / value).resolve()
            path.relative_to(data_dir.resolve())
            available = path.is_file()
        except ValueError:
            available = False
    return available, _image_pixels(image)


def select_image_variants(images: list[dict], *, data_dir: Path | None = None) -> list[dict]:
    """处理：每张原图仅保留最高分辨率，补齐同组已存在的图注和来源信息。
    输入：带实际或声明尺寸的图片详情，数据根供本地像素复核使用。
    输出：稳定原图顺序的高清图片副本，不改写或清理任何缓存文件。
    """
    from PIL import ImageChops, ImageStat

    groups = []
    previews = []
    for variants in image_variant_groups(images):
        variants = sorted(
            variants, key=lambda row: _available_image_rank(row, data_dir), reverse=True,
        )
        image = variants[0]
        preview = _photo_preview(image, data_dir) if data_dir else None
        match = None
        for position, known in enumerate(groups):
            if image.get("sha256") and image["sha256"] == known[0].get("sha256"):
                match = position
                break
            prior = previews[position]
            if preview is None or prior is None or abs(preview[0] / prior[0] - 1) > 0.01:
                continue
            difference = ImageChops.difference(preview[1], prior[1])
            if (max(ImageStat.Stat(difference).mean) <= 1.5
                    and max(high for _low, high in difference.getextrema()) <= 18):
                match = position
                break
        if match is None:
            groups.append(variants)
            previews.append(preview)
        else:
            groups[match].extend(variants)
            if (_available_image_rank(image, data_dir)
                    > _available_image_rank(groups[match][0], data_dir)):
                groups[match].remove(image)
                groups[match].insert(0, image)
                previews[match] = preview
    selected = []
    for group in groups:
        ordered = sorted(group, key=lambda row: _available_image_rank(row, data_dir),
                         reverse=True)
        image = dict(ordered[0])
        for alternate in ordered[1:]:
            for field in ("caption", "credit", "source_url", "alt", "surrounding_text"):
                if not image.get(field) and alternate.get(field):
                    image[field] = alternate[field]
        selected.append(image)
    return selected


def _photo_preview(image: dict, data_dir: Path):
    """处理：从本地已存照片提取同画幅像素样本，跳过图表、透明图和大片纯色。
    输入：图片元数据与数据根；只读取已有文件，不发起请求。
    输出：画幅与小幅 RGB 样本，用于保守合并改名后的同照片。
    """
    from PIL import Image, UnidentifiedImageError

    value = image.get("local_path")
    if not value or re.search(r"\b(?:chart|graph|plot|diagram)\b|图表|曲线|坐标", " ".join(
        str(image.get(field) or "") for field in ("alt", "caption", "url")
    ), re.I):
        return None
    try:
        path = (data_dir / value).resolve()
        path.relative_to(data_dir.resolve())
        with Image.open(path) as original:
            if "A" in original.getbands() or getattr(original, "is_animated", False):
                return None
            ratio = original.width / original.height
            original.draft("RGB", (128, 128))
            preview = original.convert("RGB").resize((64, 64), Image.Resampling.LANCZOS)
        pixels = preview.tobytes()
        colors = Counter((red // 16, green // 16, blue // 16) for red, green, blue in zip(
            pixels[::3], pixels[1::3], pixels[2::3], strict=True,
        ))
        if len(colors) < 256 or max(colors.values()) > 4096 * 0.12:
            return None
        return ratio, preview
    except (OSError, ValueError, UnidentifiedImageError):
        return None


def srcset_image_variants(value: object) -> list[dict]:
    """处理：解析响应式图片描述符，在同一单位内优先返回较大图片。
    输入：页面或 Feed 中不可信的 srcset 属性；无描述符按 1x 处理。
    输出：地址及像素宽度或密度；非法描述符丢弃，混用单位时保留组间顺序。
    """
    groups: dict[str, list[tuple[float, str]]] = {}
    # URL 本身可能含逗号；先读到空白，再解析描述符，避免拆坏 CDN 查询或 data URL。
    remaining = str(value or "")
    while remaining := remaining.lstrip(" \t\n\r\f,"):
        match = re.match(r"[^\s]+", remaining)
        assert match is not None
        token = match.group()
        remaining = remaining[match.end() :]
        url = token.rstrip(",")
        descriptors: list[str] = []
        if not token.endswith(","):
            descriptor_text, _separator, remaining = remaining.partition(",")
            descriptors = descriptor_text.split()
        if not descriptors:
            unit, size = "x", 1.0
        elif len(descriptors) == 1 and re.fullmatch(r"[0-9]+w", descriptors[0]):
            unit, size = "w", float(descriptors[0][:-1])
        elif len(descriptors) == 1 and re.fullmatch(
            r"(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?x", descriptors[0]
        ):
            unit, size = "x", float(descriptors[0][:-1])
        else:
            continue
        if size > 0 and math.isfinite(size):
            groups.setdefault(unit, []).append((size, url))
    variants = {}
    for unit, entries in groups.items():
        for size, url in sorted(entries, key=lambda entry: -entry[0]):
            variants.setdefault(url, {
                "url": url, "pixel_width" if unit == "w" else "pixel_density": size,
            })
    return list(variants.values())


def srcset_candidates(value: object) -> list[str]:
    """处理：复用完整响应式描述符解析，只向旧调用方投影 URL。
    输入：页面或 Feed 中的 srcset 字段。
    输出：同单位内从高清到低清排列、稳定去重的候选地址。
    """
    return [entry["url"] for entry in srcset_image_variants(value)]

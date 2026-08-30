from __future__ import annotations

import math
from typing import Any


_DR_VALUES = {100, 200, 400}
_GRAIN_ROUGHNESS = {0: "off", 32: "weak", 64: "strong"}
_GRAIN_SIZE = {0: "off", 16: "small", 32: "large"}
_D_RANGE_PRIORITY_LEVEL = {1: "weak", 2: "strong", 3: "plus"}
_FILM_SIMULATIONS = {
    0: "provia",
    256: "studio-portrait",
    272: "studio-portrait-enhanced-saturation",
    288: "astia",
    304: "studio-portrait-increased-sharpness",
    512: "velvia",
    768: "studio-portrait-ex",
    1024: "velvia-legacy",
    1280: "pro-neg-std",
    1281: "pro-neg-hi",
    1536: "classic-chrome",
    1792: "eterna",
    2048: "classic-negative",
    2304: "eterna-bleach-bypass",
    2560: "nostalgic-neg",
    2816: "reala-ace",
}
_SATURATION_STEPS = {
    0: 0,
    128: 1,
    192: 3,
    224: 4,
    256: 2,
    384: -1,
    1024: -2,
    1216: -3,
    1248: -4,
}
_MONOCHROME_SATURATION = {
    512: "monochrome",
    768: "monochrome",
    769: "monochrome-red-filter",
    770: "monochrome-yellow-filter",
    771: "monochrome-green-filter",
    784: "sepia",
    1280: "acros",
    1281: "acros-red-filter",
    1282: "acros-yellow-filter",
    1283: "acros-green-filter",
}
_SHARPNESS_STEPS = {0: -4, 1: -3, 2: -2, 3: 0, 4: 2, 5: 3, 6: 4, 130: -1, 132: 1}
_NOISE_REDUCTION_STEPS = {
    0: 0,
    256: 2,
    384: 1,
    448: 3,
    480: 4,
    512: -2,
    640: -1,
    704: -3,
    736: -4,
}
_CHROME_LEVELS = {0: "off", 32: "weak", 64: "strong"}
_CONTRAST_LEVELS = {
    0: "normal",
    128: "medium-high",
    256: "high",
    384: "medium-low",
    512: "low",
    768: "low",
    32768: "film-simulation",
}


def _number(row: dict[str, object], key: str) -> float | None:
    value = row.get(key)
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def resolve_dynamic_range(row: dict[str, object]) -> tuple[int | None, str | None]:
    """Resolve the developed DR percentage without treating a missing tag as DR100."""

    for key in ("FujiFilm:DevelopmentDynamicRange", "FujiFilm:AutoDynamicRange"):
        value = _number(row, key)
        if value is not None and int(round(value)) in _DR_VALUES:
            return int(round(value)), key
    setting = _number(row, "FujiFilm:DynamicRangeSetting")
    legacy = {0x100: 100, 0x201: 400}
    if setting is not None and int(round(setting)) in legacy:
        return legacy[int(round(setting))], "FujiFilm:DynamicRangeSetting"
    return None, None


def decode_tone_control(value: object) -> float | None:
    """Decode Fuji's signed MakerNote unit into the camera's half-step UI value."""

    try:
        raw = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(raw):
        return None
    decoded = -raw / 16.0
    if not -2.0 <= decoded <= 4.0 or abs(decoded * 2 - round(decoded * 2)) > 1e-6:
        return None
    return decoded


def _grain_label(value: object, labels: dict[int, str]) -> tuple[int | None, str | None]:
    try:
        code = int(value)
    except (TypeError, ValueError):
        return None, None
    return (code, labels.get(code)) if code in labels else (code, None)


def _integer(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coded_value(value: object, labels: dict[int, Any]) -> dict[str, Any]:
    code = _integer(value)
    return {"code": code, "value": labels.get(code) if code is not None else None}


def _clarity(value: object) -> dict[str, Any]:
    code = _integer(value)
    step = code / 1000 if code is not None and -5000 <= code <= 5000 and code % 1000 == 0 else None
    return {"code": code, "step": step}


def fuji_rendering_intent(row: dict[str, object]) -> dict[str, Any]:
    dynamic_range, dynamic_range_source = resolve_dynamic_range(row)
    highlight = decode_tone_control(row.get("FujiFilm:HighlightTone"))
    shadow = decode_tone_control(row.get("FujiFilm:ShadowTone"))
    roughness_code, roughness = _grain_label(
        row.get("FujiFilm:GrainEffectRoughness"), _GRAIN_ROUGHNESS
    )
    size_code, size = _grain_label(row.get("FujiFilm:GrainEffectSize"), _GRAIN_SIZE)

    priority_mode_code = row.get("FujiFilm:DRangePriority")
    priority_level_code: object | None = None
    priority_level_source: str | None = None
    priority_mode: str | None = None
    if priority_mode_code == 0:
        priority_mode = "auto"
        for key in ("FujiFilm:DRangePriorityAuto", "FujiFilm:DRangePriorityFixed"):
            if row.get(key) is not None:
                priority_level_code = row[key]
                priority_level_source = key
                break
    elif priority_mode_code == 1:
        priority_mode = "fixed"
        for key in ("FujiFilm:DRangePriorityFixed", "FujiFilm:DRangePriorityAuto"):
            if row.get(key) is not None:
                priority_level_code = row[key]
                priority_level_source = key
                break
    try:
        priority_level_number = int(priority_level_code) if priority_level_code is not None else None
    except (TypeError, ValueError):
        priority_level_number = None

    priority_level = _D_RANGE_PRIORITY_LEVEL.get(priority_level_number)
    if dynamic_range is None and priority_level in ("weak", "strong", "plus"):
        dynamic_range = 200 if priority_level == "weak" else 400
        dynamic_range_source = f"inferred_from_{priority_level_source}"

    film = _coded_value(row.get("FujiFilm:FilmMode"), _FILM_SIMULATIONS)
    saturation = _coded_value(row.get("FujiFilm:Saturation"), _SATURATION_STEPS)
    monochrome = _coded_value(row.get("FujiFilm:Saturation"), _MONOCHROME_SATURATION)
    sharpness = _coded_value(row.get("FujiFilm:Sharpness"), _SHARPNESS_STEPS)
    noise_reduction = _coded_value(
        row.get("FujiFilm:NoiseReduction"), _NOISE_REDUCTION_STEPS
    )
    color_chrome = _coded_value(
        row.get("FujiFilm:ColorChromeEffect"), _CHROME_LEVELS
    )
    color_chrome_blue = _coded_value(
        row.get("FujiFilm:ColorChromeFXBlue"), _CHROME_LEVELS
    )
    contrast = _coded_value(row.get("FujiFilm:Contrast"), _CONTRAST_LEVELS)
    lmo_code = _integer(row.get("FujiFilm:LensModulationOptimizer"))

    return {
        "dynamic_range": {
            "percent": dynamic_range,
            "source": dynamic_range_source,
            "setting_code": row.get("FujiFilm:DynamicRangeSetting"),
            "priority_mode": priority_mode,
            "priority_level": priority_level,
            "priority_level_source": priority_level_source,
        },
        "tone_curve": {
            "highlight": highlight,
            "shadow": shadow,
            "unit": "fujifilm_camera_step",
            "source": "FujiFilm MakerNote",
        },
        "grain": {
            "enabled": roughness not in (None, "off"),
            "roughness": roughness,
            "roughness_code": roughness_code,
            "size": size,
            "size_code": size_code,
            "source": "FujiFilm MakerNote",
        },
        "creative": {
            "film_simulation": film,
            "color": {"code": saturation["code"], "step": saturation["value"]},
            "monochrome_mode": monochrome,
            "monochrome_warm_cool": _integer(row.get("FujiFilm:BWAdjustment")),
            "monochrome_magenta_green": _integer(
                row.get("FujiFilm:BWMagentaGreen")
            ),
            "color_chrome": color_chrome,
            "color_chrome_blue": color_chrome_blue,
            "clarity": _clarity(row.get("FujiFilm:Clarity")),
            "sharpness": {"code": sharpness["code"], "step": sharpness["value"]},
            "high_iso_noise_reduction": {
                "code": noise_reduction["code"],
                "step": noise_reduction["value"],
            },
            "contrast": contrast,
            "lens_modulation_optimizer": {
                "code": lmo_code,
                "enabled": lmo_code == 1 if lmo_code in (0, 1) else None,
            },
            "source": "FujiFilm MakerNote",
            "application_status": "record_only_until_calibrated",
        },
    }

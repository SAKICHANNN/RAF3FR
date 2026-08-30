from __future__ import annotations

from raf2hncs.fuji_rendering import (
    decode_tone_control,
    fuji_rendering_intent,
    resolve_dynamic_range,
)


def test_dynamic_range_prefers_development_value_for_manual_dr400() -> None:
    row = {
        "FujiFilm:DevelopmentDynamicRange": 400,
        "FujiFilm:DynamicRangeSetting": 1,
    }
    assert resolve_dynamic_range(row) == (400, "FujiFilm:DevelopmentDynamicRange")


def test_dynamic_range_uses_auto_result_and_never_defaults_missing_to_dr100() -> None:
    assert resolve_dynamic_range({"FujiFilm:AutoDynamicRange": 200}) == (
        200,
        "FujiFilm:AutoDynamicRange",
    )
    assert resolve_dynamic_range({}) == (None, None)


def test_tone_control_decodes_half_steps_and_rejects_unknown_values() -> None:
    assert decode_tone_control(32) == -2
    assert decode_tone_control(8) == -0.5
    assert decode_tone_control(-64) == 4
    assert decode_tone_control(7) is None


def test_rendering_intent_keeps_dr_tone_priority_and_grain_independent() -> None:
    intent = fuji_rendering_intent(
        {
            "FujiFilm:DevelopmentDynamicRange": 400,
            "FujiFilm:DynamicRangeSetting": 1,
            "FujiFilm:DRangePriority": 1,
            "FujiFilm:DRangePriorityFixed": 2,
            "FujiFilm:HighlightTone": 8,
            "FujiFilm:ShadowTone": -8,
            "FujiFilm:GrainEffectRoughness": 32,
            "FujiFilm:GrainEffectSize": 16,
        }
    )
    assert intent["dynamic_range"] == {
        "percent": 400,
        "source": "FujiFilm:DevelopmentDynamicRange",
        "setting_code": 1,
        "priority_mode": "fixed",
        "priority_level": "strong",
        "priority_level_source": "FujiFilm:DRangePriorityFixed",
    }
    assert intent["tone_curve"]["highlight"] == -0.5
    assert intent["tone_curve"]["shadow"] == 0.5
    assert intent["grain"]["enabled"] is True
    assert intent["grain"]["roughness"] == "weak"
    assert intent["grain"]["size"] == "small"


def test_d_range_priority_accepts_observed_gfx100rf_companion_tag_layout() -> None:
    weak = fuji_rendering_intent(
        {
            "FujiFilm:DRangePriority": 0,
            "FujiFilm:DRangePriorityFixed": 1,
        }
    )
    strong = fuji_rendering_intent(
        {
            "FujiFilm:DRangePriority": 1,
            "FujiFilm:DRangePriorityAuto": 2,
        }
    )
    assert weak["dynamic_range"]["percent"] == 200
    assert weak["dynamic_range"]["priority_mode"] == "auto"
    assert weak["dynamic_range"]["priority_level"] == "weak"
    assert strong["dynamic_range"]["percent"] == 400
    assert strong["dynamic_range"]["priority_mode"] == "fixed"
    assert strong["dynamic_range"]["priority_level"] == "strong"


def test_rendering_intent_decodes_complete_gfx100rf_creative_settings() -> None:
    intent = fuji_rendering_intent(
        {
            "FujiFilm:FilmMode": 2816,
            "FujiFilm:Saturation": 192,
            "FujiFilm:ColorChromeEffect": 64,
            "FujiFilm:ColorChromeFXBlue": 32,
            "FujiFilm:Clarity": -2000,
            "FujiFilm:Sharpness": 130,
            "FujiFilm:NoiseReduction": 736,
            "FujiFilm:Contrast": 0,
            "FujiFilm:LensModulationOptimizer": 1,
        }
    )["creative"]
    assert intent["film_simulation"] == {"code": 2816, "value": "reala-ace"}
    assert intent["color"] == {"code": 192, "step": 3}
    assert intent["color_chrome"] == {"code": 64, "value": "strong"}
    assert intent["color_chrome_blue"] == {"code": 32, "value": "weak"}
    assert intent["clarity"] == {"code": -2000, "step": -2}
    assert intent["sharpness"] == {"code": 130, "step": -1}
    assert intent["high_iso_noise_reduction"] == {"code": 736, "step": -4}
    assert intent["contrast"] == {"code": 0, "value": "normal"}
    assert intent["lens_modulation_optimizer"] == {"code": 1, "enabled": True}
    assert intent["application_status"] == "record_only_until_calibrated"


def test_rendering_intent_keeps_monochrome_tint_and_unknown_codes_without_guessing() -> None:
    intent = fuji_rendering_intent(
        {
            "FujiFilm:Saturation": 1281,
            "FujiFilm:BWAdjustment": 4,
            "FujiFilm:BWMagentaGreen": -3,
            "FujiFilm:FilmMode": 9999,
            "FujiFilm:Clarity": 250,
        }
    )["creative"]
    assert intent["monochrome_mode"] == {
        "code": 1281,
        "value": "acros-red-filter",
    }
    assert intent["monochrome_warm_cool"] == 4
    assert intent["monochrome_magenta_green"] == -3
    assert intent["film_simulation"] == {"code": 9999, "value": None}
    assert intent["clarity"] == {"code": 250, "step": None}

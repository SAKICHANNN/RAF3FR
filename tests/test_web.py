import io
import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from raf2hncs.web import (
    AppServer,
    MAX_RAF_BYTES,
    WebApp,
    parse_options,
    safe_stem,
)


def test_parse_options_preserves_safe_defaults() -> None:
    assert parse_options({}) == {
        "white_balance": "auto",
        "inverse_x2d_calibration": False,
        "iso_policy": "hnnr-stable",
        "sensor_mapping": "wb-adaptive-bootstrap",
        "donor_lens_correction": "neutralize",
        "distortion_model": "camera-jpeg",
        "distortion_strength": 1.0,
        "chromatic_aberration_strength": 1.0,
        "vignetting_strength": 0.0,
    }
    assert parse_options(
        {
            "white_balance": ["as-shot"],
            "inverse_x2d_calibration": ["false"],
            "iso_policy": ["hnnr-stable"],
            "sensor_mapping": ["d65-dnglab-bootstrap"],
            "donor_lens_correction": ["preserve"],
            "distortion_model": ["legacy-in-bounds"],
            "distortion_strength": ["-0.7"],
            "chromatic_aberration_strength": ["-1.3"],
            "vignetting_strength": ["-0.5"],
        }
    ) == {
        "white_balance": "as-shot",
        "inverse_x2d_calibration": False,
        "iso_policy": "hnnr-stable",
        "sensor_mapping": "d65-dnglab-bootstrap",
        "donor_lens_correction": "preserve",
        "distortion_model": "legacy-in-bounds",
        "distortion_strength": -0.7,
        "chromatic_aberration_strength": -1.3,
        "vignetting_strength": -0.5,
    }
    with pytest.raises(ValueError):
        parse_options({"white_balance": ["invalid"]})
    with pytest.raises(ValueError):
        parse_options({"donor_lens_correction": ["invalid"]})
    with pytest.raises(ValueError):
        parse_options({"distortion_model": ["invalid"]})
    with pytest.raises(ValueError):
        parse_options({"iso_policy": ["invalid"]})
    with pytest.raises(ValueError, match="between -2 and 2"):
        parse_options({"vignetting_strength": ["3"]})
    assert parse_options({"sensor_mapping": ["wb-adaptive-bootstrap"]})[
        "sensor_mapping"
    ] == "wb-adaptive-bootstrap"


def test_safe_stem_removes_path_and_shell_punctuation() -> None:
    assert safe_stem("../../DSCF 2166;$(bad).RAF") == "DSCF-2166-bad"
    assert safe_stem(".RAF") == "converted"


def test_receive_upload_streams_and_cleans_partial(tmp_path: Path) -> None:
    app = WebApp(tmp_path / "data")
    try:
        destination = tmp_path / "data" / "uploads" / "sample.RAF"
        app.receive_upload(io.BytesIO(b"abcdef"), 6, destination, MAX_RAF_BYTES)
        assert destination.read_bytes() == b"abcdef"
        with pytest.raises(ConnectionError):
            app.receive_upload(io.BytesIO(b"short"), 8, destination.with_name("broken.RAF"), MAX_RAF_BYTES)
        assert not destination.with_name("broken.RAF.upload").exists()
    finally:
        app.close()


def test_job_runs_converter_verifier_and_lens_profile(monkeypatch, tmp_path: Path) -> None:
    donor = tmp_path / "donor.3FR"
    donor.write_bytes(b"donor")
    monkeypatch.setattr(
        "raf2hncs.web.inspect_x2d",
        lambda path: SimpleNamespace(complete=True, model="X2D 100C"),
    )
    monkeypatch.setattr("raf2hncs.web.find_tool", lambda explicit, name: name)

    def fake_convert(source, donor_path, output, **options):
        assert source.read_bytes() == b"fake-raf"
        assert donor_path == donor.resolve()
        assert options["white_balance"] == "auto"
        assert options["inverse_x2d_calibration"] is False
        assert options["iso_policy"] == "hnnr-stable"
        assert options["donor_lens_correction"] == "neutralize"
        assert options["distortion_strength"] == 1.0
        assert options["chromatic_aberration_strength"] == 1.0
        assert options["vignetting_strength"] == 0.0
        output.write_bytes(b"converted")
        output.with_suffix(output.suffix + ".json").write_text("{}\n", encoding="utf-8")
        return {
            "source": {"metadata": {"make": "Fujifilm", "model": "GFX 100RF"}},
            "output": {"sha256": "output-hash"},
            "capture_metadata": {"capture_iso": 10000, "embedded_values": {"ISO": 12800}},
        }

    def fake_verify(donor_path, output):
        assert donor_path == donor.resolve()
        assert output.read_bytes() == b"converted"
        return {"verified": True}

    app = WebApp(
        tmp_path / "data",
        donor,
        converter=fake_convert,
        verifier=fake_verify,
        lens_extractor=lambda source, exiftool: {"lens": "35mm F4"},
    )
    try:
        record = app.create_job(
            io.BytesIO(b"fake-raf"),
            8,
            "DSCF2166.RAF",
            parse_options({}),
        )
        deadline = time.monotonic() + 5
        while app.job(record.id).stage not in ("complete", "failed") and time.monotonic() < deadline:
            time.sleep(0.01)
        completed = app.job(record.id)
        assert completed.stage == "complete", completed.error
        assert completed.summary["camera"] == "Fujifilm GFX 100RF"
        assert completed.summary["iso"] == 10000
        assert completed.kind == "conversion"
        assert app.artifact(record.id, "output").read_bytes() == b"converted"
        assert json.loads(app.artifact(record.id, "verification").read_text())["verified"] is True
        assert json.loads(app.artifact(record.id, "lens_profile").read_text())["lens"] == "35mm F4"

        restored = json.loads((tmp_path / "data" / "jobs" / record.id / "job.json").read_text())
        assert restored["stage"] == "complete"
    finally:
        app.close()


def test_job_rejects_wrong_extension_before_queue(monkeypatch, tmp_path: Path) -> None:
    donor = tmp_path / "donor.3FR"
    donor.write_bytes(b"donor")
    monkeypatch.setattr(
        "raf2hncs.web.inspect_x2d",
        lambda path: SimpleNamespace(complete=True, model="X2D 100C"),
    )
    app = WebApp(tmp_path / "data", donor)
    try:
        with pytest.raises(ValueError, match=".RAF"):
            app.create_job(io.BytesIO(b"jpeg"), 4, "not-raw.jpg", parse_options({}))
        assert app.state()["jobs"] == []
    finally:
        app.close()


def test_http_state_and_post_guard(tmp_path: Path) -> None:
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("ok", encoding="utf-8")
    app = WebApp(tmp_path / "data")
    server = AppServer(("127.0.0.1", 0), app, static_dir)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urlopen(base + "/api/state", timeout=2) as response:
            payload = json.load(response)
        assert payload["app"] == "raf2hncs"
        assert payload["version"] == "0.9.7"
        assert payload["donor"]["configured"] is False

        request = Request(base + "/api/jobs", data=b"fake", method="POST")
        request.add_header("X-Filename", "DSCF2166.RAF")
        with pytest.raises(HTTPError) as raised:
            urlopen(request, timeout=2)
        assert raised.value.code == 403
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        app.close()


def test_packaged_web_ui_has_accessible_core_controls() -> None:
    static_dir = Path(__file__).parents[1] / "src" / "raf2hncs" / "web_static"
    html = (static_dir / "index.html").read_text(encoding="utf-8")
    javascript = (static_dir / "app.js").read_text(encoding="utf-8")
    css = (static_dir / "app.css").read_text(encoding="utf-8")
    assert 'lang="zh-CN"' in html
    assert 'id="raf-input"' in html
    assert 'id="donor-input"' in html
    assert 'id="tiff-input"' not in html
    assert 'id="lens-profile"' not in html
    assert 'id="correct-distortion"' in html
    assert 'id="correct-vignetting"' in html
    assert 'id="correct-distortion" type="checkbox" checked' in html
    assert 'id="correct-vignetting" type="checkbox" checked' not in html
    assert 'id="correct-ca" type="checkbox" checked' in html
    assert 'id="correct-ca"' in html
    assert html.count('type="range" min="-200" max="200"') == 3
    assert 'id="correct-defringe"' not in html
    assert 'id="inverse-calibration" type="checkbox">' in html
    assert 'aria-live="polite"' in html
    assert 'name="white-balance"' in html
    assert 'id="settings-dialog"' in html
    assert 'id="container-status"' in html
    assert 'id="language-toggle"' in html
    assert 'data-i18n="convertRaw"' in html
    assert 'class="product-grid"' in html
    assert 'class="intro"' not in html
    assert "科学选项" not in html
    assert "可核验的 3FR" not in html
    assert "prefers-reduced-motion" in css
    assert "@media (max-width: 520px)" in css
    assert 'textContent = job.filename' in javascript
    assert "X-RAF2HNCS-Request" in javascript
    assert "/api/lens-jobs" not in javascript
    assert "profile_job_id" not in javascript
    assert "chromatic_aberration_strength" in javascript
    assert "TIFF" not in html
    assert "可以开始转换" in javascript
    assert "showModal" in javascript
    assert 'stage: "receiving"' in javascript
    assert 'localStorage.setItem("raf3fr-language"' in javascript
    assert 'document.documentElement.lang' in javascript

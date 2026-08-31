"""Loopback-only Web application for the local raf2hncs converter."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import threading
import traceback
import uuid
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, unquote, urlparse

from .lens import extract_fuji_lens_profile
from .tiff import inspect_x2d
from .transplant import convert, find_tool, sha256, verify, x2d_q16_profile


MAX_RAF_BYTES = 256 * 1024 * 1024
MAX_DONOR_BYTES = 256 * 1024 * 1024
READ_CHUNK = 1024 * 1024
STAGES = (
    "queued",
    "receiving",
    "converting",
    "verifying",
    "lens_profile",
    "complete",
    "failed",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def safe_stem(filename: str) -> str:
    stem = Path(filename).stem.strip()
    if stem.lower() in ("", ".raf"):
        return "converted"
    stem = re.sub(r"[^\w.-]+", "-", stem, flags=re.UNICODE).strip(".-")
    return stem[:80] or "converted"


def atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".partial")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    with temporary.open("rb") as handle:
        os.fsync(handle.fileno())
    os.replace(temporary, path)


@dataclass
class JobRecord:
    id: str
    filename: str
    stage: str
    created_at: str
    updated_at: str
    options: dict[str, object]
    kind: str = "conversion"
    message: str = "等待转换"
    error: str | None = None
    artifacts: dict[str, str] = field(default_factory=dict)
    summary: dict[str, object] = field(default_factory=dict)


class WebApp:
    """Owns server paths, jobs, and the single conversion worker."""

    def __init__(
        self,
        data_dir: Path,
        donor: Path | None = None,
        *,
        converter: Callable[..., dict[str, object]] = convert,
        verifier: Callable[[Path, Path], dict[str, object]] = verify,
        lens_extractor: Callable[[Path, str], dict[str, object]] = extract_fuji_lens_profile,
    ) -> None:
        self.data_dir = data_dir.expanduser().resolve()
        self.upload_dir = self.data_dir / "uploads"
        self.job_dir = self.data_dir / "jobs"
        self.donor_dir = self.data_dir / "donors"
        for directory in (self.upload_dir, self.job_dir, self.donor_dir):
            directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="raf2hncs")
        self._jobs: dict[str, JobRecord] = {}
        self._converter = converter
        self._verifier = verifier
        self._lens_extractor = lens_extractor
        self._donor: Path | None = None
        if donor is not None:
            self.set_donor(donor)
        else:
            self._load_config()
        self._load_jobs()

    @property
    def config_path(self) -> Path:
        return self.data_dir / "config.json"

    @property
    def donor(self) -> Path | None:
        with self._lock:
            return self._donor

    def _load_config(self) -> None:
        if not self.config_path.is_file():
            return
        try:
            value = json.loads(self.config_path.read_text(encoding="utf-8")).get("donor")
            candidate = Path(value).resolve() if isinstance(value, str) else None
            if candidate is not None and candidate.is_file():
                inspect_x2d(candidate)
                self._donor = candidate
        except (OSError, ValueError, json.JSONDecodeError):
            self._donor = None

    def _load_jobs(self) -> None:
        for path in sorted(self.job_dir.glob("*/job.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                record = JobRecord(**payload)
                if record.stage not in STAGES:
                    continue
                if record.stage not in ("complete", "failed"):
                    record.stage = "failed"
                    record.message = "服务上次退出时任务未完成"
                    record.error = "interrupted"
                    record.updated_at = utc_now()
                    atomic_json(path, asdict(record))
                self._jobs[record.id] = record
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                continue

    def set_donor(self, path: Path) -> dict[str, object]:
        candidate = path.expanduser().resolve()
        if not candidate.is_file() or candidate.suffix.lower() != ".3fr":
            raise ValueError("供体必须是存在的 .3FR 文件")
        layout = inspect_x2d(candidate)
        if not layout.complete or layout.model != "X2D 100C":
            raise ValueError("供体必须是完整的 X2D 100C 3FR")
        with self._lock:
            self._donor = candidate
            atomic_json(self.config_path, {"donor": str(candidate), "sha256": sha256(candidate)})
        return self.donor_info()

    def donor_info(self) -> dict[str, object]:
        donor = self.donor
        if donor is None:
            return {"configured": False}
        layout = inspect_x2d(donor)
        try:
            cohort, profile = x2d_q16_profile(layout)
        except ValueError:
            cohort, profile = None, None
        return {
            "configured": True,
            "name": donor.name,
            "size": donor.stat().st_size,
            "sha256": sha256(donor),
            "software": getattr(layout, "software", None),
            "calibration_cohort": cohort,
            "inverse_calibration_supported": profile is not None,
            "inverse_q16_gains": profile["q16_gains"] if profile is not None else None,
        }

    def state(self) -> dict[str, object]:
        with self._lock:
            jobs = [asdict(item) for item in sorted(self._jobs.values(), key=lambda x: x.created_at, reverse=True)]
        return {
            "app": "raf2hncs",
            "version": "0.9.7",
            "donor": self.donor_info(),
            "defaults": {
                "white_balance": "auto",
                "inverse_x2d_calibration": False,
                "iso_policy": "hnnr-stable",
                "sensor_mapping": "wb-adaptive-bootstrap",
                "preview": "source",
                "donor_lens_correction": "neutralize",
                "distortion_model": "camera-jpeg",
                "lens_correction": {
                    "distortion_strength": 1.0,
                    "vignetting_strength": 0.0,
                    "chromatic_aberration_strength": 1.0,
                    "stage": "embedded in 3FR and applied inside Phocus",
                },
            },
            "jobs": jobs,
        }

    def close(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=False)

    def job(self, job_id: str) -> JobRecord:
        with self._lock:
            try:
                return self._jobs[job_id]
            except KeyError as error:
                raise FileNotFoundError(job_id) from error

    def _save_job(self, record: JobRecord) -> None:
        record.updated_at = utc_now()
        with self._lock:
            self._jobs[record.id] = record
            atomic_json(self.job_dir / record.id / "job.json", asdict(record))

    def receive_upload(self, stream, length: int, destination: Path, maximum: int) -> None:
        if length <= 0 or length > maximum:
            raise ValueError(f"文件大小必须在 1 到 {maximum // (1024 * 1024)} MB 之间")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + ".upload")
        if temporary.exists() or destination.exists():
            raise FileExistsError("上传目标已存在")
        remaining = length
        try:
            with temporary.open("xb") as handle:
                while remaining:
                    chunk = stream.read(min(READ_CHUNK, remaining))
                    if not chunk:
                        raise ConnectionError("上传在完成前中断")
                    handle.write(chunk)
                    remaining -= len(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

    def install_uploaded_donor(self, stream, length: int, filename: str) -> dict[str, object]:
        if Path(filename).suffix.lower() != ".3fr":
            raise ValueError("供体文件扩展名必须是 .3FR")
        destination = self.donor_dir / f"{uuid.uuid4().hex}.3FR"
        self.receive_upload(stream, length, destination, MAX_DONOR_BYTES)
        try:
            return self.set_donor(destination)
        except BaseException:
            destination.unlink(missing_ok=True)
            raise

    def create_job(self, stream, length: int, filename: str, options: dict[str, object]) -> JobRecord:
        if self.donor is None:
            raise ValueError("请先配置 X2D 100C 3FR 供体")
        if Path(filename).suffix.lower() != ".raf":
            raise ValueError("输入文件扩展名必须是 .RAF")
        job_id = uuid.uuid4().hex
        now = utc_now()
        record = JobRecord(
            id=job_id,
            filename=Path(filename).name,
            stage="receiving",
            created_at=now,
            updated_at=now,
            options=options,
            message="正在接收 RAW",
        )
        self._save_job(record)
        source = self.upload_dir / f"{job_id}.RAF"
        try:
            self.receive_upload(stream, length, source, MAX_RAF_BYTES)
        except BaseException as error:
            record.stage = "failed"
            record.message = "RAW 上传失败"
            record.error = str(error)
            self._save_job(record)
            raise
        record.stage = "queued"
        record.message = "已排队"
        self._save_job(record)
        self._executor.submit(self._run_job, record.id, source, self.donor)
        return record

    def _run_job(self, job_id: str, source: Path, donor: Path | None) -> None:
        record = self.job(job_id)
        job_path = self.job_dir / job_id
        output = job_path / f"{safe_stem(record.filename)}-HNCS.3FR"
        lens_path = job_path / f"{safe_stem(record.filename)}-lens.json"
        verify_path = job_path / "verification.json"
        try:
            if donor is None:
                raise ValueError("供体未配置")
            record.stage = "converting"
            record.message = "正在转换 Bayer RAW 与元数据"
            self._save_job(record)
            manifest = self._converter(
                source,
                donor,
                output,
                white_balance=str(record.options["white_balance"]),
                inverse_x2d_calibration=bool(record.options["inverse_x2d_calibration"]),
                iso_policy=str(record.options["iso_policy"]),
                sensor_mapping=str(record.options["sensor_mapping"]),
                preview="source",
                donor_lens_correction=str(record.options["donor_lens_correction"]),
                distortion_model=str(record.options["distortion_model"]),
                distortion_strength=float(record.options["distortion_strength"]),
                chromatic_aberration_strength=float(
                    record.options["chromatic_aberration_strength"]
                ),
                vignetting_strength=float(record.options["vignetting_strength"]),
            )
            record.stage = "verifying"
            record.message = "正在核验 3FR 结构与来源"
            self._save_job(record)
            verification = self._verifier(donor, output)
            atomic_json(verify_path, verification)
            record.stage = "lens_profile"
            record.message = "正在提取富士镜头配置"
            self._save_job(record)
            exiftool = find_tool(None, "exiftool")
            lens = self._lens_extractor(source, exiftool)
            atomic_json(lens_path, lens)
            record.artifacts = {
                "output": output.name,
                "manifest": output.name + ".json",
                "verification": verify_path.name,
                "lens_profile": lens_path.name,
            }
            source_meta = manifest.get("source", {}).get("metadata", {})
            record.summary = {
                "output_sha256": manifest.get("output", {}).get("sha256"),
                "camera": f"{source_meta.get('make', '')} {source_meta.get('model', '')}".strip(),
                "iso": manifest.get("capture_metadata", {}).get("capture_iso"),
                "phocus_model_iso": manifest.get("capture_metadata", {})
                .get("embedded_values", {})
                .get("ISO"),
                "white_balance": record.options["white_balance"],
                "inverse_x2d_calibration": record.options["inverse_x2d_calibration"],
                "sensor_mapping": record.options["sensor_mapping"],
                "donor_lens_correction": record.options["donor_lens_correction"],
                "lens_correction": manifest.get("lens_correction"),
                "lens": (
                    lens.get("lens", {}).get("model")
                    if isinstance(lens.get("lens"), dict)
                    else lens.get("lens")
                ),
                "profile_id": lens.get("profile_id"),
            }
            record.stage = "complete"
            record.message = "转换与核验完成"
            self._save_job(record)
        except BaseException as error:
            record.stage = "failed"
            record.message = "转换失败"
            record.error = str(error) or error.__class__.__name__
            record.summary = {"traceback": traceback.format_exc(limit=8)}
            self._save_job(record)

    def artifact(self, job_id: str, kind: str) -> Path:
        record = self.job(job_id)
        name = record.artifacts.get(kind)
        if name is None:
            raise FileNotFoundError(kind)
        candidate = (self.job_dir / job_id / name).resolve()
        parent = (self.job_dir / job_id).resolve()
        if candidate.parent != parent or not candidate.is_file():
            raise FileNotFoundError(kind)
        return candidate


class AppServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], app: WebApp, static_dir: Path):
        self.app = app
        self.static_dir = static_dir.resolve()
        super().__init__(address, AppRequestHandler)


class AppRequestHandler(BaseHTTPRequestHandler):
    server: AppServer
    protocol_version = "HTTP/1.1"

    def log_message(self, message: str, *args: object) -> None:
        print(f"[{self.log_date_time_string()}] {message % args}")

    def _json(self, status: int, payload: object) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, error: BaseException | str) -> None:
        self.close_connection = True
        self._json(status, {"error": str(error)})

    def _guard_post(self) -> None:
        if self.headers.get("X-RAF2HNCS-Request") != "1":
            raise PermissionError("missing localhost request marker")

    def _filename(self) -> str:
        value = self.headers.get("X-Filename")
        if not value:
            raise ValueError("missing filename")
        return Path(unquote(value)).name

    def _content_length(self) -> int:
        try:
            return int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise ValueError("invalid content length") from error

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/state":
                self._json(HTTPStatus.OK, self.server.app.state())
                return
            match = re.fullmatch(r"/api/jobs/([0-9a-f]{32})", parsed.path)
            if match:
                self._json(HTTPStatus.OK, asdict(self.server.app.job(match.group(1))))
                return
            match = re.fullmatch(r"/api/jobs/([0-9a-f]{32})/artifacts/([a-z_]+)", parsed.path)
            if match:
                self._send_file(self.server.app.artifact(match.group(1), match.group(2)), attachment=True)
                return
            relative = "index.html" if parsed.path == "/" else parsed.path.lstrip("/")
            if relative not in ("index.html", "app.css", "app.js"):
                raise FileNotFoundError(relative)
            self._send_file(self.server.static_dir / relative)
        except FileNotFoundError as error:
            self._error(HTTPStatus.NOT_FOUND, error)
        except BaseException as error:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, error)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            self._guard_post()
            if parsed.path == "/api/donor":
                result = self.server.app.install_uploaded_donor(
                    self.rfile, self._content_length(), self._filename()
                )
                self._json(HTTPStatus.CREATED, result)
                return
            if parsed.path == "/api/jobs":
                query = parse_qs(parsed.query)
                options = parse_options(query)
                record = self.server.app.create_job(
                    self.rfile, self._content_length(), self._filename(), options
                )
                self._json(HTTPStatus.ACCEPTED, asdict(record))
                return
            raise FileNotFoundError(parsed.path)
        except PermissionError as error:
            self._error(HTTPStatus.FORBIDDEN, error)
        except (ValueError, FileExistsError) as error:
            self._error(HTTPStatus.BAD_REQUEST, error)
        except FileNotFoundError as error:
            self._error(HTTPStatus.NOT_FOUND, error)
        except BaseException as error:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, error)

    def _send_file(self, path: Path, attachment: bool = False) -> None:
        if not path.is_file():
            raise FileNotFoundError(path.name)
        size = path.stat().st_size
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(size))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store" if attachment else "no-cache")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        )
        if attachment:
            self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
        self.end_headers()
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(READ_CHUNK)
                if not chunk:
                    break
                self.wfile.write(chunk)


def parse_options(query: dict[str, list[str]]) -> dict[str, object]:
    white_balance = query.get("white_balance", ["auto"])[0]
    sensor_mapping = query.get("sensor_mapping", ["wb-adaptive-bootstrap"])[0]
    inverse = query.get("inverse_x2d_calibration", ["false"])[0].lower()
    iso_policy = query.get("iso_policy", ["hnnr-stable"])[0]
    donor_lens_correction = query.get(
        "donor_lens_correction", ["neutralize"]
    )[0]
    distortion_model = query.get("distortion_model", ["camera-jpeg"])[0]

    def strength(name: str, default: float) -> float:
        try:
            value = float(query.get(name, [str(default)])[0])
        except ValueError as error:
            raise ValueError(f"invalid {name}") from error
        if not -2.0 <= value <= 2.0:
            raise ValueError(f"{name} must be between -2 and 2")
        return value
    if white_balance not in ("auto", "as-shot", "donor"):
        raise ValueError("invalid white balance")
    if sensor_mapping not in (
        "identity",
        "d65-dnglab-bootstrap",
        "wb-adaptive-bootstrap",
    ):
        raise ValueError("invalid sensor mapping")
    if inverse not in ("true", "false"):
        raise ValueError("invalid inverse calibration value")
    if iso_policy not in ("nearest-x2d", "hnnr-stable", "capture"):
        raise ValueError("invalid ISO policy")
    if donor_lens_correction not in ("neutralize", "preserve"):
        raise ValueError("invalid donor lens-correction value")
    if distortion_model not in ("camera-jpeg", "native-match", "legacy-in-bounds"):
        raise ValueError("invalid distortion model")
    return {
        "white_balance": white_balance,
        "inverse_x2d_calibration": inverse == "true",
        "iso_policy": iso_policy,
        "sensor_mapping": sensor_mapping,
        "donor_lens_correction": donor_lens_correction,
        "distortion_model": distortion_model,
        "distortion_strength": strength("distortion_strength", 1.0),
        "chromatic_aberration_strength": strength(
            "chromatic_aberration_strength", 1.0
        ),
        "vignetting_strength": strength("vignetting_strength", 0.0),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="raf2hncs-web")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path.home() / "Library" / "Application Support" / "raf2hncs-web",
    )
    parser.add_argument("--donor", type=Path)
    parser.add_argument("--no-browser", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit("refusing non-loopback host; use 127.0.0.1, localhost, or ::1")
    app = WebApp(args.data_dir, args.donor)
    static_dir = Path(__file__).with_name("web_static")
    server = AppServer((args.host, args.port), app, static_dir)
    url = f"http://{args.host}:{server.server_port}/"
    print(f"raf2hncs Web App: {url}")
    print(f"app data: {app.data_dir}")
    if not args.no_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        app.close()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas


PAGE_W, PAGE_H = A4
BG = HexColor("#111111")
PANEL = HexColor("#181818")
LINE = HexColor("#34312E")
ORANGE = HexColor("#F26A3D")
TEXT = HexColor("#F4F1EC")
MUTED = HexColor("#AAA39B")
FAINT = HexColor("#746E68")
VERSION = "0.9.6"


def register_fonts(project_root: Path) -> None:
    pdfmetrics.registerFont(TTFont("Outfit", str(project_root / "assets/fonts/Outfit-Variable.ttf")))
    pdfmetrics.registerFont(TTFont("ArialUnicode", "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"))


def choose(language: str, en: str, zh: str) -> str:
    return zh if language == "zh" else en


def font(language: str) -> str:
    return "ArialUnicode" if language == "zh" else "Outfit"


def wrap(text: str, face: str, size: float, width: float) -> list[str]:
    tokens = text.split(" ") if " " in text else list(text)
    separator = " " if " " in text else ""
    lines: list[str] = []
    current = ""
    for token in tokens:
        candidate = token if not current else current + separator + token
        if pdfmetrics.stringWidth(candidate, face, size) <= width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = token
    if current:
        lines.append(current)
    return lines


def paragraph(c: Canvas, text: str, x: float, y: float, width: float, *, face: str, size: float, color=TEXT, leading: float | None = None) -> float:
    leading = leading or size * 1.55
    c.setFont(face, size)
    c.setFillColor(color)
    for line in wrap(text, face, size, width):
        c.drawString(x, y, line)
        y -= leading
    return y


def header(c: Canvas, page: int, section_name: str, language: str) -> None:
    c.setFillColor(BG)
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    c.setFillColor(ORANGE)
    c.circle(40, PAGE_H - 38, 5, fill=1, stroke=0)
    c.setFont("Outfit", 8)
    c.setFillColor(TEXT)
    c.drawString(56, PAGE_H - 41, "RAF  /  3FR")
    c.setFillColor(FAINT)
    c.setFont(font(language), 8)
    c.drawRightString(PAGE_W - 40, PAGE_H - 41, section_name.upper() if language == "en" else section_name)
    c.setStrokeColor(LINE)
    c.line(40, PAGE_H - 56, PAGE_W - 40, PAGE_H - 56)
    c.setFont("Outfit", 7)
    c.setFillColor(FAINT)
    c.drawString(40, 28, "GFX 100RF  →  X2D 100C")
    c.drawRightString(PAGE_W - 40, 28, f"{VERSION}  ·  {page:02d}  ·  {language.upper()}")


def title(c: Canvas, language: str, en: str, zh: str, y: float) -> float:
    c.setFont(font(language), 25 if language == "en" else 22)
    c.setFillColor(TEXT)
    c.drawString(40, y, choose(language, en, zh))
    return y - 38


def section(c: Canvas, language: str, index: str, en: str, zh: str, y: float) -> float:
    c.setFont("Outfit", 8)
    c.setFillColor(ORANGE)
    c.drawString(40, y, index)
    c.setFont(font(language), 8.5)
    c.setFillColor(MUTED)
    c.drawString(68, y, choose(language, en.upper(), zh))
    return y - 21


def body(c: Canvas, language: str, en: str, zh: str, y: float, size: float = 10) -> float:
    return paragraph(c, choose(language, en, zh), 40, y, PAGE_W - 80, face=font(language), size=size, color=TEXT, leading=size * 1.65) - 16


def card(c: Canvas, language: str, y: float, en_title: str, zh_title: str, en_body: str, zh_body: str, height: float = 78) -> float:
    c.setFillColor(PANEL)
    c.setStrokeColor(LINE)
    c.rect(40, y - height, PAGE_W - 80, height, fill=1, stroke=1)
    c.setFont(font(language), 10)
    c.setFillColor(ORANGE)
    c.drawString(55, y - 22, choose(language, en_title, zh_title))
    paragraph(c, choose(language, en_body, zh_body), 55, y - 43, PAGE_W - 110, face=font(language), size=8.8, color=MUTED, leading=13)
    return y - height - 12


def build(output: Path, project_root: Path, language: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    register_fonts(project_root)
    c = Canvas(str(output), pagesize=A4, pageCompression=1)
    c.setTitle(choose(language, f"RAF / 3FR {VERSION} Quick Guide", f"RAF / 3FR {VERSION} 快速指南"))
    c.setAuthor("RAF / 3FR")

    header(c, 1, choose(language, "Quick guide", "快速指南"), language)
    c.setFillColor(ORANGE)
    c.rect(40, PAGE_H - 205, 5, 100, fill=1, stroke=0)
    c.setFillColor(TEXT)
    paragraph(c, choose(language, "RAW, thoughtfully handed over.", "将富士 RAW 交给 Phocus，保留可编辑空间。"), 62, PAGE_H - 135, PAGE_W - 110, face=font(language), size=33 if language == "en" else 26, leading=40)
    c.setFont("Outfit", 10)
    c.setFillColor(FAINT)
    c.drawString(62, PAGE_H - 199, f"RAF / 3FR  ·  macOS  ·  VERSION {VERSION}")
    y = PAGE_H - 260
    y = section(c, language, "01", "Purpose", "用途", y)
    y = body(c, language,
        "RAF / 3FR converts Fujifilm GFX100RF RAF files into X2D-style 3FR containers for editing in Hasselblad Phocus. The linear RAW payload remains the photographic source; optional rendering intent is stored in the editable Phocus sidecar.",
        "RAF / 3FR 将富士 GFX100RF 的 RAF 转换为可由 Hasselblad Phocus 编辑的 X2D 风格 3FR 容器。线性 RAW 始终是照片本体；可选的渲染意图写入可编辑的 Phocus 边车文件。", y)
    y = card(c, language, y, "DEFAULT", "默认", "HNNR-safe ISO, Fujifilm Auto WB, per-file exposure, distortion and chromatic-aberration correction on. Vignetting unchanged.", "默认使用 HNNR 安全 ISO、富士 Auto WB、逐文件曝光、畸变与色差矫正；暗角保持不变。")
    card(c, language, y, "NON-DESTRUCTIVE", "非破坏性", "Framing and rendering intent stay editable in Phocus. Exact metadata moves into standard or private XMP without replacing Hasselblad routing identity.", "构图与渲染意图在 Phocus 中保持可编辑；精确元数据写入标准或私有 XMP，不替换哈苏识别身份。")
    c.showPage()

    header(c, 2, choose(language, "Workflow", "使用流程"), language)
    y = title(c, language, "From RAF to Phocus", "从 RAF 到 Phocus", PAGE_H - 92)
    steps = [
        ("01", "Import RAF", "导入 RAF", "Drop one or more GFX100RF RAF files into the window.", "将一个或多个 GFX100RF RAF 拖入窗口。"),
        ("02", "Review capture", "确认拍摄信息", "Check the preview and open Full metadata for capture, rendering, framing, camera state and provenance.", "确认缩略图，并打开“完整元数据”查看拍摄、渲染、构图、相机状态与来源。"),
        ("03", "Choose corrections", "选择矫正", "Keep Camera JPEG match, choose Vendor RAW or Legacy no-blank-edge in Settings, or adjust lens strengths from -200% to +200%.", "保留“机内 JPEG 匹配”，在设置中选择“厂商 RAW”或“旧版无空边”，也可在 -200% 到 +200% 范围内调整镜头矫正强度。"),
        ("04", "Convert to 3FR", "转换为 3FR", "Choose an output folder. Batch jobs respect the CPU, RAM and parallel-task limits in Settings.", "选择输出文件夹。批量任务遵守设置中的 CPU、RAM 与并行任务上限。"),
        ("05", "Continue in Phocus", "在 Phocus 中继续", "Open the result in Phocus. The 3FR and its sibling .phos file belong together.", "在 Phocus 中打开结果。3FR 与同名 .phos 文件应始终放在一起。"),
    ]
    for index, en_t, zh_t, en_b, zh_b in steps:
        y = card(c, language, y, f"{index}  {en_t}", f"{index}  {zh_t}", en_b, zh_b, 82)
    c.showPage()

    header(c, 3, choose(language, "Controls", "转换选项"), language)
    y = title(c, language, "Conversion controls", "转换选项", PAGE_H - 92)
    y = section(c, language, "01", "White balance", "白平衡", y)
    y = body(c, language, "Auto uses the Fujifilm camera Auto WB measurement. As shot uses the RAF's selected shooting WB. Donor is diagnostic and preserves the X2D template neutral.", "Auto 使用富士相机测得的自动白平衡；拍摄值使用 RAF 中的拍摄白平衡；供体仅用于诊断并保留 X2D 模板中性点。", y, 9.4)
    y = section(c, language, "02", "Lens profile", "镜头配置", y)
    y = card(c, language, y, "DISTORTION MODEL", "畸变模型", "Camera JPEG match is the 0.9.6 default. Vendor RAW preserves the 0.9.5 native-render geometry; Legacy no-blank-edge preserves 0.9.3 framing.", "“机内 JPEG 匹配”是 0.9.6 默认值；“厂商 RAW”保留 0.9.5 原生渲染几何；“旧版无空边”保留 0.9.3 构图。", 76)
    y = card(c, language, y, "DISTORTION STRENGTH", "畸变强度", "+100% applies the selected model. 0% preserves the complete uncorrected framing; negative values reverse direction.", "+100% 应用所选模型；0% 保留完整未矫正视野；负值反向应用。", 66)
    y = card(c, language, y, "CHROMATIC ABERRATION", "色差", "The same signed scale applies independently to lateral chromatic aberration.", "横向色差使用相同的独立正负比例。", 70)
    y = card(c, language, y, "VIGNETTING", "暗角", "Default 0% preserves native vignetting. Positive values correct; negative values use pointwise falloff plus non-periodic noise compensation without frequency-split light halos.", "默认 0% 保留原生暗角；正值矫正；负值使用逐像素衰减与无周期噪声补偿，不再以频率拆分制造灯边暗圈。", 70)
    y = section(c, language, "03", "ISO and resources", "ISO 与资源", y)
    body(c, language, "HNNR-safe is the default and caps the Phocus-facing value at ISO 6400. Nearest X2D and capture ISO remain available but do not guarantee HNNR compatibility. Parallel jobs, CPU cores and RAM budget are separate controls.", "默认使用 HNNR 安全映射，并将 Phocus 侧数值限制在 ISO 6400；邻近 X2D 与拍摄 ISO 仍可选择，但不保证 HNNR 兼容。并行任务数、CPU 核心上限与 RAM 预算彼此独立。", y, 9.4)
    c.showPage()

    header(c, 4, choose(language, "Phocus rendering", "Phocus 渲染"), language)
    y = title(c, language, "Editable rendering intent", "可编辑的渲染意图", PAGE_H - 92)
    y = card(c, language, y, "EXPOSURE & DR  ·  DEFAULT ON", "曝光与 DR  ·  默认开启", "Per-file RawExposureBias becomes editable EV. DR100 / 200 / 400 map to 0 / 15 / 30 Highlight Recovery without scaling the RAW mosaic.", "逐文件 RawExposureBias 转成可编辑 EV；DR100 / 200 / 400 映射到 0 / 15 / 30 高光恢复，不缩放 RAW 马赛克。", 92)
    y = card(c, language, y, "TONE & GRAIN  ·  DEFAULT ON", "曲线与颗粒  ·  默认开启", "Fuji highlight/shadow steps become a master curve. Weak/Strong grain maps to Amount 20/40; Small/Large to Granularity 25/50. These remain bounded approximations.", "富士高光/阴影档位转成主曲线；弱/强颗粒映射到 20/40，小/大映射到 25/50。它们均为有边界的近似。", 102)
    y = card(c, language, y, "COLOR, CONTRAST & CLARITY", "色彩、反差与清晰度", "Camera steps map monotonically to zero-centered global Phocus adjustments. Film Simulation and Color Chrome identities remain recorded rather than being falsely reproduced.", "相机档位单调映射到以零为中心的 Phocus 全局调整。胶片模拟与彩色效果仅保留原值，不伪装成已复刻。", 98)
    card(c, language, y, "SHARPNESS & MONOCHROME", "锐度与黑白", "Conservative USM and neutral grayscale are editable. Forced NoiseFilterBias/CNFilter stays off; Fuji high-ISO NR and monochrome filter toning remain record-only.", "保守 USM 与中性黑白保持可编辑；强制 NoiseFilterBias/CNFilter 始终关闭。富士高 ISO 降噪与黑白滤镜色调仅记录。", 104)
    c.showPage()

    header(c, 5, choose(language, "Notes", "使用须知"), language)
    y = title(c, language, "Good to know", "使用须知", PAGE_H - 92)
    y = section(c, language, "01", "Keep both files", "保留两个文件", y)
    y = body(c, language, "The .3FR contains RAW and migrated capture metadata. The sibling .3FR.phos contains editable framing and rendering choices. Move or archive them together.", ".3FR 包含 RAW 与迁移后的拍摄元数据；同名 .3FR.phos 包含可编辑的构图与渲染选择。移动或归档时请一起保留。", y, 9.4)
    y = section(c, language, "02", "Claim boundary", "能力边界", y)
    y = body(c, language, "Opening in Phocus confirms container compatibility, not complete hidden HNCS identity. The Fuji-to-X2D sensor transform remains an experimental bootstrap until paired ColorChecker captures are available.", "能够在 Phocus 打开证明容器兼容，并不等于完整隐藏 HNCS 身份一致。在取得配对 ColorChecker 实拍前，富士到 X2D 的传感器变换仍是实验性 bootstrap。", y, 9.4)
    y = section(c, language, "03", "Privacy and metadata", "隐私与元数据", y)
    y = body(c, language, "Framing, GPS, rating/rights and Fujifilm provenance are independent Settings controls. Missing fields are never invented; serial and face data are always excluded.", "构图、GPS、评分/著作信息与富士来源记录均可独立控制。缺失字段不会补造；序列号与人脸数据始终排除。", y, 9.4)
    y = section(c, language, "04", "If something looks wrong", "出现异常时", y)
    y = card(c, language, y, "TOO DARK OR BRIGHT", "过暗或过亮", "Confirm Default exposure is set to Match Fujifilm rendering. Preserve linear RAW intentionally leaves Phocus at zero EV.", "确认“默认曝光”选择“匹配富士渲染”。“保留线性 RAW”会有意让 Phocus 保持 0 EV。", 80)
    y = card(c, language, y, "UNWANTED LOOK", "不想要的效果", "Disable DR, tone or grain independently in Settings, or remove the corresponding adjustment in Phocus.", "在设置中独立关闭 DR、曲线或颗粒，或直接在 Phocus 中移除相应调整。", 80)
    card(c, language, y, "FILES DO NOT MATCH", "文件未配对", "Place the .3FR.phos beside the identically named .3FR, then reopen the folder in Phocus.", "将同名 .3FR.phos 放回 .3FR 旁边，再在 Phocus 中重新打开文件夹。", 80)
    c.setFont("Outfit", 7)
    c.setFillColor(FAINT)
    c.drawString(40, 58, "Sources: fujifilm-dsc.com  ·  exiftool.org  ·  hasselblad.com/phocus")
    c.save()


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in {"en", "zh"}:
        raise SystemExit("usage: generate_macos_quick_guide.py {en|zh} OUTPUT.pdf")
    root = Path(__file__).resolve().parents[1]
    build(Path(sys.argv[2]).resolve(), root, sys.argv[1])

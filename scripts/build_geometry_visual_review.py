#!/usr/bin/env python3
"""Build a full-resolution split/blink review from a geometry report."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import cv2
import numpy as np


def full_resolution_matrix(pair: dict[str, object]) -> np.ndarray:
    matrix = np.asarray(pair["alignment"]["matrix_source_to_reference"], dtype=np.float64)
    evaluation_width, evaluation_height = pair["evaluation_size"]
    candidate_width, candidate_height = pair["candidate"]["full_size"]
    reference_width, reference_height = pair["reference"]["full_size"]
    candidate_to_evaluation = np.diag(
        [evaluation_width / candidate_width, evaluation_height / candidate_height]
    )
    evaluation_to_reference = np.diag(
        [reference_width / evaluation_width, reference_height / evaluation_height]
    )
    linear = evaluation_to_reference @ matrix[:, :2] @ candidate_to_evaluation
    translation = evaluation_to_reference @ matrix[:, 2]
    return np.column_stack((linear, translation))


def build_scene(pair: dict[str, object], output: Path) -> dict[str, object]:
    stem = str(pair["stem"])
    reference_path = Path(pair["reference"]["path"])
    candidate_path = Path(pair["candidate"]["path"])
    reference = cv2.imread(str(reference_path), cv2.IMREAD_COLOR)
    candidate = cv2.imread(str(candidate_path), cv2.IMREAD_COLOR)
    if reference is None or candidate is None:
        raise ValueError(f"cannot decode review pair for {stem}")
    matrix = full_resolution_matrix(pair)
    aligned = cv2.warpAffine(
        candidate,
        matrix,
        (reference.shape[1], reference.shape[0]),
        flags=cv2.INTER_LANCZOS4,
        borderMode=cv2.BORDER_REPLICATE,
    )
    reference_name = f"{stem}-camera.jpg"
    candidate_name = f"{stem}-candidate.jpg"
    shutil.copyfile(reference_path, output / reference_name)
    if not cv2.imwrite(
        str(output / candidate_name), aligned, [cv2.IMWRITE_JPEG_QUALITY, 96]
    ):
        raise ValueError(f"cannot write aligned candidate for {stem}")
    reference_edges_name = f"{stem}-camera-edges.png"
    candidate_edges_name = f"{stem}-candidate-edges.png"
    overlay_name = f"{stem}-edge-overlay.png"
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(16, 16))
    reference_contrast = clahe.apply(cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY))
    candidate_contrast = clahe.apply(cv2.cvtColor(aligned, cv2.COLOR_BGR2GRAY))
    reference_edges = cv2.Canny(
        cv2.GaussianBlur(reference_contrast, (5, 5), 0.9), 90, 210
    )
    candidate_edges = cv2.Canny(
        cv2.GaussianBlur(candidate_contrast, (5, 5), 0.9), 90, 210
    )
    if not cv2.imwrite(str(output / reference_edges_name), reference_edges):
        raise ValueError(f"cannot write reference edges for {stem}")
    if not cv2.imwrite(str(output / candidate_edges_name), candidate_edges):
        raise ValueError(f"cannot write candidate edges for {stem}")
    overlay = np.dstack(
        (
            np.maximum(reference_edges, candidate_edges),
            reference_edges,
            candidate_edges,
        )
    )
    if not cv2.imwrite(str(output / overlay_name), overlay):
        raise ValueError(f"cannot write edge overlay for {stem}")
    return {
        "stem": stem,
        "split": pair.get("split", "diagnostic"),
        "reference": reference_name,
        "candidate": candidate_name,
        "reference_edges": reference_edges_name,
        "candidate_edges": candidate_edges_name,
        "edge_overlay": overlay_name,
        "width": int(reference.shape[1]),
        "height": int(reference.shape[0]),
        "alignment_matrix": matrix.tolist(),
    }


HTML = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>RAF3FR geometry review</title><style>
:root{color-scheme:dark;font-family:Arial,sans-serif;background:#111;color:#eee}*{box-sizing:border-box}body{margin:0}.bar{height:68px;display:flex;gap:12px;align-items:center;padding:12px 20px;background:#1b1b1b;border-bottom:1px solid #333}.bar strong{margin-right:auto}.bar select,.bar button{background:#292929;color:#eee;border:1px solid #444;border-radius:3px;padding:9px 12px}.bar button.on{background:#c66b2b;border-color:#c66b2b}.stage{position:relative;height:calc(100vh - 112px);overflow:hidden;background:#080808}.stage img{position:absolute;max-width:none;user-select:none;pointer-events:none}.top{clip-path:inset(0 0 0 50%)}.divider{position:absolute;top:0;bottom:0;left:50%;width:1px;background:#f28b3a}.grid{position:absolute;inset:0;display:none;background-image:linear-gradient(#fff3 1px,transparent 1px),linear-gradient(90deg,#fff3 1px,transparent 1px);background-size:100px 100px}.foot{height:44px;padding:12px 20px;color:#aaa;font-size:13px}.range{width:180px}</style></head><body>
<div class="bar"><strong>Camera JPEG / Phocus candidate</strong><select id="scene"></select><select id="view"><option value="image">Image</option><option value="edges">Split edges</option><option value="overlay">Edge overlay</option></select><select id="region"><option value="full">Full frame</option><option value="tl">Top left 1:1</option><option value="tc">Top edge 1:1</option><option value="tr">Top right 1:1</option><option value="ml">Left edge 1:1</option><option value="c">Centre 1:1</option><option value="mr">Right edge 1:1</option><option value="bl">Bottom left 1:1</option><option value="bc">Bottom edge 1:1</option><option value="br">Bottom right 1:1</option></select><button id="blink">Blink</button><button id="grid">Grid</button><input class="range" id="split" type="range" min="0" max="100" value="50"></div>
<div class="stage" id="stage"><img id="base"><img id="top" class="top"><div id="divider" class="divider"></div><div id="gridLayer" class="grid"></div></div><div class="foot" id="note"></div>
<script src="scenes.js"></script><script>
const sceneEl=document.querySelector('#scene'),viewEl=document.querySelector('#view'),regionEl=document.querySelector('#region'),stage=document.querySelector('#stage'),base=document.querySelector('#base'),topImage=document.querySelector('#top'),divider=document.querySelector('#divider'),split=document.querySelector('#split'),note=document.querySelector('#note');let timer=null;
for(const s of scenes){const o=document.createElement('option');o.value=s.stem;o.textContent=`${s.stem} · ${s.split}`;sceneEl.appendChild(o)}
function position(){const s=scenes.find(v=>v.stem===sceneEl.value),region=regionEl.value,w=stage.clientWidth,h=stage.clientHeight;if(region==='full'){for(const img of [base,topImage]){img.style.width=w+'px';img.style.height=h+'px';img.style.objectFit='contain';img.style.left=0;img.style.top=0}return}const map={tl:[0,0],tc:[.5,0],tr:[1,0],ml:[0,.5],c:[.5,.5],mr:[1,.5],bl:[0,1],bc:[.5,1],br:[1,1]},p=map[region],left=-(s.width-w)*p[0],top=-(s.height-h)*p[1];for(const img of [base,topImage]){img.style.width=s.width+'px';img.style.height=s.height+'px';img.style.objectFit='fill';img.style.left=left+'px';img.style.top=top+'px'}}
function load(){const s=scenes.find(v=>v.stem===sceneEl.value),view=viewEl.value;if(view==='overlay'){base.src=s.edge_overlay;topImage.src=s.edge_overlay;topImage.style.clipPath='inset(0)';divider.style.display='none';split.style.visibility='hidden'}else{const edges=view==='edges';base.src=edges?s.reference_edges:s.reference;topImage.src=edges?s.candidate_edges:s.candidate;topImage.style.clipPath=`inset(0 0 0 ${split.value}%)`;divider.style.display='block';split.style.visibility='visible'}note.textContent=`${s.stem} · ${s.split} · centre-similarity alignment only · overlay: camera cyan, candidate magenta, agreement white`;Promise.all([base.decode(),topImage.decode()]).then(position)}
split.oninput=()=>{topImage.style.clipPath=`inset(0 0 0 ${split.value}%)`;divider.style.left=split.value+'%'};sceneEl.onchange=load;viewEl.onchange=load;regionEl.onchange=position;window.onresize=position;
document.querySelector('#grid').onclick=e=>{const g=document.querySelector('#gridLayer');g.style.display=g.style.display==='block'?'none':'block';e.currentTarget.classList.toggle('on')};document.querySelector('#blink').onclick=e=>{if(timer){clearInterval(timer);timer=null;topImage.style.visibility='visible'}else{timer=setInterval(()=>topImage.style.visibility=topImage.style.visibility==='hidden'?'visible':'hidden',450)}e.currentTarget.classList.toggle('on')};load();
</script></body></html>"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--splits", nargs="+", default=["holdout"])
    arguments = parser.parse_args()
    report = json.loads(arguments.report.read_text())
    arguments.output.mkdir(parents=True, exist_ok=True)
    scenes = [
        build_scene(pair, arguments.output)
        for pair in report["pairs"]
        if pair.get("split", "diagnostic") in arguments.splits
    ]
    if not scenes:
        raise SystemExit("no report pairs matched the requested splits")
    arguments.output.joinpath("scenes.js").write_text(
        "const scenes = " + json.dumps(scenes, ensure_ascii=False) + ";\n"
    )
    arguments.output.joinpath("index.html").write_text(HTML)


if __name__ == "__main__":
    main()

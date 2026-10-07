# -*- coding: utf-8 -*-
"""
AI 분리수거 도우미 스마트 쓰레기통 — 전처리·학습·추론 통합 파이프라인
(report/preprocess.md 의 1~11단계를 한 파일로 구현)

명령어
  calib-blur  : 예비 촬영 사진으로 블러 임계값(2) 보정
  build       : 1 얼굴 필터 → 2 품질 필터 → 3 중복 제거 → 4 라벨 검수 목록 → 5 세션 분할
  preview-aug : 9 데이터 증강 결과 미리보기
  train       : 6·7·8 전처리 → 9 증강 → 10 클래스 균형 → 11 정규화 → 학습 → KPI 평가 → TFLite INT8
  infer       : Raspberry Pi 실시간 추론 (초음파 감지 → 최선 프레임 → 추론 → Arduino)
  demo        : 가상 이미지로 build·preview-aug 동작 확인 (카메라·데이터 없이)

예시
  python code/preprocess_code.py calib-blur --raw data/calib/sharp --blurry data/calib/blurry
  python code/preprocess_code.py build --raw data/raw --out data/clean --blur-thr 100
  python code/preprocess_code.py preview-aug --image data/clean/train/can/xxx.jpg
  python code/preprocess_code.py train --data data/clean
  python code/preprocess_code.py infer --no-serial
  python code/preprocess_code.py demo

데이터 구조
  data/raw/<세션>/<클래스>/*.jpg      클래스: can, general, none, pet
  data/raw/<세션>/_review/*.jpg        판단이 애매한 사진 (학습 제외, 검수 목록 기록)
  data/raw/public_xxx/<클래스>/*.jpg   public_ 으로 시작하는 세션은 학습셋에만 사용

필요 패키지
  학습 PC : numpy opencv-python pillow imagehash albumentations>=2.0,<3 tensorflow>=2.15
  Pi      : numpy opencv-python ai-edge-litert pyserial   (+ sudo apt install v4l-utils)
"""
import argparse
import csv
import json
import platform
import random
import shutil
import subprocess
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

# =============================================================================
# 설정 (보고서 추천 파라미터) — 괄호 번호는 보고서 기법 번호
# =============================================================================
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent if HERE.name == "code" else HERE
IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}
REVIEW_DIR = "_review"


@dataclass
class Config:
    classes: list = field(default_factory=lambda: ["can", "general", "none", "pet"])  # 순서 = 모델 출력 순서
    # 1. 얼굴 필터
    face_conf: float = 0.5
    # 2. 품질 필터
    blur_thr: float = 100.0          # Laplacian 분산 (ROI를 448×448로 맞춘 뒤 계산)
    sharp_size: int = 448
    dark_thr: int = 40
    bright_thr: int = 220
    clip_ratio: float = 0.05
    # 3. 중복 제거
    hash_thr: int = 5
    # 5. 데이터 분할
    split_ratio: tuple = (0.70, 0.15, 0.15)
    split_seed: int = 42
    public_prefix: str = "public"
    # 6. ROI 크롭
    cam_w: int = 1280
    cam_h: int = 720
    roi: tuple = (280, 0, 720, 720)  # x, y, w, h : 배경판 위치
    # 7. 리사이즈
    input_size: int = 224
    # 8. CLAHE (선택)
    use_clahe: bool = False
    clahe_clip: float = 2.0
    clahe_tile: tuple = (8, 8)


# 학습
BATCH_SIZE, HEAD_EPOCHS, FT_EPOCHS, FT_LAYERS = 32, 10, 15, 40
HEAD_LR, FT_LR = 1e-3, 1e-5
KPI_ACC, KPI_CLASS_MIN = 0.90, 0.85

# 추론 (Raspberry Pi)
CLASS_TO_CMD = {"pet": "P", "can": "C", "general": "G"}
FLUSH_FRAMES, N_FRAMES = 3, 5
CONF_THR, MAX_RETRY, RETRY_WAIT, LID_OPEN_SEC = 0.7, 2, 1.0, 5.0
SERIAL_BAUD = 115200
# 자동 노출·WB 끄기. `v4l2-ctl -d /dev/video0 -l` 로 이름 확인 (구형 커널: exposure_auto, white_balance_temperature_auto)
V4L2_CONTROLS = {"auto_exposure": 1, "exposure_time_absolute": 200,
                 "white_balance_automatic": 0, "white_balance_temperature": 4500}


def save_config(cfg: Config, path: Path):
    path.write_text(json.dumps(asdict(cfg), ensure_ascii=False, indent=2), encoding="utf-8")


def load_config(path: Path) -> Config:
    """학습 때 저장한 전처리 설정을 추론에서 그대로 불러옵니다 (학습·추론 불일치 방지)."""
    d = json.loads(path.read_text(encoding="utf-8"))
    for k in ("split_ratio", "roi", "clahe_tile"):
        d[k] = tuple(d[k])
    return Config(**d)


# =============================================================================
# 공통 전처리 (6 → 7 → 8 → 11) — 학습·추론 모두 이 함수만 사용
# =============================================================================
def imread(path):
    """한글 경로에서도 동작하는 이미지 읽기 (Windows에서 cv2.imread는 한글 경로 실패)."""
    data = np.fromfile(str(path), dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None


def crop_roi(bgr, cfg: Config):
    """6. 카메라 원본은 배경판 좌표로, 다른 해상도(공개 데이터셋)는 중앙 정사각으로 크롭."""
    h, w = bgr.shape[:2]
    if (w, h) == (cfg.cam_w, cfg.cam_h):
        x, y, rw, rh = cfg.roi
        return bgr[y:y + rh, x:x + rw]
    s = min(h, w)
    y0, x0 = (h - s) // 2, (w - s) // 2
    return bgr[y0:y0 + s, x0:x0 + s]


def sharpness(bgr, cfg: Config) -> float:
    """2. Laplacian 분산. 해상도에 따라 값이 달라지므로 ROI를 고정 크기로 맞춘 뒤 계산."""
    roi = cv2.resize(crop_roi(bgr, cfg), (cfg.sharp_size, cfg.sharp_size), interpolation=cv2.INTER_AREA)
    return float(cv2.Laplacian(cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())


def exposure_issue(bgr, cfg: Config):
    """2. 노출 불량 사유 (정상이면 None)."""
    v = cv2.cvtColor(crop_roi(bgr, cfg), cv2.COLOR_BGR2HSV)[:, :, 2]
    if v.mean() < cfg.dark_thr:
        return "dark"
    if v.mean() > cfg.bright_thr:
        return "bright"
    if (v >= 255).mean() > cfg.clip_ratio:
        return "clipped"
    return None


def preprocess(bgr, cfg: Config):
    """6 → 7 → 8. BGR 원본 → RGB uint8 (224, 224, 3)."""
    rgb = cv2.cvtColor(crop_roi(bgr, cfg), cv2.COLOR_BGR2RGB)        # BGR→RGB 누락이 가장 흔한 버그
    rgb = cv2.resize(rgb, (cfg.input_size, cfg.input_size), interpolation=cv2.INTER_AREA)
    if cfg.use_clahe:                                                 # 8. L 채널에만 적용
        lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
        clahe = cv2.createCLAHE(clipLimit=cfg.clahe_clip, tileGridSize=cfg.clahe_tile)
        lab[:, :, 0] = clahe.apply(lab[:, :, 0])
        rgb = cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)
    return rgb


def normalize(rgb_batch):
    """11. Keras MobileNetV3는 모델 안에 전처리 층이 있어 0~255 그대로 입력 (/255 하면 이중 정규화)."""
    return rgb_batch.astype(np.float32)


# =============================================================================
# calib-blur : 블러 임계값 보정 (2)
# =============================================================================
def list_images(root: Path):
    return sorted(p for p in root.rglob("*") if p.suffix.lower() in IMG_EXTS)


def calibrate_blur_threshold(sharp_paths, blurry_paths, cfg: Config):
    s = np.array([sharpness(b, cfg) for p in sharp_paths if (b := imread(p)) is not None])
    if len(s) == 0:
        raise SystemExit("선명한 사진이 없습니다.")
    print(f"선명 {len(s)}장: 최소 {s.min():.1f} / 5% {np.percentile(s, 5):.1f} / 중앙 {np.median(s):.1f}")
    if blurry_paths:
        b = np.array([sharpness(x, cfg) for p in blurry_paths if (x := imread(p)) is not None])
        print(f"흐림 {len(b)}장: 95% {np.percentile(b, 95):.1f} / 최대 {b.max():.1f}")
        thr = (np.percentile(s, 5) + np.percentile(b, 95)) / 2
        if np.percentile(b, 95) >= np.percentile(s, 5):
            print("[경고] 선명·흐림 분포가 겹칩니다. 사진 분류를 다시 확인하세요.")
    else:
        thr = np.percentile(s, 5) * 0.9    # 선명한 사진의 95%가 통과하도록
    return float(thr)


# =============================================================================
# build : 1 얼굴 필터 → 2 품질 필터 → 3 중복 제거 → 4 라벨 검수 → 5 세션 분할
# =============================================================================
class FaceFilter:
    """1. res10 SSD가 있으면 DNN, 없으면 Haar Cascade(오검출 많음)."""

    def __init__(self, cfg: Config, model_dir: Path):
        self.cfg = cfg
        proto, weights = model_dir / "deploy.prototxt", model_dir / "res10_300x300_ssd_iter_140000.caffemodel"
        if proto.exists() and weights.exists():
            self.net, self.mode = cv2.dnn.readNetFromCaffe(str(proto), str(weights)), "dnn"
        else:
            print(f"[경고] {model_dir}에 res10 얼굴 모델이 없어 Haar Cascade로 대체합니다.")
            self.cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
            self.mode = "haar"

    def has_face(self, bgr) -> bool:          # 프라이버시 검사는 ROI가 아닌 원본 전체 대상
        if self.mode == "dnn":
            blob = cv2.dnn.blobFromImage(cv2.resize(bgr, (300, 300)), 1.0, (300, 300), (104.0, 177.0, 123.0))
            self.net.setInput(blob)
            return bool((self.net.forward()[0, 0, :, 2] >= self.cfg.face_conf).any())
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        scale = 640 / max(gray.shape[1], 640)  # 속도를 위해 가로 640으로 축소
        if scale < 1:
            gray = cv2.resize(gray, None, fx=scale, fy=scale)
        return len(self.cascade.detectMultiScale(gray, 1.1, 5, minSize=(24, 24))) > 0


def phash_bits(bgr, cfg: Config):
    """3. pHash 64비트 (ROI 기준)."""
    import imagehash
    from PIL import Image
    rgb = cv2.cvtColor(crop_roi(bgr, cfg), cv2.COLOR_BGR2RGB)
    return imagehash.phash(Image.fromarray(rgb)).hash.flatten()


def collect_raw(raw: Path, cfg: Config):
    items, review = [], []
    for session in sorted(p for p in raw.iterdir() if p.is_dir()):
        for cls_dir in sorted(p for p in session.iterdir() if p.is_dir()):
            files = sorted(f for f in cls_dir.iterdir() if f.suffix.lower() in IMG_EXTS)
            if cls_dir.name == REVIEW_DIR:
                review += [(session.name, f) for f in files]
            elif cls_dir.name in cfg.classes:
                items += [{"session": session.name, "cls": cls_dir.name, "path": f} for f in files]
            else:
                print(f"[경고] 알 수 없는 클래스 폴더 건너뜀: {cls_dir}")
    return items, review


def split_sessions(kept, cfg: Config):
    """5. 세션 단위 분할 — 같은 세션 사진이 학습·테스트에 나뉘지 않도록."""
    count = Counter(it["session"] for it in kept)
    public = [s for s in count if s.startswith(cfg.public_prefix)]
    onsite = [s for s in count if s not in public]
    if len(onsite) < 3:
        print(f"[경고] 현장 세션 {len(onsite)}개. 세션 단위 분할에는 최소 3개(권장 6개 이상) 필요")
    random.Random(cfg.split_seed).shuffle(onsite)
    onsite.sort(key=lambda s: -count[s])
    total, names = sum(count[s] for s in onsite), ("train", "val", "test")
    assigned, mapping = {n: 0 for n in names}, {s: "train" for s in public}
    for i, s in enumerate(onsite):
        target = names[i] if i < 3 else max(
            names, key=lambda n: cfg.split_ratio[names.index(n)] * total - assigned[n])
        mapping[s] = target
        assigned[target] += count[s]
    return mapping


def build_dataset(raw: Path, out: Path, cfg: Config, delete_faces=False):
    items, review = collect_raw(raw, cfg)
    if not items:
        raise SystemExit(f"이미지가 없습니다: {raw}/<세션>/<클래스>/")
    print(f"원본 {len(items)}장, 검수 대기(_review) {len(review)}장")

    face = FaceFilter(cfg, ROOT / "models" / "face")
    kept, rejected, conflicts = [], [], []
    kept_bits = np.zeros((0, 64), dtype=bool)

    for it in items:
        bgr = imread(it["path"])
        reason, detail = None, ""
        if bgr is None:
            reason = "unreadable"
        elif face.has_face(bgr):                                                    # 1
            reason = "face"
        else:
            it["sharp"] = sharp = sharpness(bgr, cfg)                                # 2
            # 공개 데이터셋: 이미 정제됨 + 해상도가 달라 품질 기준 미적용
            # 물체 없음(빈 배경판): 원래 질감이 없어 Laplacian 값이 낮으므로 블러 검사 제외
            public = it["session"].startswith(cfg.public_prefix)
            exp = None if public else exposure_issue(bgr, cfg)
            if not public and it["cls"] != "none" and sharp < cfg.blur_thr:
                reason, detail = "blur", f"{sharp:.1f}"
            elif exp:
                reason = exp
            else:                                                                   # 3
                bits = phash_bits(bgr, cfg)
                dist = np.count_nonzero(kept_bits != bits, axis=1)
                j = int(np.argmin(dist)) if len(dist) else -1
                if j >= 0 and dist[j] <= cfg.hash_thr:
                    other = kept[j]
                    if other["cls"] != it["cls"]:                                   # 4. 라벨 충돌
                        conflicts.append((it, other))
                    if sharp > other["sharp"]:                                      # 더 선명한 쪽 유지
                        rejected.append((other, "duplicate", f"→ {it['path'].name}"))
                        kept[j], kept_bits[j] = it, bits
                    else:
                        reason, detail = "duplicate", f"→ {other['path'].name}"
                else:
                    kept.append(it)
                    kept_bits = np.vstack([kept_bits, bits])
        if reason:
            rejected.append((it, reason, detail))

    reject_dir, report_dir = out.parent / "rejected", ROOT / "report" / "build"
    for d in (out, reject_dir):
        shutil.rmtree(d, ignore_errors=True)
    report_dir.mkdir(parents=True, exist_ok=True)

    mapping = split_sessions(kept, cfg)
    for it in kept:
        dst = out / mapping[it["session"]] / it["cls"]
        dst.mkdir(parents=True, exist_ok=True)
        shutil.copy2(it["path"], dst / f"{it['session']}__{it['path'].name}")

    n_face = 0
    for it, reason, _ in rejected:
        if reason == "face":                     # 얼굴 사진은 어디에도 복사하지 않음
            n_face += 1
            if delete_faces:
                it["path"].unlink(missing_ok=True)
            continue
        dst = reject_dir / reason
        dst.mkdir(parents=True, exist_ok=True)
        shutil.copy2(it["path"], dst / f"{it['session']}__{it['cls']}__{it['path'].name}")

    with open(report_dir / "manifest.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["path", "session", "class", "result", "detail"])
        for it in kept:
            w.writerow([it["path"], it["session"], it["cls"], f"kept:{mapping[it['session']]}", f"sharp={it['sharp']:.1f}"])
        for it, reason, detail in rejected:
            w.writerow([it["path"], it["session"], it["cls"], reason, detail])

    with open(report_dir / "label_review.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["type", "path", "class", "other_path", "other_class", "reviewer1", "reviewer2", "final"])
        for _, p in review:
            w.writerow(["경계 사례", p, "", "", "", "", "", ""])
        for a, b in conflicts:
            w.writerow(["라벨 충돌", a["path"], a["cls"], b["path"], b["cls"], "", "", ""])

    table = defaultdict(Counter)
    for it in kept:
        table[mapping[it["session"]]][it["cls"]] += 1
    summary = {
        "rejected": dict(Counter(r for _, r, _ in rejected).most_common()),
        "faces": f"{n_face} ({'raw에서 삭제' if delete_faces else '--delete-faces 로 삭제 권장'})",
        "sessions": dict(sorted(mapping.items())),
        "counts": {sp: {c: table[sp][c] for c in cfg.classes} for sp in ("train", "val", "test")},
        "label_review": f"{len(review) + len(conflicts)}건 → report/build/label_review.csv",
    }
    for sp in ("train", "val", "test"):
        missing = [c for c in cfg.classes if table[sp][c] == 0]
        if missing:
            print(f"[경고] {sp}에 없는 클래스 {missing} → 세션 추가 촬영 필요")
    return summary


# =============================================================================
# 9. 데이터 증강 (학습셋 전용, 정규화 전 0~255 이미지 기준, albumentations 2.x)
# =============================================================================
def build_train_aug(cfg: Config):
    import albumentations as A
    s, fill = cfg.input_size, 128   # 빈 영역은 회색 배경판처럼 채움 (반사 채우기는 물체가 복제되어 '여러 개'처럼 보임)
    return A.Compose([
        A.RandomResizedCrop(size=(s, s), scale=(0.7, 1.0), p=1.0),                              # 거리 변화
        A.RandomRotate90(p=0.5),                                                                # 놓는 방향
        A.Rotate(limit=30, border_mode=cv2.BORDER_CONSTANT, fill=fill, p=0.5),
        A.Perspective(scale=(0.02, 0.05), border_mode=cv2.BORDER_CONSTANT, fill=fill, p=0.3),  # 찌그러짐·각도
        A.RandomBrightnessContrast(brightness_limit=0.3, contrast_limit=0.3, p=0.8),           # 조명 변화
        A.RandomGamma(gamma_limit=(70, 150), p=0.3),
        A.HueSaturationValue(hue_shift_limit=8, sat_shift_limit=25, val_shift_limit=25, p=0.5),  # 색온도
        A.RandomShadow(shadow_intensity_range=(0.2, 0.4), p=0.3),                              # 역광·그림자
        A.MotionBlur(blur_limit=(3, 9), p=0.3),                                                 # 빠른 동작
        A.CoarseDropout(num_holes_range=(1, 1), hole_height_range=(0.3, 0.39),
                        hole_width_range=(0.3, 0.39), fill=fill, p=0.3),                       # 손 가림 9~15%
    ])


def preview_augment(image_path: Path, cfg: Config, out_path: Path):
    rgb = preprocess(imread(image_path), cfg)
    aug = build_train_aug(cfg)
    tiles = [rgb] + [aug(image=rgb)["image"] for _ in range(7)]
    grid = np.vstack([np.hstack(tiles[:4]), np.hstack(tiles[4:])])
    cv2.imencode(".jpg", cv2.cvtColor(grid, cv2.COLOR_RGB2BGR))[1].tofile(str(out_path))
    return out_path


# =============================================================================
# train : 학습 → KPI 평가 → TFLite INT8
# =============================================================================
class TFLiteClassifier:
    """TFLite 추론 래퍼 (학습 PC의 양자화 검증, Pi 추론 공용)."""

    def __init__(self, model_path, num_threads=4):
        try:
            from ai_edge_litert.interpreter import Interpreter
        except ImportError:
            try:
                from tflite_runtime.interpreter import Interpreter
            except ImportError:
                import tensorflow as tf
                Interpreter = tf.lite.Interpreter
        self.it = Interpreter(model_path=str(model_path), num_threads=num_threads)
        self.it.allocate_tensors()
        self.inp, self.out = self.it.get_input_details()[0], self.it.get_output_details()[0]

    def predict(self, rgb):
        x = normalize(rgb[None])                                    # 11
        scale, zp = self.inp["quantization"]
        if self.inp["dtype"] in (np.uint8, np.int8) and scale > 0:   # INT8 입력 양자화
            info = np.iinfo(self.inp["dtype"])
            x = np.clip(np.round(x / scale + zp), info.min, info.max).astype(self.inp["dtype"])
        self.it.set_tensor(self.inp["index"], x)
        self.it.invoke()
        y = self.it.get_tensor(self.out["index"])[0]
        scale, zp = self.out["quantization"]
        if self.out["dtype"] in (np.uint8, np.int8) and scale > 0:
            y = (y.astype(np.float32) - zp) * scale
        return y.astype(np.float32)


def load_split(data: Path, split: str, cfg: Config):
    """6→7→8 을 한 번만 적용해 메모리에 올림 (에폭마다 반복하지 않도록)."""
    xs, ys = [], []
    for ci, cls in enumerate(cfg.classes):
        d = data / split / cls
        for f in (sorted(d.iterdir()) if d.exists() else []):
            if f.suffix.lower() in IMG_EXTS and (bgr := imread(f)) is not None:
                xs.append(preprocess(bgr, cfg))
                ys.append(ci)
    x = np.stack(xs) if xs else np.zeros((0, cfg.input_size, cfg.input_size, 3), np.uint8)
    return x, np.array(ys, dtype=np.int32)


def per_class_report(y_true, y_pred, cfg: Config, title):
    k = len(cfg.classes)
    cm = np.zeros((k, k), dtype=int)
    for t, p in zip(y_true, y_pred):
        cm[t, p] += 1
    acc = float((y_true == y_pred).mean()) if len(y_true) else 0.0
    lines = [f"── {title} ──", f"전체 정확도: {acc:.3f}  (목표 {KPI_ACC})"]
    per = []
    for i, c in enumerate(cfg.classes):
        n = cm[i].sum()
        if n:
            per.append(cm[i, i] / n)
        lines.append(f"  {c:8s} {cm[i, i] / n if n else float('nan'):.3f}  ({cm[i, i]}/{n})")
    worst = min(per) if per else 0.0
    lines += [f"클래스별 최저: {worst:.3f}  (목표 {KPI_CLASS_MIN})",
              "혼동 행렬 (행=정답, 열=예측)  " + " ".join(f"{c[:4]:>5s}" for c in cfg.classes)]
    lines += [f"  {c:8s}" + " ".join(f"{v:5d}" for v in cm[i]) for i, c in enumerate(cfg.classes)]
    lines.append(f"KPI: {'통과' if acc >= KPI_ACC and worst >= KPI_CLASS_MIN else '미달'}")
    return "\n".join(lines)


def train(data: Path, cfg: Config, pretrained=True):
    import tensorflow as tf

    model_dir, report_dir = ROOT / "models", ROOT / "report"
    model_dir.mkdir(parents=True, exist_ok=True)
    (xtr, ytr), (xva, yva), (xte, yte) = (load_split(data, s, cfg) for s in ("train", "val", "test"))
    print(f"train {len(xtr)} / val {len(xva)} / test {len(xte)}")
    if len(xtr) == 0 or len(xva) == 0:
        raise SystemExit("학습/검증 데이터가 없습니다. build를 먼저 실행하세요.")

    # 10. 클래스 가중치 = 전체 / (클래스 수 × 클래스 장수)
    counts = np.bincount(ytr, minlength=len(cfg.classes))
    cw = {i: (len(ytr) / (len(cfg.classes) * n) if n else 0.0) for i, n in enumerate(counts)}
    print("클래스 가중치:", {cfg.classes[i]: round(w, 2) for i, w in cw.items()})

    aug = build_train_aug(cfg)
    Base = getattr(tf.keras.utils, "PyDataset", tf.keras.utils.Sequence)

    class Batches(Base):
        def __init__(self, x, y, augment=False):
            super().__init__()
            self.x, self.y, self.augment = x, y, augment
            self.idx = np.arange(len(x))
            self.on_epoch_end()

        def __len__(self):
            return int(np.ceil(len(self.x) / BATCH_SIZE))

        def __getitem__(self, i):
            b = self.idx[i * BATCH_SIZE:(i + 1) * BATCH_SIZE]
            imgs = self.x[b]
            if self.augment:                                         # 9 → 11 순서
                imgs = np.stack([aug(image=im)["image"] for im in imgs])
            return normalize(imgs), self.y[b]

        def on_epoch_end(self):
            if self.augment:
                np.random.shuffle(self.idx)

    base = tf.keras.applications.MobileNetV3Small(
        input_shape=(cfg.input_size, cfg.input_size, 3), include_top=False,
        weights="imagenet" if pretrained else None, include_preprocessing=True)   # 11. 모델 내장 정규화
    base.trainable = False
    inp = tf.keras.Input((cfg.input_size, cfg.input_size, 3))
    x = tf.keras.layers.GlobalAveragePooling2D()(base(inp, training=False))
    out = tf.keras.layers.Dense(len(cfg.classes), activation="softmax")(tf.keras.layers.Dropout(0.2)(x))
    model = tf.keras.Model(inp, out)

    tr, va = Batches(xtr, ytr, augment=True), Batches(xva, yva)
    stop = tf.keras.callbacks.EarlyStopping(monitor="val_loss", patience=5, restore_best_weights=True)
    loss = "sparse_categorical_crossentropy"

    model.compile(tf.keras.optimizers.Adam(HEAD_LR), loss, ["accuracy"])          # 1단계: 분류층만
    model.fit(tr, validation_data=va, epochs=HEAD_EPOCHS, class_weight=cw, callbacks=[stop])

    base.trainable = True                                                          # 2단계: 뒤쪽 미세조정
    for layer in base.layers[:-FT_LAYERS]:
        layer.trainable = False
    for layer in base.layers:
        if isinstance(layer, tf.keras.layers.BatchNormalization):                  # 소량 데이터 BN 보호
            layer.trainable = False
    model.compile(tf.keras.optimizers.Adam(FT_LR), loss, ["accuracy"])
    model.fit(tr, validation_data=va, epochs=FT_EPOCHS, class_weight=cw, callbacks=[stop])
    model.save(model_dir / "trash_cls.keras")

    xe, ye, name = (xte, yte, "test") if len(xte) else (xva, yva, "val(테스트셋 없음)")
    reports = [per_class_report(ye, model.predict(normalize(xe), verbose=0).argmax(1), cfg, f"Keras / {name}")]

    def representative():                                                          # 증강 없는 학습 이미지
        for i in np.random.permutation(len(xtr))[:200]:
            yield [normalize(xtr[i:i + 1])]

    conv = tf.lite.TFLiteConverter.from_keras_model(model)
    conv.optimizations = [tf.lite.Optimize.DEFAULT]
    conv.representative_dataset = representative
    conv.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    conv.inference_input_type = conv.inference_output_type = tf.uint8
    tfl = model_dir / "trash_cls_int8.tflite"
    tfl.write_bytes(conv.convert())
    save_config(cfg, model_dir / "preprocess.json")        # 추론이 같은 전처리 설정을 쓰도록 저장
    mb = tfl.stat().st_size / 1e6

    clf = TFLiteClassifier(tfl)                            # 양자화 후 정확도 재확인
    t0 = time.perf_counter()
    pred_q = np.array([clf.predict(im).argmax() for im in xe])
    ms = (time.perf_counter() - t0) / max(len(xe), 1) * 1000
    reports.append(per_class_report(ye, pred_q, cfg, f"TFLite INT8 / {name}"))
    reports.append(f"모델 크기 {mb:.2f} MB (목표 10MB 이하) / 이 PC 1장당 {ms:.1f} ms (Pi 4는 별도 측정)")
    text = "\n\n".join(reports)
    (report_dir / "eval.txt").write_text(text, encoding="utf-8")
    print("\n" + text)


# =============================================================================
# infer : Raspberry Pi 실시간 추론
#   Arduino → Pi : D (물체 감지)
#   Pi → Arduino : P/C/G (투입구 LED + 뚜껑), R (재시도 안내), X (취소)
# =============================================================================
class Camera:
    """한 번만 열고 계속 유지 (매번 열면 1초 이상 지연)."""

    def __init__(self, index, cfg: Config):
        self.cfg = cfg
        self.cap = cv2.VideoCapture(index, cv2.CAP_V4L2 if platform.system() == "Linux" else cv2.CAP_ANY)
        if not self.cap.isOpened():
            raise SystemExit("카메라를 열 수 없습니다.")
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, cfg.cam_w)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cfg.cam_h)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if platform.system() == "Linux":                       # 자동 노출·WB 끄기 (보고서 전제 조건)
            for k, v in V4L2_CONTROLS.items():
                r = subprocess.run(["v4l2-ctl", "-d", f"/dev/video{index}", f"--set-ctrl={k}={v}"],
                                   capture_output=True, text=True)
                if r.returncode:
                    print(f"[경고] 카메라 설정 실패 {k}={v}: {r.stderr.strip()}")
        for _ in range(10):
            self.cap.read()
        size = (int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        if size != (cfg.cam_w, cfg.cam_h):
            print(f"[경고] 카메라 해상도 {size} ≠ 학습 해상도 {(cfg.cam_w, cfg.cam_h)} → ROI 불일치")

    def capture_best(self):
        """버퍼 비우기 → N장 연속 촬영 → 가장 선명한 프레임 (2)."""
        for _ in range(FLUSH_FRAMES):
            self.cap.grab()
        best, best_score = None, -1.0
        for _ in range(N_FRAMES):
            ok, frame = self.cap.read()
            if ok and (score := sharpness(frame, self.cfg)) > best_score:
                best, best_score = frame, score
        return best, best_score


class ArduinoLink:
    def __init__(self, port):
        import serial
        self.ser = serial.Serial(port, SERIAL_BAUD, timeout=0.05)
        time.sleep(2)                       # 포트를 열면 Arduino가 리셋됨
        self.ser.reset_input_buffer()

    def wait_detect(self):
        while self.ser.readline().strip() != b"D":
            pass

    def send(self, cmd):
        self.ser.write(f"{cmd}\n".encode())

    def ignore_for(self, sec):              # 뚜껑 열린 동안 감지 신호 무시
        time.sleep(sec)
        self.ser.reset_input_buffer()


class KeyboardLink:
    def wait_detect(self):
        input("\n[Enter] 물체 감지 흉내 > ")

    def send(self, cmd):
        print(f"  → Arduino: {cmd}")

    def ignore_for(self, sec):
        pass


def classify_once(cam, clf, cfg: Config):
    frame, sharp = cam.capture_best()
    if frame is None:
        return None, 0.0, "camera", sharp
    rgb = preprocess(frame, cfg)
    del frame                                       # 원본 프레임 즉시 폐기 (저장 안 함)
    probs = clf.predict(rgb)
    idx = int(np.argmax(probs))
    label, conf = cfg.classes[idx], float(probs[idx])
    if label == "none":                             # 빈 배경은 원래 선명도가 낮으므로 블러보다 먼저 판정
        return None, conf, "none", sharp
    if sharp < cfg.blur_thr:                        # 물체는 있지만 흔들림
        return None, conf, "blur", sharp
    if conf < CONF_THR:
        return None, conf, "low_conf", sharp
    return label, conf, "", sharp


def run_inference(use_serial, port, cam_index):
    cfg_path = ROOT / "models" / "preprocess.json"
    cfg = load_config(cfg_path) if cfg_path.exists() else Config()
    if not cfg_path.exists():
        print("[경고] models/preprocess.json 이 없어 기본 설정 사용 (학습 때 설정과 다를 수 있음)")
    clf = TFLiteClassifier(ROOT / "models" / "trash_cls_int8.tflite")
    cam = Camera(cam_index, cfg)
    link = ArduinoLink(port) if use_serial else KeyboardLink()

    log_dir = ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / f"result_{datetime.now():%Y%m%d}.csv"
    is_new = not log_path.exists()
    with open(log_path, "a", newline="", encoding="utf-8-sig") as log:
        w = csv.writer(log)
        if is_new:
            w.writerow(["time", "result", "confidence", "attempts", "fallback", "fail_reasons",
                        "first_try_ms", "total_ms", "sharpness"])
        print(f"대기 중... (로그: {log_path})")
        try:
            while True:
                link.wait_detect()
                t0 = time.perf_counter()
                reasons, first_ms = [], None
                for attempt in range(1, MAX_RETRY + 2):          # 첫 시도 + 재시도 2회
                    result, conf, reason, sharp = classify_once(cam, clf, cfg)
                    first_ms = first_ms or (time.perf_counter() - t0) * 1000   # KPI: 2초 이내
                    if result:
                        break
                    reasons.append(reason)
                    if attempt <= MAX_RETRY:
                        link.send("R")                            # "다시 보여주세요"
                        time.sleep(RETRY_WAIT)
                fallback = False
                if result is None:
                    if all(r == "none" for r in reasons):         # 오감지 → 뚜껑 열지 않음
                        result = "cancel"
                        link.send("X")
                    else:                                         # 판별 실패 → 안전한 기본값
                        result, fallback = "general", True
                if result != "cancel":
                    link.send(CLASS_TO_CMD[result])
                total_ms = (time.perf_counter() - t0) * 1000
                w.writerow([datetime.now().isoformat(timespec="seconds"), result, f"{conf:.3f}", attempt,
                            fallback, "|".join(reasons), f"{first_ms:.0f}", f"{total_ms:.0f}", f"{sharp:.1f}"])
                log.flush()
                print(f"  {result} (신뢰도 {conf:.2f}, 시도 {attempt}회, 첫 판정 {first_ms:.0f} ms)")
                if result != "cancel":
                    link.ignore_for(LID_OPEN_SEC)
        except KeyboardInterrupt:
            print("\n종료")
        finally:
            cam.cap.release()


# =============================================================================
# demo : 가상 이미지로 build·preview-aug 동작 확인
# =============================================================================
def make_demo_data(raw: Path, cfg: Config, per_class=8):
    rng = np.random.default_rng(0)

    def draw(cls):
        img = (np.full((cfg.cam_h, cfg.cam_w, 3), 128.0) + rng.normal(0, 25, (cfg.cam_h, cfg.cam_w, 3)))
        img = img.clip(0, 255).astype(np.uint8)
        cx, cy = 640 + int(rng.integers(-150, 150)), 360 + int(rng.integers(-150, 150))
        col = tuple(int(v) for v in rng.integers(30, 230, 3))
        if cls == "pet":
            cv2.ellipse(img, (cx, cy), (60, 180), float(rng.integers(0, 180)), 0, 360, (200, 220, 230), -1)
            cv2.rectangle(img, (cx - 60, cy - 20), (cx + 60, cy + 20), col, -1)
        elif cls == "can":
            cv2.rectangle(img, (cx - 55, cy - 100), (cx + 55, cy + 100), col, -1)
        elif cls == "general":
            cv2.fillPoly(img, [(rng.integers(-120, 120, (7, 2)) + [cx, cy]).astype(np.int32)], col)
        for _ in range(200):
            p = (int(rng.integers(300, 980)), int(rng.integers(0, 720)))
            cv2.circle(img, p, int(rng.integers(2, 8)), tuple(int(v) for v in rng.integers(0, 255, 3)), -1)
        return img

    def write(path, img):
        path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imencode(".jpg", img)[1].tofile(str(path))

    for s in ["20261008_오전", "20261008_오후", "20261009_오전", "20261009_오후"]:
        for cls in cfg.classes:
            for i in range(per_class):
                img = draw(cls)
                write(raw / s / cls / f"{i:03d}.jpg", img)
            write(raw / s / cls / "dup.jpg", img)                                      # 중복
            write(raw / s / cls / "blur.jpg", cv2.GaussianBlur(img, (31, 31), 0))      # 흐림
            write(raw / s / cls / "dark.jpg", (img * 0.2).astype(np.uint8))            # 어두움
        write(raw / s / REVIEW_DIR / "cup.jpg", draw("pet"))                           # 경계 사례


# =============================================================================
# CLI
# =============================================================================
def main():
    ap = argparse.ArgumentParser(description="AI 분리수거 도우미 전처리·학습·추론 파이프라인")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("calib-blur", help="블러 임계값 보정")
    a.add_argument("--raw", required=True, help="선명한 사진 폴더")
    a.add_argument("--blurry", help="흐린 사진 폴더 (있으면 두 분포의 중간값)")

    b = sub.add_parser("build", help="1~5단계 데이터 정제·분할")
    b.add_argument("--raw", default=str(ROOT / "data" / "raw"))
    b.add_argument("--out", default=str(ROOT / "data" / "clean"))
    b.add_argument("--blur-thr", type=float, default=Config.blur_thr)
    b.add_argument("--roi", help="x,y,w,h (기본 280,0,720,720)")
    b.add_argument("--delete-faces", action="store_true", help="얼굴 검출 사진을 raw에서도 삭제")

    c = sub.add_parser("preview-aug", help="9단계 증강 미리보기")
    c.add_argument("--image", required=True)
    c.add_argument("--out", default="augment_preview.jpg")

    d = sub.add_parser("train", help="학습·평가·TFLite 변환")
    d.add_argument("--data", default=str(ROOT / "data" / "clean"))
    d.add_argument("--blur-thr", type=float, default=Config.blur_thr)
    d.add_argument("--roi", help="x,y,w,h")
    d.add_argument("--clahe", action="store_true", help="8. CLAHE 사용 (A/B 비교용)")
    d.add_argument("--no-pretrained", action="store_true", help="ImageNet 가중치 없이 (동작 테스트용)")

    e = sub.add_parser("infer", help="Raspberry Pi 실시간 추론")
    e.add_argument("--no-serial", action="store_true", help="Enter 키로 감지 흉내")
    e.add_argument("--port", default="/dev/ttyACM0")
    e.add_argument("--camera", type=int, default=0)

    sub.add_parser("demo", help="가상 이미지로 build·preview-aug 확인")
    args = ap.parse_args()

    cfg = Config()
    if getattr(args, "roi", None):
        cfg.roi = tuple(map(int, args.roi.split(",")))
    if getattr(args, "blur_thr", None) is not None:
        cfg.blur_thr = args.blur_thr

    if args.cmd == "calib-blur":
        thr = calibrate_blur_threshold(list_images(Path(args.raw)),
                                       list_images(Path(args.blurry)) if args.blurry else [], cfg)
        print(f"blur_thr = {thr:.1f}  (--raw 에 선명한 사진만 넣었는지 확인)")
    elif args.cmd == "build":
        print(json.dumps(build_dataset(Path(args.raw), Path(args.out), cfg, args.delete_faces),
                         ensure_ascii=False, indent=2))
    elif args.cmd == "preview-aug":
        print(f"{preview_augment(Path(args.image), cfg, Path(args.out))} 저장 (왼쪽 위가 원본)")
    elif args.cmd == "train":
        cfg.use_clahe = args.clahe
        train(Path(args.data), cfg, pretrained=not args.no_pretrained)
    elif args.cmd == "infer":
        run_inference(not args.no_serial, args.port, args.camera)
    elif args.cmd == "demo":
        demo = ROOT / "data" / "demo"
        shutil.rmtree(demo, ignore_errors=True)
        make_demo_data(demo / "raw", cfg)
        print(json.dumps(build_dataset(demo / "raw", demo / "clean", cfg), ensure_ascii=False, indent=2))
        sample = next((demo / "clean" / "train" / "can").glob("*.jpg"))
        print(f"{preview_augment(sample, cfg, demo / 'augment_preview.jpg')} 저장")


if __name__ == "__main__":
    main()
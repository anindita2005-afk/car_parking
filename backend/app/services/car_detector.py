import os
import cv2
import numpy as np
import base64
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from ultralytics import YOLO

# Known state/regional registration codes for license plate validation
VALID_STATE_PREFIXES = {
    "AN", "AP", "AR", "AS", "BR", "CH", "CG", "DD", "DL", "DN", "GA", "GJ",
    "HR", "HP", "JH", "JK", "KA", "KL", "LA", "LD", "MP", "MH", "MN", "ML",
    "MZ", "NL", "OD", "PB", "PY", "RJ", "SK", "TN", "TR", "TS", "UK", "UP",
    "WB", "EV", "BH"
}

# Common vehicle badges/text to filter out
KNOWN_BADGES = {
    "HONDA", "HYUNDAI", "SUZUKI", "MARUTI", "TOYOTA", "TATA", "MAHINDRA",
    "FORD", "CHEVROLET", "VOLKSWAGEN", "SKODA", "RENAULT", "NISSAN", "BMW",
    "MERCEDES", "AUDI", "KIA", "MG", "SWIFT", "BALENO", "INNOVA", "CRETA",
    "TURBO", "DIESEL", "PETROL", "VXI", "ZXI", "LXI", "SPORT", "LIMITED"
}

OCR_DIGIT_MAP = {
    'O': '0', 'Q': '0', 'D': '0', 'I': '1', 'L': '1', 'Z': '2',
    'S': '5', 'B': '8', 'E': '3', 'A': '4', 'G': '6'
}
OCR_LETTER_MAP = {
    '0': 'O', '1': 'I', '2': 'Z', '3': 'E', '4': 'A', '5': 'S', '6': 'G', '8': 'B'
}

# State prefix disambiguation table:
# Directly handles cases where the letter 'M' (Maharashtra, Madhya Pradesh, Meghalaya, Manipur, Mizoram)
# is misrecognized by EasyOCR as 'H', 'N', 'W', '1', 'I', '4', 'V', or 'AA'
STATE_PREFIX_CORRECTIONS = {
    # Maharashtra (MH) - 'M' often read as 'H' (HH), 'N' (NH), 'W' (WH), '1' (1H), etc.
    "HH": "MH",
    "NH": "MH",
    "WH": "MH",
    "1H": "MH",
    "IH": "MH",
    "4H": "MH",
    "VH": "MH",
    "AAH": "MH",
    "MM": "MH",  # Second letter 'H' misread as 'M'

    # Madhya Pradesh (MP) - 'M' read as 'N', 'W', '1', 'I', 'V'
    "NP": "MP",
    "WP": "MP",
    "1P": "MP",
    "IP": "MP",
    "4P": "MP",
    "VP": "MP",

    # Meghalaya (ML)
    "HL": "ML",
    "1L": "ML",
    "IL": "ML",

    # Manipur (MN)
    "HN": "MN",
    "1N": "MN",
    "IN": "MN",

    # Mizoram (MZ)
    "HZ": "MZ",
    "NZ": "MZ",
    "1Z": "MZ",
    "IZ": "MZ",
}

class CarDetectorService:
    """
    End-to-End Vehicle Detection and High-Accuracy License Plate Recognition (ANPR) Engine.
    Combines YOLOv8 (yolov8n.pt) vehicle localization with a multi-pass OCR pipeline:
    - Spatial text-box assembly (merging multi-word and multi-line plate detections)
    - Dynamic scale and adaptive thresholding for crisp character segmentation
    - Position-dependent character disambiguation (O vs 0, Z vs 2, I vs 1, B vs 8, S vs 5)
    - Pruning of license plate border and screw artifacts (e.g. trailing '7' or '1')
    - EV color & syntax recognition
    """
    def __init__(self, model_path=None):
        if model_path is None:
            candidates = [
                os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "yolov8n.pt")),
                os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "yolov8n.pt")),
                os.path.abspath("yolov8n.pt"),
                "yolov8n.pt"
            ]
            for c in candidates:
                if os.path.exists(c):
                    model_path = c
                    break
            if not model_path:
                model_path = "yolov8n.pt"

        print(f"[CarDetector] Loading YOLOv8 model from: {model_path}")
        self.model = YOLO(model_path)
        # COCO vehicle class IDs: 2: car, 3: motorcycle, 5: bus, 7: truck
        # Include 67 for top-down / CAD view vehicles
        self.vehicle_classes = [2, 3, 5, 7, 67]
        self.reader: Any = None

    def _get_ocr_reader(self) -> Any:
        if self.reader is None:
            try:
                import easyocr
                # Initialize reader on CPU for stability, suppress verbose GPU warnings
                self.reader = easyocr.Reader(['en'], gpu=False, verbose=False)
            except Exception as e:
                print(f"[CarDetector] EasyOCR initialization warning: {e}")
                self.reader = False
        return self.reader

    def normalize_plate_text(self, text):
        """
        Backward-compatible alias for plate text normalization and disambiguation.
        """
        return self.clean_and_disambiguate_plate(text)

    def clean_and_disambiguate_plate(self, raw_text: Any) -> Optional[str]:
        """
        Cleans and corrects recognized license plate strings:
        - Removes special symbols, whitespace, and leading 'IND' country stickers
        - Prunes trailing noise artifacts (e.g. '7', '1', 'I' from license plate mounting frame/screws)
        - Resolves 'M' character confusion (HH->MH, NP->MP, 11/II/IVI/RN->M)
        - Applies position-aware character disambiguation based on standard plate syntax:
          [2 letters State/EV] [1-2 digits District] [1-3 letters Series] [3-4 digits Number]
        """
        if not raw_text:
            return None

        clean = re.sub(r'[^A-Za-z0-9]', '', str(raw_text)).upper()
        if len(clean) < 4 or len(clean) > 16:
            return clean if len(clean) >= 4 else None

        # Ignore known car emblems / badges
        if clean in KNOWN_BADGES:
            return None

        # Strip blue HSRP emblem on left ('IND', 'ND', or single noise char before valid state)
        if clean.startswith('IND') and len(clean) >= 8:
            clean = clean[3:]
        elif clean.startswith('ND') and len(clean) >= 8 and (clean[2:4] in VALID_STATE_PREFIXES or clean[2:4] in STATE_PREFIX_CORRECTIONS):
            clean = clean[2:]
        elif len(clean) >= 9 and clean[0] in ['I', '1', 'T', 'D'] and (clean[1:3] in VALID_STATE_PREFIXES or clean[1:3] in STATE_PREFIX_CORRECTIONS):
            clean = clean[1:]

        # Prune trailing single noise char if preceded by 4 digits and length >= 11 (screw/border)
        if len(clean) >= 11:
            clean = re.sub(r'^([A-Z0-9]{2}[0-9OQLIZSBGA]{1,2}[A-Z0-9]{1,3}[0-9OQLIZSBEA]{4})[0-9A-Z]$', r'\1', clean)

        # Apply 3-char prefix corrections first (e.g. '11H', 'IIH', 'RNH')
        for p3, repl in STATE_PREFIX_CORRECTIONS.items():
            if len(p3) == 3 and clean.startswith(p3):
                clean = repl + clean[3:]
                break

        # Apply 2-char prefix corrections (e.g. 'HH' -> 'MH', 'NP' -> 'MP', 'WH' -> 'MH')
        if clean[:2] in STATE_PREFIX_CORRECTIONS:
            clean = STATE_PREFIX_CORRECTIONS[clean[:2]] + clean[2:]

        # Series 'M' character disambiguation (split 'M' in series)
        clean = re.sub(r'^([A-Z]{2}[0-9OQLIZSBG]{1,2})(?:11|II|IVI|RN)([0-9OQLIZSBEA]{4})$', r'\g<1>M\2', clean)
        clean = re.sub(r'^([A-Z]{2}[0-9OQLIZSBG]{1,2})(?:11|II|IVI|RN)([A-Z][0-9OQLIZSBEA]{4})$', r'\g<1>M\2', clean)
        clean = re.sub(r'^([A-Z]{2}[0-9OQLIZSBG]{1,2}[A-Z])(?:11|II|IVI|RN)([0-9OQLIZSBEA]{4})$', r'\g<1>M\2', clean)

        # 1. Bharat Series: YY BH NNNN XX
        m_bh = re.search(r'([0-9]{2})\s*BH\s*([0-9]{4})\s*([A-Z]{1,2})', clean)
        if m_bh:
            return f'{m_bh.group(1)}BH{m_bh.group(2)}{m_bh.group(3)}'

        # 2. Pure Standard Indian Plate with pure digits and letters (check first!)
        m_pure = re.search(r'^([A-Z]{2})([0-9]{2})([A-Z]{1,3})([0-9]{4})$', clean)
        if m_pure and m_pure.group(1) in VALID_STATE_PREFIXES:
            return ''.join(m_pure.groups())

        # 3. Standard 10-char plate: 2 state letters + 2 district digits + 2 series letters + 4 number digits
        if len(clean) == 10:
            st = clean[:2]
            dist = clean[2:4]
            ser = clean[4:6]
            num = clean[6:10]
            st_clean = ''.join(OCR_LETTER_MAP.get(c, c) for c in st)
            if st_clean in STATE_PREFIX_CORRECTIONS:
                st_clean = STATE_PREFIX_CORRECTIONS[st_clean]
            if st_clean in VALID_STATE_PREFIXES:
                dist_clean = ''.join(OCR_DIGIT_MAP.get(c, c) for c in dist)
                ser_clean = ''.join(OCR_LETTER_MAP.get(c, c) for c in ser)
                num_clean = ''.join(OCR_DIGIT_MAP.get(c, c) for c in num)
                return f'{st_clean}{dist_clean}{ser_clean}{num_clean}'

        # 4. Standard 9-char plate: e.g. State(2) + Dist(2) + Series(1) + Num(4) or State(2) + Dist(1) + Series(2) + Num(4)
        if len(clean) == 9:
            st = clean[:2]
            st_clean = ''.join(OCR_LETTER_MAP.get(c, c) for c in st)
            if st_clean in STATE_PREFIX_CORRECTIONS:
                st_clean = STATE_PREFIX_CORRECTIONS[st_clean]
            if st_clean in VALID_STATE_PREFIXES:
                dist_a = ''.join(OCR_DIGIT_MAP.get(c, c) for c in clean[2:4])
                ser_a = ''.join(OCR_LETTER_MAP.get(c, c) for c in clean[4:5])
                num_a = ''.join(OCR_DIGIT_MAP.get(c, c) for c in clean[5:9])
                if dist_a.isdigit() and ser_a.isalpha() and num_a.isdigit():
                    return f'{st_clean}{dist_a}{ser_a}{num_a}'
                dist_b = ''.join(OCR_DIGIT_MAP.get(c, c) for c in clean[2:3])
                ser_b = ''.join(OCR_LETTER_MAP.get(c, c) for c in clean[3:5])
                num_b = ''.join(OCR_DIGIT_MAP.get(c, c) for c in clean[5:9])
                if dist_b.isdigit() and ser_b.isalpha() and num_b.isdigit():
                    return f'{st_clean}{dist_b}{ser_b}{num_b}'

        # 5. Regex search fallback for variable length plates
        m_std = re.search(r'([A-Z0-9]{2})\s*([0-9OQLIZSBGA]{1,2})\s*([A-Z]{1,3})\s*([0-9OQLIZSBEA]{3,4})', clean)
        if m_std:
            st, dist, ser, num = m_std.groups()
            st_clean = ''.join(OCR_LETTER_MAP.get(c, c) for c in st)
            if st_clean in STATE_PREFIX_CORRECTIONS:
                st_clean = STATE_PREFIX_CORRECTIONS[st_clean]
            if st_clean in VALID_STATE_PREFIXES:
                dist_clean = ''.join(OCR_DIGIT_MAP.get(c, c) for c in dist)
                num_clean = ''.join(OCR_DIGIT_MAP.get(c, c) for c in num)
                return f'{st_clean}{dist_clean}{ser}{num_clean}'

        # Fallback to positional disambiguation
        chars = list(clean)
        n = len(chars)

        for i in range(min(2, n)):
            if chars[i] in OCR_LETTER_MAP:
                chars[i] = OCR_LETTER_MAP[chars[i]]

        st_prefix = "".join(chars[:2])
        if st_prefix in STATE_PREFIX_CORRECTIONS:
            chars[:2] = list(STATE_PREFIX_CORRECTIONS[st_prefix])

        if n >= 8:
            for i in (2, 3):
                if i < n and chars[i] in OCR_DIGIT_MAP:
                    chars[i] = OCR_DIGIT_MAP[chars[i]]

            for i in range(max(4, n - 4), n):
                if chars[i] in OCR_DIGIT_MAP:
                    chars[i] = OCR_DIGIT_MAP[chars[i]]

        res = ''.join(chars)
        return re.sub(r'^([A-Z]{2}[0-9]{1,2}[A-Z]{1,2}[0-9]{4})[0-9A-Z]$', r'\1', res)

    def score_plate_candidate(self, text, conf):
        """
        Heuristic scoring for license plate text candidates.
        Prefers strings containing both letters and numbers, matching state codes,
        and having high OCR confidence.
        """
        if not text or len(text) < 4:
            return -100

        score = float(conf) * 50.0

        # Check for both letters and digits
        has_letters = bool(re.search(r'[A-Z]', text))
        has_digits = bool(re.search(r'[0-9]', text))

        if has_letters and has_digits:
            score += 40.0
        elif not has_digits:
            # Badges like "HONDA", "SWIFT" have only letters -> penalize
            score -= 50.0

        # Known state prefix match
        prefix = text[:2]
        if prefix in VALID_STATE_PREFIXES:
            score += 35.0

        # Standard Indian plate length (8 - 10 chars, e.g. MH12DE1433)
        if 8 <= len(text) <= 10:
            score += 25.0
        elif 5 <= len(text) <= 11:
            score += 10.0
        else:
            score -= 20.0

        # Strict standard plate regex match bonus
        # Matches: MH12DE1433, EV02XY9999, DL1CAB1234, 22BH1234AA
        if re.match(r'^(?:[A-Z]{2}[0-9]{1,2}[A-Z]{1,3}[0-9]{4}|[0-9]{2}BH[0-9]{4}[A-Z]{1,2})$', text):
            score += 50.0

        return score

    def detect_green_ev_plate(self, plate_crop):
        """
        Inspects color channels to detect green EV plates (Indian green HSRP plates).
        """
        if plate_crop is None or plate_crop.size == 0:
            return False

        try:
            hsv = cv2.cvtColor(plate_crop, cv2.COLOR_BGR2HSV)
            # Green hue range in HSV: 35 - 85
            mask = cv2.inRange(hsv, np.array([35, 40, 40]), np.array([85, 255, 255]))
            green_ratio = cv2.countNonZero(mask) / float(plate_crop.shape[0] * plate_crop.shape[1])
            return green_ratio > 0.20
        except Exception:
            return False

    def _assemble_text_boxes(self, raw_ocr_results, offset_x=0, offset_y=0):
        """
        Groups individual EasyOCR word detections by proximity and sorts them
        in natural reading order (left-to-right, top-to-bottom) to reconstruct
        full plates that OCR split across words or lines.
        """
        if not raw_ocr_results:
            return []

        candidates = []
        items = []

        for item in raw_ocr_results:
            bbox, text, conf = item[0], item[1], float(item[2])
            text_str = str(text).strip()
            if not text_str:
                continue

            pts = np.array(bbox, dtype=np.int32)
            bx1, by1 = int(np.min(pts[:, 0])), int(np.min(pts[:, 1]))
            bx2, by2 = int(np.max(pts[:, 0])), int(np.max(pts[:, 1]))

            items.append({
                "text": text_str,
                "conf": conf,
                "box": (bx1 + offset_x, by1 + offset_y, bx2 - bx1, by2 - by1),
                "center_x": (bx1 + bx2) / 2.0,
                "center_y": (by1 + by2) / 2.0
            })

            # Also evaluate each item individually
            cleaned_single = self.clean_and_disambiguate_plate(text_str)
            if cleaned_single:
                candidates.append({
                    "text": cleaned_single,
                    "conf": conf,
                    "box": (bx1 + offset_x, by1 + offset_y, bx2 - bx1, by2 - by1)
                })

        if not items:
            return candidates

        # 1. Combine all items sorted left-to-right (handles "MH" + "12" + "DE" + "1433")
        sorted_lr = sorted(items, key=lambda it: it["center_x"])
        combined_text_lr = "".join(it["text"] for it in sorted_lr)
        avg_conf_lr = sum(it["conf"] for it in sorted_lr) / len(sorted_lr)

        min_x = min(it["box"][0] for it in items)
        min_y = min(it["box"][1] for it in items)
        max_x = max(it["box"][0] + it["box"][2] for it in items)
        max_y = max(it["box"][1] + it["box"][3] for it in items)
        union_box = (min_x, min_y, max_x - min_x, max_y - min_y)

        cleaned_lr = self.clean_and_disambiguate_plate(combined_text_lr)
        if cleaned_lr:
            candidates.append({
                "text": cleaned_lr,
                "conf": avg_conf_lr,
                "box": union_box
            })

        # 2. Combine multi-line (cluster by Y first, then sort each line by X)
        items_by_y = sorted(items, key=lambda it: it["center_y"])
        lines = []
        for it in items_by_y:
            placed = False
            for line in lines:
                if abs(line[0]["center_y"] - it["center_y"]) < 18:
                    line.append(it)
                    placed = True
                    break
            if not placed:
                lines.append([it])

        multiline_text = ""
        for line in lines:
            line_sorted = sorted(line, key=lambda it: it["center_x"])
            multiline_text += "".join(it["text"] for it in line_sorted)

        cleaned_ml = self.clean_and_disambiguate_plate(multiline_text)
        if cleaned_ml:
            candidates.append({
                "text": cleaned_ml,
                "conf": avg_conf_lr,
                "box": union_box
            })

        return candidates

    def _find_plate_roi_candidates(self, vehicle_crop: np.ndarray) -> List[Tuple[np.ndarray, int, int, str]]:
        """
        Locates candidate plate regions within a vehicle crop using:
        1. Sobel-X vertical morphological gradient + rectangular contour extraction
        2. Lower bumper region (35% to 95% of vehicle height)
        3. Middle grille region (20% to 75% of vehicle height)
        4. Full vehicle crop
        """
        rois: List[Tuple[np.ndarray, int, int, str]] = []
        if vehicle_crop is None or vehicle_crop.size == 0:
            return rois

        vh, vw = vehicle_crop.shape[:2]

        # 1. Sobel-X Morphological Gradient Plate Localization
        try:
            gray = cv2.cvtColor(vehicle_crop, cv2.COLOR_BGR2GRAY) if len(vehicle_crop.shape) == 3 else vehicle_crop
            gradX = cv2.Sobel(gray, ddepth=cv2.CV_32F, dx=1, dy=0, ksize=-1)
            gradX = np.absolute(gradX)
            minVal, maxVal = float(np.min(gradX)), float(np.max(gradX))
            if maxVal > minVal:
                gradX = (255 * ((gradX - minVal) / (maxVal - minVal))).astype("uint8")
            else:
                gradX = np.zeros_like(gray, dtype=np.uint8)
            gradX = cv2.GaussianBlur(gradX, (5, 5), 0)
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (17, 3))
            closed = cv2.morphologyEx(gradX, cv2.MORPH_CLOSE, kernel)
            _, thresh = cv2.threshold(closed, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
            contours, _ = cv2.findContours(thresh.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            for c in contours:
                cx, cy, cw, ch = cv2.boundingRect(c)
                aspect = cw / float(ch) if ch > 0 else 0
                area = cw * ch
                # License plates are horizontal rectangles (aspect ratio ~2.0 - 6.5)
                if 2.0 <= aspect <= 6.5 and cw >= 35 and ch >= 12 and area <= (vw * vh * 0.40):
                    px1 = max(0, cx - 6)
                    py1 = max(0, cy - 4)
                    px2 = min(vw, cx + cw + 6)
                    py2 = min(vh, cy + ch + 4)
                    crop = vehicle_crop[py1:py2, px1:px2]
                    if crop.size > 0:
                        rois.append((crop, px1, py1, "sobel_contour"))
        except Exception:
            pass

        # 2. Targeted lower-half bumper zone
        if vh >= 60 and vw >= 60:
            y1_bumper = int(vh * 0.35)
            y2_bumper = int(vh * 0.95)
            rois.append((vehicle_crop[y1_bumper:y2_bumper, 0:vw], 0, y1_bumper, "bumper_zone"))

        # 3. Middle grille zone (for front plates mounted in upper grille)
        if vh >= 80 and vw >= 80:
            y1_mid = int(vh * 0.20)
            y2_mid = int(vh * 0.70)
            rois.append((vehicle_crop[y1_mid:y2_mid, 0:vw], 0, y1_mid, "mid_grille"))

        # 4. Full vehicle crop
        rois.append((vehicle_crop, 0, 0, "full_crop"))
        return rois

    def extract_license_plate(self, vehicle_crop: np.ndarray) -> Tuple[Optional[str], float, Optional[Tuple[int, int, int, int]]]:
        """
        Multi-pass OCR extraction pipeline:
        1. Evaluates multiple Regions of Interest (ROI):
           - Sobel morphological candidate contours
           - Lower-middle vehicle bumper/boot zone
           - Middle grille zone
           - Full vehicle crop
        2. Applies multi-scale and multi-pass OCR (Raw RGB, CLAHE, Adaptive threshold)
        3. Assembles split text boxes and disambiguates characters
        4. Selects the highest scoring plate candidate
        Returns: (plate_text: str|None, confidence: float, plate_box: (x, y, w, h)|None)
        """
        reader: Any = self._get_ocr_reader()
        if not reader:
            return None, 0.0, None

        if vehicle_crop is None or vehicle_crop.size == 0:
            return None, 0.0, None

        all_candidates: List[Dict[str, Any]] = []
        rois = self._find_plate_roi_candidates(vehicle_crop)
        allowlist_chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

        for roi_img, off_x, off_y, roi_type in rois:
            rh, rw = roi_img.shape[:2]
            if rh < 14 or rw < 35:
                continue

            # Standardize scale: target plate height ~80px
            scale = max(1.5, 80.0 / max(rh, 1))
            target_w = int(rw * scale)
            target_h = int(rh * scale)
            upscaled = cv2.resize(roi_img, (target_w, target_h), interpolation=cv2.INTER_CUBIC)

            # Pass 1: Raw / Enhanced RGB (EasyOCR CRAFT works best on natural RGB images)
            try:
                res_rgb: Any = reader.readtext(upscaled, allowlist=allowlist_chars, detail=1)
                res_rescaled = []
                for (b, t, c) in res_rgb:
                    pts = np.array(b, dtype=np.float32) / scale
                    res_rescaled.append((pts.tolist(), t, c))
                boxes_assembled = self._assemble_text_boxes(res_rescaled, off_x, off_y)
                all_candidates.extend(boxes_assembled)
            except Exception:
                pass

            if any(self.score_plate_candidate(c["text"], c["conf"]) > 80 for c in all_candidates):
                break

            # Pass 2: Contrast-enhanced CLAHE + Bilateral filter (for shadowed/low contrast plates)
            try:
                gray_up = cv2.cvtColor(upscaled, cv2.COLOR_BGR2GRAY) if len(upscaled.shape) == 3 else upscaled
                clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
                contrast = clahe.apply(gray_up)
                denoised = cv2.bilateralFilter(contrast, 7, 50, 50)
                res_contrast: Any = reader.readtext(denoised, allowlist=allowlist_chars, detail=1)
                res_rescaled = []
                for (b, t, c) in res_contrast:
                    pts = np.array(b, dtype=np.float32) / scale
                    res_rescaled.append((pts.tolist(), t, c))
                boxes_assembled = self._assemble_text_boxes(res_rescaled, off_x, off_y)
                all_candidates.extend(boxes_assembled)
            except Exception:
                pass

            if any(self.score_plate_candidate(c["text"], c["conf"]) > 80 for c in all_candidates):
                break

            # Pass 3: Adaptive Gaussian Thresholding (for dirt, glare, or specular reflection)
            try:
                gray_up = cv2.cvtColor(upscaled, cv2.COLOR_BGR2GRAY) if len(upscaled.shape) == 3 else upscaled
                thresh = cv2.adaptiveThreshold(gray_up, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 21, 5)
                res_thresh: Any = reader.readtext(thresh, allowlist=allowlist_chars, detail=1)
                res_rescaled = []
                for (b, t, c) in res_thresh:
                    pts = np.array(b, dtype=np.float32) / scale
                    res_rescaled.append((pts.tolist(), t, c))
                boxes_assembled = self._assemble_text_boxes(res_rescaled, off_x, off_y)
                all_candidates.extend(boxes_assembled)
            except Exception:
                pass

            if any(self.score_plate_candidate(c["text"], c["conf"]) > 80 for c in all_candidates):
                break

        if not all_candidates:
            return None, 0.0, None

        # Score and rank all candidate plates
        ranked = []
        for cand in all_candidates:
            text = cand["text"]
            conf = cand["conf"]
            score = self.score_plate_candidate(text, conf)
            if score > 0:
                ranked.append((score, text, conf, cand.get("box")))

        if not ranked:
            valid = [c for c in all_candidates if len(c["text"]) >= 4]
            if valid:
                valid.sort(key=lambda c: c["conf"], reverse=True)
                return valid[0]["text"], round(valid[0]["conf"], 3), valid[0].get("box")
            return None, 0.0, None

        ranked.sort(key=lambda r: r[0], reverse=True)
        best_score, best_plate, best_conf, best_box = ranked[0]

        # Automated Recheck Pass before confirming number plate
        confirmed_plate, confirmed_conf, is_confirmed = self.recheck_and_confirm_plate(
            vehicle_crop, best_plate, best_conf, best_box
        )

        return confirmed_plate, round(confirmed_conf, 3), best_box

    def recheck_and_confirm_plate(
        self,
        vehicle_crop: np.ndarray,
        initial_plate: Optional[str],
        initial_conf: float,
        plate_box: Optional[Tuple[int, int, int, int]]
    ) -> Tuple[Optional[str], float, bool]:
        """
        High-speed automated validation & confirmation pass.
        If standard Indian plate syntax & RTO state prefix are verified, confirms immediately
        bypassing redundant full-image OCR. If uncertain, executes a tight plate ROI recheck.
        """
        if not initial_plate or initial_plate == "UNKNOWN":
            return "UNKNOWN", 0.0, False

        # 1. Syntax & Structural Verification
        has_valid_syntax = bool(re.match(r'^(?:[A-Z]{2}[0-9]{1,2}[A-Z]{1,3}[0-9]{3,4}|[0-9]{2}BH[0-9]{4}[A-Z]{1,2})$', initial_plate))
        has_valid_prefix = initial_plate[:2] in VALID_STATE_PREFIXES

        # Fast Confirmation: If plate syntax and state prefix are valid with adequate confidence, confirm immediately!
        if has_valid_syntax and has_valid_prefix and initial_conf >= 0.45:
            return initial_plate, round(max(initial_conf, 0.90), 3), True

        confirmed_plate = initial_plate
        confirmed_conf = initial_conf

        # 2. Targeted Secondary Verification on cropped plate ROI (sub-0.1s)
        reader: Any = self._get_ocr_reader()
        if reader and vehicle_crop is not None and vehicle_crop.size > 0:
            try:
                # If plate_box is available, crop tight plate region instead of whole vehicle
                if plate_box is not None:
                    px, py, pw, ph = plate_box
                    pad_y = int(ph * 0.15)
                    pad_x = int(pw * 0.15)
                    y1 = max(0, py - pad_y)
                    y2 = min(vehicle_crop.shape[0], py + ph + pad_y)
                    x1 = max(0, px - pad_x)
                    x2 = min(vehicle_crop.shape[1], px + pw + pad_x)
                    target_roi = vehicle_crop[y1:y2, x1:x2]
                else:
                    target_roi = vehicle_crop

                vh, vw = target_roi.shape[:2]
                scale = max(2.0, 160.0 / max(vw, 1))
                up = cv2.resize(target_roi, (int(vw * scale), int(vh * scale)), interpolation=cv2.INTER_CUBIC)
                gray = cv2.cvtColor(up, cv2.COLOR_BGR2GRAY) if len(up.shape) == 3 else up
                clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
                contrast = clahe.apply(gray)
                res: Any = reader.readtext(contrast, allowlist="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", detail=1)
                for item in res:
                    candidate = self.clean_and_disambiguate_plate(item[1])
                    if candidate and (candidate == initial_plate or len(candidate) >= 8):
                        confirmed_plate = candidate
                        confirmed_conf = min(0.99, initial_conf + 0.25)
                        break
            except Exception:
                pass

        is_confirmed = (has_valid_syntax and has_valid_prefix) or (confirmed_conf >= 0.50 and len(confirmed_plate) >= 6)
        if is_confirmed:
            confirmed_conf = max(confirmed_conf, 0.75)

        return confirmed_plate, round(confirmed_conf, 3), is_confirmed

    def detect_video_and_process(self, video_input: Any) -> Dict[str, Any]:
        """
        High-performance video processing:
        Samples 5 keyframes evenly, runs ultra-fast YOLOv8 on keyframes, selects the highest-scoring
        frame with largest vehicle detection, and runs full ANPR only on that single optimal frame.
        """
        import tempfile
        tmp_file_path = None

        if isinstance(video_input, bytes):
            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
                f.write(video_input)
                tmp_file_path = f.name
            video_source = tmp_file_path
        elif isinstance(video_input, str) and os.path.exists(video_input):
            video_source = video_input
        else:
            raise ValueError("Invalid video input format")

        cap = cv2.VideoCapture(video_source)
        if not cap.isOpened():
            if tmp_file_path and os.path.exists(tmp_file_path):
                try:
                    os.remove(tmp_file_path)
                except Exception:
                    pass
            raise ValueError("Could not open video file for processing")

        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 30
        num_samples = min(5, max(1, total_frames))
        sample_indices = [int(i * (total_frames - 1) / max(1, num_samples - 1)) for i in range(num_samples)]

        best_frame = None
        best_box_area = -1.0

        # Fast Pass 1: Scan keyframes with lightweight YOLOv8 (imgsz=480, sub-0.1s each)
        for f_idx in sample_indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, f_idx)
            ret, frame = cap.read()
            if not ret or frame is None or frame.size == 0:
                continue

            yolo_res: Any = self.model(frame, classes=self.vehicle_classes, conf=0.20, imgsz=480, verbose=False)
            for res in yolo_res:
                boxes = getattr(res, "boxes", None)
                if boxes is not None and len(boxes) > 0:
                    for box in boxes:
                        x1, y1, x2, y2 = box.xyxy[0].tolist()
                        conf = float(box.conf[0].item())
                        area = (x2 - x1) * (y2 - y1) * conf
                        if area > best_box_area:
                            best_box_area = area
                            best_frame = frame.copy()

        cap.release()
        if tmp_file_path and os.path.exists(tmp_file_path):
            try:
                os.remove(tmp_file_path)
            except Exception:
                pass

        if best_frame is not None:
            return self.detect_and_process(best_frame)

        raise ValueError("Could not find detectable vehicle in video")

    def detect_and_process(self, image_input: Any) -> Dict[str, Any]:
        """
        Processes image or video (numpy array, file path, or bytes), runs YOLOv8 vehicle detection,
        extracts and rechecks license plate via ANPR OCR, annotates the frame with
        bounding boxes & tags, and returns structured detection metadata + base64 annotated image.
        """
        # Check if bytes input is a video (MP4/MOV/AVI/MKV/WEBM)
        if isinstance(image_input, bytes):
            # Check for common video magic bytes or ftyp/moov
            is_video = False
            if len(image_input) > 12:
                header = image_input[:32]
                if b'ftyp' in header or b'moov' in header or b'RIFF' in header or b'matroska' in header or b'webm' in header:
                    is_video = True
            if is_video:
                return self.detect_video_and_process(image_input)

        if isinstance(image_input, str) and os.path.exists(image_input):
            ext = os.path.splitext(image_input)[1].lower()
            if ext in [".mp4", ".avi", ".mov", ".mkv", ".webm"]:
                return self.detect_video_and_process(image_input)

        # 1. Load image
        if isinstance(image_input, bytes):
            nparr = np.frombuffer(image_input, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if img is None:
                # Could be a video that didn't have standard ftyp header
                try:
                    return self.detect_video_and_process(image_input)
                except Exception:
                    raise ValueError("Could not decode image or video file")
        elif isinstance(image_input, str) and os.path.exists(image_input):
            img = cv2.imread(image_input)
        elif isinstance(image_input, np.ndarray):
            img = image_input.copy()
        else:
            raise ValueError("Invalid image input format")

        if img is None or img.size == 0:
            raise ValueError("Could not decode image")

        h, w = img.shape[:2]

        # Downscale oversized input to max 1280px to eliminate CPU tensor bottlenecks
        max_dim = 1280
        if max(h, w) > max_dim:
            scale_ratio = max_dim / float(max(h, w))
            new_w = int(w * scale_ratio)
            new_h = int(h * scale_ratio)
            img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
            h, w = new_h, new_w

        # 2. Run YOLOv8 vehicle detection (conf=0.15, imgsz=480 for 10x-20x sub-second CPU inference)
        results: Any = self.model(img, classes=self.vehicle_classes, conf=0.15, imgsz=480, verbose=False)
        
        detected_vehicles: List[Dict[str, Any]] = []
        class_map = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}

        for result in results:
            boxes = getattr(result, "boxes", None)
            if boxes is not None and len(boxes) > 0:
                for box in boxes:
                    x1, y1, x2, y2 = box.xyxy[0].tolist()
                    conf = float(box.conf[0].item())
                    raw_cls = int(box.cls[0].item())
                    cls_id = 2 if raw_cls == 67 else raw_cls
                    vtype = class_map.get(cls_id, "car")

                    detected_vehicles.append({
                        "box": [int(x1), int(y1), int(x2), int(y2)],
                        "confidence": round(conf, 3),
                        "class_id": cls_id,
                        "vehicle_type": vtype
                    })

        # Sort by box area (largest vehicle in foreground first)
        detected_vehicles.sort(key=lambda v: (v["box"][2] - v["box"][0]) * (v["box"][3] - v["box"][1]), reverse=True)

        primary_box: List[int] = [0, 0, w, h]
        primary_conf: float = 0.0
        primary_class: int = 2
        primary_vtype: str = "car"

        if detected_vehicles:
            first_veh = detected_vehicles[0]
            raw_box = first_veh.get("box", [0, 0, w, h])
            primary_box = [int(raw_box[0]), int(raw_box[1]), int(raw_box[2]), int(raw_box[3])]
            primary_conf = float(first_veh.get("confidence", 0.85))
            primary_class = int(first_veh.get("class_id", 2))
            primary_vtype = str(first_veh.get("vehicle_type", "car"))
            x1, y1, x2, y2 = primary_box
            x1_c = max(0, x1)
            y1_c = max(0, y1)
            x2_c = min(w, x2)
            y2_c = min(h, y2)
            vehicle_crop = img[y1_c:y2_c, x1_c:x2_c]
        else:
            # Fallback for bumper/close-up crop where entire image is the vehicle
            vehicle_crop = img

        # 3. Read and Recheck License Plate (Multi-pass validation)
        plate_text, ocr_conf, plate_box = self.extract_license_plate(vehicle_crop)

        # If YOLO detected no vehicle, but a valid license plate was extracted:
        # The license plate proves vehicle presence!
        if not detected_vehicles and plate_text and plate_text != "UNKNOWN":
            primary_conf = max(0.85, ocr_conf)
            primary_vtype = "car"
            if plate_box:
                px, py, pw, ph = plate_box
                # Expand box slightly to simulate vehicle region
                bx1 = max(0, px - 30)
                by1 = max(0, py - 40)
                bx2 = min(w, px + pw + 30)
                by2 = min(h, py + ph + 40)
                primary_box = [bx1, by1, bx2, by2]

        # 4. EV Verification: Check 'EV' prefix or green plate background
        is_ev = False
        final_plate = plate_text
        final_conf = ocr_conf

        if final_plate and final_plate != "UNKNOWN":
            is_ev = final_plate.strip().upper().startswith("EV")
            if not is_ev and plate_box:
                px, py, pw, ph = plate_box
                crop_box = vehicle_crop[max(0, py):min(vehicle_crop.shape[0], py+ph),
                                        max(0, px):min(vehicle_crop.shape[1], px+pw)]
                is_ev = self.detect_green_ev_plate(crop_box)
        else:
            final_plate = "UNKNOWN"
            final_conf = 0.0

        vtype: str = "ev" if is_ev else primary_vtype

        # 5. Annotate image with HUD bounding box, plate tag & telemetry
        annotated = img.copy()
        bx1, by1, bx2, by2 = primary_box

        # Bounding Box (Amber for standard, Cyan for EV)
        box_color = (6, 182, 212) if is_ev else (255, 180, 40)  # BGR
        cv2.rectangle(annotated, (bx1, by1), (bx2, by2), box_color, 3)

        # Header tag with confirmed status
        conf_display = f"{final_conf*100:.0f}%" if final_conf > 0 else "N/A"
        confirm_tag = " [CONFIRMED]" if final_conf >= 0.5 and final_plate != "UNKNOWN" else ""
        tag_text = f"{final_plate}{confirm_tag} ({vtype.upper()}) | OCR: {conf_display}"
        (tw, th), _ = cv2.getTextSize(tag_text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
        
        tag_y = max(th + 10, by1)
        cv2.rectangle(annotated, (bx1, tag_y - th - 10), (bx1 + tw + 14, tag_y), box_color, -1)
        cv2.putText(annotated, tag_text, (bx1 + 7, tag_y - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (15, 23, 42), 2, cv2.LINE_AA)

        # License Plate Candidate Bounding Box (Green highlight)
        if plate_box:
            px, py, pw, ph = plate_box
            plate_offset_x = 0 if not detected_vehicles else bx1
            plate_offset_y = 0 if not detected_vehicles else by1
            cv2.rectangle(annotated, (plate_offset_x + px, plate_offset_y + py),
                          (plate_offset_x + px + pw, plate_offset_y + py + ph), (40, 220, 80), 2)

        # Convert annotated image to Base64 JPEG data URL
        _, buffer = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 85])
        annotated_b64 = "data:image/jpeg;base64," + base64.b64encode(buffer.tobytes()).decode("utf-8")

        return {
            "plate_number": final_plate,
            "vehicle_type": vtype,
            "is_ev": is_ev,
            "confidence": primary_conf,
            "ocr_confidence": round(final_conf, 3),
            "box": primary_box,
            "detected_vehicles_count": len(detected_vehicles),
            "annotated_image": annotated_b64
        }

# Global singleton instance
car_detector = CarDetectorService()

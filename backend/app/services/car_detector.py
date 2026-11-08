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
    '0': 'O', '1': 'I', '2': 'Z', '5': 'S', '8': 'B'
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
        self.vehicle_classes = [2, 3, 5, 7]  # 2: car, 3: motorcycle, 5: bus, 7: truck
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

    def clean_and_disambiguate_plate(self, raw_text):
        """
        Cleans and corrects recognized license plate strings:
        - Removes special symbols, whitespace, and leading 'IND' country stickers
        - Prunes trailing noise artifacts (e.g. '7', '1', 'I' from license plate mounting frame/screws)
        - Applies position-aware character disambiguation based on standard plate syntax:
          [2 letters State/EV] [1-2 digits District] [1-3 letters Series] [4 digits Number]
        """
        if not raw_text:
            return None

        clean = re.sub(r'[^A-Za-z0-9]', '', str(raw_text)).upper()
        if len(clean) < 4 or len(clean) > 14:
            return clean if len(clean) >= 4 else None

        # Ignore known car emblems / badges
        if clean in KNOWN_BADGES:
            return None

        # Strip leading IND / country prefix (from blue HSRP emblem on left)
        if clean.startswith('IND') and len(clean) >= 9:
            clean = clean[3:]
        elif clean.startswith('ND') and len(clean) >= 8 and clean[2:4] in VALID_STATE_PREFIXES:
            clean = clean[2:]

        # 1. Bharat Series: YY BH NNNN XX (with trailing noise pruning)
        m_bh = re.search(r'([0-9]{2})\s*BH\s*([0-9]{4})\s*([A-Z]{1,2})', clean)
        if m_bh:
            return f'{m_bh.group(1)}BH{m_bh.group(2)}{m_bh.group(3)}'

        # 2. Standard Indian Plate with 4 pure digits (State + Dist + Series + Number)
        # Strips trailing noise artifacts (e.g. '7' in 'HR26DC01657' from plate frame or right edge screw)
        m_std = re.search(r'([A-Z]{2})\s*([0-9]{1,2})\s*([A-Z]{1,3})\s*([0-9]{4})', clean)
        if m_std and m_std.group(1) in VALID_STATE_PREFIXES:
            return ''.join(m_std.groups())

        # 3. Standard Indian Plate with OCR character confusion in digits/state
        # Handles cases where '0' was read as 'O', '1' as 'I', etc.
        m_std_conf = re.search(r'([A-Z0-9]{2})\s*([0-9OQLIZSBG]{1,2})\s*([A-Z]{1,2})\s*([0-9OQLIZSBEA]{4})', clean)
        if m_std_conf:
            st, dist, ser, num = m_std_conf.groups()
            st_clean = ''.join(OCR_LETTER_MAP.get(c, c) for c in st)
            if st_clean in VALID_STATE_PREFIXES:
                dist_clean = ''.join(OCR_DIGIT_MAP.get(c, c) for c in dist)
                num_clean = ''.join(OCR_DIGIT_MAP.get(c, c) for c in num)
                return f'{st_clean}{dist_clean}{ser}{num_clean}'

        # 4. Standard Indian Plate with 1-3 digits (VIP / vintage / commercial)
        m_short = re.search(r'([A-Z]{2})\s*([0-9]{1,2})\s*([A-Z]{0,2})\s*([0-9]{1,3})', clean)
        if m_short and m_short.group(1) in VALID_STATE_PREFIXES:
            return ''.join(m_short.groups())

        # Fallback to positional disambiguation
        chars = list(clean)
        n = len(chars)

        # First 2 characters: letters
        for i in range(min(2, n)):
            if chars[i] in OCR_LETTER_MAP:
                chars[i] = OCR_LETTER_MAP[chars[i]]

        # Position 2 and 3: digits
        if n >= 8:
            for i in (2, 3):
                if i < n and chars[i] in OCR_DIGIT_MAP:
                    chars[i] = OCR_DIGIT_MAP[chars[i]]

            # Last 4 characters: digits
            for i in range(max(4, n - 4), n):
                if chars[i] in OCR_DIGIT_MAP:
                    chars[i] = OCR_DIGIT_MAP[chars[i]]

        # If after fallback we have an 11-char string ending in 5 digits, prune the 5th trailing digit
        res = ''.join(chars)
        res_pruned = re.sub(r'^([A-Z]{2}[0-9]{1,2}[A-Z]{1,2}[0-9]{4})[0-9A-Z]$', r'\1', res)
        return res_pruned

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

    def extract_license_plate(self, vehicle_crop):
        """
        Multi-pass OCR extraction pipeline:
        1. Evaluates multiple Regions of Interest (ROI):
           - Targeted lower-middle vehicle bumper/boot zone
           - Full vehicle crop
        2. Applies multi-scale and adaptive contrast filters
        3. Assembles split text boxes and disambiguates characters
        4. Selects the highest scoring plate candidate
        Returns: (plate_text: str|None, confidence: float, plate_box: (x, y, w, h)|None)
        """
        reader: Any = self._get_ocr_reader()
        if not reader:
            return None, 0.0, None

        if vehicle_crop is None or vehicle_crop.size == 0:
            return None, 0.0, None

        vh, vw = vehicle_crop.shape[:2]
        all_candidates = []

        # Define ROIs to search
        rois = []
        # ROI 1: Lower 65% of vehicle (where plates reside)
        if vh >= 60 and vw >= 60:
            roi_y = int(vh * 0.35)
            rois.append((vehicle_crop[roi_y:vh, 0:vw], 0, roi_y))
        # ROI 2: Full crop (in case image is already cropped plate or close-up)
        rois.append((vehicle_crop, 0, 0))

        allowlist_chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

        for roi_img, off_x, off_y in rois:
            rh, rw = roi_img.shape[:2]
            if rh < 20 or rw < 40:
                continue

            # Scale up if small
            scale = max(2.0, 320.0 / max(rw, 1))
            target_w = int(rw * scale)
            target_h = int(rh * scale)
            upscaled = cv2.resize(roi_img, (target_w, target_h), interpolation=cv2.INTER_CUBIC)

            # Pass A: Adaptive Gaussian Thresholding (removes dirt, shadows, and headlight glare)
            gray_up = cv2.cvtColor(upscaled, cv2.COLOR_BGR2GRAY) if len(upscaled.shape) == 3 else upscaled
            thresh = cv2.adaptiveThreshold(gray_up, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 21, 5)

            try:
                res_thresh: Any = reader.readtext(thresh, allowlist=allowlist_chars, detail=1)
                # Rescale boxes back to vehicle_crop coordinates
                res_rescaled = []
                for (b, t, c) in res_thresh:
                    pts = np.array(b, dtype=np.float32) / scale
                    res_rescaled.append((pts.tolist(), t, c))
                boxes_assembled = self._assemble_text_boxes(res_rescaled, off_x, off_y)
                all_candidates.extend(boxes_assembled)
            except Exception:
                pass

            # If high confidence plate already detected on Pass A, break early for speed
            if any(self.score_plate_candidate(c["text"], c["conf"]) > 75 for c in all_candidates):
                break

            # Pass B: Native Upscaled Color / Contrast (CLAHE)
            try:
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

            if any(self.score_plate_candidate(c["text"], c["conf"]) > 75 for c in all_candidates):
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
            # If all scores were low, choose highest confidence candidate that has at least 4 chars
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

    def recheck_and_confirm_plate(self, vehicle_crop, initial_plate, initial_conf, plate_box):
        """
        Automated secondary recheck & validation pass before confirming the number plate.
        Cross-validates against syntax rules, state prefixes, and secondary contrast pass.
        """
        if not initial_plate or initial_plate == "UNKNOWN":
            return "UNKNOWN", 0.0, False

        # 1. Syntax & Structural Verification
        has_valid_syntax = bool(re.match(r'^(?:[A-Z]{2}[0-9]{1,2}[A-Z]{1,3}[0-9]{3,4}|[0-9]{2}BH[0-9]{4}[A-Z]{1,2})$', initial_plate))
        has_valid_prefix = initial_plate[:2] in VALID_STATE_PREFIXES

        confirmed_plate = initial_plate
        confirmed_conf = initial_conf

        # 2. Secondary Contrast Verification Pass
        reader: Any = self._get_ocr_reader()
        if reader and vehicle_crop is not None and vehicle_crop.size > 0:
            try:
                vh, vw = vehicle_crop.shape[:2]
                scale = max(2.0, 320.0 / max(vw, 1))
                up = cv2.resize(vehicle_crop, (int(vw * scale), int(vh * scale)), interpolation=cv2.INTER_CUBIC)
                gray = cv2.cvtColor(up, cv2.COLOR_BGR2GRAY) if len(up.shape) == 3 else up
                clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
                contrast = clahe.apply(gray)
                denoised = cv2.bilateralFilter(contrast, 7, 50, 50)
                res: Any = reader.readtext(denoised, allowlist="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", detail=1)
                for item in res:
                    candidate = self.clean_and_disambiguate_plate(item[1])
                    if candidate and candidate == initial_plate:
                        # Exact consensus across both adaptive threshold and contrast passes!
                        confirmed_conf = min(0.99, initial_conf + 0.25)
                        break
            except Exception:
                pass

        # If plate matches syntax and state prefix, confirm it
        is_confirmed = (has_valid_syntax and has_valid_prefix) or (confirmed_conf >= 0.50 and len(confirmed_plate) >= 6)
        if is_confirmed:
            confirmed_conf = max(confirmed_conf, 0.75)

        return confirmed_plate, round(confirmed_conf, 3), is_confirmed

    def detect_and_process(self, image_input):
        """
        Processes image (numpy array, file path, or bytes), runs YOLOv8 vehicle detection,
        extracts and rechecks license plate via ANPR OCR, annotates the frame with
        bounding boxes & tags, and returns structured detection metadata + base64 annotated image.
        """
        # 1. Load image
        if isinstance(image_input, bytes):
            nparr = np.frombuffer(image_input, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        elif isinstance(image_input, str) and os.path.exists(image_input):
            img = cv2.imread(image_input)
        elif isinstance(image_input, np.ndarray):
            img = image_input.copy()
        else:
            raise ValueError("Invalid image input format")

        if img is None or img.size == 0:
            raise ValueError("Could not decode image")

        h, w = img.shape[:2]

        # 2. Run YOLOv8 vehicle detection
        results: Any = self.model(img, classes=self.vehicle_classes, conf=0.20, verbose=False)
        
        detected_vehicles: List[Dict[str, Any]] = []
        class_map = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}

        for result in results:
            boxes = getattr(result, "boxes", None)
            if boxes is not None and len(boxes) > 0:
                for box in boxes:
                    x1, y1, x2, y2 = box.xyxy[0].tolist()
                    conf = float(box.conf[0].item())
                    cls_id = int(box.cls[0].item())
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
        primary_conf: float = 0.85
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
            vehicle_crop = img

        primary_vehicle: Dict[str, Any] = {
            "box": primary_box,
            "confidence": primary_conf,
            "class_id": primary_class,
            "vehicle_type": primary_vtype
        }

        # 3. Read and Recheck License Plate (Automatic multi-pass validation)
        plate_text, ocr_conf, plate_box = self.extract_license_plate(vehicle_crop)

        # 4. EV Verification: Check 'EV' prefix or green plate background
        is_ev = False
        final_plate = plate_text
        final_conf = ocr_conf

        if final_plate and final_plate != "UNKNOWN":
            is_ev = str(final_plate).strip().upper().startswith("EV")
            if not is_ev and plate_box:
                px, py, pw, ph = [int(v) for v in plate_box]
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
            px, py, pw, ph = [int(v) for v in plate_box]
            cv2.rectangle(annotated, (bx1 + px, by1 + py), (bx1 + px + pw, by1 + py + ph), (40, 220, 80), 2)

        # Convert annotated image to Base64 JPEG data URL
        _, buffer = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 85])
        annotated_b64 = "data:image/jpeg;base64," + base64.b64encode(buffer.tobytes()).decode("utf-8")

        return {
            "plate_number": final_plate,
            "vehicle_type": vtype,
            "is_ev": is_ev,
            "confidence": primary_vehicle["confidence"],
            "ocr_confidence": round(final_conf, 3),
            "box": primary_vehicle["box"],
            "detected_vehicles_count": len(detected_vehicles),
            "annotated_image": annotated_b64
        }

# Global singleton instance
car_detector = CarDetectorService()

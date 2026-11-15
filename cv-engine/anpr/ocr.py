import cv2
import numpy as np
import re

VALID_STATE_PREFIXES = {
    "AN", "AP", "AR", "AS", "BR", "CH", "CG", "DD", "DL", "DN", "GA", "GJ",
    "HR", "HP", "JH", "JK", "KA", "KL", "LA", "LD", "MP", "MH", "MN", "ML",
    "MZ", "NL", "OD", "PB", "PY", "RJ", "SK", "TN", "TR", "TS", "UK", "UP",
    "WB", "EV", "BH"
}

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
# is misrecognized by EasyOCR as 'H', 'N', 'W', '1', 'I', '4', 'V', '11', 'II', 'AA', etc.
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
    "MM": "MH",  # Second letter 'H' misread as 'M' in state code position
    "11H": "MH",
    "IIH": "MH",
    "IVIH": "MH",
    "RNH": "MH",
    "NNH": "MH",
    "WMH": "MH",

    # Madhya Pradesh (MP) - 'M' read as 'N', 'W', '1', 'I', 'V'
    "NP": "MP",
    "WP": "MP",
    "1P": "MP",
    "IP": "MP",
    "4P": "MP",
    "VP": "MP",
    "11P": "MP",
    "IIP": "MP",
    "IVIP": "MP",
    "AAP": "MP",
    "RNP": "MP",

    # Meghalaya (ML)
    "HL": "ML",
    "NL": "ML",
    "WL": "ML",
    "1L": "ML",
    "IL": "ML",
    "4L": "ML",
    "VL": "ML",
    "11L": "ML",
    "IIL": "ML",

    # Manipur (MN)
    "HN": "MN",
    "WN": "MN",
    "1N": "MN",
    "IN": "MN",
    "4N": "MN",
    "VN": "MN",
    "11N": "MN",
    "IIN": "MN",

    # Mizoram (MZ)
    "HZ": "MZ",
    "NZ": "MZ",
    "WZ": "MZ",
    "1Z": "MZ",
    "IZ": "MZ",
    "4Z": "MZ",
    "VZ": "MZ",
    "11Z": "MZ",
    "IIZ": "MZ",
}

class PlateReader:
    """
    ANPR Plate Recognition Engine.
    Performs multi-stage license plate localization, adaptive thresholding,
    character segmentation, spatial box grouping, and syntax disambiguation.
    """
    def __init__(self, languages=['en'], use_gpu=False):
        self.reader = None
        self.languages = languages
        self.use_gpu = use_gpu

    def _get_reader(self):
        if self.reader is None:
            try:
                import easyocr
                self.reader = easyocr.Reader(self.languages, gpu=self.use_gpu, verbose=False)
            except Exception as e:
                print(f"[PlateReader] EasyOCR init warning: {e}")
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
        - Resolves 'M' character confusion (HH->MH, NP->MP, 11/II/IVI/RN->M)
        - Applies position-aware character disambiguation based on standard plate syntax:
          [2 letters State/EV] [1-2 digits District] [1-3 letters Series] [4 digits Number]
        """
        if not raw_text:
            return None

        clean = re.sub(r'[^A-Za-z0-9]', '', str(raw_text)).upper()
        if len(clean) < 4 or len(clean) > 15:
            return clean if len(clean) >= 4 else None

        if clean in KNOWN_BADGES:
            return None

        # Strip leading IND / country prefix (from blue HSRP emblem on left)
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

        # Series 'M' character disambiguation:
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

        # First 2 characters: letters
        for i in range(min(2, n)):
            if chars[i] in OCR_LETTER_MAP:
                chars[i] = OCR_LETTER_MAP[chars[i]]
        st_prefix = "".join(chars[:2])
        if st_prefix in STATE_PREFIX_CORRECTIONS:
            chars[:2] = list(STATE_PREFIX_CORRECTIONS[st_prefix])

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
        if not text or len(text) < 4:
            return -100

        score = float(conf) * 50.0

        has_letters = bool(re.search(r'[A-Z]', text))
        has_digits = bool(re.search(r'[0-9]', text))

        if has_letters and has_digits:
            score += 40.0
        elif not has_digits:
            score -= 50.0

        prefix = text[:2]
        if prefix in VALID_STATE_PREFIXES or prefix in STATE_PREFIX_CORRECTIONS:
            score += 35.0

        if 8 <= len(text) <= 10:
            score += 25.0
        elif 5 <= len(text) <= 11:
            score += 10.0
        else:
            score -= 20.0

        if re.match(r'^(?:[A-Z]{2}[0-9]{1,2}[A-Z]{1,3}[0-9]{3,4}|[0-9]{2}BH[0-9]{4}[A-Z]{1,2})$', text):
            score += 50.0

        return score

    def _assemble_text_boxes(self, raw_ocr_results, offset_x=0, offset_y=0):
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

            cleaned_single = self.clean_and_disambiguate_plate(text_str)
            if cleaned_single:
                candidates.append({
                    "text": cleaned_single,
                    "conf": conf,
                    "box": (bx1 + offset_x, by1 + offset_y, bx2 - bx1, by2 - by1)
                })

        if not items:
            return candidates

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

        return candidates

    def _find_plate_rois(self, image):
        """
        Locates candidate plate regions within a vehicle crop using:
        1. Sobel-X vertical morphological gradient + rectangular contour extraction
        2. Lower bumper region (35% to 95% of vehicle height)
        3. Middle grille region (20% to 75% of vehicle height)
        4. Full vehicle crop
        """
        rois = []
        if image is None or image.size == 0:
            return rois

        vh, vw = image.shape[:2]

        # 1. Sobel-X Morphological Gradient Plate Localization
        try:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
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
                if 2.0 <= aspect <= 6.5 and cw >= 35 and ch >= 12 and area <= (vw * vh * 0.40):
                    px1 = max(0, cx - 6)
                    py1 = max(0, cy - 4)
                    px2 = min(vw, cx + cw + 6)
                    py2 = min(vh, cy + ch + 4)
                    crop = image[py1:py2, px1:px2]
                    if crop.size > 0:
                        rois.append((crop, px1, py1))
        except Exception:
            pass

        # 2. Targeted lower-half bumper zone
        if vh >= 60 and vw >= 60:
            y1_bumper = int(vh * 0.35)
            y2_bumper = int(vh * 0.95)
            rois.append((image[y1_bumper:y2_bumper, 0:vw], 0, y1_bumper))

        # 3. Middle grille zone
        if vh >= 80 and vw >= 80:
            y1_mid = int(vh * 0.20)
            y2_mid = int(vh * 0.70)
            rois.append((image[y1_mid:y2_mid, 0:vw], 0, y1_mid))

        # 4. Full vehicle crop
        rois.append((image, 0, 0))
        return rois

    def read_plate(self, image):
        """
        Extracts license plate number and confidence score from a cropped vehicle image.
        Returns: (plate_text: str|None, confidence: float)
        """
        if image is None or image.size == 0:
            return None, 0.0

        reader = self._get_reader()
        if not reader:
            return None, 0.0

        rois = self._find_plate_rois(image)
        allowlist_chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        all_candidates = []

        for roi_img, off_x, off_y in rois:
            rh, rw = roi_img.shape[:2]
            if rh < 14 or rw < 35:
                continue

            scale = max(1.5, 80.0 / max(rh, 1))
            target_w = int(rw * scale)
            target_h = int(rh * scale)
            upscaled = cv2.resize(roi_img, (target_w, target_h), interpolation=cv2.INTER_CUBIC)

            # Pass 1: Raw / Enhanced RGB
            try:
                res_rgb = reader.readtext(upscaled, allowlist=allowlist_chars, detail=1)
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

            # Pass 2: Contrast / CLAHE
            try:
                gray_up = cv2.cvtColor(upscaled, cv2.COLOR_BGR2GRAY) if len(upscaled.shape) == 3 else upscaled
                clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
                contrast = clahe.apply(gray_up)
                denoised = cv2.bilateralFilter(contrast, 7, 50, 50)
                res_contrast = reader.readtext(denoised, allowlist=allowlist_chars, detail=1)
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

            # Pass 3: Adaptive thresholding
            try:
                gray_up = cv2.cvtColor(upscaled, cv2.COLOR_BGR2GRAY) if len(upscaled.shape) == 3 else upscaled
                thresh = cv2.adaptiveThreshold(gray_up, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 21, 5)
                res_thresh = reader.readtext(thresh, allowlist=allowlist_chars, detail=1)
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
            return None, 0.0

        ranked = []
        for cand in all_candidates:
            text = cand["text"]
            conf = cand["conf"]
            score = self.score_plate_candidate(text, conf)
            if score > 0:
                ranked.append((score, text, conf))

        if not ranked:
            valid = [c for c in all_candidates if len(c["text"]) >= 4]
            if valid:
                valid.sort(key=lambda c: c["conf"], reverse=True)
                return valid[0]["text"], round(valid[0]["conf"], 3)
            return None, 0.0

        ranked.sort(key=lambda r: r[0], reverse=True)
        best_score, best_plate, best_conf = ranked[0]

        # Automated Recheck before confirming number plate
        confirmed_plate, confirmed_conf = self.recheck_and_confirm_plate(image, best_plate, best_conf)
        return confirmed_plate, round(confirmed_conf, 3)

    def recheck_and_confirm_plate(self, image, initial_plate, initial_conf):
        """
        Automated secondary recheck & validation pass before confirming the number plate.
        Zooms in and cross-validates character consistency with alternate morphological filters.
        """
        if not initial_plate or initial_plate == "UNKNOWN":
            return initial_plate, initial_conf

        reader = self._get_reader()
        if not reader or image is None or image.size == 0:
            return initial_plate, initial_conf

        vh, vw = image.shape[:2]
        crop = image[int(vh * 0.35):vh, 0:vw] if vh >= 60 else image
        if crop is None or crop.size == 0:
            return initial_plate, initial_conf

        scale = max(2.5, 360.0 / max(crop.shape[1], 1))
        zoomed = cv2.resize(crop, (int(crop.shape[1] * scale), int(crop.shape[0] * scale)), interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(zoomed, cv2.COLOR_BGR2GRAY) if len(zoomed.shape) == 3 else zoomed
        _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        enhanced = cv2.morphologyEx(otsu, cv2.MORPH_CLOSE, kernel)

        recheck_candidates = []
        try:
            res = reader.readtext(enhanced, allowlist="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", detail=1)
            for item in res:
                text_clean = self.clean_and_disambiguate_plate(item[1])
                if text_clean and len(text_clean) >= 4:
                    recheck_candidates.append((text_clean, float(item[2])))
        except Exception:
            pass

        if recheck_candidates:
            recheck_candidates.sort(key=lambda x: self.score_plate_candidate(x[0], x[1]), reverse=True)
            top_plate, top_conf = recheck_candidates[0]
            if top_plate == initial_plate:
                return initial_plate, min(0.99, max(initial_conf, top_conf) + 0.15)
            elif self.score_plate_candidate(top_plate, top_conf) > self.score_plate_candidate(initial_plate, initial_conf) and top_conf >= initial_conf:
                return top_plate, top_conf

        return initial_plate, initial_conf

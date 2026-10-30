import os
import sys
import base64
import uuid
import logging
import tempfile
import zipfile
import json
import re
import requests
from io import BytesIO
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import urllib3

# Suppress insecure SSL warnings from proxy forward tunneling
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import pikepdf
    HAS_PIKEPDF = True
except ImportError:
    HAS_PIKEPDF = False

try:
    import curl_cffi.requests as curl_requests
    from curl_cffi.curl import CurlOpt
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False

import PyPDF2
import ddddocr

logger = logging.getLogger(__name__)

# Verified active Indian proxies for UIDAI access
DEFAULT_PROXIES = [
    "https://103.251.94.188:443",
    "https://14.99.141.239:443",
    "https://163.223.186.141:443",
    "https://103.251.94.10:443",
    "https://202.162.232.76:443",
    "https://49.50.72.246:443",
    "https://182.156.203.41:443",
    "https://210.89.42.108:443",
]

UIDAI_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Origin": "https://myaadhaarbeta.uidai.gov.in",
    "Referer": "https://myaadhaarbeta.uidai.gov.in/",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36",
    "Accept-Language": "en_IN",
    "sec-ch-ua": '"Chromium";v="152", "Not?A_Brand";v="24", "Google Chrome";v="152"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Linux"',
}

def uidai_post(url, headers, json_data, proxy_url=None, timeout=20):
    """
    Robust HTTP POST using curl_cffi (libcurl) with proxy SSL verification disabled.
    Prevents hanging on TLS proxy handshakes during downloads.
    """
    if HAS_CURL_CFFI and proxy_url:
        curl_opts = {
            CurlOpt.PROXY_SSL_VERIFYPEER: 0,
            CurlOpt.PROXY_SSL_VERIFYHOST: 0,
        }
        return curl_requests.post(
            url,
            headers=headers,
            json=json_data,
            proxy=proxy_url,
            verify=False,
            curl_options=curl_opts,
            timeout=timeout
        )
    else:
        proxies = {'http': proxy_url, 'https': proxy_url} if proxy_url else None
        return requests.post(
            url,
            headers=headers,
            json=json_data,
            proxies=proxies,
            verify=False,
            timeout=timeout
        )


def _preprocess_captcha(img_bytes: bytes, thresh: int = 140) -> bytes:
    """Preprocess captcha image to enhance OCR accuracy."""
    if not HAS_PIL:
        return img_bytes
    try:
        img = Image.open(BytesIO(img_bytes)).convert("L")
        w, h = img.size
        img = img.resize((w * 3, h * 3), Image.LANCZOS)
        img = img.point(lambda p: 255 if p > thresh else 0)
        buf = BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return img_bytes


def is_uidai_maintenance_window():
    """Checks if current time in IST is within UIDAI's regular daily downtime (12:00 AM - 4:30 AM IST)."""
    try:
        from datetime import timezone, timedelta
        ist_now = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
        hour = ist_now.hour
        minute = ist_now.minute
        if (hour == 23 and minute >= 45) or (0 <= hour < 4) or (hour == 4 and minute <= 30):
            return True, ist_now.strftime("%I:%M %p IST")
        return False, ist_now.strftime("%I:%M %p IST")
    except Exception:
        return False, "IST"


# ============== PDF PASSWORD CRACKER ==============
class PDFPasswordCracker:
    def __init__(self, max_workers=6):
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.found_password = None
        self.stop_flag = False

    def crack_with_pikepdf(self, pdf_path, prefix, years_to_try):
        if not HAS_PIKEPDF:
            return False, None, None
        try:
            try:
                with pikepdf.open(pdf_path) as p:
                    tmp = tempfile.NamedTemporaryFile(suffix="_decrypted.pdf", delete=False)
                    p.save(tmp.name)
                    tmp.close()
                    return True, "None", tmp.name
            except pikepdf.PasswordError:
                pass

            for y in years_to_try:
                pwd = f"{prefix}{y}"
                try:
                    with pikepdf.open(pdf_path, password=pwd) as p:
                        tmp = tempfile.NamedTemporaryFile(suffix="_decrypted.pdf", delete=False)
                        p.save(tmp.name)
                        tmp.close()
                        logger.info(f"PDF unlocked with pikepdf: {pwd}")
                        return True, pwd, tmp.name
                except pikepdf.PasswordError:
                    continue
        except Exception as e:
            logger.warning(f"pikepdf cracker error: {e}")
        return False, None, None

    def try_password_pypdf(self, pdf_path, password):
        try:
            with open(pdf_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                if pdf_reader.decrypt(password):
                    return True, password
                return False, None
        except Exception:
            return False, None

    def decrypt_pdf_pypdf(self, pdf_path, password, output_path=None):
        try:
            if output_path is None:
                tmp = tempfile.NamedTemporaryFile(suffix="_decrypted.pdf", delete=False)
                output_path = tmp.name
                tmp.close()

            with open(pdf_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                pdf_reader.decrypt(password)
                pdf_writer = PyPDF2.PdfWriter()
                for page in pdf_reader.pages:
                    pdf_writer.add_page(page)
                with open(output_path, 'wb') as output_file:
                    pdf_writer.write(output_file)
            return output_path
        except Exception as e:
            logger.error(f"Error decrypting PDF with PyPDF2: {e}")
            return None

    def crack_pdf(self, pdf_path, name, birth_year=None, progress_callback=None):
        name_clean = "".join(ch for ch in (name or "USER").upper() if ch.isalnum())
        prefix = name_clean[:4] if len(name_clean) >= 4 else name_clean.ljust(4, 'X')

        years_to_try = []
        if birth_year and str(birth_year).isdigit():
            years_to_try.append(int(birth_year))
        
        current_year = datetime.now().year
        for y in range(current_year, 1945, -1):
            if y not in years_to_try:
                years_to_try.append(y)

        # 1. Ultra fast pikepdf attempt (C++ speed, 0.02s)
        if HAS_PIKEPDF:
            ok, pwd, path = self.crack_with_pikepdf(pdf_path, prefix, years_to_try)
            if ok:
                return True, pwd, path

        # 2. Parallel PyPDF2 fallback
        passwords = [f"{prefix}{y}" for y in years_to_try]
        batch_size = 20
        self.stop_flag = False
        for i in range(0, len(passwords), batch_size):
            if self.stop_flag:
                break
            batch = passwords[i:i + batch_size]
            futures = [self.executor.submit(self.try_password_pypdf, pdf_path, p) for p in batch]
            for fut in futures:
                try:
                    success, found_pwd = fut.result(timeout=1.0)
                    if success:
                        self.stop_flag = True
                        decrypted_path = self.decrypt_pdf_pypdf(pdf_path, found_pwd)
                        return True, found_pwd, decrypted_path
                except Exception:
                    continue

        return False, None, None


# ============== AADHAAR BOT API CLASS ==============
class AadhaarBot:
    def __init__(self, proxy_url=None):
        proxy_raw = proxy_url or os.environ.get("PROXY_LIST", "").strip() or os.environ.get("PROXY_URL", "").strip()
        if proxy_raw:
            self.proxies = [p.strip() for p in proxy_raw.split(",") if p.strip()]
        else:
            self.proxies = list(DEFAULT_PROXIES)

        self.proxy_index = 0
        self.user_proxies = {}  # Sticky proxy per user_id

        self.base_headers = dict(UIDAI_HEADERS)
        self.base_headers["appid"] = "MYAADHAAR"

        self.cracker = PDFPasswordCracker()

        try:
            self.ocr = ddddocr.DdddOcr(show_ad=False)
        except Exception as e:
            logger.error(f"Failed to initialize OCR: {e}")
            self.ocr = None

        logger.info(f"AadhaarBot API initialized (curl_cffi={HAS_CURL_CFFI}, Proxies={len(self.proxies)})")

    def get_current_proxy(self):
        if not self.proxies:
            return None
        return self.proxies[self.proxy_index % len(self.proxies)]

    def rotate_proxy(self):
        """Rotates to the next proxy in the pool."""
        if not self.proxies:
            return None
        self.proxy_index = (self.proxy_index + 1) % len(self.proxies)
        next_p = self.proxies[self.proxy_index]
        logger.warning(f"Rotating to proxy #{self.proxy_index}: {next_p}")
        return next_p

    def solve_captcha(self, image_bytes):
        if not image_bytes or not self.ocr:
            return None
        try:
            raw_res = "".join(c for c in self.ocr.classification(image_bytes) if c.isalnum())
            if len(raw_res) == 6:
                return raw_res

            candidates = [raw_res]
            for th in (110, 130, 150, 170):
                prep = _preprocess_captcha(image_bytes, th)
                cand = "".join(ch for ch in self.ocr.classification(prep) if ch.isalnum())
                if len(cand) == 6:
                    return cand
                candidates.append(cand)

            for c in candidates:
                if len(c) == 6:
                    return c
            for c in candidates:
                if len(c) > 6:
                    return c[:6]
            return candidates[0] if candidates and len(candidates[0]) >= 4 else None
        except Exception as e:
            logger.error(f"Error solving captcha: {e}")
            return None

    def generate_transaction_id(self):
        return str(uuid.uuid4())

    def get_captcha(self, user_id):
        transaction_id = self.generate_transaction_id()
        headers = dict(self.base_headers)
        headers['X-Request-ID'] = transaction_id
        headers['transactionId'] = transaction_id
        captcha_data = {'captchaLength': '6', 'captchaType': '2', 'audioCaptchaRequired': False}

        for _ in range(min(len(self.proxies) or 1, 3)):
            p = self.get_current_proxy()
            try:
                response = uidai_post(
                    'https://tathya.uidai.gov.in/audioCaptchaService/api/captcha/v3/generation',
                    headers=headers,
                    json_data=captcha_data,
                    proxy_url=p,
                    timeout=7
                )
                if response.status_code == 200:
                    resp_json = response.json()
                    c_txn = resp_json.get('transactionId')
                    c_b64 = resp_json.get('imageBase64')
                    if c_b64:
                        if c_b64.startswith('data:image'):
                            c_b64 = c_b64.split(',')[1]
                        self.user_proxies[user_id] = p
                        return base64.b64decode(c_b64), c_txn, transaction_id
            except Exception as e:
                logger.warning(f"get_captcha fail on proxy {p}: {e}. Rotating...")
                self.rotate_proxy()

        return None, None, None

    def auto_send_eid_otp(self, user_id, mobile, name="Mr", max_retries=5):
        """
        Automatically fetches captcha, solves via OCR, and requests EID OTP.
        Returns exactly 6 items: (ok, otp_txn, code, c_txn, t_id, error_message)
        """
        last_error = "Failed to solve captcha"
        for attempt in range(1, max_retries + 1):
            img_bytes, c_txn, t_id = self.get_captcha(user_id)
            if not img_bytes:
                in_maint, t_str = is_uidai_maintenance_window()
                if in_maint:
                    return False, None, None, None, None, f"🌙 UIDAI Portal is closed for daily night maintenance ({t_str}). Please try again after 4:30 AM IST!"
                self.rotate_proxy()
                last_error = "UIDAI portal is currently unreachable or slow. Retrying..."
                continue

            code = self.solve_captcha(img_bytes)
            if not code or len(code) != 6:
                continue

            proxy_used = self.user_proxies.get(user_id)
            logger.info(f"Auto-solved Captcha for Mobile (attempt {attempt}): {code}")
            ok, otp_txn, err_msg = self.send_eid_otp(user_id, mobile, name or "Mr", code, c_txn, t_id, proxy_url=proxy_used)
            if ok:
                return True, otp_txn, code, c_txn, t_id, None

            last_error = str(err_msg or "Failed to request OTP")
            err_lower = last_error.lower()
            if "no record" in err_lower or "not linked" in err_lower or "not registered" in err_lower:
                return False, None, None, None, None, "⚠️ The entered mobile number is not linked with any Aadhaar card."

        return False, None, None, None, None, last_error

    def send_eid_otp(self, user_id, mobile, name, captcha_code, captcha_txn_id, transaction_id, proxy_url=None):
        headers = dict(self.base_headers)
        headers['X-Request-ID'] = transaction_id
        headers['transactionId'] = transaction_id
        request_data = {
            'mobileNumber': str(mobile),
            'dob': None,
            'email': None,
            'name': name or "Mr",
            'option': 'EID',
            'otp': None,
            'otpTxnId': None,
            'captchaTxnId': captcha_txn_id,
            'captcha': captcha_code,
            'resendOtp': False
        }
        try:
            response = uidai_post(
                'https://tathya.uidai.gov.in/retrieveEidUid/ext/v1/generic/retrieveuideid',
                headers=headers,
                json_data=request_data,
                proxy_url=proxy_url or self.user_proxies.get(user_id) or self.get_current_proxy(),
                timeout=8
            )
            if response.status_code == 200:
                resp_json = response.json()
                rd = resp_json.get('responseData', {})
                if rd.get('otpSent') and rd.get('otpTxnId'):
                    return True, rd.get('otpTxnId'), None
                msg = rd.get('message') or (resp_json.get('errorDetails') or {}).get('messageEnglish') or resp_json.get('message')
                return False, None, msg
            else:
                return False, None, f"HTTP {response.status_code}"
        except Exception as e:
            return False, None, str(e)

    def verify_eid_otp(self, user_id, mobile, name, otp_code, otp_txn_id, captcha_txn_id, captcha_code, proxy_url=None):
        """Verifies OTP 1 and retrieves the registered EID and the full registered name."""
        headers = dict(self.base_headers)
        headers['X-Request-ID'] = self.generate_transaction_id()
        verify_data = {
            'mobileNumber': str(mobile),
            'dob': None,
            'name': name or "Mr",
            'email': None,
            'option': 'EID',
            'otp': otp_code,
            'otpTxnId': otp_txn_id,
            'captchaTxnId': captcha_txn_id,
            'captcha': captcha_code,
            'resendOtp': False
        }
        try:
            response = uidai_post(
                'https://tathya.uidai.gov.in/retrieveEidUid/ext/v1/generic/retrieveuideid',
                headers=headers,
                json_data=verify_data,
                proxy_url=proxy_url or self.user_proxies.get(user_id) or self.get_current_proxy(),
                timeout=10
            )
            if response.status_code == 200:
                resp_json = response.json()
                rd = resp_json.get('responseData', {})
                eid_number = rd.get('eidNumber')
                name_from_response = rd.get('name') or name or "USER"
                dob_from_response = rd.get('dob') or rd.get('dateOfBirth') or rd.get('birthDate')
                if eid_number:
                    return True, eid_number, name_from_response, dob_from_response

                msg = rd.get('message') or (resp_json.get('errorDetails') or {}).get('messageEnglish') or 'Invalid OTP'
                return False, None, msg, None
            else:
                return False, None, f"HTTP {response.status_code}", None
        except Exception as e:
            return False, None, str(e), None

    def auto_send_aadhaar_otp(self, user_id, eid_number, max_retries=5):
        """
        Generates the Phase 2 download OTP using the EID.
        Returns exactly 6 items: (ok, otp_txn_id, code, c_txn, t_id, error_message)
        """
        last_error = "Failed to solve captcha"
        for attempt in range(1, max_retries + 1):
            img_bytes, c_txn, t_id = self.get_captcha(user_id)
            if not img_bytes:
                self.rotate_proxy()
                continue

            code = self.solve_captcha(img_bytes)
            if not code or len(code) != 6:
                continue

            proxy_used = self.user_proxies.get(user_id)
            logger.info(f"Auto-solved Captcha for Aadhaar OTP (attempt {attempt}): {code}")
            ok, otp_txn_id, msg = self.send_aadhaar_otp(user_id, eid_number, code, c_txn, t_id, proxy_url=proxy_used)
            if ok:
                return True, otp_txn_id, code, c_txn, t_id, None
            last_error = str(msg)
            if "invalid" in last_error.lower() or "deactivated" in last_error.lower():
                return False, None, None, None, None, last_error

        return False, None, None, None, None, last_error

    def send_aadhaar_otp(self, user_id, eid_number, captcha_value, captcha_txn_id, transaction_id, proxy_url=None):
        req_txn = f"MYAADHAAR:{uuid.uuid4()}"
        headers = dict(self.base_headers)
        headers['X-Request-ID'] = req_txn
        headers['transactionId'] = req_txn
        otp_request_data = {
            'eidNumber': str(eid_number),
            'idType': 'eid',
            'captchaTxnId': captcha_txn_id,
            'captchaValue': captcha_value,
            'transactionId': req_txn,
        }
        try:
            response = uidai_post(
                'https://tathya.uidai.gov.in/unifiedAppAuthService/api/v2/generate/aadhaar/otp',
                headers=headers,
                json_data=otp_request_data,
                proxy_url=proxy_url or self.user_proxies.get(user_id) or self.get_current_proxy(),
                timeout=10
            )
            if response.status_code == 200:
                resp_json = response.json()
                otp_txn_id = resp_json.get('txnId')
                status = resp_json.get('status')
                message = resp_json.get('message') or resp_json.get('statusMessage')
                if status == "Success" or otp_txn_id:
                    return True, otp_txn_id, message
                return False, None, message
            else:
                return False, None, f"HTTP {response.status_code}"
        except Exception as e:
            return False, None, str(e)

    def extract_pdf_data(self, raw_content: bytes):
        """Extracts PDF bytes whether sent as raw PDF, ZIP archive, or Base64 inside JSON."""
        if not raw_content:
            return None
        if raw_content[:4] == b"%PDF":
            return raw_content
        if raw_content[:2] == b"PK":
            try:
                with zipfile.ZipFile(BytesIO(raw_content)) as z:
                    for name in z.namelist():
                        if name.lower().endswith(".pdf"):
                            return z.read(name)
            except Exception as e:
                logger.warning(f"ZIP extract error: {e}")

        # JSON parsing fallback
        idx1 = raw_content.find(b'{')
        idx2 = raw_content.rfind(b'}')
        if idx1 != -1 and idx2 != -1:
            raw_json = raw_content[idx1:idx2 + 1]
        else:
            raw_json = raw_content

        def _find_b64_pdf(obj):
            if isinstance(obj, str):
                s = obj.strip()
                if s.startswith("JVBERi") or s.startswith("data:application/pdf"):
                    return s
                if len(s) > 1000:
                    try:
                        if base64.b64decode(s[:20] + "==").startswith(b"%PDF"):
                            return s
                    except Exception:
                        pass
                return None
            if isinstance(obj, dict):
                for k in ("aadhaarPdf", "pdfBase64", "aadhaarPdfBase64", "pdfData", "pdf", "file", "base64", "document", "data"):
                    if k in obj:
                        res = _find_b64_pdf(obj[k])
                        if res:
                            return res
                for v in obj.values():
                    if isinstance(v, (dict, list)):
                        res = _find_b64_pdf(v)
                        if res:
                            return res
            elif isinstance(obj, list):
                for item in obj:
                    res = _find_b64_pdf(item)
                    if res:
                        return res
            return None

        try:
            parsed = json.loads(raw_json.decode("utf-8", errors="replace"))
            b64 = _find_b64_pdf(parsed)
            if b64:
                if b64.startswith("data:"):
                    b64 = b64.split(",", 1)[1]
                return base64.b64decode(b64)
        except Exception as e:
            logger.warning(f"JSON PDF decode error: {e}")

        return None

    def download_aadhaar_pdf(self, user_id, eid_number, otp, otp_txn_id, transaction_id=None, mask=False, sticky_proxy=None):
        """Downloads the Aadhaar PDF using appid=MYAADHAARREVAMP via fast libcurl."""
        headers = dict(self.base_headers)
        headers["appid"] = "MYAADHAARREVAMP"
        headers["X-Request-ID"] = str(uuid.uuid4())
        
        download_data = {
            'eid': str(eid_number),
            'mask': mask,
            'otp': str(otp),
            'otpTxnId': str(otp_txn_id)
        }

        # Sticky proxy matching the session
        sticky_target = sticky_proxy or self.user_proxies.get(user_id)
        proxy_candidates = [sticky_target] if sticky_target else []
        proxy_candidates += [p for p in self.proxies if p not in proxy_candidates]

        last_err = None
        for proxy_url in proxy_candidates[:3]:
            try:
                logger.info(f"Downloading Aadhaar PDF via proxy: {proxy_url}")
                response = uidai_post(
                    'https://tathya.uidai.gov.in/downloadAadhaarService/api/aadhaar/download',
                    headers=headers,
                    json_data=download_data,
                    proxy_url=proxy_url,
                    timeout=90
                )
                logger.info(f"Download response from {proxy_url}: status={response.status_code}, content_len={len(response.content) if response.content else 0}")
                if response.status_code == 200 and response.content:
                    pdf_bytes = self.extract_pdf_data(response.content)
                    if pdf_bytes and len(pdf_bytes) > 1000:
                        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
                        tmp.write(pdf_bytes)
                        tmp.close()
                        logger.info(f"Successfully extracted Aadhaar PDF ({len(pdf_bytes)} bytes) to {tmp.name}")
                        return True, tmp.name

                    try:
                        resp_json = response.json()
                        err = (resp_json.get('errorDetails') or {}).get('messageEnglish') or resp_json.get('message') or resp_json.get('errorMessage') or resp_json.get('statusMessage') or "Failed to retrieve PDF"
                        if isinstance(err, (dict, list)) or len(str(err)) > 200:
                            err = "Failed to parse downloaded document"
                        logger.warning(f"Download returned JSON error: {err}")
                        return False, str(err)
                    except Exception:
                        logger.warning(f"Failed to parse download response: {response.content[:200] if response.content else 'empty'}")
                        return False, "Failed to parse downloaded document"
                else:
                    last_err = f"HTTP {response.status_code}"
                    logger.warning(f"Download non-200 on {proxy_url}: {last_err}")
            except Exception as e:
                last_err = str(e)
                logger.warning(f"Download fail on {proxy_url}: {e}")

        return False, last_err or "Download failed"

    def crack_pdf_with_name(self, pdf_path, name, birth_year=None, progress_callback=None):
        return self.cracker.crack_pdf(pdf_path, name, birth_year, progress_callback)


bot_api = AadhaarBot(proxy_url=os.environ.get("PROXY_URL", "").strip() or None)

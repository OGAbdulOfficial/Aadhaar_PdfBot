import os
import sys
import base64
import uuid
import logging
import tempfile
import requests
from datetime import datetime
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor
import PyPDF2
import ddddocr

logger = logging.getLogger(__name__)

# ============== SESSION FACTORY ==============
def get_uidai_session(use_proxy=False, proxy_string=None):
    session = requests.Session()
    session.mount('https://', requests.adapters.HTTPAdapter(
        pool_connections=5, pool_maxsize=10, max_retries=3, pool_block=False
    ))
    if use_proxy and proxy_string:
        parsed = urlparse(proxy_string)
        proxy_url = f"{parsed.scheme}://{parsed.netloc}"
        session.proxies = {'http': proxy_url, 'https': proxy_url}
        logger.info(f"UIDAI Session configured with proxy: {proxy_url}")
    return session

# ============== PDF PASSWORD CRACKER ==============
class PDFPasswordCracker:
    def __init__(self, max_workers=4):
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.found_password = None
        self.stop_flag = False

    def try_password(self, pdf_path, password):
        try:
            with open(pdf_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                if pdf_reader.decrypt(password):
                    return True, password
                return False, None
        except Exception:
            return False, None

    def decrypt_pdf(self, pdf_path, password, output_path=None):
        try:
            if output_path is None:
                # Use a secure temp file to prevent disk leaks
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
            logger.info(f"Decrypted PDF written to: {output_path}")
            return output_path
        except Exception as e:
            logger.error(f"Error decrypting PDF: {e}")
            return None

    def crack_pdf(self, pdf_path, name, birth_year=None, progress_callback=None):
        """
        Cracks standard UIDAI e-Aadhaar PDF.
        Priority 1: If birth_year provided, test immediately (instant).
        Priority 2: Common birth years (1950 - 2026).
        """
        self.found_password = None
        self.stop_flag = False
        
        name_clean = "".join(ch for ch in (name or "USER").upper() if ch.isalnum())
        prefix = name_clean[:4] if len(name_clean) >= 4 else name_clean.ljust(4, 'X')
        
        # Priority 1: User specified birth year
        if birth_year and str(birth_year).isdigit():
            pwd = f"{prefix}{birth_year}"
            ok, _ = self.try_password(pdf_path, pwd)
            if ok:
                decrypted_path = self.decrypt_pdf(pdf_path, pwd)
                return True, pwd, decrypted_path

        # Generate candidates
        current_year = datetime.now().year
        candidate_years = list(range(1960, current_year + 1)) + list(range(1930, 1960))
        passwords = [f"{prefix}{y}" for y in candidate_years]

        # Fast parallel evaluation in small batches
        batch_size = 25
        for i in range(0, len(passwords), batch_size):
            if self.stop_flag:
                break
            batch = passwords[i:i + batch_size]
            futures = [self.executor.submit(self.try_password, pdf_path, p) for p in batch]
            for fut in futures:
                try:
                    success, found_pwd = fut.result(timeout=1.5)
                    if success:
                        self.found_password = found_pwd
                        self.stop_flag = True
                        decrypted_path = self.decrypt_pdf(pdf_path, found_pwd)
                        return True, found_pwd, decrypted_path
                except Exception:
                    continue

        return False, None, None

# ============== AADHAAR BOT CLASS ==============
class AadhaarBot:
    def __init__(self, proxy_url=None):
        self.session = get_uidai_session(use_proxy=bool(proxy_url), proxy_string=proxy_url)
        self.base_headers = {
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en_IN',
            'Connection': 'keep-alive',
            'Content-Type': 'application/json',
            'Origin': 'https://myaadhaar.uidai.gov.in',
            'Referer': 'https://myaadhaar.uidai.gov.in/',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-site',
            'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36',
            'appid': 'MYAADHAAR',
            'sec-ch-ua': '"Not-A.Brand";v="99", "Chromium";v="124"',
            'sec-ch-ua-mobile': '?1',
            'sec-ch-ua-platform': '"Android"',
        }
        self.session.headers.update(self.base_headers)
        self.cracker = PDFPasswordCracker()
        try:
            self.ocr = ddddocr.DdddOcr(show_ad=False)
        except Exception as e:
            logger.error(f"Failed to initialize OCR: {e}")
            self.ocr = None
        logger.info("AadhaarBot initialized with Auto-Captcha OCR")

    def solve_captcha(self, image_bytes):
        if not image_bytes or not self.ocr:
            return None
        try:
            res = self.ocr.classification(image_bytes)
            return res.strip() if res else None
        except Exception as e:
            logger.error(f"Error solving captcha: {e}")
            return None

    def auto_send_eid_otp(self, user_id, mobile, name, max_retries=3):
        """
        Automatically gets UIDAI captcha, solves it via OCR, and requests EID OTP.
        Retries up to max_retries if UIDAI rejects the captcha.
        Returns: (success, otp_txn_id, captcha_code, captcha_txn_id, transaction_id, error_message)
        """
        last_error = "Failed to solve captcha"
        for attempt in range(1, max_retries + 1):
            img_bytes, c_txn, t_id = self.get_captcha(user_id)
            if not img_bytes:
                last_error = "UIDAI captcha server unreachable"
                continue
            code = self.solve_captcha(img_bytes)
            if not code or len(code) < 4:
                continue
            logger.info(f"Auto-solved Captcha for Mobile (attempt {attempt}): {code}")
            ok, res = self.send_eid_otp(user_id, mobile, name, code, c_txn, t_id)
            if ok:
                return True, res, code, c_txn, t_id, None
            last_error = str(res)
            # If it's not a captcha error (e.g. invalid mobile, no record), don't retry endlessly
            if "record" in last_error.lower() or "mobile" in last_error.lower():
                return False, None, None, None, None, last_error
        return False, None, None, None, None, last_error

    def auto_send_aadhaar_otp(self, user_id, eid_number, max_retries=3):
        """
        Automatically gets UIDAI captcha, solves it via OCR, and requests Aadhaar/EID OTP.
        """
        last_error = "Failed to solve captcha"
        for attempt in range(1, max_retries + 1):
            img_bytes, c_txn, t_id = self.get_captcha(user_id)
            if not img_bytes:
                last_error = "UIDAI captcha server unreachable"
                continue
            code = self.solve_captcha(img_bytes)
            if not code or len(code) < 4:
                continue
            logger.info(f"Auto-solved Captcha for Aadhaar OTP (attempt {attempt}): {code}")
            ok, otp_txn_id, msg = self.send_aadhaar_otp(user_id, eid_number, code, c_txn, t_id)
            if ok:
                return True, otp_txn_id, code, c_txn, t_id, None
            last_error = str(msg)
            if "invalid aadhaar" in last_error.lower():
                return False, None, None, None, None, last_error
        return False, None, None, None, None, last_error

    def generate_transaction_id(self):
        return str(uuid.uuid4())

    def is_base64(self, s):
        if not isinstance(s, str) or len(s) < 100:
            return False
        if s.startswith('data:'):
            s = s.split(',')[1] if ',' in s else s
        if len(s) % 4 != 0:
            return False
        try:
            base64.b64decode(s)
            return True
        except Exception:
            return False

    def detect_file_type(self, file_bytes):
        if file_bytes[:4] == b'%PDF':
            return 'pdf'
        elif file_bytes[:8] == b'\x89PNG\r\n\x1a\n':
            return 'png'
        elif file_bytes[:2] == b'\xff\xd8':
            return 'jpg'
        return 'unknown'

    def detect_and_decode_base64(self, data, field_name="unknown"):
        """Extracts decoded bytes without saving to disk unnecessarily."""
        decoded_items = []
        if isinstance(data, dict):
            for key, value in list(data.items()):
                if isinstance(value, str) and len(value) > 100 and self.is_base64(value):
                    try:
                        clean_base64 = value.split(',')[1] if value.startswith('data:') and ',' in value else value
                        decoded_bytes = base64.b64decode(clean_base64)
                        file_type = self.detect_file_type(decoded_bytes)
                        decoded_items.append({'field': key, 'type': file_type, 'size': len(decoded_bytes), 'data': decoded_bytes})
                    except Exception as e:
                        logger.error(f"Base64 decode error: {e}")
                if isinstance(value, (dict, list)):
                    decoded_items.extend(self.detect_and_decode_base64(value, f"{field_name}.{key}"))
        elif isinstance(data, list):
            for idx, item in enumerate(data):
                if isinstance(item, (dict, list)):
                    decoded_items.extend(self.detect_and_decode_base64(item, f"{field_name}[{idx}]"))
        return decoded_items

    def get_captcha(self, user_id):
        transaction_id = self.generate_transaction_id()
        self.session.headers.update({'x-request-id': transaction_id, 'transactionId': transaction_id})
        captcha_data = {'captchaLength': '6', 'captchaType': '2', 'audioCaptchaRequired': True}
        try:
            response = self.session.post(
                'https://tathya.uidai.gov.in/audioCaptchaService/api/captcha/v3/generation',
                json=captcha_data, timeout=15
            )
            if response.status_code != 200:
                return None, None, None
            resp_json = response.json()
            captcha_txn_id = resp_json.get('transactionId')
            captcha_base64 = resp_json.get('imageBase64')
            if not captcha_base64:
                for key, value in resp_json.items():
                    if isinstance(value, str) and len(value) > 100 and self.is_base64(value):
                        captcha_base64 = value
                        break
            if not captcha_base64:
                return None, None, None
            if captcha_base64.startswith('data:image'):
                captcha_base64 = captcha_base64.split(',')[1]
            image_bytes = base64.b64decode(captcha_base64)
            return image_bytes, captcha_txn_id, transaction_id
        except Exception as e:
            logger.error(f"Error getting captcha: {str(e)}")
            return None, None, None

    def send_aadhaar_otp(self, user_id, eid_number, captcha_value, captcha_txn_id, transaction_id):
        self.session.headers.update({'x-request-id': transaction_id, 'transactionId': transaction_id})
        otp_request_data = {
            'eidNumber': eid_number, 'idType': 'eid',
            'captchaTxnId': captcha_txn_id, 'captchaValue': captcha_value,
            'transactionId': transaction_id, 'resendOTP': False
        }
        try:
            response = self.session.post(
                'https://tathya.uidai.gov.in/unifiedAppAuthService/api/v2/generate/aadhaar/otp',
                json=otp_request_data, timeout=15
            )
            if response.status_code == 200:
                resp_json = response.json()
                otp_txn_id = resp_json.get('txnId')
                status = resp_json.get('status')
                message = resp_json.get('message')
                if otp_txn_id and status == "Success":
                    return True, otp_txn_id, message
                else:
                    return False, None, message
            else:
                return False, None, f"HTTP {response.status_code}"
        except Exception as e:
            return False, None, str(e)

    def download_aadhaar_pdf(self, user_id, eid_number, otp, otp_txn_id, transaction_id, mask=False):
        self.session.headers.update({'x-request-id': transaction_id, 'transactionId': transaction_id})
        download_data = {'eid': eid_number, 'mask': mask, 'otp': otp, 'otpTxnId': otp_txn_id}
        try:
            response = self.session.post(
                'https://tathya.uidai.gov.in/downloadAadhaarService/api/aadhaar/download',
                json=download_data, timeout=20
            )
            if response.status_code == 200:
                resp_json = response.json()
                decoded_files = self.detect_and_decode_base64(resp_json, "aadhaar_download")
                for f in decoded_files:
                    if f.get('type') == 'pdf':
                        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
                        tmp.write(f['data'])
                        tmp.close()
                        return True, tmp.name
                
                error_msg = resp_json.get('message', resp_json.get('errorMessage', 'No PDF data found'))
                return False, error_msg
            else:
                return False, f"HTTP {response.status_code}"
        except Exception as e:
            return False, str(e)

    def send_eid_otp(self, user_id, mobile, name, captcha_code, captcha_txn_id, transaction_id):
        self.session.headers.update({'x-request-id': transaction_id, 'transactionId': transaction_id})
        request_data = {
            'mobileNumber': mobile, 'dob': None, 'email': None,
            'name': name.upper(), 'option': 'EID', 'otp': None,
            'otpTxnId': None, 'captchaTxnId': captcha_txn_id,
            'captcha': captcha_code, 'resendOtp': False
        }
        try:
            response = self.session.post(
                'https://tathya.uidai.gov.in/retrieveEidUid/ext/v1/generic/retrieveuideid',
                json=request_data, timeout=15
            )
            if response.status_code == 200:
                resp_json = response.json()
                if 'responseData' in resp_json:
                    response_data = resp_json['responseData']
                    otp_txn_id = response_data.get('otpTxnId')
                    status = response_data.get('status')
                    if otp_txn_id and status == "Success":
                        return True, otp_txn_id
                    else:
                        return False, response_data.get('message', 'Unknown error')
                return False, 'Invalid response structure'
            else:
                return False, f'HTTP {response.status_code}'
        except Exception as e:
            return False, str(e)

    def verify_eid_otp(self, user_id, mobile, name, otp_code, otp_txn_id, captcha_txn_id, captcha_code):
        self.session.headers.update({'x-request-id': self.generate_transaction_id()})
        verify_data = {
            'mobileNumber': mobile, 'dob': None, 'name': name.upper(),
            'email': None, 'option': 'EID', 'otp': otp_code,
            'otpTxnId': otp_txn_id, 'captchaTxnId': captcha_txn_id,
            'captcha': captcha_code, 'resendOtp': False
        }
        try:
            response = self.session.post(
                'https://tathya.uidai.gov.in/retrieveEidUid/ext/v1/generic/retrieveuideid',
                json=verify_data, timeout=15
            )
            if response.status_code == 200:
                resp_json = response.json()
                if resp_json.get('status') in [200, "Success", True]:
                    if 'responseData' in resp_json:
                        response_data = resp_json['responseData']
                        eid_number = response_data.get('eidNumber')
                        name_from_response = response_data.get('name', name)
                        if eid_number:
                            return True, eid_number, name_from_response
                        return False, None, "No EID found"
                    return False, None, "Invalid response"
                else:
                    error_msg = resp_json.get('errorDetails', {}).get('messageEnglish', 'Verification failed')
                    return False, None, error_msg
            else:
                return False, None, f'HTTP {response.status_code}'
        except Exception as e:
            return False, None, str(e)

    def crack_pdf_with_name(self, pdf_path, name, birth_year=None, progress_callback=None):
        return self.cracker.crack_pdf(pdf_path, name, birth_year, progress_callback)

bot_api = AadhaarBot()

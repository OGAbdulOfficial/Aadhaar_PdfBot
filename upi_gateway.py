import os
import io
import requests
import logging
import qrcode
from typing import Optional, Dict, Any, Tuple

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://upi-email-verifier.abdulstoreapi.workers.dev"
DEFAULT_VPA = "faisal786786@fam"
DEFAULT_NAME = "Faisal Abdul Aziz Ansari"

class UPIGateway:
    def __init__(self, base_url: Optional[str] = None):
        self.base_url = (base_url or os.getenv("UPI_BASE_URL", DEFAULT_BASE_URL)).rstrip('/')
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "AadhaarPDFBot-PaymentClient/2.0",
            "Accept": "application/json"
        })

    def generate_payment(self, amount: float) -> Tuple[bool, Dict[str, Any]]:
        """
        Calls GET /pay/{amount} to obtain payment deep link, web checkout, and metadata.
        """
        url = f"{self.base_url}/pay/{amount}"
        try:
            resp = self.session.get(url, timeout=12)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "success":
                    return True, data
            logger.warning(f"Failed to generate payment from gateway: {resp.status_code} {resp.text}")
        except Exception as e:
            logger.error(f"Error calling /pay/{amount}: {e}")
        
        # Fallback offline UPI intent link generator
        fallback_link = f"upi://pay?pa={DEFAULT_VPA}&pn={requests.utils.quote(DEFAULT_NAME)}&am={amount}&cu=INR"
        return True, {
            "status": "success",
            "amount": amount,
            "currency": "INR",
            "payee_vpa": DEFAULT_VPA,
            "payee_name": DEFAULT_NAME,
            "upi_link": fallback_link,
            "qr_image_url": f"{self.base_url}/qr/{amount}",
            "checkout_page": f"{self.base_url}/pay/{amount}"
        }

    def generate_qr_bytes(self, upi_link: str) -> bytes:
        """
        Generates high-contrast scannable PNG QR code bytes for Telegram send_photo.
        """
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=2,
        )
        qr.add_data(upi_link)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        
        bio = io.BytesIO()
        img.save(bio, format="PNG")
        bio.seek(0)
        return bio.getvalue()

    def verify_utr(self, utr: str) -> Tuple[bool, Dict[str, Any]]:
        """
        Verifies 12-digit UPI transaction reference (UTR) with the Cloudflare Worker.
        Returns (is_verified, response_dict).
        """
        clean_utr = str(utr).strip()
        if not clean_utr.isdigit() or len(clean_utr) != 12:
            return False, {"status": "error", "message": "UTR must be exactly 12 numeric digits."}
            
        url = f"{self.base_url}/verify/{clean_utr}"
        try:
            resp = self.session.get(url, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "success":
                    return True, data
                elif data.get("status") == "pending":
                    return False, {"status": "pending", "message": "Payment not yet received or still processing."}
                else:
                    return False, data
            else:
                return False, {"status": "error", "message": f"Gateway HTTP {resp.status_code}"}
        except Exception as e:
            logger.error(f"Error verifying UTR {clean_utr}: {e}")
            return False, {"status": "error", "message": str(e)}

    def check_recent_payment(self, amount: float) -> Tuple[bool, Dict[str, Any]]:
        """
        Polls GET /check-payment/{amount} to check if a payment for this amount arrived in the last 10 minutes.
        """
        url = f"{self.base_url}/check-payment/{amount}"
        try:
            resp = self.session.get(url, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "success" and data.get("paid"):
                    return True, data
                return False, data
            return False, {"status": "pending", "paid": False}
        except Exception as e:
            logger.error(f"Error polling /check-payment/{amount}: {e}")
            return False, {"status": "error", "message": str(e)}

gateway = UPIGateway()


import firebase_admin
from firebase_admin import auth
from firebase_admin._auth_utils import InvalidIdTokenError, ExpiredIdTokenError

def verify_firebase_token(id_token: str):
    try:
        decoded_token = auth.verify_id_token(id_token)
        return decoded_token
    except (InvalidIdTokenError, ExpiredIdTokenError):
        return None
    except Exception:
        return None
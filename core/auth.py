import os
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from core import config_manager
from core.utils import resource_path

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/documents',
    'https://www.googleapis.com/auth/drive'
]

TOKEN_PATH = os.path.join(config_manager.APP_DATA_DIR, 'token.json')
CLIENT_SECRET_PATH = resource_path('client_secret.json')

def get_credentials():
    """
    OAuth 2.0 방식으로 인증 (기본 방식)
    """
    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                print("OAuth 2.0 토큰 갱신 성공")
            except Exception as e:
                print(f"OAuth 2.0 토큰 갱신 실패: {e}")
                print("새로운 인증이 필요합니다.")
                creds = None
        
        if not creds:
            flow = InstalledAppFlow.from_client_secrets_file(
                CLIENT_SECRET_PATH, SCOPES)
            creds = flow.run_local_server(port=0)
            print("OAuth 2.0 새 인증 완료")
        
        with open(TOKEN_PATH, 'w') as token:
            token.write(creds.to_json())
    
    return creds

from googleapiclient.discovery import build
from core.auth import get_credentials
from core import config_manager
import datetime
import base64
import requests
import markdown
import os # os 모듈 임포트

def get_services():
    creds = get_credentials()
    docs_service = build('docs', 'v1', credentials=creds)
    sheets_service = build('sheets', 'v4', credentials=creds)
    drive_service = build('drive', 'v3', credentials=creds)
    return docs_service, sheets_service, drive_service

def save_memo(title, markdown_content):
    docs_service, sheets_service, drive_service = get_services()
    SPREADSHEET_ID = config_manager.get_setting('Google', 'spreadsheet_id')
    MEMO_FOLDER_ID = config_manager.get_setting('Google', 'folder_id')
    try:
        doc_body = {'title': title}
        doc = docs_service.documents().create(body=doc_body).execute()
        doc_id = doc.get('documentId')

        if MEMO_FOLDER_ID:
            file = drive_service.files().get(fileId=doc_id, fields='parents').execute()
            previous_parents = ",".join(file.get('parents'))
            drive_service.files().update(
                fileId=doc_id, addParents=MEMO_FOLDER_ID,
                removeParents=previous_parents, fields='id, parents').execute()

        requests_body = [{'insertText': {'location': {'index': 1}, 'text': markdown_content}}]
        docs_service.documents().batchUpdate(documentId=doc_id, body={'requests': requests_body}).execute()
        
        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        row_data = [title, now, doc_id]
        sheets_service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID, range='A1', valueInputOption='USER_ENTERED',
            insertDataOption='INSERT_ROWS', body={'values': [row_data]}).execute()
        return True
    except Exception as e:
        print(f"메모 저장 중 오류 발생: {e}")
        return False

def update_memo(doc_id, new_title, markdown_content):
    docs_service, sheets_service, drive_service = get_services()
    SPREADSHEET_ID = config_manager.get_setting('Google', 'spreadsheet_id')
    try:
        doc = docs_service.documents().get(documentId=doc_id).execute()
        end_index = doc.get('body').get('content')[-1].get('endIndex') - 1
        
        requests_body = []
        if end_index > 1:
            requests_body.append({'deleteContentRange': {'range': {'startIndex': 1, 'endIndex': end_index}}})
        requests_body.append({'insertText': {'location': {'index': 1}, 'text': markdown_content}})

        if requests_body:
            docs_service.documents().batchUpdate(documentId=doc_id, body={'requests': requests_body}).execute()
        
        drive_service.files().update(fileId=doc_id, body={'name': new_title}).execute()

        result = sheets_service.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range='C:C').execute()
        values = result.get('values', []); row_number = -1
        for i, row in enumerate(values):
            if row and row[0] == doc_id: row_number = i + 1; break
        if row_number != -1:
            sheets_service.spreadsheets().values().update(
                spreadsheetId=SPREADSHEET_ID, range=f'A{row_number}',
                valueInputOption='USER_ENTERED', body={'values': [[new_title]]}).execute()
        return True
    except Exception as e:
        print(f"메모 업데이트 중 오류 발생: {e}")
        return False

import markdown

# get_credentials, get_services 함수는 기존과 동일하다고 가정합니다.
# from your_google_api_setup import get_credentials, get_services

def load_doc_content(doc_id, as_html=True, body_only=False):
    docs_service, _, _ = get_services()
    try:
        doc = docs_service.documents().get(documentId=doc_id).execute()
        title = doc.get('title', '제목 없음')
        
        plain_text_parts = []
        body_content = doc.get('body').get('content')
        for element in body_content:
            if 'paragraph' in element:
                for pe in element.get('paragraph').get('elements', []):
                    if 'textRun' in pe:
                        plain_text_parts.append(pe.get('textRun').get('content', ''))
        
        plain_text = "".join(plain_text_parts)

        if not as_html:
            return title, plain_text.strip()
            
        # --- HTML 변환 로직 ---
        html_body = markdown.markdown(plain_text, extensions=['fenced_code', 'codehilite', 'tables', 'nl2br', 'sane_lists'])
        
        print(f"문서 ID '{doc_id}'의 HTML 본문 생성 성공!")
        return title, html_body

    except Exception as e:
        print(f"문서 내용 변환 중 오류 발생: {e}")
        return "오류", "<p>내용을 불러올 수 없습니다.</p>"

def load_memo_list():
    docs_service, sheets_service, drive_service = get_services()
    SPREADSHEET_ID = config_manager.get_setting('Google', 'spreadsheet_id')
    try:
        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID, range='A2:C').execute()
        values = result.get('values', [])
        print(f"로컬 캐시용 전체 목록 로딩 성공! {len(values)}개 항목.")
        return values
    except Exception as e:
        print(f"전체 목록 로딩 중 오류 발생: {e}")
        return []

def search_memos_by_content(query=None, page_token=None):
    docs_service, sheets_service, drive_service = get_services()
    MEMO_FOLDER_ID = config_manager.get_setting('Google', 'folder_id')
    PAGE_SIZE = int(config_manager.get_setting('Display', 'page_size'))
    try:
        search_query = f"mimeType='application/vnd.google-apps.document' and '{MEMO_FOLDER_ID}' in parents and trashed=false"
        request_params = {'q': search_query, 'spaces': 'drive',
                          'fields': 'nextPageToken, files(id, name, createdTime)', 'pageSize': PAGE_SIZE}
        if page_token: request_params['pageToken'] = page_token
        if query:
            sanitized_query = query.replace("'", "\\'"); search_query += f" and fullText contains '{sanitized_query}'"
            request_params['q'] = search_query
        else: request_params['orderBy'] = 'createdTime desc'
        response = drive_service.files().list(**request_params).execute()
        files = response.get('files', []); next_page_token = response.get('nextPageToken', None)
        values = []
        for file in files:
            created_time_str = file.get('createdTime').split('T')[0]
            values.append([file.get('name'), created_time_str, file.get('id')])
        return values, next_page_token
    except Exception as e:
        print(f"본문 검색 중 오류 발생: {e}")
        return [], None

def delete_memo(doc_id, row_index=None):
    creds = get_credentials()
    SPREADSHEET_ID = config_manager.get_setting('Google', 'spreadsheet_id')
    try:
        sheets_service = build('sheets', 'v4', credentials=creds)
        drive_service = build('drive', 'v3', credentials=creds)

        # 1. (필요 시) 문서 ID를 기반으로 시트의 행 번호 찾기
        if row_index is None:
            print(f"'{doc_id}'의 행 번호를 찾는 중...")
            # C열(문서 ID가 있는 열)의 모든 값을 가져옵니다.
            result = sheets_service.spreadsheets().values().get(
                spreadsheetId=SPREADSHEET_ID, range='C:C').execute()
            values = result.get('values', [])
            
            found_row = -1
            for i, row in enumerate(values):
                if row and row[0] == doc_id:
                    # 인덱스는 0부터 시작하지만, 시트 API는 1부터 시작하므로 +1
                    found_row = i + 1
                    break
            
            if found_row == -1:
                print("경고: 시트에서 해당 문서 ID를 찾지 못했습니다. 드라이브 파일만 삭제합니다.")
            else:
                row_index = found_row
                print(f"행 번호 {row_index}를 찾았습니다.")

        # 2. 구글 시트에서 해당 행 삭제 (row_index가 있을 경우에만)
        if row_index is not None:
            spreadsheet_metadata = sheets_service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
            sheet_id = spreadsheet_metadata['sheets'][0]['properties']['sheetId']
            
            request_body = {
                'requests': [{'deleteDimension': {
                    'range': {
                        'sheetId': sheet_id,
                        'dimension': 'ROWS',
                        # API는 0-based index를 사용하므로, 1-based인 row_index에서 1을 빼줍니다.
                        'startIndex': row_index - 1,
                        'endIndex': row_index
                    }
                }}]
            }
            sheets_service.spreadsheets().batchUpdate(
                spreadsheetId=SPREADSHEET_ID, body=request_body).execute()
            print(f"시트의 {row_index}행 삭제 완료.")

        # 3. 구글 드라이브에서 실제 문서 파일 삭제
        drive_service.files().delete(fileId=doc_id).execute()
        print(f"드라이브 파일 '{doc_id}' 삭제 완료!")
        
        return True
    except Exception as e:
        print(f"메모 삭제 중 오류 발생: {e}")
        return False
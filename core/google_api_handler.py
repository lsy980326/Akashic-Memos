from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from core.auth import get_credentials
from core import config_manager
import datetime
import markdown
import os
import re
import uuid

def get_services():
    creds = get_credentials()
    docs_service = build('docs', 'v1', credentials=creds)
    sheets_service = build('sheets', 'v4', credentials=creds)
    drive_service = build('drive', 'v3', credentials=creds)
    return docs_service, sheets_service, drive_service

IMAGE_FOLDER_NAME = "Akashic Records Images"
IMAGE_FOLDER_ID = None

def _get_or_create_image_folder(drive_service):
    global IMAGE_FOLDER_ID
    if IMAGE_FOLDER_ID:
        return IMAGE_FOLDER_ID
    
    MEMO_FOLDER_ID = config_manager.get_setting('Google', 'folder_id')
    q = f"name='{IMAGE_FOLDER_NAME}' and mimeType='application/vnd.google-apps.folder' and '{MEMO_FOLDER_ID}' in parents and trashed=false"
    response = drive_service.files().list(q=q, spaces='drive', fields='files(id)').execute()
    files = response.get('files', [])
    
    if files:
        IMAGE_FOLDER_ID = files[0].get('id')
        return IMAGE_FOLDER_ID
    else:
        file_metadata = {
            'name': IMAGE_FOLDER_NAME,
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [MEMO_FOLDER_ID]
        }
        file = drive_service.files().create(body=file_metadata, fields='id').execute()
        IMAGE_FOLDER_ID = file.get('id')
        return IMAGE_FOLDER_ID

def _upload_image_to_drive(drive_service, image_path):
    try:
        image_folder_id = _get_or_create_image_folder(drive_service)
        
        file_name = os.path.basename(image_path)
        unique_file_name = f"{uuid.uuid4()}_{file_name}"

        file_metadata = {'name': unique_file_name, 'parents': [image_folder_id]}
        media = MediaFileUpload(image_path, mimetype='image/jpeg') # MimeType can be more dynamic
        
        file = drive_service.files().create(body=file_metadata, media_body=media, fields='id, webContentLink').execute()
        
        # Make the file publicly readable
        permission = {'type': 'anyone', 'role': 'reader'}
        drive_service.permissions().create(fileId=file.get('id'), body=permission).execute()
        
        # Re-fetch the file to get the updated webContentLink
        updated_file = drive_service.files().get(fileId=file.get('id'), fields='webContentLink').execute()
        return updated_file.get('webContentLink')
    except Exception as e:
        print(f"이미지 업로드 실패: {image_path}, 오류: {e}")
        return None

def _process_images_for_upload(drive_service, markdown_content):
    # Regex to find markdown image tags with local paths
    # It should not match http/https links
    pattern = re.compile(r'\!\\\[(.*?)\]\((?!https?://)(.*?)\)')
    
    new_content = markdown_content
    matches = pattern.finditer(markdown_content)
    
    for match in matches:
        alt_text = match.group(1)
        local_path = match.group(2)
        
        if os.path.exists(local_path):
            print(f"로컬 이미지 발견: {local_path}")
            image_url = _upload_image_to_drive(drive_service, local_path)
            if image_url:
                print(f"업로드 성공: {image_url}")
                # Replace the local path with the new URL in the content
                original_tag = f"![{alt_text}]({local_path})"
                new_tag = f"![{alt_text}]({image_url})"
                new_content = new_content.replace(original_tag, new_tag)
        else:
            print(f"이미지 경로를 찾을 수 없음: {local_path}")
            
    return new_content

def save_memo(title, markdown_content, tags_text):
    docs_service, sheets_service, drive_service = get_services()
    SPREADSHEET_ID = config_manager.get_setting('Google', 'spreadsheet_id')
    MEMO_FOLDER_ID = config_manager.get_setting('Google', 'folder_id')
    try:
        # Process images before saving
        processed_content = _process_images_for_upload(drive_service, markdown_content)

        doc_body = {'title': title}
        doc = docs_service.documents().create(body=doc_body).execute()
        doc_id = doc.get('documentId')

        if MEMO_FOLDER_ID:
            file = drive_service.files().get(fileId=doc_id, fields='parents').execute()
            previous_parents = ",".join(file.get('parents'))
            drive_service.files().update(
                fileId=doc_id, addParents=MEMO_FOLDER_ID,
                removeParents=previous_parents, fields='id, parents').execute()

        requests_body = [{'insertText': {'location': {'index': 1}, 'text': processed_content}}]
        if processed_content:
            docs_service.documents().batchUpdate(documentId=doc_id, body={'requests': requests_body}).execute()
        
        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        row_data = [title, now, doc_id, tags_text]
        sheets_service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID, range='A1', valueInputOption='USER_ENTERED',
            insertDataOption='INSERT_ROWS', body={'values': [row_data]}).execute()
        return True, doc_id
    except Exception as e:
        print(f"메모 저장 중 오류 발생: {e}")
        return False, None

def update_memo(doc_id, new_title, markdown_content, tags_text):
    docs_service, sheets_service, drive_service = get_services()
    SPREADSHEET_ID = config_manager.get_setting('Google', 'spreadsheet_id')
    try:
        # Process images before updating
        processed_content = _process_images_for_upload(drive_service, markdown_content)

        doc = docs_service.documents().get(documentId=doc_id).execute()
        end_index = doc.get('body').get('content')[-1].get('endIndex') - 1
        
        requests_body = []
        if end_index > 1:
            requests_body.append({'deleteContentRange': {'range': {'startIndex': 1, 'endIndex': end_index}}})
        
        if processed_content:
            requests_body.append({'insertText': {'location': {'index': 1}, 'text': processed_content}})

        if requests_body:
            docs_service.documents().batchUpdate(documentId=doc_id, body={'requests': requests_body}).execute()
        
        drive_service.files().update(fileId=doc_id, body={'name': new_title}).execute()

        result = sheets_service.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range='C:D').execute()
        values = result.get('values', []); row_number = -1
        for i, row in enumerate(values):
            if row and row[0] == doc_id: row_number = i + 1; break
        if row_number != -1:
            now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            sheets_service.spreadsheets().values().update(
                spreadsheetId=SPREADSHEET_ID, range=f'A{row_number}',
                valueInputOption='USER_ENTERED', body={'values': [[new_title, now]]}).execute()
            sheets_service.spreadsheets().values().update(
                spreadsheetId=SPREADSHEET_ID, range=f'D{row_number}',
                valueInputOption='USER_ENTERED', body={'values': [[tags_text]]}).execute()
        return True
    except Exception as e:
        print(f"메모 업데이트 중 오류 발생: {e}")
        return False

import markdown

# get_credentials, get_services 함수는 기존과 동일하다고 가정합니다.
# from your_google_api_setup import get_credentials, get_services

def load_doc_content(doc_id, as_html=True, body_only=False):
    docs_service, sheets_service, _ = get_services()
    SPREADSHEET_ID = config_manager.get_setting('Google', 'spreadsheet_id')
    try:
        # Request inlineObjects to get image data
        doc = docs_service.documents().get(documentId=doc_id, fields="title,body(content),inlineObjects").execute()
        title = doc.get('title', '제목 없음')
        
        plain_text_parts = []
        body_content = doc.get('body').get('content')
        
        # A map to hold image URLs by their object ID
        image_urls = {}
        if 'inlineObjects' in doc:
            for obj_id, obj_data in doc['inlineObjects'].items():
                img_props = obj_data.get('inlineObjectProperties', {}).get('embeddedObject', {}).get('imageProperties', {})
                if 'contentUri' in img_props:
                    image_urls[obj_id] = img_props['contentUri']

        for element in body_content:
            if 'paragraph' in element:
                for pe in element.get('paragraph').get('elements', []):
                    if 'textRun' in pe:
                        plain_text_parts.append(pe.get('textRun').get('content', ''))
                    elif 'inlineObjectElement' in pe:
                        obj_id = pe['inlineObjectElement']['inlineObjectId']
                        if obj_id in image_urls:
                            # In markdown format, we represent the image with its URL
                            plain_text_parts.append(f'![image]({image_urls[obj_id]})')

        plain_text = "".join(plain_text_parts)

        result = sheets_service.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range='C:D').execute()
        values = result.get('values', []); tags_text = ""
        for row in values:
            if row and row[0] == doc_id and len(row) > 1:
                tags_text = row[1]; break

        if not as_html:
            return title, plain_text.strip(), tags_text
            
        # The markdown converter will now automatically handle the image URLs
        html_body = markdown.markdown(plain_text, extensions=['fenced_code', 'codehilite', 'tables', 'nl2br', 'sane_lists'])
        return title, html_body, tags_text

    except HttpError as e:
        if e.resp.status == 404:
            print(f"문서(ID: {doc_id})를 찾을 수 없습니다 (404).")
            return None, None, None
        else:
            print(f"문서 내용 변환 중 HttpError 발생: {e}")
            return "오류", f"<p>내용을 불러오는 중 오류가 발생했습니다: {e}</p>", ""
    except Exception as e:
        print(f"문서 내용 변환 중 알 수 없는 오류 발생: {e}")
        return "오류", f"<p>내용을 불러오는 중 알 수 없는 오류가 발생했습니다: {e}</p>", ""



def load_memo_list():
    docs_service, sheets_service, drive_service = get_services()
    SPREADSHEET_ID = config_manager.get_setting('Google', 'spreadsheet_id')
    try:
        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID, range='A2:D').execute()
        values = result.get('values', [])
        
        # 행 데이터가 부족할 경우 빈 문자열로 채워줌 (안정성)
        processed_values = []
        for row in values:
            while len(row) < 4:
                row.append("")
            processed_values.append(row)

        print(f"로컬 캐시용 전체 목록 로딩 성공! {len(processed_values)}개 항목.")
        return processed_values
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
            sanitized_query = query.replace("'", "\'"); search_query += f" and fullText contains '{sanitized_query}'"
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
    
def update_checklist_item(doc_id, original_line, is_checked):
    docs_service, _, _ = get_services()
    try:
        doc = docs_service.documents().get(documentId=doc_id, fields='body').execute()
        body_content = doc.get('body').get('content')

        target_line_to_find = original_line.strip()
        new_line_prefix = "- [x] " if is_checked else "- [ ] "
        old_line_prefix = "- [ ] " if is_checked else "- [x] "
        
        requests = []
        found_and_updated = False

        for element in body_content:
            if 'paragraph' in element:
                for pe in element.get('paragraph').get('elements', []):
                    if 'textRun' in pe:
                        text_run_content = pe.get('textRun').get('content', '')
                        
                        # textRun 안에 목표 라인이 정확히 있는지 확인
                        if target_line_to_find in text_run_content:
                            # textRun 내에서 실제 줄의 시작 위치를 찾음
                            line_start_in_textrun = text_run_content.find(target_line_to_find)
                            
                            # 문서 전체에서 삭제할 체크박스의 시작 위치를 계산
                            # pe['startIndex']는 textRun의 시작 위치
                            delete_start_index = pe['startIndex'] + line_start_in_textrun
                            
                            # 요청 생성
                            requests = [
                                {
                                    'deleteContentRange': {
                                        'range': {
                                            'startIndex': delete_start_index,
                                            'endIndex': delete_start_index + len(old_line_prefix)
                                        }
                                    }
                                },
                                {
                                    'insertText': {
                                        'location': {'index': delete_start_index},
                                        'text': new_line_prefix
                                    }
                                }
                            ]
                            
                            found_and_updated = True
                            break # 정확한 위치를 찾았으므로 내부 루프 종료
                if found_and_updated:
                    break # 외부 루프도 종료

        if not found_and_updated:
            print(f"오류: 문서 '{doc_id}'에서 원본 줄 '{target_line_to_find}'을(를) 찾을 수 없습니다.")
            return False

        docs_service.documents().batchUpdate(documentId=doc_id, body={'requests': requests}).execute()
        print(f"체크리스트 업데이트 성공: '{target_line_to_find}' -> {is_checked}")
        return True

    except Exception as e:
        print(f"체크리스트 업데이트 중 오류 발생: {e}")
        return False

def get_all_tags():
    _, sheets_service, _ = get_services()
    SPREADSHEET_ID = config_manager.get_setting('Google', 'spreadsheet_id')
    try:
        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID, range='D2:D').execute()
        values = result.get('values', [])
        all_tags = set()
        for row in values:
            if row:
                tags = [tag.strip() for tag in row[0].replace(',', ' ').split() if tag.strip()]
                all_tags.update(tags)
        return sorted(list(all_tags))
    except Exception as e:
        print(f"태그 로딩 중 오류 발생: {e}")
        return []

def check_doc_exists(doc_id):
    _, _, drive_service = get_services()
    try:
        drive_service.files().get(fileId=doc_id, fields='id').execute()
        return True
    except HttpError as e:
        if e.resp.status == 404:
            return False
        print(f"문서 존재 확인 중 오류 발생 (ID: {doc_id}): {e}")
        return False
    except Exception as e:
        print(f"문서 존재 확인 중 알 수 없는 오류 발생 (ID: {doc_id}): {e}")
        return False

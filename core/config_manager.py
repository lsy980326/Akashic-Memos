import configparser
import os
import winreg
import sys

APP_NAME = "AkashicMemo"
APP_DATA_DIR = os.path.join(os.getenv('APPDATA'), APP_NAME)

CONTENT_CACHE_DIR = os.path.join(APP_DATA_DIR, 'content_cache')

# 해당 폴더들이 없으면 새로 생성
if not os.path.exists(APP_DATA_DIR):
    os.makedirs(APP_DATA_DIR)
if not os.path.exists(CONTENT_CACHE_DIR):
    os.makedirs(CONTENT_CACHE_DIR)

CONFIG_FILE = os.path.join(APP_DATA_DIR, 'config.ini')
CACHE_FILE = os.path.join(APP_DATA_DIR, 'cache.json') # 목록 캐시
config = configparser.ConfigParser()

def load_config():
    """설정 파일을 읽고, 없는 섹션이나 키는 기본값으로."""
    if not os.path.exists(CONFIG_FILE):
        create_default_config()
    
    config.read(CONFIG_FILE, encoding='utf-8')

    default_config = {
        'Hotkeys': {'new_memo': 'ctrl+1', 'list_memos': 'ctrl+2', 'quick_launcher': 'ctrl+p'},
        'Google': {
            'spreadsheet_id': 'YOUR_SPREADSHEET_ID', # 기본값은 비워두거나 예시 ID 사용
            'folder_id': 'YOUR_FOLDER_ID'
        },
        'Display': {'page_size': '30'}
    }
    
    changes_made = False
    for section, keys in default_config.items():
        if not config.has_section(section):
            config.add_section(section)
            changes_made = True
        for key, value in keys.items():
            if not config.has_option(section, key):
                config.set(section, key, value)
                changes_made = True

    if changes_made:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as configfile:
            config.write(configfile)

def create_default_config():
    """기본 설정값으로 config.ini 파일을 생성"""
    # load_config가 대부분의 일을 하므로 이 함수는 간단하게 유지
    if os.path.exists(CONFIG_FILE):
        os.remove(CONFIG_FILE)
    load_config()

def get_setting(section, key):
    return config.get(section, key)

def save_settings(hotkey_new, hotkey_list, hotkey_launcher, sheet_id, folder_id, page_size):
    config['Hotkeys']['new_memo'] = hotkey_new
    config['Hotkeys']['list_memos'] = hotkey_list
    config['Hotkeys']['quick_launcher'] = hotkey_launcher
    config['Google']['spreadsheet_id'] = sheet_id
    config['Google']['folder_id'] = folder_id
    config['Display']['page_size'] = page_size
    with open(CONFIG_FILE, 'w', encoding='utf-8') as configfile:
        config.write(configfile)

load_config()

RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME_IN_REGISTRY = "AkashicMemo"

def is_startup_enabled():
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_READ)
        winreg.QueryValueEx(key, APP_NAME_IN_REGISTRY)
        winreg.CloseKey(key)
        return True
    except FileNotFoundError:
        return False
    except Exception:
        return False

def set_startup(enabled: bool):
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_WRITE)
        if enabled:
            executable_path = sys.executable
            # .exe로 실행될 때를 대비해, pythonw.exe가 아닌 실제 exe 경로를 찾도록 시도
            if "pythonw.exe" in executable_path.lower():
                pass
            winreg.SetValueEx(key, APP_NAME_IN_REGISTRY, 0, winreg.REG_SZ, f'"{executable_path}"')
        else:
            winreg.DeleteValue(key, APP_NAME_IN_REGISTRY)
        winreg.CloseKey(key)
        return True
    except Exception:
        return False
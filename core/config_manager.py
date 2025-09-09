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
    if not os.path.exists(CONFIG_FILE):
        create_default_config()
    
    config.read(CONFIG_FILE, encoding='utf-8')

    default_config = {
        'Hotkeys': {'new_memo': 'ctrl+1', 'list_memos': 'ctrl+2', 'quick_launcher': 'ctrl+p'},
        'Google': {
            'spreadsheet_id': 'YOUR_SPREADSHEET_ID', # 기본값은 비워두거나 예시 ID 사용
            'folder_id': 'YOUR_FOLDER_ID'
        },
        'Display': {'page_size': '30', 'local_page_size': '20', 'custom_css_path': '', 'autosave_interval_ms': '3000'},
        'WindowStates': {}
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
    if os.path.exists(CONFIG_FILE):
        os.remove(CONFIG_FILE)
    load_config()

def get_setting(section, key):
    return config.get(section, key)

def save_settings(hotkey_new, hotkey_list, hotkey_launcher, sheet_id, folder_id, page_size, custom_css_path, autosave_interval_ms):
    config['Hotkeys']['new_memo'] = hotkey_new
    config['Hotkeys']['list_memos'] = hotkey_list
    config['Hotkeys']['quick_launcher'] = hotkey_launcher
    config['Google']['spreadsheet_id'] = sheet_id
    config['Google']['folder_id'] = folder_id
    config['Display']['page_size'] = page_size
    config['Display']['custom_css_path'] = custom_css_path
    config['Display']['autosave_interval_ms'] = autosave_interval_ms
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
    
def get_favorites():
    if not config.has_section('Favorites'):
        return []
    pinned_ids_str = config.get('Favorites', 'pinned_ids', fallback='')
    if not pinned_ids_str:
        return []
    return pinned_ids_str.split(',')

def set_favorites(id_list):
    if not config.has_section('Favorites'):
        config.add_section('Favorites')
    config.set('Favorites', 'pinned_ids', ",".join(id_list))
    with open(CONFIG_FILE, 'w', encoding='utf-8') as configfile:
        config.write(configfile)

def add_favorite(doc_id):
    favs = get_favorites()
    if doc_id not in favs:
        favs.append(doc_id)
        set_favorites(favs)

def remove_favorite(doc_id):
    favs = get_favorites()
    if doc_id in favs:
        favs.remove(doc_id)
        set_favorites(favs)


def save_window_state(window_name, geometry_hex):
    if not config.has_section('WindowStates'):
        config.add_section('WindowStates')
    config.set('WindowStates', window_name, geometry_hex)
    with open(CONFIG_FILE, 'w', encoding='utf-8') as configfile:
        config.write(configfile)

def get_window_state(window_name):
    return config.get('WindowStates', window_name, fallback=None)

# ===================================================================
# Notified Tasks Management
# ===================================================================
import json

FAVORITES_FILE = os.path.join(APP_DATA_DIR, 'favorites.json')
NOTIFIED_TASKS_FILE = os.path.join(APP_DATA_DIR, 'notified_tasks.json')
SERIES_CACHE_FILE = os.path.join(APP_DATA_DIR, 'series_cache.json')

# --- 설정 파일 관리 ---

def save_notified_tasks(tasks_dict):
    """Saves the dictionary of notified task IDs and their notification dates to the file."""
    try:
        with open(NOTIFIED_TASKS_FILE, 'w', encoding='utf-8') as f:
            json.dump(tasks_dict, f, indent=4)
    except IOError as e:
        print(f"Error saving notified tasks file: {e}")

def load_notified_tasks():
    """Loads the dictionary of notified task IDs and dates from the file."""
    if not os.path.exists(NOTIFIED_TASKS_FILE):
        return {}
    try:
        with open(NOTIFIED_TASKS_FILE, 'r', encoding='utf-8') as f:
            tasks_dict = json.load(f)
            # Ensure it's a dictionary, for backward compatibility from old set format
            if isinstance(tasks_dict, list):
                return {}
            return tasks_dict
    except (IOError, json.JSONDecodeError) as e:
        print(f"Error loading notified tasks file: {e}")
        return {}

# --- 시리즈 캐시 관리 ---
def load_series_cache():
    if not os.path.exists(SERIES_CACHE_FILE):
        return {}
    try:
        with open(SERIES_CACHE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (IOError, json.JSONDecodeError) as e:
        print(f"시리즈 캐시 로드 실패: {e}")
        return {}

def save_series_cache(cache_data):
    try:
        with open(SERIES_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=4)
    except IOError as e:
        print(f"시리즈 캐시 저장 실패: {e}")
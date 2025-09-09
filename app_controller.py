import sys
import threading
import json
import os
import shutil
import markdown
import re
import webbrowser
import requests
from bs4 import BeautifulSoup
import hashlib
from PyQt5.QtWidgets import QApplication, QMessageBox, QMenu, QDesktopWidget, QInputDialog
from PyQt5.QtCore import QObject, pyqtSignal, QTimer, Qt, QUrl, QByteArray
from PyQt5.QtGui import QDesktopServices, QFont, QIcon
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEnginePage
import keyboard
from pystray import Icon as pystray_icon, Menu as pystray_menu, MenuItem as pystray_menu_item
from PIL import Image
from core import google_api_handler, config_manager
from core.config_manager import load_series_cache, save_series_cache
from core.utils import resource_path
from app_windows import (MarkdownEditorWindow, MemoListWindow, SettingsWindow, RichMemoViewWindow,
                        QuickLauncherWindow, TodoDashboardWindow, TodoItemWidget, CustomNotificationWindow,
                        ToastNotificationWindow,KnowledgeGraphWindow)
import qtawesome as qta
from datetime import datetime, time
from pyvis.network import Network
import networkx as nx
import http.server
import socketserver
import threading
import functools

import colorsys


class SignalEmitter(QObject):
    show_new_memo = pyqtSignal()
    show_list_memo = pyqtSignal()
    show_settings = pyqtSignal()
    show_quick_launcher = pyqtSignal()
    show_edit_memo = pyqtSignal(str, str, str, str)
    show_rich_view = pyqtSignal(str, str, str, dict)
    list_data_loaded = pyqtSignal(list, bool, dict)
    nav_tree_updated = pyqtSignal(set, list)
    status_update = pyqtSignal(str, int)
    persistent_notification = pyqtSignal(str, str, str)  # For persistent notifications like deadlines
    toast_notification = pyqtSignal(str, str)  # For temporary notifications like save/update
    favorite_status_changed = pyqtSignal(str, bool)
    auto_save_status_update = pyqtSignal(str)
    todo_list_updated = pyqtSignal(list)
    sync_finished_update_list = pyqtSignal()
    tasks_data_loaded = pyqtSignal(dict)
    toggle_todo_dashboard_signal = pyqtSignal()
    graph_data_generated = pyqtSignal(dict)

class AppController:
    def __init__(self, app):
        self.app = app
        self.emitter = SignalEmitter()
        
        app_icon = QIcon(resource_path("resources/icon.ico"))
        self.app.setWindowIcon(app_icon)

        self.wakeup_timer = QTimer()
        self.wakeup_timer.timeout.connect(self.stay_awake)
        self.wakeup_timer.start(30 * 1000)

        self.memo_editor = MarkdownEditorWindow()
        self.memo_editor.setWindowIcon(app_icon)
        self.memo_list = MemoListWindow()
        self.memo_list.setWindowIcon(app_icon)
        self.settings = SettingsWindow()
        self.settings.setWindowIcon(app_icon)
        self.rich_viewer = RichMemoViewWindow()
        self.rich_viewer.setWindowIcon(app_icon)
        self.quick_launcher = QuickLauncherWindow()
        self.quick_launcher.setWindowIcon(app_icon)
        self.todo_dashboard = TodoDashboardWindow()
        self.notification_window = CustomNotificationWindow()
        self.graph_window = KnowledgeGraphWindow()
        self.toast_notification_window = ToastNotificationWindow()

        self.notification_queue = []
        self.is_notification_active = False

        self.local_cache = []
        self.all_tags = set()
        
        self.tag_colors = {}
        self.current_viewing_doc_id = None
        self.current_editing_doc_id = None
        self.current_page_token = None
        self.next_page_token = None
        self.prev_page_tokens = []
        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self.perform_search)
        self.icon = None
        self.launcher_mode = 'memos'
        self.is_loading_tasks = False
        self.cache_lock = threading.Lock()
        self.series_cache = {}

        self.all_tasks = []
        self.show_completed_tasks = False
        self.notified_tasks = config_manager.load_notified_tasks()
        self.notification_timer = QTimer()

        self.auto_save_timer = QTimer()
        self.auto_save_timer.setSingleShot(True)
        self.auto_save_interval_ms = 3000

        self.connect_signals_and_slots()
        self.load_cache_only(initial_load=True)
        self.setup_hotkeys()
        self.setup_tray_icon()

        self.notification_timer.start(60000) 
        QTimer.singleShot(2000, self.start_initial_sync)

        self.favorites = []
        self.load_favorites()

        self.series_cache = load_series_cache()
        QTimer.singleShot(3000, self.rebuild_series_cache_if_needed) # 3초 후 실행

    def connect_signals_and_slots(self):
        self.emitter.show_new_memo.connect(self.show_new_memo_window, Qt.QueuedConnection)
        self.emitter.show_list_memo.connect(self.show_memo_list_window, Qt.QueuedConnection)
        self.emitter.show_settings.connect(self.show_settings_window, Qt.QueuedConnection)
        self.emitter.show_quick_launcher.connect(self.toggle_quick_launcher, Qt.QueuedConnection)
        self.emitter.list_data_loaded.connect(self.memo_list.populate_table, Qt.QueuedConnection)
        self.emitter.nav_tree_updated.connect(self.memo_list.update_nav_tree, Qt.QueuedConnection)
        self.emitter.show_edit_memo.connect(self.memo_editor.open_document, Qt.QueuedConnection)
        self.emitter.show_edit_memo.connect(self.open_editor_with_content, Qt.QueuedConnection)
        self.emitter.show_rich_view.connect(self.rich_viewer.set_content, Qt.QueuedConnection)
        self.emitter.status_update.connect(self.memo_list.statusBar.showMessage, Qt.QueuedConnection)
        self.emitter.persistent_notification.connect(self.show_persistent_notification)
        self.emitter.toast_notification.connect(self.show_toast_notification)
        self.notification_window.view_memo_requested.connect(self.view_memo_from_notification)
        self.notification_window.notification_closed.connect(self.on_notification_closed)
        self.emitter.sync_finished_update_list.connect(self.on_sync_finished_update_list, Qt.QueuedConnection)
        self.emitter.todo_list_updated.connect(self.todo_dashboard.update_tasks, Qt.QueuedConnection)
        self.emitter.tasks_data_loaded.connect(self.process_loaded_tasks, Qt.QueuedConnection)
        self.emitter.toggle_todo_dashboard_signal.connect(self.toggle_todo_dashboard, Qt.QueuedConnection)

        self.todo_dashboard.completion_filter_changed.connect(self.on_completion_filter_changed)
        self.notification_timer.timeout.connect(self.check_task_deadlines)
        self.search_timer.timeout.connect(self.perform_search)
        self.todo_dashboard.task_toggled.connect(self.on_task_toggled)
        self.todo_dashboard.item_clicked.connect(self.view_memo_by_id)
        self.todo_dashboard.refresh_requested.connect(self.refresh_todo_dashboard)

        self.memo_list.search_bar.textChanged.connect(self.on_search_text_changed)
        self.memo_list.full_text_search_check.stateChanged.connect(self.search_mode_changed)
        self.memo_list.table.itemDoubleClicked.connect(self.view_memo_from_item)
        self.memo_list.memo_selected.connect(self.view_memo_by_id)
        self.memo_list.table.customContextMenuRequested.connect(self.show_context_menu)
        self.memo_list.prev_button.clicked.connect(self.go_to_prev_page)
        self.memo_list.next_button.clicked.connect(self.go_to_next_page)
        self.memo_list.refresh_button.clicked.connect(self.start_initial_sync)
        self.memo_list.navigation_selected.connect(self.on_navigation_selected)
        
        self.memo_editor.save_button.clicked.connect(lambda: self.save_memo(is_auto_save=False))
        self.memo_editor.preview_timer.timeout.connect(self.update_editor_preview)
        self.memo_editor.editor.textChanged.connect(lambda: self.memo_editor.preview_timer.start(500))
        
        self.settings.save_button.clicked.connect(self.save_settings)
        self.settings.startup_checkbox.stateChanged.connect(config_manager.set_startup)

        self.quick_launcher.search_box.textChanged.connect(self.search_for_launcher)
        self.quick_launcher.memo_selected.connect(self.on_launcher_item_selected)
        self.rich_viewer.link_activated.connect(self.on_link_activated)
        self.rich_viewer.tags_edit_requested.connect(self.edit_tags_from_viewer)
        self.rich_viewer.edit_requested.connect(self.edit_current_viewing_memo)
        self.rich_viewer.open_in_gdocs_requested.connect(self.open_current_memo_in_gdocs)
        self.rich_viewer.refresh_requested.connect(self.on_viewer_refresh_requested)

        self.rich_viewer.add_chapter_requested.connect(self.on_add_chapter_requested) 
        self.rich_viewer.navigation_requested.connect(self.view_memo_by_id)
        self.rich_viewer.favorite_toggled.connect(self.toggle_favorite_from_viewer)
        self.memo_list.favorite_toggled_from_list.connect(self.toggle_favorite)
        self.emitter.favorite_status_changed.connect(self.on_favorite_status_changed)

        # 자동 저장 관련
        self.memo_editor.editor.textChanged.connect(self.on_editor_text_changed)
        self.memo_editor.title_input.textChanged.connect(self.on_editor_text_changed)
        self.memo_editor.tag_input.textChanged.connect(self.on_editor_text_changed)
        self.auto_save_timer.timeout.connect(lambda: self.save_memo(is_auto_save=True))
        self.emitter.auto_save_status_update.connect(self.memo_editor.update_auto_save_status, Qt.QueuedConnection)
        
        self.memo_list.graph_view_requested.connect(self.show_knowledge_graph)
        self.emitter.graph_data_generated.connect(self.on_graph_data_generated)
        self.graph_window.node_clicked.connect(self.on_graph_node_clicked)

    

    def get_tag_color(self, tag):
        if tag not in self.tag_colors:
            # 태그의 해시 값을 기반으로 일관된 색상 생성
            hue = (hash(tag) & 0xFFFFFF) / 0xFFFFFF  # 0.0 ~ 1.0
            saturation = 0.85  # 채도
            lightness = 0.60  # 명도
            rgb_float = colorsys.hls_to_rgb(hue, lightness, saturation)
            color_hex = f"#{int(rgb_float[0] * 255):02x}{int(rgb_float[1] * 255):02x}{int(rgb_float[2] * 255):02x}"
            self.tag_colors[tag] = color_hex
        return self.tag_colors[tag]

    def setup_hotkeys(self):
        try:
            hotkey_new = config_manager.get_setting('Hotkeys', 'new_memo')
            hotkey_list = config_manager.get_setting('Hotkeys', 'list_memos')
            hotkey_launcher = config_manager.get_setting('Hotkeys', 'quick_launcher')
            keyboard.add_hotkey(hotkey_new, lambda: self.emitter.show_new_memo.emit())
            keyboard.add_hotkey(hotkey_list, lambda: self.emitter.show_list_memo.emit())
            keyboard.add_hotkey(hotkey_launcher, lambda: self.emitter.show_quick_launcher.emit())
            print(f"단축키 '{hotkey_new}', '{hotkey_list}', '{hotkey_launcher}'가 성공적으로 등록되었습니다.")
        except Exception as e:
            print(f"단축키 등록 실패: {e}")

    def request_toggle_todo_dashboard(self):
        self.emitter.toggle_todo_dashboard_signal.emit()

    def setup_tray_icon(self):
        try:
            image = Image.open(resource_path("resources/icon.ico"))
        except:
            image = Image.new('RGB', (64, 64), color='blue')
        menu = pystray_menu(
            pystray_menu_item('오늘 할 일 보기', self.request_toggle_todo_dashboard, default=True),
            pystray_menu_item('---', None, enabled=False),
            pystray_menu_item('새 메모 작성', lambda: self.emitter.show_new_memo.emit(),),
            pystray_menu_item('메모 목록 보기', lambda: self.emitter.show_list_memo.emit()),
            pystray_menu_item('빠른 실행', lambda: self.emitter.show_quick_launcher.emit()),
            pystray_menu_item('설정', lambda: self.emitter.show_settings.emit()),
            pystray_menu_item('종료', self.exit_app)
        )
        self.icon = pystray_icon("AkashicMemo", image, "Akashic Memo", menu)
        threading.Thread(target=self.icon.run, daemon=True).start()

    def exit_app(self):
        self.wakeup_timer.stop()
        keyboard.unhook_all()
        if self.icon:
            self.icon.stop()
        self.app.quit()

    def toggle_quick_launcher(self):
        if self.quick_launcher.isVisible():
            self.quick_launcher.hide()
        else:
            self.launcher_mode = 'memos'
            self.quick_launcher.search_box.setPlaceholderText("메모 검색...")

            screen_geometry = QApplication.primaryScreen().geometry()
            x = (screen_geometry.width() - self.quick_launcher.width()) // 2
            y = (screen_geometry.height() - self.quick_launcher.height()) // 4
            self.quick_launcher.move(x, y)
            
            self.quick_launcher.show()
            self.quick_launcher.activateWindow()
            self.quick_launcher.search_box.setFocus()
            self.quick_launcher.search_box.clear()

    def search_for_launcher(self, query):
        if query.startswith('#'):
            self.launcher_mode = 'tags'
            self.quick_launcher.search_box.setPlaceholderText("태그 검색...")
            tag_query = query[1:].lower()
            filtered_tags = sorted([tag for tag in self.all_tags if tag_query in tag.lower()])
            results = [(f"#{tag}", "태그", tag) for tag in filtered_tags]
            self.quick_launcher.update_results(results)
        else:
            self.launcher_mode = 'memos'
            self.quick_launcher.search_box.setPlaceholderText("메모 검색...")
            if query:
                filtered = [row[:3] for row in self.local_cache if query.lower() in row[0].lower()]
                self.quick_launcher.update_results(filtered)
            else:
                results = [row[:3] for row in self.local_cache]
                self.quick_launcher.update_results(results)

    def on_sync_finished_update_list(self):
        print("DEBUG: on_sync_finished_update_list 호출됨")
        if self.memo_list.isVisible() and not self.memo_list.full_text_search_check.isChecked():
            print("DEBUG: memo_list가 보이고 전체 텍스트 검색이 아님")
            current_nav_item = self.memo_list.nav_tree.currentItem()
            if current_nav_item:
                nav_text = current_nav_item.text(0)
                nav_id = current_nav_item.data(0, Qt.UserRole)
                print(f"DEBUG: 현재 네비게이션 아이템: {nav_text} (ID: {nav_id})")
                
                # ID가 있으면 ID로, 없으면 텍스트로 네비게이션 실행
                if nav_id:
                    self.on_navigation_selected(nav_id)
                else:
                    self.on_navigation_selected(nav_text)
            else:
                print("DEBUG: 현재 네비게이션 아이템이 없음, 전체 메모로 설정")
                self.on_navigation_selected("전체 메모")
        else:
            print("DEBUG: memo_list가 보이지 않거나 전체 텍스트 검색 중")

    def start_initial_sync(self):
        self.emitter.status_update.emit("최신 정보 동기화 중...", 2000)
        threading.Thread(target=self.sync_cache_thread, daemon=True).start()

    def sync_cache_thread(self):
        sheet_data = google_api_handler.load_memo_list()
        if sheet_data is None:
            self.emitter.status_update.emit("목록 동기화 실패 (시트 로드 오류)", 5000)
            return

        # 데이터베이스 유효성 검사: 시트에 있는 ID가 실제 Drive에 존재하는지 확인
        validated_data = []
        for row in sheet_data:
            if len(row) > 2 and row[2]: # ID가 있는지 확인
                if google_api_handler.check_doc_exists(row[2]):
                    validated_data.append(row)
                else:
                    print(f"[Sync] 구글 시트의 문서 ID({row[2]})가 실제 구글 드라이브에 존재하지 않아 목록에서 제외합니다: {row[0]}")
            else:
                 print(f"[Sync] 구글 시트의 행에 문서 ID가 없어 제외합니다: {row}")

        with self.cache_lock:
            if validated_data != self.local_cache:
                print(f"DEBUG: sync_cache_thread - local_cache 변경됨: {len(self.local_cache)} -> {len(validated_data)}")
                
                # 새로 추가된 항목들을 보존하기 위해 기존 local_cache의 ID들을 확인
                existing_ids = {row[2] for row in self.local_cache if len(row) > 2}
                validated_ids = {row[2] for row in validated_data if len(row) > 2}
                
                # 기존에 있던 항목들 중에서 validated_data에 없는 항목들 (새로 추가된 항목들)
                new_items = [row for row in self.local_cache if len(row) > 2 and row[2] not in validated_ids]
                
                if new_items:
                    print(f"DEBUG: 새로 추가된 항목 {len(new_items)}개 보존: {[row[0] for row in new_items]}")
                    # 새로 추가된 항목들을 validated_data 앞에 추가
                    self.local_cache = new_items + validated_data
                else:
                    self.local_cache = validated_data
                
                self.update_tags_from_cache()
                try:
                    with open(config_manager.CACHE_FILE, 'w', encoding='utf-8') as f:
                        json.dump(self.local_cache, f, ensure_ascii=False, indent=4)
                except IOError:
                    pass
                
                self.emitter.nav_tree_updated.emit(self.all_tags, self.local_cache)
                self.emitter.sync_finished_update_list.emit()
                self.emitter.status_update.emit("동기화 완료.", 5000)
                self.rebuild_series_cache_if_needed() # 시리즈 캐시 업데이트
            else:
                print("DEBUG: sync_cache_thread - local_cache 변경 없음")
                self.emitter.status_update.emit("이미 최신 상태입니다.", 3000)

    def load_cache_only(self, initial_load=False):
        try:
            if os.path.exists(config_manager.CACHE_FILE):
                with open(config_manager.CACHE_FILE, 'r', encoding='utf-8') as f:
                    self.local_cache = json.load(f)
                self.update_tags_from_cache()
                if initial_load:
                    series_cache = self.series_cache if hasattr(self, 'series_cache') else {}
                    self.emitter.list_data_loaded.emit(self.local_cache, True, series_cache)
                    self.emitter.nav_tree_updated.emit(self.all_tags, self.local_cache)
        except Exception as e:
            print(f"캐시 로딩 실패: {e}")
            self.local_cache = []
            
    def update_tags_from_cache(self):
        self.all_tags.clear()
        for row in self.local_cache:
            if len(row) > 3 and row[3]:
                tags = [t.strip().lstrip('#') for t in row[3].replace(',', ' ').split() if t.strip().startswith('#')]
                self.all_tags.update(tags)
        
        

    def on_navigation_selected(self, selected_item_id):
        self.memo_list.search_bar.clear()
        self.memo_list.full_text_search_check.setChecked(False)

        # 시리즈 캐시 가져오기
        series_cache = self.series_cache if hasattr(self, 'series_cache') else {}
        
        # id가 favorites이면 즐겨찾기 목록을 표시
        if selected_item_id == "favorites":
            fav_memos = [row for row in self.local_cache if len(row) > 2 and row[2] in self.favorites]
            self.emitter.list_data_loaded.emit(fav_memos, True, series_cache)
            return

        # "태그 (12)" 와 같은 형식에서 텍스트 부분만 추출
        clean_selected_item = re.sub(r'\s*\(\d+\)', '', selected_item_id).strip()

        if clean_selected_item == "전체 메모":
            self.emitter.list_data_loaded.emit(self.local_cache, True, series_cache)
        elif clean_selected_item not in ["태그", ""]:
            # 선택된 태그를 포함하는 메모만 필터링
            filtered_data = [
                row for row in self.local_cache
                if len(row) > 3 and row[3] and clean_selected_item in [tag.strip().lstrip('#') for tag in row[3].replace(',', ' ').split()]
            ]
            self.emitter.list_data_loaded.emit(filtered_data, True, series_cache)

    def on_editor_text_changed(self):
        self.emitter.auto_save_status_update.emit("변경사항이 있습니다...")
        try:
            interval_str = config_manager.get_setting('Display', 'autosave_interval_ms')
            self.auto_save_interval_ms = int(interval_str)
        except (ValueError, TypeError):
            self.auto_save_interval_ms = 0 # 기본값 또는 오류 처리

        if self.auto_save_interval_ms > 0:
            self.auto_save_timer.start(self.auto_save_interval_ms)

    def show_new_memo_window(self):
        geometry_hex = config_manager.get_window_state(self.memo_editor.window_name)
        if geometry_hex:
            self.memo_editor.restoreGeometry(QByteArray.fromHex(geometry_hex.encode('utf-8')))

        self.memo_editor.clear_fields()
        self.emitter.auto_save_status_update.emit("새 메모")
        self.memo_editor.show()
        self.memo_editor.activateWindow()

    def show_memo_list_window(self):
        geometry_hex = config_manager.get_window_state(self.memo_list.window_name)
        if geometry_hex:
            self.memo_list.restoreGeometry(QByteArray.fromHex(geometry_hex.encode('utf-8')))

        # 현재 선택된 네비게이션 아이템을 기억
        current_nav_item = None
        if hasattr(self, 'memo_list') and self.memo_list.isVisible():
            current_nav_item = self.memo_list.nav_tree.currentItem()
            if current_nav_item:
                current_nav_text = current_nav_item.text(0)
                current_nav_id = current_nav_item.data(0, Qt.UserRole)
                print(f"DEBUG: 현재 선택된 네비게이션 아이템 기억: {current_nav_text} (ID: {current_nav_id})")

        self.memo_list.show()
        self.memo_list.activateWindow()
        self.memo_list.raise_()
        is_full_text = self.memo_list.full_text_search_check.isChecked()
        self.memo_list.search_bar.setPlaceholderText("본문 내용으로 검색..." if is_full_text else "제목으로 실시간 필터링...")
        
        # 네비게이션 트리 업데이트
        self.memo_list.update_nav_tree(self.all_tags, self.local_cache)

        # 이전에 선택된 아이템이 있으면 복원
        if current_nav_item:
            current_nav_text = current_nav_item.text(0)
            current_nav_id = current_nav_item.data(0, Qt.UserRole)
            
            # 같은 텍스트나 ID를 가진 아이템을 찾아서 선택
            restored = False
            if current_nav_id:
                # ID로 찾기 (즐겨찾기, 태그 등)
                items = self.memo_list.nav_tree.findItems(current_nav_text, Qt.MatchFixedString | Qt.MatchRecursive, 0)
                for item in items:
                    if item.data(0, Qt.UserRole) == current_nav_id:
                        self.memo_list.nav_tree.setCurrentItem(item)
                        # 네비게이션 선택 이벤트는 자동으로 발생
                        print(f"DEBUG: 네비게이션 아이템 복원됨 (ID로): {current_nav_text}")
                        restored = True
                        break
            else:
                # 텍스트로 찾기 (전체 메모 등)
                items = self.memo_list.nav_tree.findItems(current_nav_text, Qt.MatchFixedString | Qt.MatchRecursive, 0)
                if items:
                    self.memo_list.nav_tree.setCurrentItem(items[0])
                    # 네비게이션 선택 이벤트는 자동으로 발생
                    print(f"DEBUG: 네비게이션 아이템 복원됨 (텍스트로): {current_nav_text}")
                    restored = True
            
            if not restored:
                print(f"DEBUG: 네비게이션 아이템 복원 실패, 기본값으로 설정")
                # 복원 실패 시 기본값으로 설정
                all_memos_item = self.memo_list.nav_tree.findItems("전체 메모", Qt.MatchFixedString | Qt.MatchRecursive, 0)
                if all_memos_item:
                    self.memo_list.nav_tree.setCurrentItem(all_memos_item[0])
                # 네비게이션 선택 이벤트는 자동으로 발생
        else:
            # 이전 선택이 없으면 기본값으로 '전체 메모' 선택
            all_memos_item = self.memo_list.nav_tree.findItems("전체 메모", Qt.MatchFixedString | Qt.MatchRecursive, 0)
            if all_memos_item:
                self.memo_list.nav_tree.setCurrentItem(all_memos_item[0])
            # 네비게이션 선택 이벤트는 자동으로 발생


    def on_search_text_changed(self):
        if self.memo_list.full_text_search_check.isChecked():
            self.search_timer.start(600)
        else:
            self.filter_local_cache()
    
    def search_mode_changed(self):
        is_full_text = self.memo_list.full_text_search_check.isChecked()
        self.memo_list.search_bar.setPlaceholderText("본문 내용으로 검색..." if is_full_text else "제목으로 실시간 필터링...")
        
        if is_full_text:
            series_cache = self.series_cache if hasattr(self, 'series_cache') else {}
            self.emitter.list_data_loaded.emit([], False, series_cache)
            self.memo_list.update_paging_buttons(False, False, 1)
            self.perform_search()
        else:
            current_nav = self.memo_list.nav_tree.currentItem()
            if current_nav:
                self.on_navigation_selected(current_nav.text(0))
            else:
                self.on_navigation_selected("전체 메모")

    def filter_local_cache(self):
        query = self.memo_list.search_bar.text().lower()
        # 제목 필터링 시, 현재 네비게이션 뷰를 유지하도록 수정
        current_nav_item = self.memo_list.nav_tree.currentItem()
        nav_text = "전체 메모"
        if current_nav_item:
            nav_text = re.sub(r'\s*\(\d+\)', '', current_nav_item.text(0)).strip()

        base_data = self.local_cache
        if nav_text != "전체 메모":
             base_data = [
                row for row in self.local_cache 
                if len(row) > 3 and row[3] and nav_text in [tag.strip().lstrip('#') for tag in row[3].replace(',', ' ').split()]
            ]

        if query:
            filtered_data = [row for row in base_data if query in row[0].lower()]
        else:
            filtered_data = base_data
            
        series_cache = self.series_cache if hasattr(self, 'series_cache') else {}
        self.emitter.list_data_loaded.emit(filtered_data, True, series_cache)


    def perform_search(self, page_token=None, is_prev=False, is_next=False):
        query = self.memo_list.search_bar.text()
        if not query:
            series_cache = self.series_cache if hasattr(self, 'series_cache') else {}
            self.emitter.list_data_loaded.emit([], False, series_cache)
            self.memo_list.update_paging_buttons(False, False, 1)
            self.emitter.status_update.emit("검색어를 입력하세요.", 3000)
            return

        self.emitter.status_update.emit(f"'{query}' 검색 중...", 0)
        if not is_prev and not is_next:
            self.prev_page_tokens.clear()
        if is_next:
            self.prev_page_tokens.append(self.current_page_token)
        self.current_page_token = page_token
        threading.Thread(target=self.fetch_data_api, args=(query, page_token), daemon=True).start()

    def fetch_data_api(self, query, page_token):
        data, next_token = google_api_handler.search_memos_by_content(query, page_token)
        self.next_page_token = next_token
        series_cache = self.series_cache if hasattr(self, 'series_cache') else {}
        self.emitter.list_data_loaded.emit(data if data else [], False, series_cache)
        prev_enabled = len(self.prev_page_tokens) > 0
        page_num = len(self.prev_page_tokens) + 1
        self.memo_list.update_paging_buttons(prev_enabled, self.next_page_token is not None, page_num)
        self.emitter.status_update.emit(f"'{query}' 검색 완료.", 3000)

        
    def go_to_prev_page(self):
        if self.prev_page_tokens:
            prev_token = self.prev_page_tokens.pop()
            self.perform_search(page_token=prev_token, is_prev=True)

    def go_to_next_page(self):
        if self.next_page_token:
            self.perform_search(page_token=self.next_page_token, is_next=True)

    def save_memo(self, is_auto_save=False):
        self.auto_save_timer.stop()
        editor = self.memo_editor
        title = editor.title_input.text()
        content = editor.editor.toPlainText()
        tags = editor.tag_input.text()
        doc_id = editor.current_doc_id

        if not (title and content):
            if not is_auto_save:
                QMessageBox.warning(editor, "경고", "제목과 내용을 모두 입력해야 합니다.")
            return

        self.emitter.auto_save_status_update.emit("저장 중...")

        if doc_id:
            threading.Thread(target=self.update_memo_thread, args=(doc_id, title, content, tags, is_auto_save), daemon=True).start()
        else:
            threading.Thread(target=self.save_memo_thread, args=(title, content, tags, is_auto_save), daemon=True).start()
        
        if not is_auto_save:
            editor.close()

    def save_memo_thread(self, title, content, tags, is_auto_save=False):
        from datetime import datetime
        self.emitter.status_update.emit(f"'{title}' 저장 중...", 0)
        success, new_doc_id = google_api_handler.save_memo(title, content, tags)
        if success:
            self.emitter.auto_save_status_update.emit("모든 변경사항이 저장됨")
            if not is_auto_save:
                self.emitter.toast_notification.emit("저장 완료", f"'{title}' 메모가 저장되었습니다.")
            
            # 새 문서 ID를 에디터에 설정 (자동 저장 후 수동 저장 시 업데이트를 위함)
            if self.memo_editor.isVisible() and not self.memo_editor.current_doc_id:
                self.memo_editor.current_doc_id = new_doc_id

            # 로컬 캐시에 새 메모 추가
            current_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            new_row = [title, current_date, new_doc_id, tags]
            self.local_cache.insert(0, new_row) # 새 메모를 맨 위에 추가

            # 캐시 파일 저장
            try:
                with open(config_manager.CACHE_FILE, 'w', encoding='utf-8') as f:
                    json.dump(self.local_cache, f, ensure_ascii=False, indent=4)
            except IOError as e:
                print(f"캐시 파일 쓰기 오류: {e}")

            # UI 업데이트
            self.update_tags_from_cache()
            self.emitter.nav_tree_updated.emit(self.all_tags, self.local_cache)
            if self.memo_list.isVisible():
                current_nav_item = self.memo_list.nav_tree.currentItem()
                nav_text = current_nav_item.text(0) if current_nav_item else "전체 메모"
                self.on_navigation_selected(nav_text)

            self.emitter.status_update.emit("저장 완료.", 5000)
        else:
            self.emitter.status_update.emit("저장 실패", 5000)
            self.emitter.auto_save_status_update.emit("저장 실패")

    def update_memo_thread(self, doc_id, title, content, tags, is_auto_save=False):
        from datetime import datetime
        self.emitter.status_update.emit(f"'{title}' 업데이트 중...", 0)
        success = google_api_handler.update_memo(doc_id, title, content, tags)
        if success:
            self.emitter.auto_save_status_update.emit("모든 변경사항이 저장됨")
            cache_path_html = os.path.join(config_manager.CONTENT_CACHE_DIR, f"{doc_id}.html")
            if os.path.exists(cache_path_html):
                os.remove(cache_path_html)
            
            if not is_auto_save:
                self.emitter.toast_notification.emit("업데이트 완료", f"'{title}' 메모가 업데이트되었습니다.")

            # 로컬 캐시 직접 업데이트
            current_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            for i, row in enumerate(self.local_cache):
                if len(row) > 2 and row[2] == doc_id:
                    self.local_cache[i][0] = title
                    self.local_cache[i][1] = current_date
                    if len(self.local_cache[i]) > 3:
                        self.local_cache[i][3] = tags
                    else: # 태그 필드가 없는 경우
                        while len(self.local_cache[i]) < 4:
                            self.local_cache[i].append("")
                        self.local_cache[i][3] = tags
                    break
            
            # 캐시 파일 저장
            try:
                with open(config_manager.CACHE_FILE, 'w', encoding='utf-8') as f:
                    json.dump(self.local_cache, f, ensure_ascii=False, indent=4)
            except IOError as e:
                print(f"캐시 파일 쓰기 오류: {e}")

            # UI 업데이트
            self.update_tags_from_cache()
            self.emitter.nav_tree_updated.emit(self.all_tags, self.local_cache)
            if self.memo_list.isVisible():
                current_nav_item = self.memo_list.nav_tree.currentItem()
                nav_text = current_nav_item.text(0) if current_nav_item else "전체 메모"
                self.on_navigation_selected(nav_text)

            if self.rich_viewer.isVisible() and self.current_viewing_doc_id == doc_id:
                self.view_memo_by_id(doc_id)
            
            self.emitter.status_update.emit("업데이트 완료.", 5000)
        else:
            self.emitter.status_update.emit("업데이트 실패", 5000)


    def _get_view_mode_info(self, doc_id):
        print(f"DEBUG: _get_view_mode_info 호출됨 - doc_id: {doc_id}")
        
        is_moc = False
        is_chapter = False
        parent_moc_info = None
        prev_chapter_id = None
        next_chapter_id = None

        cached_info = next((row for row in self.local_cache if row[2] == doc_id), None)
        if cached_info:
            tags_text = cached_info[3].lower() if len(cached_info) > 3 else ""
            current_title = cached_info[0]
            print(f"DEBUG: cached_info - title: {current_title}, tags: {tags_text}")
            
            if '#moc' in tags_text or '#시리즈' in tags_text:
                is_moc = True
                print(f"DEBUG: MOC 문서로 인식됨")
            else:
                if doc_id in self.series_cache:
                    is_chapter = True
                    print(f"DEBUG: series_cache에서 시리즈 문서로 인식됨")
                else:
                    all_mocs = [row for row in self.local_cache if len(row) > 3 and ('#moc' in row[3].lower() or '#시리즈' in row[3].lower())]
                    for moc_row in all_mocs:
                        moc_title = moc_row[0]
                        if current_title.startswith(moc_title + " - "):
                            is_chapter = True
                            print(f"DEBUG: 제목 패턴으로 시리즈 문서로 인식됨 - MOC: {moc_title}")
                            break
        
        # 대소문자 구분 없이 series_cache에서 찾기
        series_info = None
        for cache_id, info in self.series_cache.items():
            if cache_id.lower() == doc_id.lower():
                series_info = info
                break
        
        if series_info:
            is_chapter = True  # 시리즈 정보를 찾았으면 시리즈 문서로 설정
            parent_moc_info = {
                'doc_id': series_info['parent_moc_id'],
                'title': series_info['parent_moc_title']
            }
            prev_chapter_id = series_info['prev_chapter_id']
            next_chapter_id = series_info['next_chapter_id']
            print(f"DEBUG: series_cache 정보 찾음 - parent: {parent_moc_info}, prev: {prev_chapter_id}, next: {next_chapter_id}")
        else:
            print(f"DEBUG: series_cache에 정보 없음 - doc_id: {doc_id}")
            print(f"DEBUG: 현재 series_cache 키들: {list(self.series_cache.keys())}")
        
        result = {
            'is_moc': is_moc,
            'is_chapter': is_chapter,
            'parent_moc_info': parent_moc_info,
            'prev_chapter_id': prev_chapter_id,
            'next_chapter_id': next_chapter_id
        }
        print(f"DEBUG: 반환값: {result}")
        return result

    def view_memo_from_item(self, item):
        # QTreeWidgetItem인 경우와 QTableWidgetItem인 경우 모두 처리
        try:
            # QTreeWidgetItem인 경우 (column, role 순서)
            doc_id = item.data(0, Qt.UserRole)
        except (TypeError, AttributeError):
            try:
                # QTableWidgetItem인 경우 (role만)
                doc_id = item.data(Qt.UserRole)
            except (TypeError, AttributeError):
                print(f"DEBUG: view_memo_from_item - 아이템 타입을 확인할 수 없음: {type(item)}")
                return
        
        if doc_id:
            self.view_memo_by_id(doc_id)

    def view_memo_by_id(self, doc_id, force_refresh=False):
        if self.rich_viewer.isVisible() and self.current_viewing_doc_id == doc_id and not force_refresh:
            self.rich_viewer.activateWindow()
            return

        view_mode_info = self._get_view_mode_info(doc_id)
        self.rich_viewer.update_favorite_status(doc_id in self.favorites)
        self.current_viewing_doc_id = doc_id
        
        cached_info = next((row for row in self.local_cache if row[2] == doc_id), None)
        title_from_cache = cached_info[0] if cached_info else "불러오는 중..."
        tags_from_cache = cached_info[3] if cached_info and len(cached_info) > 3 else ""

        cache_path = os.path.join(config_manager.CONTENT_CACHE_DIR, f"{doc_id}.html")
        is_background_check = False
        
        # 강제 새로고침이거나 캐시가 없는 경우
        if force_refresh or not os.path.exists(cache_path):
            loading_html = self._get_final_html(title_from_cache, "<body><p>콘텐츠를 불러오는 중입니다...</p></body>", tags_from_cache)
            self.emitter.show_rich_view.emit(doc_id, title_from_cache, loading_html, view_mode_info)
        else:
            # 캐시가 있는 경우
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    cached_html_full = f.read()
                self.emitter.show_rich_view.emit(doc_id, title_from_cache, cached_html_full, view_mode_info)
                is_background_check = True
            except Exception:
                error_html = self._get_final_html("오류", "<body><p>캐시 파일을 읽을 수 없습니다.</p></body>", "")
                self.emitter.show_rich_view.emit(doc_id, "오류", error_html, view_mode_info)

        threading.Thread(target=self.sync_rich_content_thread, args=(doc_id, is_background_check), daemon=True).start()

    def sync_rich_content_thread(self, doc_id, is_background_check=False):
        title, html_body, tags = google_api_handler.load_doc_content(doc_id, as_html=True)
        view_mode_info = self._get_view_mode_info(doc_id)

        if title is None: # 404 Not Found
            if not is_background_check:
                error_html = self._get_final_html("오류: 문서를 찾을 수 없음", "<body><h2>문서를 찾을 수 없습니다.</h2><p>해당 문서가 삭제되었거나 접근 권한이 없는 것 같습니다.</p></body>", "")
                self.emitter.show_rich_view.emit(doc_id, "오류: 문서를 찾을 수 없음", error_html, view_mode_info)
            
            self.cleanup_stale_document(doc_id)
            return

        processed_html_body = self._process_html_images(html_body)
        new_html_full = self._get_final_html(title, processed_html_body, tags)
        
        current_html_full = ""
        cache_path = os.path.join(config_manager.CONTENT_CACHE_DIR, f"{doc_id}.html")
        if os.path.exists(cache_path):
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    current_html_full = f.read()
            except IOError:
                pass

        if new_html_full != current_html_full:
            try:
                with open(cache_path, 'w', encoding='utf-8') as f:
                    f.write(new_html_full)
                if self.rich_viewer.isVisible() and self.current_viewing_doc_id == doc_id:
                    self.emitter.show_rich_view.emit(doc_id, title, new_html_full, view_mode_info)
            except Exception as e:
                print(f"콘텐츠 캐시 저장 오류: {e}")

    def cleanup_stale_document(self, doc_id):
        # 1. 오래된 로컬 콘텐츠 캐시 파일(.html, .txt) 삭제
        cache_path_html = os.path.join(config_manager.CONTENT_CACHE_DIR, f"{doc_id}.html")
        cache_path_txt = os.path.join(config_manager.CONTENT_CACHE_DIR, f"{doc_id}.txt")
        if os.path.exists(cache_path_html):
            try: os.remove(cache_path_html)
            except OSError as e: print(f"HTML 캐시 삭제 오류: {e}")
        if os.path.exists(cache_path_txt):
            try: os.remove(cache_path_txt)
            except OSError as e: print(f"TXT 캐시 삭제 오류: {e}")

        # 2. 메인 캐시 리스트(self.local_cache)에서 해당 문서 제거
        with self.cache_lock:
            initial_len = len(self.local_cache)
            self.local_cache = [row for row in self.local_cache if len(row) > 2 and row[2] != doc_id]
            if len(self.local_cache) < initial_len:
                print(f"삭제된 문서({doc_id})를 메인 캐시에서 제거했습니다.")
                try:
                    with open(config_manager.CACHE_FILE, 'w', encoding='utf-8') as f:
                        json.dump(self.local_cache, f, ensure_ascii=False, indent=4)
                except IOError as e:
                    print(f"캐시 파일 쓰기 오류: {e}")
                
                # 3. UI 업데이트 (목록 및 태그 트리 새로고침)
                self.update_tags_from_cache()
                self.emitter.nav_tree_updated.emit(self.all_tags, self.local_cache)
                self.emitter.sync_finished_update_list.emit()

    def _process_html_images(self, html_body):
        soup = BeautifulSoup(html_body, 'html.parser')
        images_dir = os.path.join(config_manager.CONTENT_CACHE_DIR, 'images')
        if not os.path.exists(images_dir):
            os.makedirs(images_dir)

        for img in soup.find_all('img'):
            src = img.get('src')
            if src and src.startswith('http'):
                try:
                    # 이미지 URL로부터 고유한 파일명 생성
                    filename = hashlib.md5(src.encode()).hexdigest()
                    file_extension = os.path.splitext(src.split('?')[0])[-1] or '.png'
                    if not file_extension.startswith('.'):
                        file_extension = '.' + file_extension
                    
                    filepath = os.path.join(images_dir, filename + file_extension)

                    # 이미지가 로컬에 없으면 다운로드
                    if not os.path.exists(filepath):
                        response = requests.get(src, stream=True, timeout=10)
                        response.raise_for_status()
                        with open(filepath, 'wb') as f:
                            for chunk in response.iter_content(8192):
                                f.write(chunk)
                    
                    # 이미지 태그의 src를 로컬 파일 경로로 변경
                    img['src'] = f"file:///{os.path.abspath(filepath).replace(os.sep, '/')}"
                except requests.exceptions.RequestException as e:
                    print(f"Error downloading image {src}: {e}")
                    img['alt'] = f"이미지 로드 실패: {src}"
        
        return str(soup)

    def edit_memo(self, doc_id):
        self.current_editing_doc_id = doc_id
        self.emitter.status_update.emit("편집할 내용 불러오는 중...", 0)
        threading.Thread(target=self.load_for_edit_thread, args=(doc_id,)).start()
        
    def load_for_edit_thread(self, doc_id):
        title, markdown_content, tags_text = google_api_handler.load_doc_content(doc_id, as_html=False)
        if title is not None:
            self.emitter.show_edit_memo.emit(doc_id, title, markdown_content, tags_text)
            self.emitter.status_update.emit("편집 준비 완료.", 2000)
        else:
            self.emitter.status_update.emit("내용을 불러오지 못했습니다.", 3000)
        
    def delete_memo(self, doc_id):
        title_to_delete = "메모"
        cached_info = next((row for row in self.local_cache if row[2] == doc_id), None)
        if cached_info:
            title_to_delete = cached_info[0]

        reply = QMessageBox.question(self.memo_list, '삭제 확인', f"'{title_to_delete}' 메모를 정말로 삭제하시겠습니까?\n이 작업은 되돌릴 수 없습니다.", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        
        if reply == QMessageBox.Yes:
            threading.Thread(target=self.delete_memo_thread, args=(doc_id,)).start()
    
    def delete_memo_thread(self, doc_id):
        self.emitter.status_update.emit("삭제 중...", 0)
        
        # 삭제할 메모의 정보를 먼저 가져옴
        deleted_memo_info = next((row for row in self.local_cache if row[2] == doc_id), None)
        deleted_title = deleted_memo_info[0] if deleted_memo_info else "알 수 없는 메모"
        
        success = google_api_handler.delete_memo(doc_id)
        if success:
            # 로컬 캐시에서 해당 메모 제거
            self.local_cache = [row for row in self.local_cache if len(row) > 2 and row[2] != doc_id]
            
            # 시리즈 문서인 경우 MOC 문서에서 링크 제거
            if deleted_memo_info and len(deleted_memo_info) > 3:
                tags = deleted_memo_info[3]
                # 시리즈 문서인지 확인 (#moc 태그가 없고, 시리즈 관련 태그가 있는 경우)
                if tags and '#moc' not in tags.lower() and any(tag.lower() in ['#시리즈', '#series'] for tag in tags.split()):
                    print(f"DEBUG: 시리즈 문서 삭제됨 - {deleted_title}")
                    self.remove_chapter_from_moc_documents(doc_id, deleted_title)
                else:
                    # 시리즈 캐시에 있는지 확인 (태그로 판단이 안 되는 경우)
                    if doc_id in self.series_cache:
                        print(f"DEBUG: 시리즈 캐시에서 발견된 문서 삭제됨 - {deleted_title}")
                        self.remove_chapter_from_moc_documents(doc_id, deleted_title)
                    else:
                        print(f"DEBUG: 일반 문서로 판단됨 - {deleted_title}")
            
            # 캐시 파일에 변경사항 저장
            with open(config_manager.CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.local_cache, f, ensure_ascii=False, indent=4)
            
            # 태그 목록 업데이트 및 UI 갱신
            self.update_tags_from_cache()
            self.emitter.nav_tree_updated.emit(self.all_tags, self.local_cache)
            self.on_navigation_selected("전체 메모") # 전체 메모 목록으로 돌아가기
            self.emitter.status_update.emit("삭제 완료", 5000)
            self.emitter.toast_notification.emit("삭제 완료", f"메모가 삭제되었습니다.")
        else:
            self.emitter.status_update.emit("삭제 실패", 5000)
            self.emitter.toast_notification.emit("삭제 실패", f"메모 삭제에 실패했습니다.")

    def remove_chapter_from_moc_documents(self, deleted_doc_id, deleted_title):
        """삭제된 시리즈 문서를 참조하는 MOC 문서들에서 링크를 제거"""
        try:
            print(f"DEBUG: MOC 문서에서 시리즈 링크 제거 시작 - {deleted_title}")
            
            # 시리즈 캐시에서 삭제된 문서의 부모 MOC 찾기
            if deleted_doc_id in self.series_cache:
                parent_moc_id = self.series_cache[deleted_doc_id].get('parent_moc_id')
                if parent_moc_id:
                    print(f"DEBUG: 부모 MOC 문서에서 링크 제거: {parent_moc_id}")
                    self.remove_chapter_link_from_moc(parent_moc_id, deleted_title)
                    
                    # 시리즈 캐시에서도 제거
                    del self.series_cache[deleted_doc_id]
                    print(f"DEBUG: 시리즈 캐시에서 제거됨: {deleted_doc_id}")
                    
                    # 이전/다음 회차 연결 업데이트
                    self.update_adjacent_chapters(deleted_doc_id)
            else:
                print(f"DEBUG: 시리즈 캐시에서 삭제된 문서를 찾을 수 없음, 모든 MOC 문서에서 검색: {deleted_doc_id}")
                # 시리즈 캐시에 없어도 모든 MOC 문서에서 해당 링크를 찾아서 제거
                self.search_and_remove_from_all_mocs(deleted_title)
                
        except Exception as e:
            print(f"DEBUG: MOC 문서에서 시리즈 링크 제거 중 오류: {e}")
            import traceback
            traceback.print_exc()

    def remove_chapter_link_from_moc(self, moc_doc_id, deleted_title):
        """특정 MOC 문서에서 삭제된 시리즈 문서의 링크를 제거"""
        try:
            # MOC 문서의 현재 내용을 가져옴
            title, html_body, tags_text = google_api_handler.load_doc_content(moc_doc_id, as_html=False)
            if not title or not html_body:
                print(f"DEBUG: MOC 문서 내용을 가져올 수 없음: {moc_doc_id}")
                return
            
            # 삭제할 링크 패턴 찾기 (- [[제목]] 형태)
            import re
            print(f"DEBUG: 삭제할 제목: '{deleted_title}'")
            print(f"DEBUG: 문서 내용 일부: {html_body[:500]}...")
            
            # 여러 가지 패턴을 시도 (줄 시작에 -, 공백, 탭 등이 있을 수 있음)
            link_patterns = [
                rf'^\s*-\s*\[\[{re.escape(deleted_title)}\]\]\s*$',  # - [[제목]] 형태
                rf'^\s*\[\[{re.escape(deleted_title)}\]\]\s*$',      # [[제목]] 형태
                rf'\[\[{re.escape(deleted_title)}\]\]'               # 일반적인 [[제목]] 형태
            ]
            
            # 각 패턴을 테스트해보기
            for i, pattern in enumerate(link_patterns):
                matches = re.findall(pattern, html_body, re.MULTILINE)
                print(f"DEBUG: 패턴 {i+1} 매치 결과: {matches}")
            
            # 링크가 있는지 확인 (문자열 검색 사용)
            link_pattern = f"[[{deleted_title}]]"
            link_found = link_pattern in html_body
            print(f"DEBUG: 링크 패턴 '{link_pattern}' 검색 결과: {link_found}")
            
            if link_found:
                # 링크가 포함된 줄을 찾아서 제거
                lines = html_body.split('\n')
                updated_lines = []
                
                for line in lines:
                    # 해당 줄에 삭제할 링크가 있는지 확인
                    if link_pattern in line:
                        # 해당 줄 전체를 제거 (링크가 포함된 줄)
                        print(f"DEBUG: 줄 전체 제거됨: {line.strip()}")
                        # updated_lines에 추가하지 않음 (줄 제거)
                    else:
                        updated_lines.append(line)
                
                # 업데이트된 내용으로 MOC 문서 수정
                updated_content = '\n'.join(updated_lines)
                if updated_content != html_body:
                    # Google Docs에서 문서 내용 교체
                    success = self.update_moc_document_content(moc_doc_id, updated_content)
                    if success:
                        print(f"DEBUG: MOC 문서 업데이트 완료: {moc_doc_id}")
                        # MOC 문서 캐시 삭제하여 다음에 열 때 최신 내용이 보이도록 함
                        self.clear_moc_cache(moc_doc_id)
                    else:
                        print(f"DEBUG: MOC 문서 업데이트 실패: {moc_doc_id}")
                else:
                    print(f"DEBUG: MOC 문서에 변경사항 없음: {moc_doc_id}")
            else:
                print(f"DEBUG: MOC 문서에서 삭제할 링크를 찾을 수 없음: {deleted_title}")
                
        except Exception as e:
            print(f"DEBUG: MOC 문서에서 링크 제거 중 오류: {e}")
            import traceback
            traceback.print_exc()

    def update_moc_document_content(self, doc_id, new_content):
        """MOC 문서의 내용을 새로운 내용으로 교체"""
        try:
            docs_service, _, _ = google_api_handler.get_services()
            
            # 문서의 현재 끝 인덱스 가져오기
            doc = docs_service.documents().get(documentId=doc_id, fields='body(content)').execute()
            end_index = doc.get('body').get('content')[-1].get('endIndex')
            
            # 기존 내용 삭제 (제목 제외)
            requests = []
            if end_index > 1:
                requests.append({
                    'deleteContentRange': {
                        'range': {
                            'startIndex': 1,
                            'endIndex': end_index - 1
                        }
                    }
                })
            
            # 새 내용 삽입
            if new_content.strip():
                requests.append({
                    'insertText': {
                        'location': {'index': 1},
                        'text': new_content
                    }
                })
            
            if requests:
                docs_service.documents().batchUpdate(documentId=doc_id, body={'requests': requests}).execute()
                return True
            return False
            
        except Exception as e:
            print(f"DEBUG: MOC 문서 내용 업데이트 중 오류: {e}")
            return False

    def clear_moc_cache(self, moc_doc_id):
        """MOC 문서의 캐시를 삭제"""
        try:
            cache_path_html = os.path.join(config_manager.CONTENT_CACHE_DIR, f"{moc_doc_id}.html")
            cache_path_txt = os.path.join(config_manager.CONTENT_CACHE_DIR, f"{moc_doc_id}.txt")
            
            if os.path.exists(cache_path_html):
                os.remove(cache_path_html)
                print(f"DEBUG: MOC HTML 캐시 삭제: {cache_path_html}")
            if os.path.exists(cache_path_txt):
                os.remove(cache_path_txt)
                print(f"DEBUG: MOC TXT 캐시 삭제: {cache_path_txt}")
                
        except Exception as e:
            print(f"DEBUG: MOC 캐시 삭제 중 오류: {e}")

    def update_adjacent_chapters(self, deleted_doc_id):
        """삭제된 회차의 이전/다음 회차 연결을 업데이트"""
        try:
            if deleted_doc_id not in self.series_cache:
                return
                
            deleted_info = self.series_cache[deleted_doc_id]
            prev_id = deleted_info.get('prev_chapter_id')
            next_id = deleted_info.get('next_chapter_id')
            
            # 이전 회차의 next_chapter_id를 다음 회차로 변경
            if prev_id and prev_id in self.series_cache:
                self.series_cache[prev_id]['next_chapter_id'] = next_id
                print(f"DEBUG: 이전 회차 연결 업데이트: {prev_id} -> {next_id}")
            
            # 다음 회차의 prev_chapter_id를 이전 회차로 변경
            if next_id and next_id in self.series_cache:
                self.series_cache[next_id]['prev_chapter_id'] = prev_id
                print(f"DEBUG: 다음 회차 연결 업데이트: {next_id} -> {prev_id}")
                
        except Exception as e:
            print(f"DEBUG: 인접 회차 연결 업데이트 중 오류: {e}")

    def search_and_remove_from_all_mocs(self, deleted_title):
        """모든 MOC 문서에서 삭제된 시리즈 문서의 링크를 찾아서 제거"""
        try:
            print(f"DEBUG: 모든 MOC 문서에서 '{deleted_title}' 검색 시작")
            
            # 로컬 캐시에서 MOC 문서들 찾기 (#moc 태그가 있는 문서들)
            moc_documents = []
            for row in self.local_cache:
                if len(row) > 3 and row[3] and '#moc' in row[3].lower():
                    moc_documents.append((row[2], row[0]))  # (doc_id, title)
            
            print(f"DEBUG: 발견된 MOC 문서 {len(moc_documents)}개: {[title for _, title in moc_documents]}")
            
            # 각 MOC 문서에서 링크 검색 및 제거
            for moc_doc_id, moc_title in moc_documents:
                print(f"DEBUG: MOC 문서 검색 중: {moc_title} ({moc_doc_id})")
                self.remove_chapter_link_from_moc(moc_doc_id, deleted_title)
                
        except Exception as e:
            print(f"DEBUG: 모든 MOC 문서에서 검색 중 오류: {e}")
            import traceback
            traceback.print_exc()

    def show_context_menu(self, pos):
        item = self.memo_list.table.itemAt(pos)
        if not item: return
        doc_id = item.data(Qt.UserRole)
        menu = QMenu()
        edit_action = menu.addAction("편집하기")
        edit_tags_action = menu.addAction("태그 수정하기")
        menu.addSeparator()
        delete_action = menu.addAction("삭제하기")
        action = menu.exec_(self.memo_list.table.mapToGlobal(pos))
        if action == edit_action:
            self.edit_memo(doc_id)
        elif action == edit_tags_action:
            self.edit_tags_from_list(doc_id)
        elif action == delete_action:
            self.delete_memo(doc_id)

    def edit_tags_from_list(self, doc_id):
        # 로컬 캐시에서 정보를 먼저 찾음
        title, content, current_tags = "","",""
        cached_info = next((row for row in self.local_cache if row[2] == doc_id), None)
        if cached_info:
            current_tags = cached_info[3]
        
        # 태그 편집 다이얼로그
        new_tags, ok = QInputDialog.getText(self.memo_list, "태그 편집", "태그를 입력하세요 (쉼표나 공백으로 구분):", text=current_tags)

        if ok and new_tags != current_tags:
            # API를 통해 전체 문서 내용 로드
            title, content, _ = google_api_handler.load_doc_content(doc_id, as_html=False)
            if title is None:
                QMessageBox.warning(self.memo_list, "오류", "문서 내용을 불러올 수 없어 태그를 편집할 수 없습니다.")
                return
            # 업데이트 스레드 실행
            self.update_memo_thread(doc_id, title, content, new_tags)


    def show_settings_window(self):
        self.settings.load_current_settings()
        self.settings.show()
        self.settings.activateWindow()

    def save_settings(self):
        s = self.settings
        config_manager.save_settings(s.hotkey_new_edit.text(), s.hotkey_list_edit.text(), s.hotkey_launcher_edit.text(), s.sheet_id_edit.text(), s.folder_id_edit.text(), s.page_size_edit.text(), s.css_path_edit.text())
        QMessageBox.information(s, "저장 완료", "설정이 저장되었습니다.\n일부 설정은 프로그램을 다시 시작해야 적용됩니다.")
        # 핫키 재설정
        keyboard.unhook_all()
        self.setup_hotkeys()

    def show_toast_notification(self, title, message):
        screen_geometry = QApplication.primaryScreen().availableGeometry()
        win_size = self.toast_notification_window.size()
        x = screen_geometry.width() - win_size.width() - 15
        y = screen_geometry.height() - win_size.height() - 15
        self.toast_notification_window.move(x, y)
        self.toast_notification_window.show_toast(title, message)
    
    def update_editor_preview(self):
        markdown_text = self.memo_editor.editor.toPlainText()
        html_body = markdown.markdown(markdown_text, extensions=['fenced_code', 'codehilite', 'tables', 'nl2br'])
        tags_text = self.memo_editor.tag_input.text()
        final_html_with_css = self._get_final_html("미리보기", html_body, tags_text)
        base_url = QUrl.fromLocalFile(os.path.abspath(os.getcwd()).replace('\\', '/') + '/')
        self.memo_editor.viewer.setHtml(final_html_with_css, base_url)

    def on_launcher_item_selected(self, selected_data):
        self.quick_launcher.hide()
        if self.launcher_mode == 'tags':
            tag_name = selected_data
            self.show_memo_list_window()
            # 네비게이션 트리에서 해당 태그를 찾아 선택
            items = self.memo_list.nav_tree.findItems(tag_name, Qt.MatchContains | Qt.MatchRecursive, 0)
            if items:
                self.memo_list.nav_tree.setCurrentItem(items[0])
                self.on_navigation_selected(items[0].text(0))
        else:
            doc_id = selected_data
            self.view_memo_by_id(doc_id)
    
    def _get_final_html(self, title, html_body, tags_text=""):
        # 위키 링크 [[문서제목]]을 하이퍼링크로 변환
        title_to_id_map = {row[0]: row[2] for row in self.local_cache if len(row) > 2}

        def replace_wiki_links(match):
            linked_title = match.group(1)
            doc_id = title_to_id_map.get(linked_title)
            if doc_id:
                return f'<a href="memo://{doc_id}" title="메모 열기: {linked_title}">{linked_title}</a>'
            return f'<span class="broken-link" title="존재하지 않는 메모: {linked_title}">[[{linked_title}]]</span>'
        
        def convert_local_images(html):
            """로컬 이미지 경로를 절대 경로로 변환"""
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, 'html.parser')
            for img in soup.find_all('img'):
                src = img.get('src')
                if src and not src.startswith(('http://', 'https://', 'file://')):
                    # 상대 경로인 경우 절대 경로로 변환
                    if src.startswith('resources/'):
                        abs_path = os.path.abspath(resource_path(src))
                        img['src'] = f"file:///{abs_path.replace(os.sep, '/')}"
                    elif src.startswith('./') or src.startswith('../'):
                        abs_path = os.path.abspath(os.path.join(os.getcwd(), src))
                        img['src'] = f"file:///{abs_path.replace(os.sep, '/')}"
            return str(soup)
        
        def style_checkboxes(html):
            # 완료되지 않은 체크박스
            html = re.sub(r'<li>\[ \]', r'<li><span class="task-checkbox-empty"></span>', html)
            # 완료된 체크박스: '✔'
            html = re.sub(r'<li>\[x\]', r'<li><span class="task-checkbox-done"></span>', html)
            return html

        def style_priority_tags(html):
            # !p1, !p2 등을 - [ ] 로 보이게 함
            html = re.sub(r'!p([1-5])', r'<span class="rank-\1"></span>', html)
            return html
        
        def style_todotime_tags(html):
            html = re.sub(r'\s(@\S+\s\S*:\S+)', r'<span class="datetime-tag">\1</span>', html)
            html = re.sub(r'\s(@\S+)', r'<span class="date-tag">\1</span>', html)
            return html

        # 이미지 경로 변환 먼저 적용
        processed_html = convert_local_images(html_body)
        # 위키 링크 변환 적용
        parsed_body = re.sub(r'\[\[(.*?)\]\]', replace_wiki_links, processed_html)
        parsed_body = style_checkboxes(parsed_body)
        parsed_body = style_priority_tags(parsed_body)
        parsed_body = style_todotime_tags(parsed_body)
        

        # 태그를 표시하고 클릭 가능하게 만듦
        tags_html = ""
        if tags_text:
            tags = [t.strip() for t in tags_text.replace(',', ' ').split() if t.strip()]
            tags_html = '<div class="tags-container">'
            for tag in tags:
                clean_tag = tag.lstrip('#')
                tags_html += f'<a href="tag://{clean_tag}" class="tag-link">#{clean_tag}</a> '
            tags_html += '</div>'

        # 기본 CSS
        DEFAULT_CSS = """
        <style>
            body { font-family: "Segoe UI", "Malgun Gothic", sans-serif; line-height: 1.7; padding: 35px; background-color: #ffffff; color: #333333; }
            h1, h2, h3, h4, h5, h6 { font-weight: 600; color: #111111; margin-top: 1.5em; margin-bottom: 0.5em; line-height: 1.25; }
            h1 { font-size: 2em; border-bottom: 1px solid #eaecef; padding-bottom: 0.3em; }
            h2 { font-size: 1.5em; border-bottom: 1px solid #eaecef; padding-bottom: 0.3em; }
            p { margin: 0 0 16px 0; }
            a { color: #0366d6; text-decoration: none; } a:hover { text-decoration: underline; }
            .broken-link { color: #dc3545; text-decoration: line-through; cursor: help; }
            pre { background-color: #f6f8fa; border-radius: 4px; padding: 16px; overflow: auto; font-size: 85%; }
            code { font-family: "D2Coding", "Consolas", monospace; background-color: rgba(27,31,35,0.05); border-radius: 3px; padding: .2em .4em; font-size: 90%; }
            pre > code { padding: 0; background-color: transparent; }
            blockquote { margin: 0 0 16px 0; padding: 0 1.2em; color: #6a737d; border-left: 0.25em solid #dfe2e5; }
            ul, ol { padding-left: 2em; margin-bottom: 16px; }
            table { border-collapse: collapse; margin-bottom: 16px; display: block; width: 100%; overflow: auto; }
            th, td { border: 1px solid #dfe2e5; padding: 8px 13px; }
            tr { border-top: 1px solid #c6cbd1; background-color: #fff; }
            tr:nth-child(2n) { background-color: #f6f8fa; }
            hr { height: .25em; padding: 0; margin: 24px 0; background-color: #e1e4e8; border: 0; }
            .tags-container { margin-bottom: 20px; border-bottom: 1px solid #eaecef; padding-bottom: 10px; }
            .tag-link { background-color: #f1f8ff; color: #0366d6; padding: 3px 8px; border-radius: 12px; font-size: 0.9em; margin-right: 5px; }
            .tag-link:hover { background-color: #ddeeff; }
        </style>
        """
        
        final_css = DEFAULT_CSS
        custom_css_path = config_manager.get_setting('Display', 'custom_css_path')
        if custom_css_path and os.path.exists(custom_css_path):
            try:
                with open(custom_css_path, 'r', encoding='utf-8') as f:
                    final_css = f"<style>{f.read()}</style>"
            except Exception:
                pass
        
        return f'<html><head><meta charset="UTF-8"><title>{title}</title>{final_css}</head><body>{tags_html}{parsed_body}</body></html>'
    
    def on_link_activated(self, url):
        url_string = url.toString()
        if url_string.startswith('memo://'):
            doc_id = url_string.replace('memo://', '')
            print("[Link] 시리즈 캐시를 강제로 재구성합니다.")
            self.rebuild_series_cache() # 링크 클릭 시 시리즈 캐시를 동기적으로 재구성
            self.view_memo_from_cache_only(doc_id)
        elif url_string.startswith('tag://'):
            tag_name = url_string.replace('tag://', '')
            self.show_memo_list_window()
            items = self.memo_list.nav_tree.findItems(tag_name, Qt.MatchContains | Qt.MatchRecursive, 0)
            if items:
                self.memo_list.nav_tree.setCurrentItem(items[0])
                self.on_navigation_selected(items[0].text(0))
        else:
            QDesktopServices.openUrl(url)

    def view_memo_from_cache_only(self, doc_id):
        view_mode_info = self._get_view_mode_info(doc_id)
        cached_info = next((row for row in self.local_cache if row[2] == doc_id), None)
        title = cached_info[0] if cached_info else "캐시된 메모"

        cache_path = os.path.join(config_manager.CONTENT_CACHE_DIR, f"{doc_id}.html")
        
        if os.path.exists(cache_path):
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    cached_html_full = f.read()
                
                self.rich_viewer.update_favorite_status(doc_id in self.favorites)
                self.current_viewing_doc_id = doc_id
                self.emitter.show_rich_view.emit(doc_id, title, cached_html_full, view_mode_info)
            except Exception as e:
                error_html = self._get_final_html("오류", f"<body><p>캐시 파일을 읽는 중 오류가 발생했습니다: {e}</p></body>", "")
                self.emitter.show_rich_view.emit(doc_id, "오류", error_html, view_mode_info)
        else:
            error_html = self._get_final_html("오프라인", "<body><p>이 문서에 대한 로컬 캐시가 없습니다. 목록에서 문서를 열어 동기화해주세요.</p></body>", "")
            self.emitter.show_rich_view.emit(doc_id, "오프라인", error_html, view_mode_info)

    def edit_tags_from_viewer(self):
        if not self.current_viewing_doc_id:
            return

        doc_id = self.current_viewing_doc_id
        
        # API를 통해 최신 정보 로드
        title, content, current_tags = google_api_handler.load_doc_content(doc_id, as_html=False)

        if title is None:
            QMessageBox.warning(self.rich_viewer, "오류", "문서 내용을 불러올 수 없어 태그를 편집할 수 없습니다.")
            return
        
        new_tags, ok = QInputDialog.getText(self.rich_viewer, "태그 편집", "태그를 입력하세요 (쉼표나 공백으로 구분):", text=current_tags)

        if ok and new_tags != current_tags:
            self.update_memo_thread(doc_id, title, content, new_tags)

    def stay_awake(self):
        pass

    def edit_current_viewing_memo(self):
        if self.current_viewing_doc_id:
            print(f"뷰어에서 편집 요청: {self.current_viewing_doc_id}")
            self.rich_viewer.hide() # 현재 뷰어 창은 닫고
            self.edit_memo(self.current_viewing_doc_id) # 편집 창을 연다
    
    def open_current_memo_in_gdocs(self):
        if self.current_viewing_doc_id:
            url_string = f"https://docs.google.com/document/d/{self.current_viewing_doc_id}/edit"
            QDesktopServices.openUrl(QUrl(url_string))
            print(f"Google Docs에서 열기: {url_string}")

    def load_favorites(self):
        self.favorites = config_manager.get_favorites()

    def toggle_favorite(self, doc_id):
        if doc_id in self.favorites:
            self.favorites.remove(doc_id)
            config_manager.remove_favorite(doc_id)
            self.emitter.status_update.emit("즐겨찾기에서 해제되었습니다.", 3000)
            self.emitter.favorite_status_changed.emit(doc_id, False)
        else:
            self.favorites.append(doc_id)
            config_manager.add_favorite(doc_id)
            self.emitter.status_update.emit("즐겨찾기에 추가되었습니다.", 3000)
            self.emitter.favorite_status_changed.emit(doc_id, True)
        
        # 목록 창이 '즐겨찾기' 뷰 상태였다면, 목록을 즉시 새로고침
        current_item = self.memo_list.nav_tree.currentItem()
        if current_item and current_item.data(0, Qt.UserRole) == "favorites":
            self.on_navigation_selected("favorites")
            
    def toggle_favorite_from_viewer(self):
        if self.current_viewing_doc_id:
            self.toggle_favorite(self.current_viewing_doc_id)

    def on_favorite_status_changed(self, doc_id, is_favorite):
        # 1. 목록 창의 아이콘 업데이트
        for row in range(self.memo_list.table.rowCount()):
            item = self.memo_list.table.item(row, 1) # 제목 아이템
            if item and item.data(Qt.UserRole) == doc_id:
                fav_item = self.memo_list.table.item(row, 0)
                if fav_item:
                    icon = qta.icon('fa5s.star', color='#f0c420') if is_favorite else qta.icon('fa5s.star', color='#aaa')
                    fav_item.setIcon(icon)
                break
        
        if self.rich_viewer.isVisible() and self.current_viewing_doc_id == doc_id:
            self.rich_viewer.update_favorite_status(is_favorite)

        # 2. 네비게이션 트리 업데이트
        self.emitter.nav_tree_updated.emit(self.all_tags, self.local_cache)

    def load_tasks_thread(self):
        with self.cache_lock:
            local_cache_copy = list(self.local_cache)
        try:
            contents = {}
            for memo in local_cache_copy:
                doc_id, source_memo = memo[2], memo[0]
                cache_path = os.path.join(config_manager.CONTENT_CACHE_DIR, f"{doc_id}.txt")
                content = None
                if os.path.exists(cache_path):
                    try:
                        with open(cache_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                    except Exception as e:
                        print(f"Error reading cache for {doc_id}: {e}")

                if content is None:
                    _, markdown_content, _ = google_api_handler.load_doc_content(doc_id, as_html=False)
                    # 문서 로드에 실패한 경우(None) content는 None으로 유지
                    if markdown_content is not None:
                        content = markdown_content
                        try:
                            cache_dir = os.path.dirname(cache_path)
                            if not os.path.exists(cache_dir):
                                os.makedirs(cache_dir)
                            with open(cache_path, 'w', encoding='utf-8') as f:
                                f.write(content)
                        except Exception as e:
                            print(f"Error writing cache for {doc_id}: {e}")
                
                if content:
                    contents[doc_id] = {'content': content, 'source_memo': source_memo}
            
            self.emitter.tasks_data_loaded.emit(contents)

        except Exception as e:
            print(f"할 일 데이터 로딩 중 오류: {e}")
            self.emitter.todo_list_updated.emit([])
        finally:
            self.is_loading_tasks = False
    
    def process_loaded_tasks(self, contents):
        tasks = []
        # 마감일 패턴: @YYYY-MM-DD 또는 @YYYY-MM-DD HH:MM
        deadline_pattern = re.compile(r'@(\d{4}-\d{2}-\d{2}(?:\s\d{2}:\d{2})?)')
        # 우선순위 패턴: !p1, !p2, !p3 등
        priority_pattern = re.compile(r'!p([1-5])')

        for doc_id, data in contents.items():
            content = data['content']
            source_memo = data['source_memo']
            for line in content.split('\n'):
                stripped_line = line.strip()
                if stripped_line.startswith(("- [ ] ", "- [x] ")):
                    is_checked = stripped_line.startswith("- [x] ")
                    task_text = stripped_line[5:].strip()

                    deadline_str = None
                    priority_val = None
                    
                    # 마감일 찾기
                    deadline_match = deadline_pattern.search(task_text)
                    if deadline_match:
                        deadline_str = deadline_match.group(1)
                        task_text = task_text.replace(deadline_match.group(0), '').strip()
                    
                    # 우선순위 찾기
                    priority_match = priority_pattern.search(task_text)
                    if priority_match:
                        priority_val = int(priority_match.group(1))
                        task_text = task_text.replace(priority_match.group(0), '').strip()

                    tasks.append({
                        'doc_id': doc_id,
                        'line_text': task_text,          # 순수 할 일 텍스트
                        'original_line': stripped_line,
                        'source_memo': source_memo,
                        'is_checked': is_checked,
                        'deadline': deadline_str,    # @ 파싱 결과 (문자열)
                        'priority': priority_val,    # !p 파싱 결과 (숫자)
                    })
        
        self.all_tasks = tasks
        self.apply_task_filter_and_update_ui()

    def toggle_todo_dashboard(self):
        if self.is_loading_tasks: return
        
        if self.todo_dashboard.isVisible():
            self.todo_dashboard.hide()
        else:
            # 먼저 로딩 상태로 창을 보여줌
            self.todo_dashboard.show_message("🔄 할 일 목록을 불러오는 중...")
            
            screen_geometry = QApplication.primaryScreen().availableGeometry()
            x = screen_geometry.width() - self.todo_dashboard.width() - 10
            y = screen_geometry.height() - self.todo_dashboard.height() - 10
            self.todo_dashboard.move(x, y); self.todo_dashboard.show(); self.todo_dashboard.activateWindow()

            self.is_loading_tasks = True
            threading.Thread(target=self.load_tasks_thread, daemon=True).start()

    def on_task_toggled(self, task_info, is_checked):
        for task in self.all_tasks:
            if task['original_line'] == task_info['original_line'] and task['doc_id'] == task_info['doc_id']:
                task['is_checked'] = is_checked
                break

        self.apply_task_filter_and_update_ui()
        
        # 백그라운드에서 실제 파일 업데이트
        threading.Thread(target=self.update_task_thread, args=(task_info, is_checked), daemon=True).start()

    def update_task_thread(self, task_info, is_checked):
        success = google_api_handler.update_checklist_item(
            task_info['doc_id'],
            task_info['original_line'], # 'line_text' -> 'original_line'
            is_checked
        )
        if success:
            print("Task successfully updated in Google Docs.")
            # 성공 시, 콘텐츠 캐시도 업데이트하여 데이터 일관성 유지
            self.update_content_cache_after_toggle(task_info, is_checked)
        else:
            print("Failed to update task in Google Docs.")

    def update_content_cache_after_toggle(self, task_info, is_checked):
        doc_id = task_info['doc_id']
        cache_path = os.path.join(config_manager.CONTENT_CACHE_DIR, f"{doc_id}.txt")
        if not os.path.exists(cache_path): 
            print(f"Cache file not found for {doc_id}, cannot update.")
            return
        
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            new_line_prefix = "- [x] " if is_checked else "- [ ] "
            original_line_lf = task_info['original_line']

            new_lines = []
            found = False
            for line in lines:
                # 개행문자 차이(CRLF, LF)를 고려하여 비교
                if line.strip() == original_line_lf:
                    new_lines.append(new_line_prefix + task_info['line_text'] + '\n')
                    found = True
                else:
                    new_lines.append(line)
            
            if not found:
                print(f"Original line not found in cache file: {original_line_lf}")
                # 만약 못찾으면, 그냥 새로고침해서 서버로부터 다시 받도록 유도할 수 있음
                return

            with open(cache_path, 'w', encoding='utf-8') as f:
                f.writelines(new_lines)
            print("Content cache updated successfully.")
        except Exception as e:
            print(f"Error updating content cache: {e}")

    def open_editor_with_content(self, doc_id, title, markdown_content, tags_text):
        geometry_hex = config_manager.get_window_state(self.memo_editor.window_name)
        if geometry_hex:
            self.memo_editor.restoreGeometry(QByteArray.fromHex(geometry_hex.encode('utf-8')))
            
        self.memo_editor.open_document(doc_id, title, markdown_content, tags_text)
    
    def sync_cache_and_reload_tasks(self):
        print("메인 캐시 동기화 시작...")
        new_data = google_api_handler.load_memo_list()
        if new_data is not None:
            with self.cache_lock:
                # 변경된 문서를 확인하기 위해 이전 캐시의 문서 ID와 날짜를 맵으로 저장
                old_dates = {row[2]: row[1] for row in self.local_cache if len(row) > 2}
                self.local_cache = new_data
                try:
                    with open(config_manager.CACHE_FILE, 'w', encoding='utf-8') as f:
                        json.dump(self.local_cache, f, ensure_ascii=False, indent=4)
                    print("메인 캐시 동기화 완료.")
                except IOError as e:
                    print(f"메인 캐시 저장 오류: {e}")

                # 새 목록과 이전 날짜를 비교하여 변경된 문서의 콘텐츠 캐시만 삭제
                for memo in self.local_cache:
                    if len(memo) > 2:
                        doc_id = memo[2]
                        new_date = memo[1]
                        if doc_id not in old_dates or old_dates[doc_id] != new_date:
                            cache_path = os.path.join(config_manager.CONTENT_CACHE_DIR, f"{doc_id}.txt")
                            if os.path.exists(cache_path):
                                try:
                                    os.remove(cache_path)
                                    print(f"콘텐츠 캐시 무효화 (업데이트됨): {doc_id}")
                                except OSError as e:
                                    print(f"콘텐츠 캐시 파일 삭제 오류: {e}")
        
        # 최적화된 로드 스레드 시작
        self.load_tasks_thread()


    def refresh_todo_dashboard(self):
        if self.is_loading_tasks: return

        print("투두리스트 새로고침 요청 수신됨.")
        self.todo_dashboard.show_message("🔄 할 일 목록을 새로고침하는 중...")
        
        self.is_loading_tasks = True
        threading.Thread(target=self.sync_cache_and_reload_tasks, daemon=True).start()

    def on_completion_filter_changed(self, show_completed):
        self.show_completed_tasks = show_completed
        self.apply_task_filter_and_update_ui()

    def apply_task_filter_and_update_ui(self):
        if self.show_completed_tasks:
            tasks_to_show = self.all_tasks
        else:
            tasks_to_show = [task for task in self.all_tasks if not task['is_checked']]

        # ★★★ 정렬 로직 추가 ★★★
        def sort_key(task):
            # 우선순위, 마감일, 일반 항목 순서로 정렬
            priority = task['priority'] if task['priority'] is not None else 99  # 우선순위 없으면 가장 낮게
            try:
                # 시간 정보가 있는 경우 (예: 2024-12-25 10:00)
                if task['deadline'] and ':' in task['deadline']:
                    deadline_dt = datetime.strptime(task['deadline'], "%Y-%m-%d %H:%M")
                # 시간 정보가 없는 경우 (예: 2024-12-25)
                elif task['deadline']:
                     deadline_dt = datetime.strptime(task['deadline'], "%Y-%m-%d")
                else:
                    deadline_dt = datetime.max # 마감일 없으면 가장 늦게
            except (ValueError, TypeError):
                deadline_dt = datetime.max # 마감일 형식 오류 또는 None인 경우 가장 늦게
            
            return (priority, deadline_dt) # 우선순위 오름차순, 마감일 오름차순
        
        tasks_to_show.sort(key=sort_key)
        self.emitter.todo_list_updated.emit(tasks_to_show)

    def check_task_deadlines(self):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 마감일 알림 검사 시작...")
        now = datetime.now()
        today_str = now.date().isoformat()

        tasks_to_notify = []

        for task in self.all_tasks:
            if task['is_checked'] or not task['deadline']:
                continue

            task_id = f"{task['doc_id']}-{task['original_line']}"
            
            try:
                if ':' in task['deadline']:
                    deadline_dt = datetime.strptime(task['deadline'], "%Y-%m-%d %H:%M")
                else:
                    deadline_dt = datetime.strptime(task['deadline'], "%Y-%m-%d").replace(hour=23, minute=59, second=59)

                if deadline_dt <= now:
                    last_notified_str = self.notified_tasks.get(task_id)
                    
                    if last_notified_str is None:
                        # Never notified before
                        tasks_to_notify.append(task)
                        self.notified_tasks[task_id] = today_str
                    else:
                        # Notified before, check if it was on a previous day
                        last_notified_date = datetime.fromisoformat(last_notified_str).date()
                        if last_notified_date < now.date():
                            tasks_to_notify.append(task)
                            self.notified_tasks[task_id] = today_str

            except (ValueError, TypeError) as e:
                print(f"마감일 파싱 중 오류 (무시됨): {e}")
                pass

        if tasks_to_notify:
            for task in tasks_to_notify:
                title = "마감일 알림 ⏰"
                message = f"할 일: {task['line_text']}\n출처: {task['source_memo']}"
                print(f"알림 발생: {message}")
                self.emitter.persistent_notification.emit(title, message, task['doc_id'])
            
            # Save the updated notification history
            config_manager.save_notified_tasks(self.notified_tasks)

    def view_memo_from_notification(self, doc_id):
        self.view_memo_by_id(doc_id)

    def show_persistent_notification(self, title, message, doc_id):
        self.notification_queue.append((title, message, doc_id))
        self.process_notification_queue()

    def process_notification_queue(self):
        if not self.is_notification_active and self.notification_queue:
            self.is_notification_active = True
            title, message, doc_id = self.notification_queue.pop(0)
            
            screen_geometry = QApplication.primaryScreen().availableGeometry()
            win_size = self.notification_window.size()
            x = screen_geometry.width() - win_size.width() - 15
            y = screen_geometry.height() - win_size.height() - 15
            
            self.notification_window.move(x, y)
            self.notification_window.set_notification_data(title, message, doc_id)
            self.notification_window.show()
            self.notification_window.activateWindow()

    def on_notification_closed(self):
        self.is_notification_active = False
        self.process_notification_queue()

    

    def show_knowledge_graph(self):
        self.emitter.status_update.emit("지식 그래프를 생성하는 중입니다...", 0)
        threading.Thread(target=self.build_graph_thread, daemon=True).start()

    def on_graph_data_generated(self, graph_data):
        if graph_data:
            try:
                tag_info = graph_data.get("tag_info", {})
                self.graph_window.show_graph(graph_data, tag_info)
                self.graph_window.show()
                self.graph_window.activateWindow()
                self.emitter.status_update.emit("그래프 생성 완료.", 3000)
            except Exception as e:
                print(f"그래프를 표시하는 중 오류 발생: {e}")
                self.emitter.status_update.emit("그래프를 표시할 수 없습니다.", 5000)
        else:
            self.emitter.status_update.emit("그래프 생성 실패.", 5000)

    def build_graph_thread(self):
        try:
            print("[Graph] 지식 그래프 데이터 생성을 시작합니다.")

            # NetworkX 그래프 생성
            G = nx.DiGraph()

            # --- 데이터 준비 ---
            title_to_id_map = {row[0]: row[2] for row in self.local_cache if len(row) > 2}
            doc_id_to_info_map = {row[2]: {"title": row[0], "tags": [t.strip().lstrip('#') for t in row[3].replace(',', ' ').split() if t.strip().startswith('#')] if len(row) > 3 and row[3] else []} for row in self.local_cache if len(row) > 2}

            # --- 노드 추가 ---
            for doc_id, info in doc_id_to_info_map.items():
                G.add_node(doc_id, label=info['title'], title=f"메모 열기: {info['title']}")
            print(f"[Graph] {G.number_of_nodes()}개의 노드를 추가했습니다.")

            # --- 엣지 추가 ---
            link_pattern = re.compile(r'\[\[(.*?)\]\]')
            for source_doc_id in G.nodes():
                cache_path = os.path.join(config_manager.CONTENT_CACHE_DIR, f"{source_doc_id}.txt")
                content = ""
                if os.path.exists(cache_path):
                    with open(cache_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                else:
                    _, content, _ = google_api_handler.load_doc_content(source_doc_id, as_html=False)

                if content:
                    matches = link_pattern.findall(content)
                    for target_title in matches:
                        target_doc_id = title_to_id_map.get(target_title)
                        if target_doc_id and G.has_node(target_doc_id) and source_doc_id != target_doc_id:
                            G.add_edge(source_doc_id, target_doc_id)
            
            print(f"[Graph] {G.number_of_edges()}개의 엣지를 추가했습니다.")

            # --- 시각적 속성 설정 ---
            tag_colors = {}
            def get_tag_color(tag):
                if tag not in tag_colors:
                    hue = (hash(tag) & 0xFFFFFF) / 0xFFFFFF
                    saturation = 0.85
                    lightness = 0.60
                    rgb_float = colorsys.hls_to_rgb(hue, lightness, saturation)
                    color_hex = f"#{int(rgb_float[0] * 255):02x}{int(rgb_float[1] * 255):02x}{int(rgb_float[2] * 255):02x}"
                    tag_colors[tag] = color_hex
                return tag_colors[tag]

            # 1. 태그별 색상 매핑
            all_graph_tags = {tag for doc_id in G.nodes() for tag in doc_id_to_info_map.get(doc_id, {}).get('tags', [])}
            
            tag_to_color_map = {tag: get_tag_color(tag) for tag in all_graph_tags}

            # 2. 노드 크기 및 색상 설정
            in_degrees = G.in_degree()
            BASE_NODE_SIZE = 12
            SCALE_FACTOR = 4
            
            nodes_for_vis = []
            for node_id, data in G.nodes(data=True):
                degree = in_degrees[node_id]
                tags = doc_id_to_info_map.get(node_id, {}).get('tags', [])
                
                node_color = '#9E9E9E' # 기본 색상
                if tags:
                    for tag in tags:
                        if tag in tag_to_color_map:
                            node_color = tag_to_color_map[tag]
                            break
                
                nodes_for_vis.append({
                    "id": node_id,
                    "label": data['label'],
                    "title": data['title'],
                    "size": BASE_NODE_SIZE + (degree * SCALE_FACTOR),
                    "color": node_color,
                    "tags": tags
                })

            # --- 최종 데이터 생성 ---
            edges_for_vis = [{"from": u, "to": v} for u, v in G.edges()]
            
            tag_info = {}
            for tag, color in tag_to_color_map.items():
                count = sum(1 for doc_id in G.nodes() if tag in doc_id_to_info_map.get(doc_id, {}).get('tags', []))
                if count > 0:
                    tag_info[tag] = {"color": color, "count": count}

            graph_data = {"nodes": nodes_for_vis, "edges": edges_for_vis, "tag_info": tag_info}
            
            self.emitter.graph_data_generated.emit(graph_data)

        except Exception as e:
            print(f"그래프 데이터 생성 중 오류: {e}")
            import traceback
            traceback.print_exc()
            self.emitter.graph_data_generated.emit(None)

    def on_graph_node_clicked(self, doc_id):
        self.graph_window.hide()
        self.view_memo_by_id(doc_id)

    def on_viewer_refresh_requested(self, doc_id):
        print(f"뷰어에서 새로고침 요청: {doc_id}")
        # 해당 문서의 로컬 콘텐츠 캐시를 삭제
        cache_path_html = os.path.join(config_manager.CONTENT_CACHE_DIR, f"{doc_id}.html")
        cache_path_txt = os.path.join(config_manager.CONTENT_CACHE_DIR, f"{doc_id}.txt")
        if os.path.exists(cache_path_html):
            try: os.remove(cache_path_html)
            except OSError as e: print(f"HTML 캐시 삭제 오류: {e}")
        if os.path.exists(cache_path_txt):
            try: os.remove(cache_path_txt)
            except OSError as e: print(f"TXT 캐시 삭제 오류: {e}")
        
        # 문서를 다시 로드하여 뷰를 갱신
        self.view_memo_by_id(doc_id)

    def refresh_document_content(self, doc_id):
        """문서 콘텐츠를 새로고침하는 백그라운드 함수"""
        try:
            print(f"DEBUG: refresh_document_content 시작 - doc_id: {doc_id}")
            
            # 로딩 상태 표시
            loading_html = self._get_final_html("새로고침 중...", "<body><p>콘텐츠를 새로고침하는 중입니다...</p></body>", "")
            view_mode_info = self._get_view_mode_info(doc_id)
            self.emitter.show_rich_view.emit(doc_id, "새로고침 중...", loading_html, view_mode_info)
            
            # 추가로 캐시 파일이 남아있으면 강제 삭제
            cache_path_html = os.path.join(config_manager.CONTENT_CACHE_DIR, f"{doc_id}.html")
            cache_path_txt = os.path.join(config_manager.CONTENT_CACHE_DIR, f"{doc_id}.txt")
            if os.path.exists(cache_path_html):
                try:
                    os.remove(cache_path_html)
                    print(f"DEBUG: 추가 캐시 삭제 완료: {cache_path_html}")
                except OSError as e:
                    print(f"DEBUG: 추가 캐시 삭제 오류: {e}")
            if os.path.exists(cache_path_txt):
                try:
                    os.remove(cache_path_txt)
                    print(f"DEBUG: 추가 캐시 삭제 완료: {cache_path_txt}")
                except OSError as e:
                    print(f"DEBUG: 추가 캐시 삭제 오류: {e}")
            
            # Google Drive에서 최신 콘텐츠 가져오기
            title, html_body, tags_text = google_api_handler.load_doc_content(doc_id, as_html=True)
            
            if title and html_body is not None:
                # 최종 HTML 생성
                final_html = self._get_final_html(title, html_body, tags_text)
                view_mode_info = self._get_view_mode_info(doc_id)
                
                # UI 업데이트
                self.emitter.show_rich_view.emit(doc_id, title, final_html, view_mode_info)
                print(f"DEBUG: 문서 {doc_id} 새로고침 완료 - 제목: {title}")
            else:
                print(f"DEBUG: 문서 {doc_id} 새로고침 실패 - title: {title}, html_body: {html_body is not None}")
        except Exception as e:
            print(f"DEBUG: 문서 {doc_id} 새로고침 중 오류: {e}")
            import traceback
            traceback.print_exc()

    def update_memo_list_table(self):
        """현재 선택된 네비게이션에 따라 문서 목록 테이블을 업데이트"""
        try:
            if not hasattr(self, 'memo_list') or not self.memo_list.isVisible():
                print("DEBUG: memo_list가 없거나 보이지 않음")
                return
            
            print("DEBUG: memo_list 테이블 업데이트 시작")
            
            # 현재 선택된 네비게이션 아이템 확인
            current_item = self.memo_list.nav_tree.currentItem()
            if not current_item:
                # 기본적으로 전체 메모 표시
                print("DEBUG: 현재 선택된 아이템이 없음, 전체 메모 표시")
                series_cache = self.series_cache if hasattr(self, 'series_cache') else {}
                self.emitter.list_data_loaded.emit(self.local_cache, True, series_cache)
                return
            
            nav_id = current_item.data(0, Qt.UserRole)
            print(f"DEBUG: 현재 선택된 nav_id: {nav_id}")
            
            if nav_id:
                # 특정 태그나 즐겨찾기 선택된 경우
                if nav_id == "favorites":
                    favorites = config_manager.get_favorites()
                    filtered_data = [row for row in self.local_cache if row[2] in favorites]
                    print(f"DEBUG: 즐겨찾기 필터링 결과: {len(filtered_data)}개")
                    series_cache = self.series_cache if hasattr(self, 'series_cache') else {}
                    self.emitter.list_data_loaded.emit(filtered_data, True, series_cache)
                else:
                    # 태그별 필터링
                    filtered_data = []
                    for row in self.local_cache:
                        if len(row) > 3 and row[3]:
                            tags_in_row = [t.strip().lstrip('#') for t in row[3].replace(',', ' ').split() if t.strip().startswith('#')]
                            if nav_id in tags_in_row:
                                filtered_data.append(row)
                    print(f"DEBUG: 태그 '{nav_id}' 필터링 결과: {len(filtered_data)}개")
                    series_cache = self.series_cache if hasattr(self, 'series_cache') else {}
                    self.emitter.list_data_loaded.emit(filtered_data, True, series_cache)
            else:
                # 전체 메모 표시
                print("DEBUG: 전체 메모 표시")
                series_cache = self.series_cache if hasattr(self, 'series_cache') else {}
                self.emitter.list_data_loaded.emit(self.local_cache, True, series_cache)
                
        except Exception as e:
            print(f"DEBUG: update_memo_list_table 오류: {e}")
            import traceback
            traceback.print_exc()

    def update_series_cache_immediately(self, moc_doc_id, new_chapter_id, new_chapter_title):
        """새 회차 추가 시 시리즈 캐시를 즉시 업데이트"""
        try:
            # 기존 회차들의 정보를 가져옴
            existing_chapters = []
            for chapter_id, info in self.series_cache.items():
                if info.get('parent_moc_id') == moc_doc_id:
                    existing_chapters.append(chapter_id)
            
            # 새 회차를 맨 앞에 추가 (최신 회차)
            if existing_chapters:
                # 기존 첫 번째 회차의 이전 회차를 새 회차로 설정
                first_chapter = existing_chapters[0]
                if first_chapter in self.series_cache:
                    self.series_cache[first_chapter]['prev_chapter_id'] = new_chapter_id
            
            # 새 회차의 시리즈 정보 설정
            moc_info = next((row for row in self.local_cache if row[2] == moc_doc_id), None)
            if moc_info:
                self.series_cache[new_chapter_id] = {
                    'parent_moc_id': moc_doc_id,
                    'parent_moc_title': moc_info[0],
                    'prev_chapter_id': None,
                    'next_chapter_id': existing_chapters[0] if existing_chapters else None,
                    'chapter_title': new_chapter_title
                }
                print(f"시리즈 캐시에 새 회차 추가: {new_chapter_title}")
        except Exception as e:
            print(f"시리즈 캐시 즉시 업데이트 오류: {e}")

    def rebuild_series_cache_if_needed(self):
        # 앱 시작 시 또는 데이터 동기화 후 호출되어 시리즈 정보를 재구성합니다.
        print("시리즈 캐시 재구성 시작...")
        threading.Thread(target=self.rebuild_series_cache, daemon=True).start()

    def rebuild_series_cache(self):
        print("DEBUG: rebuild_series_cache 시작")
        new_series_cache = {}
        title_to_id_map = {row[0]: row[2] for row in self.local_cache if len(row) > 2}
        print(f"DEBUG: title_to_id_map 생성됨 - {len(title_to_id_map)}개 항목")

        # 1. 모든 MOC 문서를 찾는다.
        moc_docs = []
        for row in self.local_cache:
            if len(row) > 3 and ('#moc' in row[3].lower() or '#시리즈' in row[3].lower()):
                moc_docs.append({"id": row[2], "title": row[0]})
        print(f"DEBUG: MOC 문서 {len(moc_docs)}개 발견")

        # 2. 각 MOC에 대해 회차 목록을 파싱한다.
        for moc in moc_docs:
            moc_id = moc['id']
            moc_title = moc['title']
            print(f"DEBUG: MOC 처리 중 - {moc_title} ({moc_id})")
            
            # MOC의 콘텐츠를 가져온다 (캐시 우선, 없으면 API)
            content = ""
            cache_path = os.path.join(config_manager.CONTENT_CACHE_DIR, f"{moc_id}.txt")
            if os.path.exists(cache_path):
                with open(cache_path, 'r', encoding='utf-8') as f: content = f.read()
                print(f"DEBUG: 캐시에서 콘텐츠 로드됨 - 길이: {len(content)}")
            else:
                _, content, _ = google_api_handler.load_doc_content(moc_id, as_html=False)
                if content: 
                    with open(cache_path, 'w', encoding='utf-8') as f: f.write(content)
                    print(f"DEBUG: API에서 콘텐츠 로드됨 - 길이: {len(content)}")

            if not content:
                print(f"DEBUG: 콘텐츠 없음, 건너뜀")
                continue

            # 3. 회차 목록을 기반으로 각 회차의 이전/다음 정보를 계산한다.
            link_pattern = re.compile(r'\[\[(.*?)\]\]')
            chapter_titles = link_pattern.findall(content)
            print(f"DEBUG: 링크 패턴으로 찾은 회차 제목들: {chapter_titles}")
            
            chapter_ids = [title_to_id_map.get(title) for title in chapter_titles]
            chapter_ids = [id for id in chapter_ids if id] # None 값 제거
            print(f"DEBUG: 매핑된 회차 ID들: {chapter_ids}")

            for i, chapter_id in enumerate(chapter_ids):
                prev_id = chapter_ids[i-1] if i > 0 else None
                next_id = chapter_ids[i+1] if i < len(chapter_ids) - 1 else None
                
                new_series_cache[chapter_id] = {
                    "parent_moc_id": moc_id,
                    "parent_moc_title": moc_title,
                    "prev_chapter_id": prev_id,
                    "next_chapter_id": next_id
                }
                print(f"DEBUG: 회차 캐시 추가됨 - {chapter_id}: prev={prev_id}, next={next_id}")

        # 4. 완성된 새 캐시를 저장한다.
        self.series_cache = new_series_cache
        save_series_cache(self.series_cache)
        print(f"DEBUG: 시리즈 캐시 재구성 완료. 총 {len(new_series_cache)}개 항목")
        print(f"DEBUG: 시리즈 캐시 내용: {new_series_cache}")

    def on_add_chapter_requested(self):
        if not self.current_viewing_doc_id:
            return

        # 1. 부모 MOC 메모의 정보 가져오기
        moc_doc_id = self.current_viewing_doc_id
        moc_info = next((row for row in self.local_cache if row[2] == moc_doc_id), None)
        if not moc_info:
            self.emitter.status_update.emit("오류: 현재 MOC 메모 정보를 찾을 수 없습니다.", 4000)
            return
        
        moc_title = moc_info[0]

        # 2. 새 회차의 제목을 사용자에게 입력받기
        new_chapter_title, ok = QInputDialog.getText(self.rich_viewer, "새 회차 추가", f"'{moc_title}' 시리즈에 추가할 새 회차의 제목을 입력하세요:")

        if ok and new_chapter_title:
            # 3. 새 메모 생성 및 MOC 업데이트를 백그라운드 스레드에서 실행
            self.emitter.status_update.emit(f"'{new_chapter_title}' 회차를 추가하는 중...", 0)
            threading.Thread(target=self.add_chapter_thread, 
                             args=(moc_doc_id, moc_title, new_chapter_title), 
                             daemon=True).start()

    # ★★★ 백그라운드에서 실행될 스레드 함수 ★★★
    def add_chapter_thread(self, moc_doc_id, moc_title, chapter_title):
        # 1. 새 회차 메모 생성
        full_new_title = f"{moc_title} - {chapter_title}"
        initial_content = f"# {chapter_title}\n\n이전 시리즈: [[{moc_title}]]\n\n"
        
        moc_tags_text = next((row[3] for row in self.local_cache if row[2] == moc_doc_id), "")
        inherited_tags = [t for t in moc_tags_text.replace(',', ' ').split() if t.lower() not in ['#moc', '#시리즈']]
        tags_str = " ".join(inherited_tags)
        
        success, new_doc_id = google_api_handler.save_memo(full_new_title, initial_content, tags_str)

        if not success:
            self.emitter.status_update.emit("새 회차 메모 생성에 실패했습니다.", 5000)
            return

        # 2. 부모 MOC 문서에 새 회차 링크 추가 (예쁘게 포맷팅)
        # 먼저 MOC 문서의 현재 내용을 확인하여 목록 섹션 찾기
        moc_title, moc_content, moc_tags = google_api_handler.load_doc_content(moc_doc_id, as_html=False)
        
        if moc_content:
            # 기존 회차 개수 세기 (더 정확한 패턴 매칭)
            existing_chapters = []
            lines = moc_content.split('\n')
            
            # 목록 섹션 찾기
            list_section_start = -1
            for i, line in enumerate(lines):
                if '#### 목록' in line or '### 목록' in line or '## 목록' in line:
                    list_section_start = i
                    break
            
            if list_section_start >= 0:
                # 목록 섹션 내에서 기존 회차들 찾기
                for i in range(list_section_start + 1, len(lines)):
                    line = lines[i].strip()
                    # 번호가 매겨진 회차 항목 찾기 (1. [[...]], 2. [[...]] 등)
                    if re.match(r'^\d+\.\s*\[\[.*\]\]', line):
                        existing_chapters.append(line)
                    elif line.startswith('####') or line.startswith('###') or line.startswith('##'):
                        # 다른 섹션이 시작되면 목록 섹션 종료
                        break
                    elif not line:
                        # 빈 줄은 무시
                        continue
                    elif '[[(' in line and ']]' in line:
                        # 번호가 없는 회차도 카운트
                        existing_chapters.append(line)
            else:
                # 목록 섹션이 없는 경우 모든 회차 링크 찾기
                for line in lines:
                    if '[[(' in line and ']]' in line and '테스트 회차' in line:
                        existing_chapters.append(line.strip())
            
            chapter_number = len(existing_chapters) + 1
            print(f"DEBUG: 기존 회차 {len(existing_chapters)}개 발견, 새 회차 번호: {chapter_number}")
            
            # 목록 섹션이 있는지 확인
            has_list_section = list_section_start >= 0
            
            if has_list_section:
                # 기존 목록 섹션에 추가
                link_to_add = f"\n{chapter_number}. [[{full_new_title}]]"
                print(f"DEBUG: 기존 목록 섹션에 추가: {link_to_add}")
            else:
                # 새로운 목록 섹션 생성
                link_to_add = f"\n\n#### 목록\n{chapter_number}. [[{full_new_title}]]"
                print(f"DEBUG: 새로운 목록 섹션 생성: {link_to_add}")
        else:
            # MOC 문서 내용을 가져올 수 없는 경우 기본 형태로 추가
            link_to_add = f"\n\n#### 목록\n1. [[{full_new_title}]]"
            print(f"DEBUG: MOC 문서 내용 없음, 기본 형태로 추가: {link_to_add}")
        
        update_success = google_api_handler.append_text_to_doc(moc_doc_id, link_to_add)

        if not update_success:
            self.emitter.status_update.emit("MOC에 링크를 추가하는 데 실패했습니다.", 5000)
            return
            
        # 3. 로컬 캐시를 즉시 수동으로 업데이트 (레이스 컨디션 방지)
        from datetime import datetime
        current_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        new_row = [full_new_title, current_date, new_doc_id, tags_str]
        
        # 새 항목이 이미 있는지 확인하고 중복 방지
        existing_ids = {row[2] for row in self.local_cache if len(row) > 2}
        if new_doc_id not in existing_ids:
            self.local_cache.insert(0, new_row)
            print(f"DEBUG: 새 회차가 local_cache에 추가됨: {full_new_title}")
        else:
            print(f"DEBUG: 새 회차가 이미 local_cache에 존재함: {full_new_title}")
        
        self.update_tags_from_cache()

        # 4. MOC 문서의 로컬 콘텐츠 캐시 삭제
        moc_cache_path_html = os.path.join(config_manager.CONTENT_CACHE_DIR, f"{moc_doc_id}.html")
        moc_cache_path_txt = os.path.join(config_manager.CONTENT_CACHE_DIR, f"{moc_doc_id}.txt")
        if os.path.exists(moc_cache_path_html):
            try: 
                os.remove(moc_cache_path_html)
                print(f"DEBUG: MOC HTML 캐시 삭제 완료: {moc_cache_path_html}")
            except OSError as e: 
                print(f"MOC HTML 캐시 삭제 오류: {e}")
        if os.path.exists(moc_cache_path_txt):
            try: 
                os.remove(moc_cache_path_txt)
                print(f"DEBUG: MOC TXT 캐시 삭제 완료: {moc_cache_path_txt}")
            except OSError as e: 
                print(f"MOC TXT 캐시 삭제 오류: {e}")

        # 5. UI 업데이트
        self.emitter.status_update.emit("새 회차가 성공적으로 추가되었습니다.", 3000)
        
        # MOC 문서가 열려있는 경우 즉시 새로고침
        if self.rich_viewer.isVisible() and self.current_viewing_doc_id == moc_doc_id:
            print("DEBUG: MOC 문서가 열려있어서 즉시 새로고침")
            # MOC 문서의 캐시를 삭제했으므로 강제로 새로고침
            threading.Thread(target=self.refresh_document_content, args=(moc_doc_id,), daemon=True).start()
        else:
            print("DEBUG: MOC 문서가 열려있지 않음")
            # MOC 문서가 열려있지 않더라도 나중에 열 때 최신 내용이 보이도록 강제 새로고침
            print("DEBUG: MOC 문서 강제 새로고침을 위해 view_memo_by_id 호출")
            self.view_memo_by_id(moc_doc_id, force_refresh=True)
        
        # 네비게이션 트리 업데이트
        print("DEBUG: 네비게이션 트리 업데이트")
        self.emitter.nav_tree_updated.emit(self.all_tags, self.local_cache)
        
        # 문서 목록 테이블도 즉시 업데이트 (memo_list가 열려있을 때만)
        if hasattr(self, 'memo_list') and self.memo_list.isVisible():
            print("DEBUG: memo_list가 열려있어서 테이블 업데이트")
            self.update_memo_list_table()
        else:
            print("DEBUG: memo_list가 열려있지 않아서 테이블 업데이트 건너뜀")
        
        # 시리즈 캐시 즉시 업데이트
        print("DEBUG: 시리즈 캐시 즉시 업데이트")
        self.update_series_cache_immediately(moc_doc_id, new_doc_id, chapter_title)
        
        # 6. 백그라운드에서 전체 동기화 실행 (다른 변경사항과의 일관성 유지)
        print("DEBUG: 백그라운드 동기화 시작")
        self.rebuild_series_cache_if_needed()

        # 7. 새로 생성된 회차의 콘텐츠를 미리 캐싱
        print("DEBUG: 새 회차 콘텐츠 캐싱 시작")
        threading.Thread(target=self.sync_rich_content_thread, args=(new_doc_id, False), daemon=True).start()
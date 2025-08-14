import sys
import threading
import json
import os
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
from core.utils import resource_path
from app_windows import MarkdownEditorWindow, MemoListWindow, SettingsWindow, RichMemoViewWindow, QuickLauncherWindow, TodoDashboardWindow, TodoItemWidget
import qtawesome as qta

class SignalEmitter(QObject):
    show_new_memo = pyqtSignal()
    show_list_memo = pyqtSignal()
    show_settings = pyqtSignal()
    show_quick_launcher = pyqtSignal()
    show_edit_memo = pyqtSignal(str, str, str, str)
    show_rich_view = pyqtSignal(str, str)
    list_data_loaded = pyqtSignal(list, bool)
    nav_tree_updated = pyqtSignal(set, list)
    status_update = pyqtSignal(str, int)
    notification = pyqtSignal(str, str)
    favorite_status_changed = pyqtSignal(str, bool)
    auto_save_status_update = pyqtSignal(str)
    todo_list_updated = pyqtSignal(list)
    sync_finished_update_list = pyqtSignal()
    tasks_data_loaded = pyqtSignal(dict)
    toggle_todo_dashboard_signal = pyqtSignal()

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

        self.local_cache = []
        self.all_tags = set()
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

        self.auto_save_timer = QTimer()
        self.auto_save_timer.setSingleShot(True)
        self.auto_save_interval_ms = 3000

        self.connect_signals_and_slots()
        self.load_cache_only(initial_load=True)
        self.setup_hotkeys()
        self.setup_tray_icon()
        QTimer.singleShot(2000, self.start_initial_sync)

        self.favorites = []
        self.load_favorites()

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
        self.emitter.notification.connect(self.show_notification, Qt.QueuedConnection)
        self.emitter.sync_finished_update_list.connect(self.on_sync_finished_update_list, Qt.QueuedConnection)
        self.emitter.todo_list_updated.connect(self.todo_dashboard.update_tasks, Qt.QueuedConnection)
        self.emitter.tasks_data_loaded.connect(self.process_loaded_tasks, Qt.QueuedConnection)
        self.emitter.toggle_todo_dashboard_signal.connect(self.toggle_todo_dashboard, Qt.QueuedConnection)

        self.search_timer.timeout.connect(self.perform_search)
        
        self.todo_dashboard.task_toggled.connect(self.on_task_toggled)
        self.todo_dashboard.item_clicked.connect(self.view_memo_by_id)
        self.todo_dashboard.refresh_requested.connect(self.refresh_todo_dashboard)

        self.memo_list.search_bar.textChanged.connect(self.on_search_text_changed)
        self.memo_list.full_text_search_check.stateChanged.connect(self.search_mode_changed)
        self.memo_list.table.itemDoubleClicked.connect(self.view_memo_from_item)
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

        self.rich_viewer.favorite_toggled.connect(self.toggle_favorite_from_viewer)
        self.memo_list.favorite_toggled_from_list.connect(self.toggle_favorite)
        self.emitter.favorite_status_changed.connect(self.on_favorite_status_changed)

        # 자동 저장 관련
        self.memo_editor.editor.textChanged.connect(self.on_editor_text_changed)
        self.memo_editor.title_input.textChanged.connect(self.on_editor_text_changed)
        self.memo_editor.tag_input.textChanged.connect(self.on_editor_text_changed)
        self.auto_save_timer.timeout.connect(lambda: self.save_memo(is_auto_save=True))
        self.emitter.auto_save_status_update.connect(self.memo_editor.update_auto_save_status, Qt.QueuedConnection)
        

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
        if self.memo_list.isVisible() and not self.memo_list.full_text_search_check.isChecked():
            current_nav_item = self.memo_list.nav_tree.currentItem()
            if current_nav_item:
                self.on_navigation_selected(current_nav_item.text(0))

    def start_initial_sync(self):
        self.emitter.status_update.emit("최신 정보 동기화 중...", 2000)
        threading.Thread(target=self.sync_cache_thread, daemon=True).start()

    def sync_cache_thread(self):
        new_data = google_api_handler.load_memo_list()
        with self.cache_lock:
            if new_data is not None and new_data != self.local_cache:
                self.local_cache = new_data
                self.update_tags_from_cache()
                try:
                    with open(config_manager.CACHE_FILE, 'w', encoding='utf-8') as f:
                        json.dump(self.local_cache, f, ensure_ascii=False, indent=4)
                except IOError:
                    pass
                
                self.emitter.nav_tree_updated.emit(self.all_tags, self.local_cache)
                self.emitter.sync_finished_update_list.emit()
                self.emitter.status_update.emit("동기화 완료.", 5000)

    def load_cache_only(self, initial_load=False):
        try:
            if os.path.exists(config_manager.CACHE_FILE):
                with open(config_manager.CACHE_FILE, 'r', encoding='utf-8') as f:
                    self.local_cache = json.load(f)
                self.update_tags_from_cache()
                if initial_load:
                    self.emitter.list_data_loaded.emit(self.local_cache, True)
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

        # id가 favorites이면 즐겨찾기 목록을 표시
        if selected_item_id == "favorites":
            fav_memos = [row for row in self.local_cache if len(row) > 2 and row[2] in self.favorites]
            self.emitter.list_data_loaded.emit(fav_memos, True)
            return

        # "태그 (12)" 와 같은 형식에서 텍스트 부분만 추출
        clean_selected_item = re.sub(r'\s*\(\d+\)', '', selected_item_id).strip()

        if clean_selected_item == "전체 메모":
            self.emitter.list_data_loaded.emit(self.local_cache, True)
        elif clean_selected_item not in ["태그", ""]:
            # 선택된 태그를 포함하는 메모만 필터링
            filtered_data = [
                row for row in self.local_cache
                if len(row) > 3 and row[3] and clean_selected_item in [tag.strip().lstrip('#') for tag in row[3].replace(',', ' ').split()]
            ]
            self.emitter.list_data_loaded.emit(filtered_data, True)

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

        self.memo_list.show()
        self.memo_list.activateWindow()
        self.memo_list.raise_()
        is_full_text = self.memo_list.full_text_search_check.isChecked()
        self.memo_list.search_bar.setPlaceholderText("본문 내용으로 검색..." if is_full_text else "제목으로 실시간 필터링...")
        
        # 네비게이션 트리 업데이트
        self.memo_list.update_nav_tree(self.all_tags, self.local_cache)

        current_nav = self.memo_list.nav_tree.currentItem()
        if current_nav:
            self.on_navigation_selected(current_nav.text(0))
        else:
            # 기본값으로 '전체 메모' 선택
            all_memos_item = self.memo_list.nav_tree.findItems("전체 메모", Qt.MatchFixedString | Qt.MatchRecursive, 0)
            if all_memos_item:
                self.memo_list.nav_tree.setCurrentItem(all_memos_item[0])
            self.on_navigation_selected("전체 메모")


    def on_search_text_changed(self):
        if self.memo_list.full_text_search_check.isChecked():
            self.search_timer.start(600)
        else:
            self.filter_local_cache()
    
    def search_mode_changed(self):
        is_full_text = self.memo_list.full_text_search_check.isChecked()
        self.memo_list.search_bar.setPlaceholderText("본문 내용으로 검색..." if is_full_text else "제목으로 실시간 필터링...")
        
        if is_full_text:
            self.emitter.list_data_loaded.emit([], False)
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
            
        self.emitter.list_data_loaded.emit(filtered_data, True)


    def perform_search(self, page_token=None, is_prev=False, is_next=False):
        query = self.memo_list.search_bar.text()
        if not query:
            self.emitter.list_data_loaded.emit([], False)
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
        self.emitter.list_data_loaded.emit(data if data else [], False)
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
                self.emitter.notification.emit("저장 완료", f"'{title}' 메모가 저장되었습니다.")
            
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
                self.emitter.notification.emit("업데이트 완료", f"'{title}' 메모가 업데이트되었습니다.")

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


    def view_memo_from_item(self, item):
        doc_id = item.data(Qt.UserRole)
        self.view_memo_by_id(doc_id)

    def view_memo_by_id(self, doc_id):
        if self.rich_viewer.isVisible() and self.current_viewing_doc_id == doc_id:
            self.rich_viewer.activateWindow()
            return

        self.rich_viewer.update_favorite_status(doc_id in self.favorites)
        
        self.current_viewing_doc_id = doc_id
        
        # 로컬 캐시에서 제목과 태그 우선 로드
        cached_info = next((row for row in self.local_cache if row[2] == doc_id), None)
        title_from_cache = cached_info[0] if cached_info else "불러오는 중..."
        tags_from_cache = cached_info[3] if cached_info else ""

        cache_path = os.path.join(config_manager.CONTENT_CACHE_DIR, f"{doc_id}.html")
        if os.path.exists(cache_path):
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    cached_html_full = f.read()
                self.emitter.show_rich_view.emit(title_from_cache, cached_html_full)
            except Exception:
                self.emitter.show_rich_view.emit("오류", "캐시 파일을 읽을 수 없습니다.")
        else:
            # 콘텐츠가 캐시에 없으면 '불러오는 중' 메시지를 즉시 표시
            loading_html = self._get_final_html(title_from_cache, "<body><p>콘텐츠를 불러오는 중입니다...</p></body>", tags_from_cache)
            self.emitter.show_rich_view.emit(title_from_cache, loading_html)

        # 항상 최신 콘텐츠를 백그라운드에서 동기화
        threading.Thread(target=self.sync_rich_content_thread, args=(doc_id,), daemon=True).start()

    def sync_rich_content_thread(self, doc_id):
        # API에서 최신 콘텐츠 로드
        title, html_body, tags = google_api_handler.load_doc_content(doc_id, as_html=True)
        if title is None:
            # 로드 실패 시 현재 뷰어에 표시된 콘텐츠를 유지
            return

        # 이미지 처리 및 HTML 완성
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

        # 콘텐츠에 변경이 있을 경우에만 캐시 파일 업데이트 및 뷰 갱신
        if new_html_full != current_html_full:
            try:
                with open(cache_path, 'w', encoding='utf-8') as f:
                    f.write(new_html_full)
            except Exception as e:
                print(f"콘텐츠 캐시 저장 오류: {e}")
            
            # 현재 보고 있는 문서일 경우에만 뷰를 새로고침
            if self.rich_viewer.isVisible() and self.current_viewing_doc_id == doc_id:
                self.emitter.show_rich_view.emit(title, new_html_full)

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
        success = google_api_handler.delete_memo(doc_id)
        if success:
            # 로컬 캐시에서 해당 메모 제거
            self.local_cache = [row for row in self.local_cache if len(row) > 2 and row[2] != doc_id]
            # 캐시 파일에 변경사항 저장
            with open(config_manager.CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.local_cache, f, ensure_ascii=False, indent=4)
            # 태그 목록 업데이트 및 UI 갱신
            self.update_tags_from_cache()
            self.emitter.nav_tree_updated.emit(self.all_tags, self.local_cache)
            self.on_navigation_selected("전체 메모") # 전체 메모 목록으로 돌아가기
            self.emitter.status_update.emit("삭제 완료", 5000)
        else:
            self.emitter.status_update.emit("삭제 실패", 5000)

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

    def show_notification(self, title, message):
        if self.icon and self.icon.visible:
            self.icon.notify(message, title)
    
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
        
        def style_checkboxes(html):
            # 완료되지 않은 체크박스
            html = re.sub(r'<li>\[ \]', r'<li><span class="task-checkbox-empty"></span>', html)
            # 완료된 체크박스: '✔'
            html = re.sub(r'<li>\[x\]', r'<li><span class="task-checkbox-done"></span>', html)
            return html

        parsed_body = re.sub(r'\[\[(.*?)\]\]', replace_wiki_links, html_body)
        parsed_body = style_checkboxes(parsed_body)

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
            self.view_memo_by_id(url_string.replace('memo://', ''))
        elif url_string.startswith('tag://'):
            tag_name = url_string.replace('tag://', '')
            self.show_memo_list_window()
            items = self.memo_list.nav_tree.findItems(tag_name, Qt.MatchContains | Qt.MatchRecursive, 0)
            if items:
                self.memo_list.nav_tree.setCurrentItem(items[0])
                self.on_navigation_selected(items[0].text(0))
        else:
            QDesktopServices.openUrl(url)

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
                    if markdown_content:
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
        for doc_id, data in contents.items():
            content = data['content']
            source_memo = data['source_memo']
            for line in content.split('\n'):
                stripped_line = line.strip()
                if stripped_line.startswith(("- [ ] ", "- [x] ")):
                    is_checked = stripped_line.startswith("- [x] ")
                    task_text = stripped_line[5:].strip()
                    tasks.append({
                        'doc_id': doc_id,
                        'line_text': task_text,
                        'original_line': stripped_line,
                        'source_memo': source_memo,
                        'is_checked': is_checked
                    })
        
        tasks.sort(key=lambda x: x['is_checked'])
        self.emitter.todo_list_updated.emit(tasks)

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
        for i in range(self.todo_dashboard.content_layout.count()):
            widget = self.todo_dashboard.content_layout.itemAt(i).widget()
            if isinstance(widget, TodoItemWidget) and widget.checkbox.property("task_info") == task_info:
                widget.set_checked_state(is_checked); break
        
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
                self.local_cache = new_data
                self.update_tags_from_cache()
                try:
                    with open(config_manager.CACHE_FILE, 'w', encoding='utf-8') as f:
                        json.dump(self.local_cache, f, ensure_ascii=False, indent=4)
                    print("메인 캐시 동기화 완료.")
                except IOError:
                    pass
        
        # 콘텐츠 캐시(.txt) 제거
        print("콘텐츠 캐시 비우는 중...")
        cache_dir = config_manager.CONTENT_CACHE_DIR
        try:
            for filename in os.listdir(cache_dir):
                if filename.endswith(".txt"):
                    os.remove(os.path.join(cache_dir, filename))
            print("콘텐츠 캐시 비우기 완료.")
        except Exception as e:
            print(f"캐시 비우기 중 오류: {e}")

        self.load_tasks_thread()


    def refresh_todo_dashboard(self):
        if self.is_loading_tasks: return

        print("투두리스트 새로고침 요청 수신됨.")
        self.todo_dashboard.show_message("🔄 할 일 목록을 새로고침하는 중...")
        
        self.is_loading_tasks = True
        threading.Thread(target=self.sync_cache_and_reload_tasks, daemon=True).start()
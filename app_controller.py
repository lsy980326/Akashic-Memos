import sys
import threading
import json
import os
import markdown
from PyQt5.QtWidgets import QApplication, QMessageBox, QMenu, QDesktopWidget
from PyQt5.QtCore import QObject, pyqtSignal, QTimer, Qt
from PyQt5.QtGui import QTextDocument
import keyboard
from pystray import Icon as pystray_icon, Menu as pystray_menu, MenuItem as pystray_menu_item
from PIL import Image
from core import google_api_handler, config_manager
from core.utils import resource_path
from app_windows import MarkdownEditorWindow, MemoListWindow, SettingsWindow, RichMemoViewWindow, QuickLauncherWindow

class SignalEmitter(QObject):
    show_new_memo = pyqtSignal()
    show_list_memo = pyqtSignal()
    show_settings = pyqtSignal()
    show_quick_launcher = pyqtSignal()
    show_edit_memo = pyqtSignal(str, str, str)
    show_rich_view = pyqtSignal(str, str)
    list_data_loaded = pyqtSignal(list, bool)
    status_update = pyqtSignal(str, int)
    notification = pyqtSignal(str, str)

class AppController:
    def __init__(self, app):
        self.app = app; self.emitter = SignalEmitter()
        self.memo_editor = MarkdownEditorWindow(); self.memo_list = MemoListWindow(); self.settings = SettingsWindow(); self.rich_viewer = RichMemoViewWindow(); self.quick_launcher = QuickLauncherWindow()
        self.local_cache = []; self.current_page_token = None; self.next_page_token = None; self.prev_page_tokens = []
        self.search_timer = QTimer(); self.search_timer.setSingleShot(True); self.search_timer.timeout.connect(self.perform_search)
        self.icon = None
        self.connect_signals_and_slots()
        self.setup_hotkeys()
        self.setup_tray_icon()
        self.sync_cache_from_google()

    def connect_signals_and_slots(self):
        self.emitter.show_new_memo.connect(self.show_new_memo_window)
        self.emitter.show_list_memo.connect(self.show_memo_list_window)
        self.emitter.show_settings.connect(self.show_settings_window)
        self.emitter.show_quick_launcher.connect(self.toggle_quick_launcher)
        self.emitter.list_data_loaded.connect(self.memo_list.populate_table)
        self.emitter.show_edit_memo.connect(self.memo_editor.open_document)
        self.emitter.show_rich_view.connect(self.rich_viewer.set_content)
        self.emitter.status_update.connect(self.memo_list.statusBar.showMessage)
        self.emitter.notification.connect(self.show_notification)
        
        self.search_timer.timeout.connect(self.perform_search)
        self.memo_list.search_bar.textChanged.connect(self.on_search_text_changed)
        self.memo_list.full_text_search_check.stateChanged.connect(self.search_mode_changed)
        self.memo_list.table.itemDoubleClicked.connect(self.view_memo_from_item)
        self.memo_list.table.customContextMenuRequested.connect(self.show_context_menu)
        self.memo_list.prev_button.clicked.connect(self.go_to_prev_page)
        self.memo_list.next_button.clicked.connect(self.go_to_next_page)
        
        self.memo_editor.save_button.clicked.connect(self.save_memo)
        self.memo_editor.preview_timer.timeout.connect(self.update_editor_preview)
        self.memo_editor.editor.textChanged.connect(lambda: self.memo_editor.preview_timer.start(500))
        
        self.settings.save_button.clicked.connect(self.save_settings)
        self.settings.startup_checkbox.stateChanged.connect(config_manager.set_startup)

        self.quick_launcher.search_box.textChanged.connect(self.search_for_launcher)
        self.quick_launcher.memo_selected.connect(self.view_memo_by_id)

    def setup_hotkeys(self):
        try:
            hotkey_new = config_manager.get_setting('Hotkeys', 'new_memo'); hotkey_list = config_manager.get_setting('Hotkeys', 'list_memos'); hotkey_launcher = config_manager.get_setting('Hotkeys', 'quick_launcher')
            keyboard.add_hotkey(hotkey_new, lambda: self.emitter.show_new_memo.emit())
            keyboard.add_hotkey(hotkey_list, lambda: self.emitter.show_list_memo.emit())
            keyboard.add_hotkey(hotkey_launcher, lambda: self.emitter.show_quick_launcher.emit())
            print(f"단축키 '{hotkey_new}', '{hotkey_list}', '{hotkey_launcher}'가 성공적으로 등록되었습니다.")
        except Exception as e: print(f"단축키 등록 실패: {e}")

    def setup_tray_icon(self):
        try: image = Image.open(resource_path("icon.gif"))
        except: image = Image.new('RGB', (64, 64), color='blue')
        menu = pystray_menu(pystray_menu_item('새 메모 작성', lambda: self.emitter.show_new_memo.emit(), default=True), pystray_menu_item('메모 목록 보기', lambda: self.emitter.show_list_memo.emit()), pystray_menu_item('빠른 실행', lambda: self.emitter.show_quick_launcher.emit()), pystray_menu_item('설정', lambda: self.emitter.show_settings.emit()), pystray_menu_item('종료', self.exit_app))
        self.icon = pystray_icon("AkashicMemo", image, "Akashic Memo", menu)
        threading.Thread(target=self.icon.run, daemon=True).start()

    def exit_app(self):
        keyboard.unhook_all();
        if self.icon: self.icon.stop()
        self.app.quit()

    def toggle_quick_launcher(self):
        if self.quick_launcher.isVisible(): self.quick_launcher.hide()
        else:
            screen_geometry = QApplication.primaryScreen().geometry(); x = (screen_geometry.width() - self.quick_launcher.width()) // 2; y = (screen_geometry.height() - self.quick_launcher.height()) // 4
            self.quick_launcher.move(x, y); self.quick_launcher.show(); self.quick_launcher.activateWindow(); self.quick_launcher.search_box.setFocus(); self.quick_launcher.search_box.selectAll(); self.search_for_launcher("")

    def search_for_launcher(self, query):
        if query: filtered = [row for row in self.local_cache if query.lower() in row[0].lower()]; self.quick_launcher.update_results(filtered[:10])
        else: self.quick_launcher.update_results(self.local_cache[:10])

    def show_new_memo_window(self): self.memo_editor.clear_fields(); self.memo_editor.show(); self.memo_editor.activateWindow()

    def show_memo_list_window(self):
        self.memo_list.show(); self.memo_list.activateWindow(); self.memo_list.raise_()
        is_full_text = self.memo_list.full_text_search_check.isChecked()
        self.memo_list.search_bar.setPlaceholderText("본문 내용으로 검색..." if is_full_text else "제목으로 실시간 필터링..."); self.load_cache_and_sync()

    def load_cache_and_sync(self):
        try:
            if os.path.exists(config_manager.CACHE_FILE):
                with open(config_manager.CACHE_FILE, 'r', encoding='utf-8') as f: self.local_cache = json.load(f)
                self.emitter.list_data_loaded.emit(self.local_cache, True)
        except: self.local_cache = []
        self.emitter.status_update.emit("최신 정보 동기화 중...", 2000)
        threading.Thread(target=self.sync_cache_from_google, daemon=True).start()

    def sync_cache_from_google(self):
        new_data = google_api_handler.load_memo_list()
        if new_data is not None and new_data != self.local_cache:
            self.local_cache = new_data
            try:
                with open(config_manager.CACHE_FILE, 'w', encoding='utf-8') as f: json.dump(self.local_cache, f, ensure_ascii=False, indent=4)
            except IOError: pass
            if not self.memo_list.full_text_search_check.isChecked(): self.emitter.list_data_loaded.emit(self.local_cache, True)
            self.emitter.status_update.emit("동기화 완료. 최신 목록입니다.", 5000)

    def on_search_text_changed(self):
        if self.memo_list.full_text_search_check.isChecked(): self.search_timer.start(600)
        else: self.filter_local_cache()
    
    def search_mode_changed(self): self.show_memo_list_window()

    def filter_local_cache(self):
        query = self.memo_list.search_bar.text().lower(); filtered_data = [row for row in self.local_cache if query in row[0].lower()]; self.emitter.list_data_loaded.emit(filtered_data, True)

    def perform_search(self, page_token=None, is_prev=False):
        query = self.memo_list.search_bar.text(); self.emitter.status_update.emit(f"'{query}' 검색 중...", 0)
        if not page_token: self.prev_page_tokens.clear()
        if not is_prev and self.current_page_token: self.prev_page_tokens.append(self.current_page_token)
        self.current_page_token = page_token; threading.Thread(target=self.fetch_data_api, args=(query, page_token), daemon=True).start()

    def fetch_data_api(self, query, page_token):
        data, next_token = google_api_handler.search_memos_by_content(query, page_token); self.next_page_token = next_token
        self.emitter.list_data_loaded.emit(data if data else [], False)
        prev_enabled = len(self.prev_page_tokens) > 0; page_num = len(self.prev_page_tokens) + 1
        self.memo_list.update_paging_buttons(prev_enabled, self.next_page_token is not None, page_num)
        
    def go_to_prev_page(self):
        if self.prev_page_tokens: self.next_page_token = self.current_page_token; prev_token = self.prev_page_tokens.pop(); self.perform_search(page_token=prev_token, is_prev=True)

    def go_to_next_page(self): self.perform_search(page_token=self.next_page_token)

    def save_memo(self):
        editor = self.memo_editor; title = editor.title_input.text(); content = editor.editor.toPlainText(); doc_id = editor.current_doc_id
        if not (title and content): return
        if doc_id: threading.Thread(target=self.update_memo_thread, args=(doc_id, title, content)).start()
        else: threading.Thread(target=self.save_memo_thread, args=(title, content)).start()
        editor.close()

    def save_memo_thread(self, title, content):
        self.emitter.status_update.emit(f"'{title}' 저장 중...", 0)
        success = google_api_handler.save_memo(title, content)
        if success: self.emitter.notification.emit("저장 완료", f"'{title}' 메모가 저장되었습니다."); self.sync_cache_from_google()
        else: self.emitter.status_update.emit("저장 실패", 5000)

    def update_memo_thread(self, doc_id, title, content):
        self.emitter.status_update.emit(f"'{title}' 업데이트 중...", 0)
        success = google_api_handler.update_memo(doc_id, title, content)
        if success: self.emitter.status_update.emit("업데이트 완료", 5000); self.sync_cache_from_google()
        else: self.emitter.status_update.emit("업데이트 실패", 5000)

    def view_memo_from_item(self, item):
        doc_id = item.data(Qt.UserRole)
        self.view_memo_by_id(doc_id)

    def view_memo_by_id(self, doc_id):
        threading.Thread(target=self.load_and_show_rich_content, args=(doc_id,)).start()
    
    def load_and_show_rich_content(self, doc_id):
        self.emitter.status_update.emit("내용 불러오는 중...", 0)
        title, html = google_api_handler.load_doc_content(doc_id)
        self.emitter.show_rich_view.emit(title, html)

    def edit_memo(self, doc_id):
        threading.Thread(target=self.load_for_edit_thread, args=(doc_id,)).start()
        
    def load_for_edit_thread(self, doc_id):
        self.emitter.status_update.emit("편집할 내용 불러오는 중...", 0)
        title, markdown_content = google_api_handler.load_doc_content(doc_id, as_html=False)
        self.emitter.show_edit_memo.emit(doc_id, title, markdown_content)
        
    def delete_memo(self, doc_id):
        reply = QMessageBox.question(self.memo_list, '삭제 확인', f"메모를 정말로 삭제하시겠습니까?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes: threading.Thread(target=self.delete_memo_thread, args=(doc_id,)).start()
    
    def delete_memo_thread(self, doc_id):
        self.emitter.status_update.emit("삭제 중...", 0)
        success = google_api_handler.delete_memo(doc_id)
        if success: self.emitter.status_update.emit("삭제 완료", 5000); self.sync_cache_from_google()
        else: self.emitter.status_update.emit("삭제 실패", 5000)

    def show_context_menu(self, pos):
        item = self.memo_list.table.itemAt(pos)
        if not item: return
        doc_id = item.data(Qt.UserRole); menu = QMenu()
        edit_action = menu.addAction("편집하기"); delete_action = menu.addAction("삭제하기")
        action = menu.exec_(self.memo_list.table.mapToGlobal(pos))
        if action == edit_action: self.edit_memo(doc_id)
        elif action == delete_action: self.delete_memo(doc_id)

    def show_settings_window(self):
        self.settings.load_current_settings(); self.settings.show(); self.settings.activateWindow()

    def save_settings(self):
        s = self.settings
        config_manager.save_settings(s.hotkey_new_edit.text(), s.hotkey_list_edit.text(), s.hotkey_launcher_edit.text(), s.sheet_id_edit.text(), s.folder_id_edit.text(), s.page_size_edit.text())
        QMessageBox.information(s, "저장 완료", "설정이 저장되었습니다.\n프로그램을 다시 시작해야 적용됩니다.")

    def show_notification(self, title, message):
        if self.icon and self.icon.visible: self.icon.notify(message, title)
    
    def update_editor_preview(self):
        markdown_text = self.memo_editor.editor.toPlainText()
        html = markdown.markdown(markdown_text, extensions=['fenced_code', 'codehilite', 'tables', 'nl2br'])
        self.memo_editor.viewer.setHtml(html)
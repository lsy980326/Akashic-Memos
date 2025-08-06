import sys
import threading
import json
import os
import markdown
import re
import webbrowser
from PyQt5.QtWidgets import QApplication, QMessageBox, QMenu, QDesktopWidget
from PyQt5.QtCore import QObject, pyqtSignal, QTimer, Qt, QUrl
from PyQt5.QtGui import QDesktopServices, QFont
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEnginePage
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
    show_edit_memo = pyqtSignal(str, str, str, str)
    show_rich_view = pyqtSignal(str, str)
    list_data_loaded = pyqtSignal(list, bool)
    nav_tree_updated = pyqtSignal(set)
    status_update = pyqtSignal(str, int)
    notification = pyqtSignal(str, str)

class AppController:
    def __init__(self, app):
        self.app = app
        self.emitter = SignalEmitter()
        self.memo_editor = MarkdownEditorWindow()
        self.memo_list = MemoListWindow()
        self.settings = SettingsWindow()
        self.rich_viewer = RichMemoViewWindow()
        self.quick_launcher = QuickLauncherWindow()
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
        self.connect_signals_and_slots()
        self.load_cache_only(initial_load=True)
        self.setup_hotkeys()
        self.setup_tray_icon()
        QTimer.singleShot(2000, self.start_initial_sync)

    def connect_signals_and_slots(self):
        self.emitter.show_new_memo.connect(self.show_new_memo_window, Qt.QueuedConnection)
        self.emitter.show_list_memo.connect(self.show_memo_list_window, Qt.QueuedConnection)
        self.emitter.show_settings.connect(self.show_settings_window, Qt.QueuedConnection)
        self.emitter.show_quick_launcher.connect(self.toggle_quick_launcher, Qt.QueuedConnection)
        self.emitter.list_data_loaded.connect(self.memo_list.populate_table, Qt.QueuedConnection)
        self.emitter.nav_tree_updated.connect(self.memo_list.update_nav_tree, Qt.QueuedConnection)
        self.emitter.show_edit_memo.connect(self.memo_editor.open_document, Qt.QueuedConnection)
        self.emitter.show_rich_view.connect(self.rich_viewer.set_content, Qt.QueuedConnection)
        self.emitter.status_update.connect(self.memo_list.statusBar.showMessage, Qt.QueuedConnection)
        self.emitter.notification.connect(self.show_notification, Qt.QueuedConnection)
        
        self.search_timer.timeout.connect(self.perform_search)
        self.memo_list.search_bar.textChanged.connect(self.on_search_text_changed)
        self.memo_list.full_text_search_check.stateChanged.connect(self.search_mode_changed)
        self.memo_list.table.itemDoubleClicked.connect(self.view_memo_from_item)
        self.memo_list.table.customContextMenuRequested.connect(self.show_context_menu)
        self.memo_list.prev_button.clicked.connect(self.go_to_prev_page)
        self.memo_list.next_button.clicked.connect(self.go_to_next_page)
        self.memo_list.refresh_button.clicked.connect(self.start_initial_sync)
        self.memo_list.navigation_selected.connect(self.on_navigation_selected)
        
        self.memo_editor.save_button.clicked.connect(self.save_memo)
        self.memo_editor.preview_timer.timeout.connect(self.update_editor_preview)
        self.memo_editor.editor.textChanged.connect(lambda: self.memo_editor.preview_timer.start(500))
        
        self.settings.save_button.clicked.connect(self.save_settings)
        self.settings.startup_checkbox.stateChanged.connect(config_manager.set_startup)

        self.quick_launcher.search_box.textChanged.connect(self.search_for_launcher)
        self.quick_launcher.memo_selected.connect(self.on_launcher_item_selected)
        self.rich_viewer.link_activated.connect(self.on_link_activated)

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

    def setup_tray_icon(self):
        try:
            image = Image.open(resource_path("icon.gif"))
        except:
            image = Image.new('RGB', (64, 64), color='blue')
        menu = pystray_menu(
            pystray_menu_item('새 메모 작성', lambda: self.emitter.show_new_memo.emit(), default=True),
            pystray_menu_item('메모 목록 보기', lambda: self.emitter.show_list_memo.emit()),
            pystray_menu_item('빠른 실행', lambda: self.emitter.show_quick_launcher.emit()),
            pystray_menu_item('설정', lambda: self.emitter.show_settings.emit()),
            pystray_menu_item('종료', self.exit_app)
        )
        self.icon = pystray_icon("AkashicMemo", image, "Akashic Memo", menu)
        threading.Thread(target=self.icon.run, daemon=True).start()

    def exit_app(self):
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

    def start_initial_sync(self):
        self.emitter.status_update.emit("최신 정보 동기화 중...", 2000)
        threading.Thread(target=self.sync_cache_thread, daemon=True).start()

    def sync_cache_thread(self):
        new_data = google_api_handler.load_memo_list()
        if new_data is not None and new_data != self.local_cache:
            self.local_cache = new_data
            self.update_tags_from_cache()
            try:
                with open(config_manager.CACHE_FILE, 'w', encoding='utf-8') as f:
                    json.dump(self.local_cache, f, ensure_ascii=False, indent=4)
            except IOError:
                pass
            
            self.emitter.nav_tree_updated.emit(self.all_tags)
            if self.memo_list.isVisible() and not self.memo_list.full_text_search_check.isChecked():
                current_nav_item = self.memo_list.nav_tree.currentItem()
                if current_nav_item:
                    self.on_navigation_selected(current_nav_item.text(0))
            self.emitter.status_update.emit("동기화 완료.", 5000)

    def load_cache_only(self, initial_load=False):
        try:
            if os.path.exists(config_manager.CACHE_FILE):
                with open(config_manager.CACHE_FILE, 'r', encoding='utf-8') as f:
                    self.local_cache = json.load(f)
                self.update_tags_from_cache()
                if initial_load:
                    self.emitter.list_data_loaded.emit(self.local_cache, True)
                    self.emitter.nav_tree_updated.emit(self.all_tags)
        except Exception as e:
            print(f"캐시 로딩 실패: {e}")
            self.local_cache = []
            
    def update_tags_from_cache(self):
        self.all_tags.clear()
        for row in self.local_cache:
            if len(row) > 3 and row[3]:
                tags = [t.strip().lstrip('#') for t in row[3].replace(',', ' ').split() if t.strip().startswith('#')]
                self.all_tags.update(tags)

    def on_navigation_selected(self, selected_item_text):
        if selected_item_text in ["태그", ""]:
            return
        self.memo_list.search_bar.clear()
        self.memo_list.full_text_search_check.setChecked(False)
        if selected_item_text == "전체 메모":
            self.emitter.list_data_loaded.emit(self.local_cache, True)
        else:
            filtered_data = [row for row in self.local_cache if len(row) > 3 and selected_item_text in row[3]]
            self.emitter.list_data_loaded.emit(filtered_data, True)

    def show_new_memo_window(self):
        self.memo_editor.clear_fields()
        self.memo_editor.show()
        self.memo_editor.activateWindow()

    def show_memo_list_window(self):
        self.memo_list.show()
        self.memo_list.activateWindow()
        self.memo_list.raise_()
        is_full_text = self.memo_list.full_text_search_check.isChecked()
        self.memo_list.search_bar.setPlaceholderText("본문 내용으로 검색..." if is_full_text else "제목으로 실시간 필터링...")
        
        current_nav = self.memo_list.nav_tree.currentItem()
        if current_nav:
            self.on_navigation_selected(current_nav.text(0))
        else:
            self.on_navigation_selected("전체 메모")

        self.memo_list.update_nav_tree(self.all_tags)

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
        filtered_data = [row for row in self.local_cache if query in row[0].lower()]
        self.emitter.list_data_loaded.emit(filtered_data, True)

    def perform_search(self, page_token=None, is_prev=False, is_next=False):
        query = self.memo_list.search_bar.text()
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
        
    def go_to_prev_page(self):
        if self.prev_page_tokens:
            prev_token = self.prev_page_tokens.pop()
            self.perform_search(page_token=prev_token, is_prev=True)

    def go_to_next_page(self):
        if self.next_page_token:
            self.perform_search(page_token=self.next_page_token, is_next=True)

    def save_memo(self):
        editor = self.memo_editor
        title = editor.title_input.text()
        content = editor.editor.toPlainText()
        tags = editor.tag_input.text()
        doc_id = editor.current_doc_id
        if not (title and content):
            return
        if doc_id:
            threading.Thread(target=self.update_memo_thread, args=(doc_id, title, content, tags)).start()
        else:
            threading.Thread(target=self.save_memo_thread, args=(title, content, tags)).start()
        editor.close()

    def save_memo_thread(self, title, content, tags):
        self.emitter.status_update.emit(f"'{title}' 저장 중...", 0)
        success = google_api_handler.save_memo(title, content, tags)
        if success:
            self.emitter.notification.emit("저장 완료", f"'{title}' 메모가 저장되었습니다.")
            self.start_initial_sync()
        else:
            self.emitter.status_update.emit("저장 실패", 5000)

    def update_memo_thread(self, doc_id, title, content, tags):
        self.emitter.status_update.emit(f"'{title}' 업데이트 중...", 0)
        success = google_api_handler.update_memo(doc_id, title, content, tags)
        if success:
            cache_path = os.path.join(config_manager.CONTENT_CACHE_DIR, f"{doc_id}.txt")
            with open(cache_path, 'w', encoding='utf-8') as f:
                f.write(f"{title}\n{content}\n{tags}")
            self.emitter.status_update.emit("업데이트 완료", 5000)
            self.start_initial_sync()
        else:
            self.emitter.status_update.emit("업데이트 실패", 5000)

    def view_memo_from_item(self, item):
        doc_id = item.data(Qt.UserRole)
        self.view_memo_by_id(doc_id)

    def view_memo_by_id(self, doc_id):
        if self.rich_viewer.isVisible() and self.current_viewing_doc_id == doc_id:
            self.rich_viewer.activateWindow()
            return
        self.current_viewing_doc_id = doc_id
        cache_path = os.path.join(config_manager.CONTENT_CACHE_DIR, f"{doc_id}.html")
        if os.path.exists(cache_path):
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    cached_html_full = f.read()
                title = cached_html_full.split('<title>')[1].split('</title>')[0]
                self.emitter.show_rich_view.emit(title, cached_html_full)
            except:
                self.emitter.show_rich_view.emit("오류", "캐시 파일을 읽을 수 없습니다.")
        else:
            self.emitter.show_rich_view.emit("불러오는 중...", "<body><p>콘텐츠를 불러오는 중입니다...</p></body>")
        threading.Thread(target=self.sync_rich_content_thread, args=(doc_id,)).start()

    def sync_rich_content_thread(self, doc_id):
        title, html_body, _ = google_api_handler.load_doc_content(doc_id, as_html=True)
        if "내용을 불러올 수 없습니다" in html_body:
            return
        new_html_full = self._get_final_html(title, html_body)
        current_html_full = ""
        cache_path = os.path.join(config_manager.CONTENT_CACHE_DIR, f"{doc_id}.html")
        if os.path.exists(cache_path):
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    current_html_full = f.read()
            except: pass
        if new_html_full != current_html_full:
            try:
                with open(cache_path, 'w', encoding='utf-8') as f:
                    f.write(new_html_full)
            except Exception as e:
                print(f"콘텐츠 캐시 저장 오류: {e}")
            if self.rich_viewer.isVisible() and self.current_viewing_doc_id == doc_id:
                self.emitter.show_rich_view.emit(title, new_html_full)

    def edit_memo(self, doc_id):
        self.current_editing_doc_id = doc_id
        self.emitter.status_update.emit("편집할 내용 불러오는 중...", 0)
        threading.Thread(target=self.load_for_edit_thread, args=(doc_id,)).start()
        
    def load_for_edit_thread(self, doc_id):
        title, markdown_content, tags_text = google_api_handler.load_doc_content(doc_id, as_html=False)
        self.emitter.show_edit_memo.emit(doc_id, title, markdown_content, tags_text)
        
    def delete_memo(self, doc_id):
        reply = QMessageBox.question(self.memo_list, '삭제 확인', "메모를 정말로 삭제하시겠습니까?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            threading.Thread(target=self.delete_memo_thread, args=(doc_id,)).start()
    
    def delete_memo_thread(self, doc_id):
        self.emitter.status_update.emit("삭제 중...", 0)
        success = google_api_handler.delete_memo(doc_id)
        if success:
            self.local_cache = [row for row in self.local_cache if len(row) > 2 and row[2] != doc_id]
            self.emitter.status_update.emit("삭제 완료", 5000)
            self.start_initial_sync()
        else:
            self.emitter.status_update.emit("삭제 실패", 5000)

    def show_context_menu(self, pos):
        item = self.memo_list.table.itemAt(pos)
        if not item: return
        doc_id = item.data(Qt.UserRole)
        menu = QMenu()
        edit_action = menu.addAction("편집하기")
        delete_action = menu.addAction("삭제하기")
        action = menu.exec_(self.memo_list.table.mapToGlobal(pos))
        if action == edit_action:
            self.edit_memo(doc_id)
        elif action == delete_action:
            self.delete_memo(doc_id)

    def show_settings_window(self):
        self.settings.load_current_settings()
        self.settings.show()
        self.settings.activateWindow()

    def save_settings(self):
        s = self.settings
        config_manager.save_settings(s.hotkey_new_edit.text(), s.hotkey_list_edit.text(), s.hotkey_launcher_edit.text(), s.sheet_id_edit.text(), s.folder_id_edit.text(), s.page_size_edit.text(), s.css_path_edit.text())
        QMessageBox.information(s, "저장 완료", "설정이 저장되었습니다.\n프로그램을 다시 시작해야 적용됩니다.")

    def show_notification(self, title, message):
        if self.icon and self.icon.visible:
            self.icon.notify(message, title)
    
    def update_editor_preview(self):
        markdown_text = self.memo_editor.editor.toPlainText()
        html_body = markdown.markdown(markdown_text, extensions=['fenced_code', 'codehilite', 'tables', 'nl2br'])
        final_html_with_css = self._get_final_html("미리보기", html_body)
        self.memo_editor.viewer.setHtml(final_html_with_css, QUrl("file:///"))

    def on_launcher_item_selected(self, selected_data):
        if self.launcher_mode == 'tags':
            tag_name = selected_data
            self.show_memos_for_tag_in_launcher(tag_name)
        else:
            doc_id = selected_data
            self.view_memo_by_id(doc_id)
            self.quick_launcher.hide()

    def show_memos_for_tag_in_launcher(self, tag_name):
        self.launcher_mode = 'memos'
        self.quick_launcher.search_box.setPlaceholderText("메모 검색...")
        self.quick_launcher.search_box.clear()
        filtered_memos = [
            row[:3] for row in self.local_cache
            if len(row) > 3 and tag_name in [t.strip().lstrip('#') for t in row[3].replace(',', ' ').split()]
        ]
        self.quick_launcher.update_results(filtered_memos)
    
    def _get_final_html(self, title, html_body):
        title_to_id_map = {row[0]: row[2] for row in self.local_cache if len(row) > 2}
        def replace_wiki_links(match):
            linked_title = match.group(1)
            if linked_title in title_to_id_map:
                return f'<a href="memo://{title_to_id_map[linked_title]}">{linked_title}</a>'
            return f'<span style="color: #dc3545;">[[{linked_title}]]</span>'
        parsed_body = re.sub(r'[[(.*?)]]', replace_wiki_links, html_body)
        
        DEFAULT_CSS = """
        <style>
            body { font-family: "Segoe UI", "Malgun Gothic", sans-serif; line-height: 1.7; padding: 35px; background-color: #ffffff; color: #333333; }
            h1, h2, h3, h4, h5, h6 { font-weight: 600; color: #111111; margin-top: 1.5em; margin-bottom: 0.5em; line-height: 1.25; }
            h1 { font-size: 2em; border-bottom: 1px solid #eaecef; padding-bottom: 0.3em; }
            h2 { font-size: 1.5em; border-bottom: 1px solid #eaecef; padding-bottom: 0.3em; }
            p { margin: 0 0 16px 0; }
            a { color: #0366d6; text-decoration: none; } a:hover { text-decoration: underline; }
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
        </style>
        """
        final_css = DEFAULT_CSS
        custom_css_path = config_manager.get_setting('Display', 'custom_css_path')
        if custom_css_path and os.path.exists(custom_css_path):
            try:
                with open(custom_css_path, 'r', encoding='utf-8') as f:
                    final_css = f"<style>{f.read()}</style>"
            except: pass
        return f'<html><head><meta charset="UTF-8"><title>{title}</title>{final_css}</head><body>{parsed_body}</body></html>'
    
    def on_link_activated(self, url):
        url_string = url.toString()
        if url_string.startswith('memo://'):
            self.view_memo_by_id(url_string.replace('memo://', ''))
        else:
            QDesktopServices.openUrl(url)
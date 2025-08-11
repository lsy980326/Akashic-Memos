from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QUrl, QSize
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEnginePage
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QLineEdit, QHBoxLayout,
                             QTextEdit, QPushButton, QTableWidget, QTableWidgetItem,
                             QHeaderView, QMessageBox, QMenu, QStatusBar, QLabel,
                             QFormLayout, QCheckBox, QSplitter, QListWidget,
                             QListWidgetItem, QTreeWidget, QTreeWidgetItem, QFrame,
                             QFileDialog, QToolBar, QAction, QSizePolicy)
from PyQt5.QtGui import QDesktopServices, QFont, QTextCursor
from core import config_manager
import qtawesome as qta
import os

class LinkHandlingPage(QWebEnginePage):
    linkClicked = pyqtSignal(QUrl)

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        if nav_type == QWebEnginePage.NavigationTypeLinkClicked:
            self.linkClicked.emit(url)
            return False
        return True

class PreviewWebPage(QWebEnginePage):
    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        if nav_type == QWebEnginePage.NavigationTypeLinkClicked:
            QDesktopServices.openUrl(url)
            return False
        return True

class QuickLauncherWindow(QWidget):
    memo_selected = pyqtSignal(str)
    def __init__(self):
        super().__init__(); self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool); self.initUI()
    def initUI(self):
        self.setFixedSize(600, 300); layout = QVBoxLayout(); layout.setContentsMargins(5, 5, 5, 5)
        self.search_box = QLineEdit(); self.search_box.setPlaceholderText("메모 검색...")
        self.search_box.setStyleSheet("padding: 8px; font-size: 12pt;")
        self.results_list = QListWidget(); self.results_list.setStyleSheet("font-size: 11pt;")
        self.results_list.itemActivated.connect(self.item_activated)
        layout.addWidget(self.search_box); layout.addWidget(self.results_list); self.setLayout(layout)
    def update_results(self, results):
        self.results_list.clear()
        for title, date, doc_id in results:
            item = QListWidgetItem(f"{title} ({date})"); item.setData(Qt.UserRole, doc_id); self.results_list.addItem(item)
        if self.results_list.count() > 0: self.results_list.setCurrentRow(0)
    def item_activated(self, item): self.memo_selected.emit(item.data(Qt.UserRole))
    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape: self.hide()
        elif event.key() == Qt.Key_Down: self.results_list.setCurrentRow(min(self.results_list.currentRow() + 1, self.results_list.count() - 1))
        elif event.key() == Qt.Key_Up: self.results_list.setCurrentRow(max(self.results_list.currentRow() - 1, 0))
        else: super().keyPressEvent(event)

class SearchWidget(QWidget):
    search_edited = pyqtSignal(str)
    find_next = pyqtSignal()
    find_prev = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.initUI()

    def initUI(self):
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.find_box = QLineEdit()
        self.find_box.setPlaceholderText("내용에서 검색")
        self.find_box.setFixedWidth(180)
        self.find_box.textChanged.connect(self.search_edited.emit)
        self.find_box.returnPressed.connect(self.find_next.emit)
        layout.addWidget(self.find_box)

        icon_color = '#495057'
        find_prev_button = QPushButton(qta.icon('fa5s.chevron-up', color=icon_color), "")
        find_prev_button.clicked.connect(self.find_prev.emit)
        layout.addWidget(find_prev_button)

        find_next_button = QPushButton(qta.icon('fa5s.chevron-down', color=icon_color), "")
        find_next_button.clicked.connect(self.find_next.emit)
        layout.addWidget(find_next_button)

        self.setLayout(layout)

    def focus_search_box(self):
        self.find_box.setFocus()

    def clear_search_box(self):
        self.find_box.clear()

    def get_search_text(self):
        return self.find_box.text()

class CustomWebEngineView(QWebEngineView):
    tags_edit_requested = pyqtSignal(str)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        
        edit_tags_action = menu.addAction("태그 편집")
        action = menu.exec_(self.mapToGlobal(event.pos()))
        
        if action == edit_tags_action:
            # 메뉴를 통해 직접 태그 편집을 요청할 수도 있으므로, 선택된 텍스트가 없는 경우를 대비합니다.
            self.page().runJavaScript("window.getSelection().toString();", self.handle_selection_callback)

    def handle_selection_callback(self, selected_text):
        # 선택된 텍스트가 있는 경우, 해당 텍스트를 태그로 간주하고 시그널을 보냅니다.
        if selected_text:
            self.tags_edit_requested.emit(selected_text)
        else:
            # 선택된 텍스트가 없으면, 빈 문자열을 보내 일반적인 태그 편집을 유도합니다.
            self.tags_edit_requested.emit("")

class RichMemoViewWindow(QWidget):
    link_activated = pyqtSignal(QUrl)
    tags_edit_requested = pyqtSignal(str)
    edit_requested = pyqtSignal()
    open_in_gdocs_requested = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.current_zoom_factor = 1.0
        self.initUI()

    def initUI(self):
        self.setWindowTitle('메모 보기')
        self.setGeometry(250, 250, 700, 800)
        self.setStyleSheet("background-color: #ffffff;")
        
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.content_display = CustomWebEngineView()
        self.page = LinkHandlingPage(self)
        self.content_display.setPage(self.page)
        self.page.linkClicked.connect(self.link_activated)
        self.content_display.tags_edit_requested.connect(self.tags_edit_requested.emit)

        toolbar = QToolBar("Main Toolbar")
        toolbar.setObjectName("RichViewToolbar")
        toolbar.setIconSize(QSize(22, 22))

        icon_color = '#495057'
        self.edit_action = QAction(qta.icon('fa5s.pencil-alt', color=icon_color), "편집", self)
        self.edit_action.setToolTip("이 메모를 편집합니다.")
        self.edit_action.triggered.connect(self.edit_requested.emit)
        toolbar.addAction(self.edit_action)

        self.gdocs_action = QAction(qta.icon('fa5b.google-drive', color=icon_color), "Google Docs에서 열기", self)
        self.gdocs_action.setToolTip("웹 브라우저에서 Google Docs로 엽니다.")
        self.gdocs_action.triggered.connect(self.open_in_gdocs_requested.emit)
        toolbar.addAction(self.gdocs_action)
        
        toolbar.addSeparator()

        find_button = QPushButton(qta.icon('fa5s.search', color=icon_color), "")
        find_button.setToolTip("내용에서 텍스트를 검색합니다.")
        find_button.setCheckable(True)
        find_button.toggled.connect(self.toggle_find_box)
        toolbar.addWidget(find_button)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        toolbar.addWidget(spacer)

        zoom_out_action = QAction(qta.icon('fa5s.search-minus', color=icon_color), "축소", self)
        zoom_out_action.setToolTip("본문 축소")
        zoom_out_action.triggered.connect(self.zoom_out)
        toolbar.addAction(zoom_out_action)

        self.zoom_label = QLabel(f"{int(self.current_zoom_factor * 100)}%")
        self.zoom_label.setStyleSheet("padding: 0 8px; color: #333;")
        toolbar.addWidget(self.zoom_label)

        zoom_in_action = QAction(qta.icon('fa5s.search-plus', color=icon_color), "확대", self)
        zoom_in_action.setToolTip("본문 확대")
        zoom_in_action.triggered.connect(self.zoom_in)
        toolbar.addAction(zoom_in_action)

        toolbar_area = QFrame()
        toolbar_area.setObjectName("ToolbarArea")
        toolbar_area.setAutoFillBackground(True)
        toolbar_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        toolbar_layout = QVBoxLayout()
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_layout.setSpacing(0)
        
        toolbar_layout.addWidget(toolbar)

        self.search_widget = SearchWidget(self)
        self.search_widget.setObjectName("SearchWidget")
        self.search_widget.setVisible(False)
        
        self.search_widget.search_edited.connect(self.find_text)
        self.search_widget.find_next.connect(self.find_next)
        self.search_widget.find_prev.connect(self.find_prev)
        toolbar_layout.addWidget(self.search_widget)
        
        toolbar_area.setLayout(toolbar_layout)
        layout.addWidget(toolbar_area)

        layout.addWidget(self.content_display)
        self.setLayout(layout)

    def set_content(self, title, html_content):
        self.setWindowTitle(title)
        base_url = QUrl.fromLocalFile(os.path.abspath(os.getcwd()).replace('\\', '/') + '/')
        self.content_display.setHtml(html_content, base_url)
        self.content_display.setZoomFactor(self.current_zoom_factor)
        self.show()
        self.activateWindow()
        self.raise_()

    def zoom_in(self):
        self.current_zoom_factor = min(2.0, self.current_zoom_factor + 0.1)
        self.content_display.setZoomFactor(self.current_zoom_factor)
        self.zoom_label.setText(f"{int(self.current_zoom_factor * 100)}%")

    def zoom_out(self):
        self.current_zoom_factor = max(0.5, self.current_zoom_factor - 0.1)
        self.content_display.setZoomFactor(self.current_zoom_factor)
        self.zoom_label.setText(f"{int(self.current_zoom_factor * 100)}%")

    def toggle_find_box(self, checked):
        self.search_widget.setVisible(checked)
        if checked:
            self.search_widget.focus_search_box()
        else:
            self.search_widget.clear_search_box()

    def find_text(self, text):
        if text:
            self.content_display.findText(text)
        else:
            self.content_display.findText("")

    def find_next(self):
        text = self.search_widget.get_search_text()
        if text:
            self.content_display.findText(text)

    def find_prev(self):
        text = self.search_widget.get_search_text()
        if text:
            self.content_display.findText(text, QWebEnginePage.FindBackward)


    def closeEvent(self, event):
        self.hide()

class MarkdownEditorWindow(QWidget):
    def __init__(self):
        super().__init__(); self.current_doc_id = None; self.initUI(); self.preview_timer = QTimer(self); self.preview_timer.setSingleShot(True)
    def initUI(self):
        self.setWindowTitle('새 메모 작성'); self.setGeometry(150, 150, 1200, 800)
        main_layout = QVBoxLayout(); main_layout.setContentsMargins(10, 10, 10, 10); main_layout.setSpacing(10)
        top_layout = QHBoxLayout()
        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText('제목')
        
        self.add_image_button = QPushButton(' 이미지 추가')
        self.add_image_button.setIcon(qta.icon('fa5s.image', color='white'))
        self.add_image_button.clicked.connect(self.add_image)

        self.add_file_button = QPushButton(' 파일 추가')
        self.add_file_button.setIcon(qta.icon('fa5s.paperclip', color='white'))
        self.add_file_button.clicked.connect(self.add_file)

        self.save_button = QPushButton(' 저장')
        self.save_button.setIcon(qta.icon('fa5s.save', color='white'))
        
        top_layout.addWidget(self.title_input)
        top_layout.addWidget(self.add_image_button)
        top_layout.addWidget(self.add_file_button)
        top_layout.addWidget(self.save_button)
        main_layout.addLayout(top_layout)
        splitter = QSplitter(Qt.Horizontal); self.editor = QTextEdit()
        self.viewer = QWebEngineView()
        self.editor.setPlaceholderText("# 마크다운으로 메모를 작성하세요...");
        self.viewer_page = PreviewWebPage(self)
        self.viewer.setPage(self.viewer_page)
        self.editor.setStyleSheet("font-family: Consolas, 'Courier New', monospace;"); splitter.addWidget(self.editor); splitter.addWidget(self.viewer); splitter.setSizes([600, 600])
        main_layout.addWidget(splitter)
        tag_layout = QHBoxLayout(); tag_layout.setContentsMargins(0, 5, 0, 0); tag_label = QLabel("태그:"); self.tag_input = QLineEdit(); self.tag_input.setPlaceholderText("#태그1, #태그2, ...")
        tag_layout.addWidget(tag_label); tag_layout.addWidget(self.tag_input); main_layout.addLayout(tag_layout)
        self.setLayout(main_layout)
    def open_document(self, doc_id, title, markdown_content, tags_text):
        self.current_doc_id = doc_id; self.setWindowTitle(f'메모 편집: {title}'); self.title_input.setText(title); self.editor.setPlainText(markdown_content); self.tag_input.setText(tags_text); self.show(); self.activateWindow()
    def clear_fields(self):
        self.current_doc_id = None; self.setWindowTitle('새 메모 작성'); self.title_input.clear(); self.editor.clear(); self.viewer.setHtml(""); self.tag_input.clear()
    
    def add_image(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "이미지 선택", "", "Image Files (*.png *.jpg *.bmp *.gif)")
        if file_name:
            import os
            import shutil
            from core.utils import resource_path

            image_dir = resource_path("resources/images")
            if not os.path.exists(image_dir):
                os.makedirs(image_dir)
            
            new_file_path = os.path.join(image_dir, os.path.basename(file_name))
            shutil.copy(file_name, new_file_path)
            
            # 마크다운 이미지 태그로 변환하여 에디터에 삽입
            markdown_image_tag = f"![image](resources/images/{os.path.basename(file_name)})"
            self.editor.insertPlainText(markdown_image_tag)

    def add_file(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "파일 선택", "", "All Files (*)")
        if file_name:
            import os
            import shutil
            from core.utils import resource_path

            file_dir = resource_path("resources/files")
            if not os.path.exists(file_dir):
                os.makedirs(file_dir)
            
            new_file_path = os.path.join(file_dir, os.path.basename(file_name))
            shutil.copy(file_name, new_file_path)
            
            # 마크다운 링크로 변환하여 에디터에 삽입
            markdown_link = f"[{os.path.basename(file_name)}](resources/files/{os.path.basename(file_name)})"
            self.editor.insertPlainText(markdown_link)

    def closeEvent(self, event): self.clear_fields(); self.hide(); event.ignore()

class MemoListWindow(QWidget):
    navigation_selected = pyqtSignal(str); context_menu_requested = pyqtSignal(object)
    def __init__(self):
        super().__init__(); self.initUI()
    def initUI(self):
        self.setWindowTitle('메모 목록'); self.setGeometry(200, 200, 800, 500); main_layout = QHBoxLayout(self)
        left_panel = QFrame(); left_layout = QVBoxLayout(left_panel); left_panel.setMaximumWidth(200)
        self.nav_tree = QTreeWidget(); self.nav_tree.setHeaderHidden(True); left_layout.addWidget(self.nav_tree)
        right_panel = QFrame(); right_layout = QVBoxLayout(right_panel)
        search_layout = QHBoxLayout(); self.search_bar = QLineEdit(); self.full_text_search_check = QCheckBox("본문 포함"); self.refresh_button = QPushButton(qta.icon('fa5s.sync-alt', color='#495057'), ""); self.refresh_button.setObjectName("PagingButton");
        search_layout.addWidget(self.search_bar); search_layout.addWidget(self.full_text_search_check); search_layout.addWidget(self.refresh_button)
        right_layout.addLayout(search_layout)
        self.table = QTableWidget(); self.table.setColumnCount(3); self.table.setHorizontalHeaderLabels(['제목', '날짜', '태그']); self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch); self.table.setEditTriggers(QTableWidget.NoEditTriggers); self.table.setSortingEnabled(True);
        right_layout.addWidget(self.table)
        paging_layout = QHBoxLayout(); self.prev_button = QPushButton(qta.icon('fa5s.chevron-left', color='#495057'), ""); self.prev_button.setObjectName("PagingButton"); self.page_label = QLabel("1 페이지"); self.page_label.setAlignment(Qt.AlignCenter); self.next_button = QPushButton(qta.icon('fa5s.chevron-right', color='#495057'), ""); self.next_button.setObjectName("PagingButton"); paging_layout.addWidget(self.prev_button); paging_layout.addWidget(self.page_label); paging_layout.addWidget(self.next_button);
        right_layout.addLayout(paging_layout)
        self.statusBar = QStatusBar(); right_layout.addWidget(self.statusBar)
        splitter = QSplitter(Qt.Horizontal); splitter.addWidget(left_panel); splitter.addWidget(right_panel); splitter.setSizes([180, 620]); main_layout.addWidget(splitter)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu); self.table.customContextMenuRequested.connect(self.context_menu_requested.emit)
        self.nav_tree.currentItemChanged.connect(self.on_nav_selected)
    def on_nav_selected(self, current, previous):
        if current: self.navigation_selected.emit(current.text(0))
    def update_nav_tree(self, all_tags, local_cache):
        self.nav_tree.blockSignals(True)
        self.nav_tree.clear()
        
        # 전체 메모 카운트
        all_memos_count = len(local_cache)
        all_memos_item = QTreeWidgetItem(self.nav_tree)
        all_memos_item.setText(0, f"전체 메모 ({all_memos_count})")
        all_memos_item.setIcon(0, qta.icon('fa5s.inbox'))

        if all_tags:
            tags_root_item = QTreeWidgetItem(self.nav_tree)
            tags_root_item.setText(0, f"태그 ({len(all_tags)})")
            tags_root_item.setIcon(0, qta.icon('fa5s.tags'))
            
            # 각 태그의 문서 수 계산
            tag_counts = {}
            for row in local_cache:
                if len(row) > 3 and row[3]:
                    tags_in_row = [t.strip().lstrip('#') for t in row[3].replace(',', ' ').split() if t.strip().startswith('#')]
                    for tag in tags_in_row:
                        tag_counts[tag] = tag_counts.get(tag, 0) + 1

            for tag in sorted(all_tags):
                count = tag_counts.get(tag, 0)
                tag_item = QTreeWidgetItem(tags_root_item)
                tag_item.setText(0, f"{tag} ({count})")
            tags_root_item.setExpanded(True)
            
        self.nav_tree.setCurrentItem(all_memos_item)
        self.nav_tree.blockSignals(False)

    def populate_table(self, data, is_local):
        is_api_result = not is_local
        self.prev_button.setVisible(is_api_result)
        self.next_button.setVisible(is_api_result)
        self.page_label.setVisible(is_api_result)
        self.table.setSortingEnabled(is_local)
        
        self.table.clearContents()
        self.table.setRowCount(len(data))
        
        for i, row in enumerate(data):
            # 데이터 길이에 따라 안전하게 값 추출
            title = row[0] if len(row) > 0 else ""
            date = row[1] if len(row) > 1 else ""
            doc_id = row[2] if len(row) > 2 else ""
            tags = row[3] if len(row) > 3 else ""

            title_item = QTableWidgetItem(title)
            date_item = QTableWidgetItem(date)
            tags_item = QTableWidgetItem(tags)
            
            # 모든 아이템에 doc_id 저장
            title_item.setData(Qt.UserRole, doc_id)
            date_item.setData(Qt.UserRole, doc_id)
            tags_item.setData(Qt.UserRole, doc_id)

            self.table.setItem(i, 0, title_item)
            self.table.setItem(i, 1, date_item)
            self.table.setItem(i, 2, tags_item)
    def update_paging_buttons(self, prev_enabled, next_enabled, page_num):
        self.prev_button.setEnabled(prev_enabled); self.next_button.setEnabled(next_enabled); self.page_label.setText(f"{page_num} 페이지")
    def closeEvent(self, event): event.ignore(); self.hide()

class SettingsWindow(QWidget):
    def __init__(self):
        super().__init__(); self.initUI(); self.load_current_settings()
    def initUI(self):
        self.setWindowTitle('설정'); self.setGeometry(400, 400, 500, 310); form_layout = QFormLayout(); form_layout.setSpacing(10)
        self.hotkey_new_edit = QLineEdit(); self.hotkey_list_edit = QLineEdit(); self.hotkey_launcher_edit = QLineEdit()
        self.sheet_id_edit = QLineEdit(); self.folder_id_edit = QLineEdit(); self.page_size_edit = QLineEdit()
        form_layout.addRow(QLabel("새 메모 단축키:"), self.hotkey_new_edit); form_layout.addRow(QLabel("목록 보기 단축키:"), self.hotkey_list_edit); form_layout.addRow(QLabel("빠른 실행 단축키:"), self.hotkey_launcher_edit)
        form_layout.addRow(QLabel("Google Sheet ID:"), self.sheet_id_edit); form_layout.addRow(QLabel("Google Drive Folder ID:"), self.folder_id_edit); form_layout.addRow(QLabel("페이지 당 항목 수:"), self.page_size_edit)
        css_layout = QHBoxLayout(); self.css_path_edit = QLineEdit(); self.css_path_edit.setPlaceholderText("CSS 파일 경로 (비워두면 기본 스타일 사용)"); css_browse_button = QPushButton("찾아보기"); css_browse_button.clicked.connect(self.browse_css_file)
        css_layout.addWidget(self.css_path_edit); css_layout.addWidget(css_browse_button); form_layout.addRow(QLabel("사용자 정의 뷰어 CSS:"), css_layout)
        self.startup_checkbox = QCheckBox("윈도우 시작 시 자동 실행"); self.save_button = QPushButton("설정 저장");
        main_layout = QVBoxLayout(); main_layout.addLayout(form_layout); main_layout.addWidget(self.startup_checkbox); main_layout.addWidget(self.save_button); self.setLayout(main_layout)
    def load_current_settings(self):
        self.hotkey_new_edit.setText(config_manager.get_setting('Hotkeys', 'new_memo')); self.hotkey_list_edit.setText(config_manager.get_setting('Hotkeys', 'list_memos')); self.hotkey_launcher_edit.setText(config_manager.get_setting('Hotkeys', 'quick_launcher'))
        self.sheet_id_edit.setText(config_manager.get_setting('Google', 'spreadsheet_id')); self.folder_id_edit.setText(config_manager.get_setting('Google', 'folder_id')); self.page_size_edit.setText(config_manager.get_setting('Display', 'page_size'))
        self.css_path_edit.setText(config_manager.get_setting('Display', 'custom_css_path')); self.startup_checkbox.setChecked(config_manager.is_startup_enabled())
    def browse_css_file(self):
        fname, _ = QFileDialog.getOpenFileName(self, '사용자 CSS 파일 선택', '', 'CSS Files (*.css)');
        if fname: self.css_path_edit.setText(fname)
    def closeEvent(self, event): self.hide()
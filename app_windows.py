from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QLineEdit, QHBoxLayout,
                             QTextEdit, QPushButton, QTableWidget, QTableWidgetItem,
                             QHeaderView, QMessageBox, QMenu, QStatusBar, QLabel, QFrame,QTreeWidget,QTreeWidgetItem,
                             QFormLayout, QCheckBox, QTextBrowser, QSplitter, QListWidget, QListWidgetItem, QFileDialog)
from core import config_manager
import qtawesome as qta

class QuickLauncherWindow(QWidget):
    memo_selected = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.initUI()
    def initUI(self):
        self.setFixedSize(600, 300)
        layout = QVBoxLayout(); layout.setContentsMargins(5, 5, 5, 5)
        self.search_box = QLineEdit(); self.search_box.setPlaceholderText("메모 검색...")
        self.search_box.setStyleSheet("padding: 8px; font-size: 12pt;")
        self.results_list = QListWidget(); self.results_list.setStyleSheet("font-size: 11pt;")
        self.results_list.itemActivated.connect(self.item_activated)
        layout.addWidget(self.search_box); layout.addWidget(self.results_list); self.setLayout(layout)
    def update_results(self, results):
        self.results_list.clear()
        for title, date, doc_id in results:
            item = QListWidgetItem(f"{title} ({date})")
            item.setData(Qt.UserRole, doc_id)
            self.results_list.addItem(item)
        if self.results_list.count() > 0: self.results_list.setCurrentRow(0)
    def item_activated(self, item):
        data = item.data(Qt.UserRole);
        self.memo_selected.emit(data);
    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape: self.hide()
        elif event.key() == Qt.Key_Down: self.results_list.setCurrentRow(min(self.results_list.currentRow() + 1, self.results_list.count() - 1))
        elif event.key() == Qt.Key_Up: self.results_list.setCurrentRow(max(self.results_list.currentRow() - 1, 0))
        else: super().keyPressEvent(event)

class RichMemoViewWindow(QWidget):
    def __init__(self):
        super().__init__(); self.initUI()
    def initUI(self):
        self.setWindowTitle('메모 보기'); self.setGeometry(250, 250, 600, 700); self.setStyleSheet("background-color: #ffffff;")
        layout = QVBoxLayout(); self.content_display = QTextBrowser()
        self.content_display.setStyleSheet("QTextBrowser { background-color: #ffffff; border: none; font-size: 11pt; }")
        self.content_display.setOpenExternalLinks(True); layout.addWidget(self.content_display); self.setLayout(layout)
    def set_content(self, title, html_content):
        self.setWindowTitle(title); self.content_display.setHtml(html_content); self.show(); self.activateWindow(); self.raise_()
    def closeEvent(self, event): self.hide()

class MarkdownEditorWindow(QWidget):
    def __init__(self):
        super().__init__(); self.current_doc_id = None; self.initUI(); self.preview_timer = QTimer(self); self.preview_timer.setSingleShot(True)
    def initUI(self):
        self.setWindowTitle('새 메모 작성')
        self.setGeometry(150, 150, 1200, 800)
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)
        
        top_layout = QHBoxLayout()
        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText('제목')
        self.save_button = QPushButton(' 저장')
        self.save_button.setIcon(qta.icon('fa5s.save', color='white'))
        top_layout.addWidget(self.title_input)
        top_layout.addWidget(self.save_button)
        main_layout.addLayout(top_layout)

        splitter = QSplitter(Qt.Horizontal)
        self.editor = QTextEdit()
        self.viewer = QTextBrowser()
        self.editor.setPlaceholderText("# 마크다운으로 메모를 작성하세요...")
        self.viewer.setOpenExternalLinks(True)
        self.editor.setStyleSheet("font-family: Consolas, 'Courier New', monospace;")
        splitter.addWidget(self.editor)
        splitter.addWidget(self.viewer)
        splitter.setSizes([600, 600])
        main_layout.addWidget(splitter)
        
        # ★★★ 핵심 수정: 불필요한 QFrame을 제거하고 QHBoxLayout을 직접 사용합니다. ★★★
        tag_layout = QHBoxLayout()
        tag_layout.setContentsMargins(0, 5, 0, 0) # 위쪽 여백만 살짝 줍니다.
        tag_label = QLabel("태그:")
        self.tag_input = QLineEdit()
        self.tag_input.setPlaceholderText("#태그1, #태그2, ...")
        tag_layout.addWidget(tag_label)
        tag_layout.addWidget(self.tag_input)
        
        # 메인 레이아웃에 태그 레이아웃을 추가
        main_layout.addLayout(tag_layout)
        self.setLayout(main_layout)
        self.setLayout(main_layout)

    def open_document(self, doc_id, title, markdown_content,tags_text):
        self.current_doc_id = doc_id
        self.setWindowTitle(f'메모 편집: {title}')
        self.title_input.setText(title)
        self.editor.setPlainText(markdown_content)
        self.tag_input.setText(tags_text) # 태그 입력창에 내용 설정
        self.show()
        self.activateWindow()

    def clear_fields(self):
        self.current_doc_id = None; self.setWindowTitle('새 메모 작성'); self.title_input.clear(); self.editor.clear(); self.viewer.clear();  self.tag_input.clear()
    def closeEvent(self, event): self.clear_fields(); self.hide(); event.ignore()

class MemoListWindow(QWidget):
    navigation_selected = pyqtSignal(str) 
    context_menu_requested = pyqtSignal(object)
    def __init__(self):
        super().__init__(); self.initUI()
    def initUI(self):
        self.setWindowTitle('메모 목록')
        self.setGeometry(200, 200, 800, 500) # 창 크기 확장
        main_layout = QHBoxLayout(self) # ★★★ 메인 레이아웃을 QHBoxLayout으로 변경

        # --- 좌측 네비게이션 영역 ---
        left_panel = QFrame()
        left_layout = QVBoxLayout(left_panel)
        left_panel.setMaximumWidth(200)

        self.nav_tree = QTreeWidget()
        self.nav_tree.setHeaderHidden(True)
        left_layout.addWidget(self.nav_tree)
        
        # --- 우측 메인 콘텐츠 영역 (기존 창의 내용) ---
        right_panel = QFrame()
        right_layout = QVBoxLayout(right_panel)

        search_layout = QHBoxLayout(); self.search_bar = QLineEdit(); self.full_text_search_check = QCheckBox("본문 포함"); search_layout.addWidget(self.search_bar); search_layout.addWidget(self.full_text_search_check);
        self.refresh_button = QPushButton(qta.icon('fa5s.sync-alt', color='#495057'), ""); self.refresh_button.setObjectName("PagingButton");
        search_layout.addWidget(self.refresh_button)
        right_layout.addLayout(search_layout)

        self.table = QTableWidget(); self.table.setColumnCount(2); self.table.setHorizontalHeaderLabels(['제목', '생성일']); self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch); self.table.setEditTriggers(QTableWidget.NoEditTriggers); self.table.setSortingEnabled(True);
        right_layout.addWidget(self.table)
        
        paging_layout = QHBoxLayout(); self.prev_button = QPushButton(qta.icon('fa5s.chevron-left', color='#495057'), ""); self.prev_button.setObjectName("PagingButton"); self.page_label = QLabel("1 페이지"); self.page_label.setAlignment(Qt.AlignCenter); self.next_button = QPushButton(qta.icon('fa5s.chevron-right', color='#495057'), ""); self.next_button.setObjectName("PagingButton"); paging_layout.addWidget(self.prev_button); paging_layout.addWidget(self.page_label); paging_layout.addWidget(self.next_button);
        right_layout.addLayout(paging_layout)
        
        self.statusBar = QStatusBar();
        right_layout.addWidget(self.statusBar)

        # --- 스플리터로 좌/우 패널 결합 ---
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([180, 620])
        main_layout.addWidget(splitter)
        
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.context_menu_requested.emit)
        self.nav_tree.currentItemChanged.connect(self.on_nav_selected)

    def on_nav_selected(self, current, previous):
        if current:
            self.navigation_selected.emit(current.text(0))

    def update_nav_tree(self, tags):
        self.nav_tree.clear()
        
        all_memos_item = QTreeWidgetItem(self.nav_tree)
        all_memos_item.setText(0, "전체 메모")
        all_memos_item.setIcon(0, qta.icon('fa5s.inbox'))
        
        if tags:
            tags_root_item = QTreeWidgetItem(self.nav_tree)
            tags_root_item.setText(0, "태그")
            tags_root_item.setIcon(0, qta.icon('fa5s.tags'))
            
            for tag in sorted(tags):
                tag_item = QTreeWidgetItem(tags_root_item)
                tag_item.setText(0, tag)
            
            tags_root_item.setExpanded(True)
        
        self.nav_tree.setCurrentItem(all_memos_item)
    def populate_table(self, data, is_local):
        is_full_text = self.full_text_search_check.isChecked()
        self.prev_button.setVisible(is_full_text)
        self.next_button.setVisible(is_full_text)
        self.page_label.setVisible(is_full_text)
        
        self.table.setSortingEnabled(not is_full_text)
        self.table.clearContents()
        self.table.setRowCount(len(data))
        for i, row in enumerate(data):
            title, date, doc_id = row[0], row[1], row[2]
            title_item = QTableWidgetItem(title)
            date_item = QTableWidgetItem(date)
            
            title_item.setData(Qt.UserRole, doc_id)
            date_item.setData(Qt.UserRole, doc_id)
            
            self.table.setItem(i, 0, title_item)
            self.table.setItem(i, 1, date_item)
    def update_paging_buttons(self, prev_enabled, next_enabled, page_num):
        self.prev_button.setEnabled(prev_enabled); self.next_button.setEnabled(next_enabled); self.page_label.setText(f"{page_num} 페이지")
    def closeEvent(self, event): event.ignore(); self.hide()

class SettingsWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()
        self.load_current_settings()
    def initUI(self):
        self.setWindowTitle('설정')
        self.setGeometry(400, 400, 500, 310) # 창 크기 조정
        form_layout = QFormLayout()
        form_layout.setSpacing(10)

        self.hotkey_new_edit = QLineEdit()
        self.hotkey_list_edit = QLineEdit()
        self.hotkey_launcher_edit = QLineEdit()
        self.sheet_id_edit = QLineEdit()
        self.folder_id_edit = QLineEdit()
        self.page_size_edit = QLineEdit()
        
        form_layout.addRow(QLabel("새 메모 단축키:"), self.hotkey_new_edit)
        form_layout.addRow(QLabel("목록 보기 단축키:"), self.hotkey_list_edit)
        form_layout.addRow(QLabel("빠른 실행 단축키:"), self.hotkey_launcher_edit)
        form_layout.addRow(QLabel("Google Sheet ID:"), self.sheet_id_edit)
        form_layout.addRow(QLabel("Google Drive Folder ID:"), self.folder_id_edit)
        form_layout.addRow(QLabel("페이지 당 항목 수:"), self.page_size_edit)

        # ★★★ 핵심 수정: 사용자 CSS 경로 지정을 위한 UI 추가 ★★★
        css_layout = QHBoxLayout()
        self.css_path_edit = QLineEdit()
        self.css_path_edit.setPlaceholderText("CSS 파일 경로 (비워두면 기본 스타일 사용)")
        css_browse_button = QPushButton("찾아보기")
        css_browse_button.clicked.connect(self.browse_css_file)
        css_layout.addWidget(self.css_path_edit)
        css_layout.addWidget(css_browse_button)
        form_layout.addRow(QLabel("사용자 정의 뷰어 CSS:"), css_layout)

        self.startup_checkbox = QCheckBox("윈도우 시작 시 자동 실행")
        self.save_button = QPushButton("설정 저장")
        
        main_layout = QVBoxLayout()
        main_layout.addLayout(form_layout)
        main_layout.addWidget(self.startup_checkbox)
        main_layout.addWidget(self.save_button)
        self.setLayout(main_layout)

    def load_current_settings(self):
        self.hotkey_new_edit.setText(config_manager.get_setting('Hotkeys', 'new_memo'))
        self.hotkey_list_edit.setText(config_manager.get_setting('Hotkeys', 'list_memos'))
        self.hotkey_launcher_edit.setText(config_manager.get_setting('Hotkeys', 'quick_launcher'))
        self.sheet_id_edit.setText(config_manager.get_setting('Google', 'spreadsheet_id'))
        self.folder_id_edit.setText(config_manager.get_setting('Google', 'folder_id'))
        self.page_size_edit.setText(config_manager.get_setting('Display', 'page_size'))
        # ★★★ 핵심 수정: CSS 경로 설정 불러오기 ★★★
        self.css_path_edit.setText(config_manager.get_setting('Display', 'custom_css_path'))
        self.startup_checkbox.setChecked(config_manager.is_startup_enabled())

    # ★★★ 핵심 수정: CSS 파일 찾아보기 대화상자를 여는 함수 추가 ★★★
    def browse_css_file(self):
        fname, _ = QFileDialog.getOpenFileName(self, '사용자 CSS 파일 선택', '', 'CSS Files (*.css)')
        if fname:
            self.css_path_edit.setText(fname)

    def closeEvent(self, event):
        self.hide()
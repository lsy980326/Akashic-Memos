from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QLineEdit, QHBoxLayout,
                             QTextEdit, QPushButton, QTableWidget, QTableWidgetItem,
                             QHeaderView, QMessageBox, QMenu, QStatusBar, QLabel,
                             QFormLayout, QCheckBox, QTextBrowser, QSplitter, QListWidget, QListWidgetItem)
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
        doc_id = item.data(Qt.UserRole); self.memo_selected.emit(doc_id); self.hide()
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
        self.setWindowTitle('새 메모 작성'); self.setGeometry(150, 150, 1200, 800)
        main_layout = QVBoxLayout(); main_layout.setContentsMargins(10, 10, 10, 10); main_layout.setSpacing(10)
        top_layout = QHBoxLayout(); self.title_input = QLineEdit(); self.title_input.setPlaceholderText('제목')
        self.save_button = QPushButton(' 저장'); self.save_button.setIcon(qta.icon('fa5s.save', color='white'))
        top_layout.addWidget(self.title_input); top_layout.addWidget(self.save_button)
        main_layout.addLayout(top_layout)
        splitter = QSplitter(Qt.Horizontal); self.editor = QTextEdit(); self.viewer = QTextBrowser()
        self.editor.setPlaceholderText("# 마크다운으로 메모를 작성하세요..."); self.viewer.setOpenExternalLinks(True)
        self.editor.setStyleSheet("font-family: Consolas, 'Courier New', monospace;");
        splitter.addWidget(self.editor); splitter.addWidget(self.viewer); splitter.setSizes([600, 600])
        main_layout.addWidget(splitter); self.setLayout(main_layout)
    def open_document(self, doc_id, title, markdown_content):
        self.current_doc_id = doc_id; self.setWindowTitle(f'메모 편집: {title}'); self.title_input.setText(title); self.editor.setPlainText(markdown_content); self.show(); self.activateWindow()
    def clear_fields(self):
        self.current_doc_id = None; self.setWindowTitle('새 메모 작성'); self.title_input.clear(); self.editor.clear(); self.viewer.clear()
    def closeEvent(self, event): self.clear_fields(); self.hide(); event.ignore()

class MemoListWindow(QWidget):
    context_menu_requested = pyqtSignal(object)
    def __init__(self):
        super().__init__(); self.initUI()
    def initUI(self):
        self.setWindowTitle('메모 목록'); self.setGeometry(200, 200, 500, 400); main_layout = QVBoxLayout(); main_layout.setContentsMargins(10, 10, 10, 10); main_layout.setSpacing(10)
        search_layout = QHBoxLayout(); self.search_bar = QLineEdit(); self.full_text_search_check = QCheckBox("본문 포함"); search_layout.addWidget(self.search_bar); search_layout.addWidget(self.full_text_search_check); main_layout.addLayout(search_layout)
        self.table = QTableWidget(); self.table.setColumnCount(2); self.table.setHorizontalHeaderLabels(['제목', '생성일']); self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch); self.table.setEditTriggers(QTableWidget.NoEditTriggers); self.table.setSortingEnabled(True); main_layout.addWidget(self.table)
        paging_layout = QHBoxLayout(); self.prev_button = QPushButton(qta.icon('fa5s.chevron-left', color='#495057'), ""); self.prev_button.setObjectName("PagingButton"); self.page_label = QLabel("1 페이지"); self.page_label.setAlignment(Qt.AlignCenter); self.next_button = QPushButton(qta.icon('fa5s.chevron-right', color='#495057'), ""); self.next_button.setObjectName("PagingButton"); paging_layout.addWidget(self.prev_button); paging_layout.addWidget(self.page_label); paging_layout.addWidget(self.next_button); main_layout.addLayout(paging_layout)
        self.statusBar = QStatusBar(); main_layout.addWidget(self.statusBar); self.setLayout(main_layout)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu); self.table.customContextMenuRequested.connect(self.context_menu_requested.emit)
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
        super().__init__(); self.initUI(); self.load_current_settings()
    def initUI(self):
        self.setWindowTitle('설정'); self.setGeometry(400, 400, 450, 280); form_layout = QFormLayout()
        self.hotkey_new_edit = QLineEdit(); self.hotkey_list_edit = QLineEdit(); self.hotkey_launcher_edit = QLineEdit()
        self.sheet_id_edit = QLineEdit(); self.folder_id_edit = QLineEdit(); self.page_size_edit = QLineEdit()
        form_layout.addRow(QLabel("새 메모 단축키:"), self.hotkey_new_edit); form_layout.addRow(QLabel("목록 보기 단축키:"), self.hotkey_list_edit); form_layout.addRow(QLabel("빠른 실행 단축키:"), self.hotkey_launcher_edit)
        form_layout.addRow(QLabel("Google Sheet ID:"), self.sheet_id_edit); form_layout.addRow(QLabel("Google Drive Folder ID:"), self.folder_id_edit); form_layout.addRow(QLabel("페이지 당 항목 수:"), self.page_size_edit)
        self.startup_checkbox = QCheckBox("윈도우 시작 시 자동 실행");
        self.save_button = QPushButton("설정 저장");
        main_layout = QVBoxLayout(); main_layout.addLayout(form_layout); main_layout.addWidget(self.startup_checkbox); main_layout.addWidget(self.save_button); self.setLayout(main_layout)
    def load_current_settings(self):
        self.hotkey_new_edit.setText(config_manager.get_setting('Hotkeys', 'new_memo')); self.hotkey_list_edit.setText(config_manager.get_setting('Hotkeys', 'list_memos')); self.hotkey_launcher_edit.setText(config_manager.get_setting('Hotkeys', 'quick_launcher'))
        self.sheet_id_edit.setText(config_manager.get_setting('Google', 'spreadsheet_id')); self.folder_id_edit.setText(config_manager.get_setting('Google', 'folder_id')); self.page_size_edit.setText(config_manager.get_setting('Display', 'page_size'))
        self.startup_checkbox.setChecked(config_manager.is_startup_enabled())
    def closeEvent(self, event): self.hide()
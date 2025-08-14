from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QUrl, QSize
from datetime import datetime
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEnginePage
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QLineEdit, QHBoxLayout,
                             QTextEdit, QPushButton, QTableWidget, QTableWidgetItem,
                             QHeaderView, QMessageBox, QMenu, QStatusBar, QLabel,
                             QFormLayout, QCheckBox, QSplitter, QListWidget,
                             QListWidgetItem, QTreeWidget, QTreeWidgetItem, QFrame,
                             QFileDialog, QToolBar, QAction, QSizePolicy,QScrollArea)
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
            self.page().runJavaScript("window.getSelection().toString();", self.handle_selection_callback)

    def handle_selection_callback(self, selected_text):
        if selected_text:
            self.tags_edit_requested.emit(selected_text)
        else:
            self.tags_edit_requested.emit("")

class RichMemoViewWindow(QWidget):
    link_activated = pyqtSignal(QUrl)
    tags_edit_requested = pyqtSignal(str)
    edit_requested = pyqtSignal()
    open_in_gdocs_requested = pyqtSignal()
    favorite_toggled = pyqtSignal()

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

        self.fav_action = QAction(qta.icon('fa5s.star', color='#666'), "즐겨찾기", self)
        self.fav_action.setCheckable(True) # 토글 버튼으로 만듬
        self.fav_action.triggered.connect(self.favorite_toggled.emit)
        toolbar.addAction(self.fav_action)

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

    def update_favorite_status(self, is_favorite):
        self.fav_action.setChecked(is_favorite)
        # 아이콘 색상을 상태에 따라 변경
        color = '#f0c420' if is_favorite else '#666'
        self.fav_action.setIcon(qta.icon('fa5s.star' if is_favorite else 'fa5s.star', color=color))

    def closeEvent(self, event):
        self.hide()

class MarkdownEditorWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.window_name = "MarkdownEditorWindow"
        self.current_doc_id = None
        self.initUI()
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.autosave_timer = QTimer(self)
        self.autosave_timer.setSingleShot(True)

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

        tag_layout = QHBoxLayout();
        tag_layout.setContentsMargins(0, 5, 0, 0);

        
        tag_label = QLabel("태그:");
        self.tag_input = QLineEdit();
        self.tag_input.setPlaceholderText("#태그1, #태그2, ...")

        bottom_layout = QHBoxLayout()
        self.auto_save_status_label = QLabel("모든 변경사항이 저장됨")
        self.auto_save_status_label.setAlignment(Qt.AlignLeft)
        self.auto_save_status_label.setStyleSheet("color: #6c757d; padding-top: 5px;") # 위쪽 여백 추가
        self.auto_save_status_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum) 

        tag_layout.addWidget(tag_label);
        tag_layout.addWidget(self.tag_input);
        bottom_layout.addWidget(self.auto_save_status_label)
        main_layout.addLayout(tag_layout)
        main_layout.addLayout(bottom_layout)
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

    def closeEvent(self, event):
        geometry_hex = self.saveGeometry().toHex().data().decode('utf-8')
        config_manager.save_window_state(self.window_name, geometry_hex)
        self.clear_fields()
        self.hide()
        event.ignore()

    def update_auto_save_status(self, status: str):
        if status == "모든 변경사항이 저장됨":
            self.auto_save_status_label.setText(f"✅ {status}")
            self.auto_save_status_label.setStyleSheet("color: #28a745;") # 초록색
        elif status == "저장 중...":
            self.auto_save_status_label.setText(f"💾 {status}")
            self.auto_save_status_label.setStyleSheet("color: #007bff;") # 파란색
        elif status == "변경사항이 있습니다...":
            self.auto_save_status_label.setText(f"📝 {status}")
            self.auto_save_status_label.setStyleSheet("color: #6c757d;") # 회색
        elif status == "저장 실패":
            self.auto_save_status_label.setText(f"❌ {status}")
            self.auto_save_status_label.setStyleSheet("color: #dc3545;") # 빨간색
        else:
            self.auto_save_status_label.setText(f"{status}")
            self.auto_save_status_label.setStyleSheet("color: #6c757d;") # 기본 회색

class MemoListWindow(QWidget):
    navigation_selected = pyqtSignal(str);
    context_menu_requested = pyqtSignal(object);
    favorite_toggled_from_list = pyqtSignal(str);

    def __init__(self):
        super().__init__();
        self.window_name = "MemoListWindow"
        self.initUI()

    def initUI(self):
        # ===================================================================
        # 윈도우 기본 설정
        # ===================================================================
        self.setWindowTitle('메모 목록')
        self.setGeometry(200, 200, 800, 500)

        # ===================================================================
        # 패널 및 레이아웃 생성
        # ===================================================================
        # --- 전체를 감싸는 메인 레이아웃 ---
        main_layout = QHBoxLayout(self)

        # --- 좌/우 분할을 위한 스플리터 ---
        splitter = QSplitter(Qt.Horizontal)

        # --- 왼쪽 패널 (네비게이션 트리용) ---
        left_panel = QFrame()
        left_layout = QVBoxLayout(left_panel)
        # left_panel.setMaximumWidth(200)

        # --- 오른쪽 패널 (메인 콘텐츠용) ---
        right_panel = QFrame()
        right_layout = QVBoxLayout(right_panel)

        # ===================================================================
        # 왼쪽 패널 위젯 설정
        # ===================================================================
        self.nav_tree = QTreeWidget()
        self.nav_tree.setHeaderHidden(True)
        left_layout.addWidget(self.nav_tree)

        # ===================================================================
        # 오른쪽 패널 위젯 설정
        # ===================================================================
        # --- 1. 검색 바 ---
        search_layout = QHBoxLayout()
        self.search_bar = QLineEdit()
        self.full_text_search_check = QCheckBox("본문 포함")
        self.refresh_button = QPushButton(qta.icon('fa5s.sync-alt', color='#495057'), "")
        self.refresh_button.setObjectName("PagingButton")

        search_layout.addWidget(self.search_bar)
        search_layout.addWidget(self.full_text_search_check)
        search_layout.addWidget(self.refresh_button)
        right_layout.addLayout(search_layout)

        # --- 2. 데이터 테이블 ---
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(['', '제목', '날짜', '태그'])
        self.table.setColumnWidth(0, 30)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed) # 첫 번째 열 너비 고정
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch) # 두 번째 열 너비 확장
        self.table.setEditTriggers(QTableWidget.NoEditTriggers) # 직접 편집 방지
        self.table.setSortingEnabled(True) # 정렬 기능 활성화
        right_layout.addWidget(self.table)

        # --- 3. 페이징 컨트롤 ---
        paging_layout = QHBoxLayout()
        self.prev_button = QPushButton(qta.icon('fa5s.chevron-left', color='#495057'), "")
        self.prev_button.setObjectName("PagingButton")
        self.page_label = QLabel("1 페이지")
        self.page_label.setAlignment(Qt.AlignCenter)
        self.next_button = QPushButton(qta.icon('fa5s.chevron-right', color='#495057'), "")
        self.next_button.setObjectName("PagingButton")

        paging_layout.addWidget(self.prev_button)
        paging_layout.addWidget(self.page_label)
        paging_layout.addWidget(self.next_button)
        right_layout.addLayout(paging_layout)

        # --- 4. 상태 바 ---
        self.statusBar = QStatusBar()
        right_layout.addWidget(self.statusBar)

        # ===================================================================
        # 스플리터 및 메인 레이아웃에 위젯 배치
        # ===================================================================
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([180, 620]) # 초기 분할 크기 설정
        main_layout.addWidget(splitter)

        # ===================================================================
        # 시그널(Signal) / 슬롯(Slot) 연결
        # ===================================================================
        self.nav_tree.currentItemChanged.connect(self.on_nav_selected)
        self.table.cellClicked.connect(self.on_cell_clicked)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.context_menu_requested.emit)

    def on_nav_selected(self, current, previous):
        if current:
            nav_id = current.data(0, Qt.UserRole)
            if nav_id:
                self.navigation_selected.emit(nav_id)
            else:
                self.navigation_selected.emit(current.text(0))

    def update_nav_tree(self, all_tags, local_cache):
        self.nav_tree.blockSignals(True)
        self.nav_tree.clear()

        # 즐겨찾기 카운트
        favorites_count = len(config_manager.get_favorites())
        favorites_item = QTreeWidgetItem(self.nav_tree)
        favorites_item.setText(0, f"즐겨찾기 ({favorites_count})")
        favorites_item.setIcon(0, qta.icon('fa5s.star', color='#f0c420'))
        favorites_item.setData(0, Qt.UserRole, "favorites")

        # 전체 메모 카운트
        all_memos_count = len(local_cache)
        all_memos_item = QTreeWidgetItem(self.nav_tree)
        all_memos_item.setText(0, f"전체 메모 ({all_memos_count})")
        all_memos_item.setIcon(0, qta.icon('fa5s.inbox'))

        # --- 구분선 아이템 추가 ---
        separator = QTreeWidgetItem(self.nav_tree)
        separator.setText(0, "──────────")
        separator.setFlags(separator.flags() & ~Qt.ItemIsSelectable) # 선택 불가능하게 설정

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
        
        favorites = config_manager.get_favorites()

        for i, row in enumerate(data):
            title = row[0] if len(row) > 0 else ""
            date = row[1] if len(row) > 1 else ""
            doc_id = row[2] if len(row) > 2 else ""
            tags = row[3] if len(row) > 3 else ""

            # 즐겨찾기 아이콘 아이템
            is_favorite = doc_id in favorites
            fav_item = QTableWidgetItem()
            icon = qta.icon('fa5s.star', color='#f0c420') if is_favorite else qta.icon('fa5s.star', color='#aaa')
            fav_item.setIcon(icon)
            fav_item.setData(Qt.UserRole, doc_id) # 여기에도 doc_id를 저장해두면 유용할 수 있음

            title_item = QTableWidgetItem(title)
            date_item = QTableWidgetItem(date)
            tags_item = QTableWidgetItem(tags)
            
            # 모든 아이템에 doc_id 저장
            title_item.setData(Qt.UserRole, doc_id)
            date_item.setData(Qt.UserRole, doc_id)
            tags_item.setData(Qt.UserRole, doc_id)

            self.table.setItem(i, 0, fav_item)
            self.table.setItem(i, 1, title_item)
            self.table.setItem(i, 2, date_item)
            self.table.setItem(i, 3, tags_item)
    
    def update_paging_buttons(self, prev_enabled, next_enabled, page_num):
        self.prev_button.setEnabled(prev_enabled); self.next_button.setEnabled(next_enabled); self.page_label.setText(f"{page_num} 페이지")
    
    def on_cell_clicked(self, row, column):
        if column == 0: # 0번 열(즐겨찾기 아이콘)이 클릭되었을 때
            doc_id = self.table.item(row, 1).data(Qt.UserRole)
            if doc_id:
                self.favorite_toggled_from_list.emit(doc_id)

    def closeEvent(self, event):
        geometry_hex = self.saveGeometry().toHex().data().decode('utf-8')
        config_manager.save_window_state(self.window_name, geometry_hex)
        event.ignore()
        self.hide()

class SettingsWindow(QWidget):
    def __init__(self):
        super().__init__(); self.initUI(); self.load_current_settings()
    def initUI(self):
        self.setWindowTitle('설정'); self.setGeometry(400, 400, 500, 350); form_layout = QFormLayout(); form_layout.setSpacing(10)
        self.hotkey_new_edit = QLineEdit(); self.hotkey_list_edit = QLineEdit(); self.hotkey_launcher_edit = QLineEdit()
        self.sheet_id_edit = QLineEdit(); self.folder_id_edit = QLineEdit(); self.page_size_edit = QLineEdit()
        form_layout.addRow(QLabel("새 메모 단축키:"), self.hotkey_new_edit); form_layout.addRow(QLabel("목록 보기 단축키:"), self.hotkey_list_edit); form_layout.addRow(QLabel("빠른 실행 단축키:"), self.hotkey_launcher_edit)
        form_layout.addRow(QLabel("Google Sheet ID:"), self.sheet_id_edit); form_layout.addRow(QLabel("Google Drive Folder ID:"), self.folder_id_edit); form_layout.addRow(QLabel("페이지 당 항목 수:"), self.page_size_edit)
        css_layout = QHBoxLayout(); self.css_path_edit = QLineEdit(); self.css_path_edit.setPlaceholderText("CSS 파일 경로 (비워두면 기본 스타일 사용)"); css_browse_button = QPushButton("찾아보기"); css_browse_button.clicked.connect(self.browse_css_file)
        css_layout.addWidget(self.css_path_edit); css_layout.addWidget(css_browse_button); form_layout.addRow(QLabel("사용자 정의 뷰어 CSS:"), css_layout)
        
        self.autosave_checkbox = QCheckBox("자동 저장 활성화 (ms, 0이면 비활성화)")
        self.autosave_interval_edit = QLineEdit()
        form_layout.addRow(self.autosave_checkbox, self.autosave_interval_edit)

        self.startup_checkbox = QCheckBox("윈도우 시작 시 자동 실행"); self.save_button = QPushButton("설정 저장");
        main_layout = QVBoxLayout(); main_layout.addLayout(form_layout); main_layout.addWidget(self.startup_checkbox); main_layout.addWidget(self.save_button); self.setLayout(main_layout)
    def load_current_settings(self):
        self.hotkey_new_edit.setText(config_manager.get_setting('Hotkeys', 'new_memo')); self.hotkey_list_edit.setText(config_manager.get_setting('Hotkeys', 'list_memos')); self.hotkey_launcher_edit.setText(config_manager.get_setting('Hotkeys', 'quick_launcher'))
        self.sheet_id_edit.setText(config_manager.get_setting('Google', 'spreadsheet_id')); self.folder_id_edit.setText(config_manager.get_setting('Google', 'folder_id')); self.page_size_edit.setText(config_manager.get_setting('Display', 'page_size'))
        self.css_path_edit.setText(config_manager.get_setting('Display', 'custom_css_path'))
        
        autosave_interval = config_manager.get_setting('Display', 'autosave_interval_ms')
        self.autosave_interval_edit.setText(autosave_interval)
        self.autosave_checkbox.setChecked(int(autosave_interval) > 0)

        self.startup_checkbox.setChecked(config_manager.is_startup_enabled())

    def get_autosave_settings(self):
        return self.autosave_checkbox.isChecked(), self.autosave_interval_edit.text()
    def browse_css_file(self):
        fname, _ = QFileDialog.getOpenFileName(self, '사용자 CSS 파일 선택', '', 'CSS Files (*.css)');
        if fname: self.css_path_edit.setText(fname)
    def closeEvent(self, event): self.hide()


class SourceMemoWidget(QFrame):
    def __init__(self, text, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(5)

        self.setObjectName("SourceMemoWidget")
        self.setStyleSheet("""
            #SourceMemoWidget {
                background-color: #f1f3f5;
                border-radius: 10px;
                border: none;
            }
        """)

        icon = QLabel()
        icon.setPixmap(qta.icon('fa5s.rocket', color='#4c6ef5').pixmap(QSize(12, 12)))
        self.label = QLabel(text)
        self.label.setStyleSheet("color: #495057; background-color: transparent; border: none;")

        layout.addWidget(icon)
        layout.addWidget(self.label)
    
    def set_checked_state(self, is_checked):
        if is_checked:
            self.label.setStyleSheet("color: #adb5bd; background-color: transparent; border: none; text-decoration: line-through;")
            self.setStyleSheet("""
                #SourceMemoWidget {
                    background-color: #f8f9fa;
                    border-radius: 10px;
                    border: none;
                }
            """)
        else:
            self.label.setStyleSheet("color: #495057; background-color: transparent; border: none;")
            self.setStyleSheet("""
                #SourceMemoWidget {
                    background-color: #f1f3f5;
                    border-radius: 10px;
                    border: none;
                }
            """)


class TodoItemWidget(QFrame):
    toggled = pyqtSignal(bool)

    def __init__(self, text, source_memo, is_checked, deadline, priority, parent=None):
        super().__init__(parent)
        self.setObjectName("TodoItemFrame")
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(12)

        self.checkbox = QCheckBox()
        self.checkbox.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        self.text_label = QLabel(text)
        self.text_label.setWordWrap(True)
        self.text_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.text_label.setFont(QFont("Segoe UI", 10))

        layout.addWidget(self.checkbox)
        layout.addWidget(self.text_label, 1)

        # 우선순위 표시
        if priority:
            priority_colors = {1: '#e03131', 2: '#f08c00', 3: '#2f9e44', 4: '#1971c2', 5: '#868e96'}
            color = priority_colors.get(priority, '#868e96')
            priority_label = QLabel()
            priority_label.setPixmap(qta.icon('fa5s.flag', color=color).pixmap(QSize(14, 14)))
            priority_label.setToolTip(f"우선순위: {priority}")
            layout.addWidget(priority_label)

        # 마감일 표시
        if deadline:
            deadline_icon_label = QLabel()
            deadline_text_label = QLabel(deadline.split(' ')[0]) # 날짜 부분만 표시
            
            is_overdue = False
            try:
                deadline_format = "%Y-%m-%d %H:%M" if ':' in deadline else "%Y-%m-%d"
                deadline_dt = datetime.strptime(deadline, deadline_format)
                if not is_checked and deadline_dt < datetime.now():
                    is_overdue = True
            except (ValueError, TypeError):
                pass
            
            # 마감일이 지났을 때 더 눈에 띄는 빨간색으로 변경
            color = "#e03131" if is_overdue else "#495057"
            icon = qta.icon('fa5s.calendar-alt', color=color)
            
            deadline_icon_label.setPixmap(icon.pixmap(QSize(14, 14)))
            deadline_text_label.setStyleSheet(f"color: {color}; background: transparent;")
            
            # 툴팁 추가
            deadline_icon_label.setToolTip(f"마감일: {deadline}")
            deadline_text_label.setToolTip(f"마감일: {deadline}")

            layout.addWidget(deadline_icon_label)
            layout.addWidget(deadline_text_label)


        self.source_widget = SourceMemoWidget(source_memo)
        layout.addWidget(self.source_widget, 1)
        self.checkbox.toggled.connect(self.toggled.emit)
        self.set_checked_state(is_checked)

    def set_checked_state(self, is_checked):
        self.checkbox.blockSignals(True)
        self.checkbox.setChecked(is_checked)
        self.checkbox.blockSignals(False)

        font = self.text_label.font()
        font.setStrikeOut(is_checked)
        self.text_label.setFont(font)
        
        if is_checked:
            self.text_label.setStyleSheet("color: #adb5bd;")
            self.setObjectName("TodoItemFrameChecked")
            self.setStyleSheet("""
                #TodoItemFrameChecked {
                    background-color: #f8f9fa;
                    border: none;
                    border-radius: 8px;
                }
            """)
        else:
            self.text_label.setStyleSheet("color: #212529;")
            self.setObjectName("TodoItemFrame")
            self.setStyleSheet("""
                #TodoItemFrame {
                    background-color: #ffffff;
                    border: none;
                    border-radius: 8px;
                }
            """)

        self.source_widget.set_checked_state(is_checked)


class TodoDashboardWindow(QWidget):
    task_toggled = pyqtSignal(dict, bool)
    item_clicked = pyqtSignal(str)
    refresh_requested = pyqtSignal()
    completion_filter_changed = pyqtSignal(bool)

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.initUI()
        self.offset = None # 창 이동을 위한 변수
        
    def initUI(self):
        self.setFixedSize(500, 600)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        self.setStyleSheet("""
            background-color: #f8f9fa; 
            border: 1px solid #dee2e6; 
            border-radius: 8px;
        """)

        # --- 상단 바 (제목 및 닫기 버튼) ---
        top_bar = QFrame() # 드래그 이벤트를 처리할 상단 바 프레임
        top_bar.setObjectName("TopBar")
        top_bar_layout = QHBoxLayout(top_bar)
        top_bar_layout.setContentsMargins(10, 5, 5, 5)
        top_bar_layout.setSpacing(10)
        title_label = QLabel("<b>오늘 할 일</b>")

        self.show_completed_checkbox = QCheckBox("완료 항목 표시")
        self.show_completed_checkbox.setStyleSheet("color: #495057; spacing: 5px;")
        self.show_completed_checkbox.toggled.connect(self.completion_filter_changed.emit)

        
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        refresh_button = QPushButton(qta.icon('fa5s.sync-alt', color='#888'), "")
        refresh_button.setFlat(True)
        refresh_button.setStyleSheet("QPushButton { border: none; }")
        refresh_button.setToolTip("목록 새로고침")
        refresh_button.clicked.connect(self.refresh_requested.emit)
        
        close_button = QPushButton(qta.icon('fa5s.times', color='#888'), "")
        close_button.setFlat(True) # 버튼 배경을 투명하게
        close_button.setStyleSheet("QPushButton { border: none; }")
        close_button.clicked.connect(self.hide)
        
        top_bar_layout.addWidget(title_label)
        top_bar_layout.addWidget(self.show_completed_checkbox)
        top_bar_layout.addWidget(spacer)
        top_bar_layout.addWidget(refresh_button)
        top_bar_layout.addWidget(close_button)
        main_layout.addWidget(top_bar)
        
        # --- 스크롤 영역 ---
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("QScrollArea { border: none; }") 
        
        container = QWidget()
        self.content_layout = QVBoxLayout(container)
        self.content_layout.setAlignment(Qt.AlignTop)
        self.content_layout.setSpacing(4)
        
        scroll_area.setWidget(container)
        main_layout.addWidget(scroll_area)
        self.setLayout(main_layout) 

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.hide()

    def mousePressEvent(self, event):
        child_widget = self.childAt(event.pos())
    
        if event.button() == Qt.LeftButton and child_widget is not None and child_widget.objectName() == "TopBar":
            self.offset = event.pos()
        else:
            # 그 외의 경우는 기본 이벤트를 처리하도록 넘깁니다.
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.offset is not None and event.buttons() == Qt.LeftButton:
            self.move(self.pos() + event.pos() - self.offset)
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.offset = None
        super().mouseReleaseEvent(event)

    def show_message(self, message):
        self._clear_layout()
        label = QLabel(message)
        label.setAlignment(Qt.AlignCenter)
        self.content_layout.addWidget(label)

    def _clear_layout(self):
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def update_tasks(self, tasks):
        self._clear_layout()
        if not tasks:
            self.show_message("✅ 할 일이 없거나 모두 완료했습니다!")
        else:
            for task in tasks:
                widget = TodoItemWidget(
                    task['line_text'], 
                    task['source_memo'], 
                    task['is_checked'],
                    task['deadline'],
                    task['priority']
                )
                widget.checkbox.setProperty("task_info", task)
                widget.toggled.connect(self.on_task_toggled)
                
                # 항목 클릭 시 원본 메모 보기 (소스 버블 제외)
                widget.mousePressEvent = lambda event, t=task: self.on_item_clicked(event, t)
                self.content_layout.addWidget(widget)

    def on_task_toggled(self, checked):
        sender_widget = self.sender()
        if sender_widget:
            task_info = sender_widget.checkbox.property("task_info")
            if task_info:
                self.task_toggled.emit(task_info, checked)
    
    def on_item_clicked(self, event, task):
        # 소스 위젯을 클릭한 경우는 제외하고, 본문 영역을 클릭했을 때만 반응
        if not isinstance(self.childAt(event.globalPos()), SourceMemoWidget):
            self.item_clicked.emit(task['doc_id'])


class CustomNotificationWindow(QWidget):
    view_memo_requested = pyqtSignal(str) # '메모 보기' 클릭 시 doc_id를 전달할 신호
    notification_closed = pyqtSignal() # 알림 창이 닫힐 때 발생하는 신호

    def __init__(self, parent=None):
        super().__init__(parent)
        self.doc_id = None
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground) # 투명 배경 허용
        self.initUI()
        
    def initUI(self):
        self.setFixedSize(380, 150)

        # 전체 레이아웃
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # 배경 및 테두리 역할을 할 프레임
        bg_frame = QFrame(self)
        bg_frame.setObjectName("NotificationFrame")
        bg_frame.setStyleSheet("""
            #NotificationFrame {
                background-color: #ffffff;
                border: 1px solid #dee2e6;
                border-radius: 8px;
            }
        """)
        
        frame_layout = QVBoxLayout(bg_frame)
        frame_layout.setContentsMargins(15, 10, 15, 10)
        frame_layout.setSpacing(8)
        main_layout.addWidget(bg_frame)

        # 1. 제목 영역
        title_layout = QHBoxLayout()
        icon_label = QLabel()
        icon_label.setPixmap(qta.icon('fa5s.clock', color='#1971c2').pixmap(QSize(16, 16)))
        self.title_label = QLabel("<b>마감일 알림</b>")
        self.title_label.setStyleSheet("font-size: 11pt; background: transparent; border: none;")
        title_layout.addWidget(icon_label)
        title_layout.addWidget(self.title_label)
        title_layout.addStretch()
        
        # 2. 내용 영역
        self.message_label = QLabel("여기에 알림 내용이 표시됩니다.")
        self.message_label.setWordWrap(True)
        self.message_label.setStyleSheet("background: transparent; border: none;")

        # 3. 버튼 영역
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        view_button = QPushButton("메모 보기")
        view_button.clicked.connect(self.view_memo)
        
        dismiss_button = QPushButton("확인")
        dismiss_button.setObjectName("PagingButton") # 다른 스타일 적용
        dismiss_button.clicked.connect(self.hide)

        button_layout.addWidget(view_button)
        button_layout.addWidget(dismiss_button)

        frame_layout.addLayout(title_layout)
        frame_layout.addWidget(self.message_label)
        frame_layout.addStretch()
        frame_layout.addLayout(button_layout)

    def set_notification_data(self, title, message, doc_id):
        self.title_label.setText(f"<b>{title}</b>")
        self.message_label.setText(message)
        self.doc_id = doc_id

    def view_memo(self):
        if self.doc_id:
            self.view_memo_requested.emit(self.doc_id)
        self.hide()

    def hideEvent(self, event):
        super().hideEvent(event)
        self.notification_closed.emit()

class ToastNotificationWindow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(350, 80)

        self.bg_frame = QFrame(self)
        self.bg_frame.setObjectName("ToastFrame")
        self.bg_frame.setStyleSheet("""
            #ToastFrame {
                /* 전체 테마와 일관성을 위한 약간 밝은 회색 배경 */
                background-color: #f8f9fa; 
                /* 흰색 배경 위에 떴을 때를 대비한 미세한 테두리 */
                border: 1px solid #e9ecef; 
                /* 다른 위젯보다 약간 부드러운 느낌을 주는 6px 곡률 */
                border-radius: 6px; 
            }
            #ToastFrame QLabel {
                /* 테마의 기본 텍스트 색상으로 가독성 확보 */
                color: #212529; 
                font-size: 10pt;
                font-weight: 500; /* 살짝 두께감 추가 */
                background-color: transparent;
                border: none;
                /* 텍스트가 답답하지 않도록 내부 여백 설정 */
                padding: 8px 15px;
            }
        """)
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self.bg_frame)

        frame_layout = QHBoxLayout(self.bg_frame)
        frame_layout.setContentsMargins(15, 10, 15, 10)

        self.icon_label = QLabel()
        self.message_label = QLabel()
        
        frame_layout.addWidget(self.icon_label)
        frame_layout.addWidget(self.message_label)
        frame_layout.addStretch()

        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self.hide)

    def show_toast(self, title, message):
        self.message_label.setText(f"<b>{title}</b><br>{message}")
        # Simple icon logic based on title
        if "완료" in title or "성공" in title:
            icon = qta.icon('fa5s.check-circle', color='#28a745') # Green
        elif "오류" in title or "실패" in title:
            icon = qta.icon('fa5s.exclamation-circle', color='#dc3545') # Red
        else:
            icon = qta.icon('fa5s.info-circle', color='#17a2b8') # Blue
        self.icon_label.setPixmap(icon.pixmap(QSize(24, 24)))
        
        self.show()
        self.hide_timer.start(3000) # Hide after 3 seconds
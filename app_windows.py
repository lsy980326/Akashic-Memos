from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QUrl, QSize, QObject, pyqtSlot
from datetime import datetime
from PyQt5.QtWebChannel import QWebChannel
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEnginePage, QWebEngineSettings
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QLineEdit, QHBoxLayout,
                             QTextEdit, QPushButton, QTableWidget, QTableWidgetItem,
                             QHeaderView, QMessageBox, QMenu, QStatusBar, QLabel,
                             QFormLayout, QCheckBox, QSplitter, QListWidget,
                             QListWidgetItem, QTreeWidget, QTreeWidgetItem, QFrame,
                             QFileDialog, QToolBar, QAction, QSizePolicy,QScrollArea, QGraphicsDropShadowEffect)
from PyQt5.QtGui import QDesktopServices, QFont, QTextCursor, QColor, QCursor, QPixmap, QIcon

class ClickableLabel(QLabel):
    clicked = pyqtSignal(str)

    def __init__(self, text, tag, parent=None):
        super().__init__(text, parent)
        self.tag = tag
        self.setCursor(QCursor(Qt.PointingHandCursor))

    def mousePressEvent(self, event):
        self.clicked.emit(self.tag)

from core import config_manager
from core.utils import get_screen_geometry, center_window, resource_path
import qtawesome as qta
import os
import json

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
        self.resize(600, 300); center_window(self); layout = QVBoxLayout(); layout.setContentsMargins(5, 5, 5, 5)
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
    add_chapter_requested = pyqtSignal()
    navigation_requested = pyqtSignal(str)
    refresh_requested = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.current_zoom_factor = 1.0
        self.parent_moc_id = None
        self.current_doc_id = None # 현재 문서 ID 저장
        self.initUI()

    def initUI(self):
        self.setWindowTitle('메모 보기')
        screen_geometry = get_screen_geometry()
        self.resize(int(screen_geometry.width() * 0.4), int(screen_geometry.height() * 0.7))
        center_window(self)
        self.setStyleSheet("background-color: #ffffff;")
        
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.content_display = CustomWebEngineView()
        self.page = LinkHandlingPage(self)
        self.content_display.setPage(self.page)
        self.page.linkClicked.connect(self.link_activated)
        self.content_display.tags_edit_requested.connect(self.tags_edit_requested.emit)
        
        # 더블클릭으로 편집 모드 전환
        self.content_display.mouseDoubleClickEvent = self.on_content_double_click


        self.toolbar = QToolBar("Main Toolbar")
        self.toolbar.setObjectName("RichViewToolbar")
        self.toolbar.setIconSize(QSize(22, 22))

        icon_color = '#495057'
        

        self.edit_action = QAction(qta.icon('fa5s.pencil-alt', color=icon_color), "편집", self)
        self.edit_action.setToolTip("이 메모를 편집합니다. (Ctrl+E, F2, 더블클릭)")
        self.edit_action.triggered.connect(self.edit_requested.emit)
        self.toolbar.addAction(self.edit_action)

        refresh_action = QAction(qta.icon('fa5s.sync-alt', color=icon_color), "새로고침", self)
        refresh_action.setToolTip("현재 메모를 새로고침합니다.")
        refresh_action.triggered.connect(self.on_refresh_triggered)
        self.toolbar.addAction(refresh_action)

        self.add_chapter_action = QAction(qta.icon('fa5s.plus-circle', color=icon_color), "회차 추가", self)
        self.add_chapter_action.setToolTip("이 시리즈에 새로운 회차 메모를 추가합니다.")
        self.add_chapter_action.triggered.connect(self.add_chapter_requested.emit)
        self.add_chapter_action.setVisible(False) # ★★★ 기본적으로는 숨겨 둠 ★★★
        self.toolbar.addAction(self.add_chapter_action)

        self.gdocs_action = QAction(qta.icon('fa5b.google-drive', color=icon_color), "Google Docs에서 열기", self)

        self.gdocs_action = QAction(qta.icon('fa5b.google-drive', color=icon_color), "Google Docs에서 열기", self)
        self.gdocs_action.setToolTip("웹 브라우저에서 Google Docs로 엽니다.")
        self.gdocs_action.triggered.connect(self.open_in_gdocs_requested.emit)
        self.toolbar.addAction(self.gdocs_action)
        
        self.toolbar.addSeparator()

        self.prev_chapter_action = QAction(qta.icon('fa5s.arrow-left', color=icon_color), "이전 회차", self)
        self.prev_chapter_action.triggered.connect(lambda: self.navigation_requested.emit(self.prev_chapter_id))
        self.prev_chapter_action.setVisible(False)
        self.toolbar.addAction(self.prev_chapter_action)

        self.moc_action = QAction(qta.icon('fa5s.list-ul', color=icon_color), "목차로", self)
        self.moc_action.triggered.connect(lambda: self.navigation_requested.emit(self.parent_moc_id))
        self.moc_action.setVisible(False)
        self.toolbar.addAction(self.moc_action)

        self.next_chapter_action = QAction(qta.icon('fa5s.arrow-right', color=icon_color), "다음 회차", self)
        self.next_chapter_action.triggered.connect(lambda: self.navigation_requested.emit(self.next_chapter_id))
        self.next_chapter_action.setVisible(False)
        self.toolbar.addAction(self.next_chapter_action)

        find_button = QPushButton(qta.icon('fa5s.search', color=icon_color), "")
        find_button.setToolTip("내용에서 텍스트를 검색합니다.")
        find_button.setCheckable(True)
        find_button.toggled.connect(self.toggle_find_box)
        self.toolbar.addWidget(find_button)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.toolbar.addWidget(spacer)

        zoom_out_action = QAction(qta.icon('fa5s.search-minus', color=icon_color), "축소", self)
        zoom_out_action.setToolTip("본문 축소")
        zoom_out_action.triggered.connect(self.zoom_out)
        self.toolbar.addAction(zoom_out_action)

        self.zoom_label = QLabel(f"{int(self.current_zoom_factor * 100)}%")
        self.zoom_label.setStyleSheet("padding: 0 8px; color: #333;")
        self.toolbar.addWidget(self.zoom_label)

        zoom_in_action = QAction(qta.icon('fa5s.search-plus', color=icon_color), "확대", self)
        zoom_in_action.setToolTip("본문 확대")
        zoom_in_action.triggered.connect(self.zoom_in)
        self.toolbar.addAction(zoom_in_action)

        self.fav_action = QAction(qta.icon('fa5s.star', color='#666'), "즐겨찾기", self)
        self.fav_action.setCheckable(True) # 토글 버튼으로 만듬
        self.fav_action.triggered.connect(self.favorite_toggled.emit)
        self.toolbar.addAction(self.fav_action)

        toolbar_area = QFrame()
        toolbar_area.setObjectName("ToolbarArea")
        toolbar_area.setAutoFillBackground(True)
        toolbar_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        toolbar_layout = QVBoxLayout()
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_layout.setSpacing(0)
        
        toolbar_layout.addWidget(self.toolbar)

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

    def set_view_mode(self, is_moc, is_chapter, parent_moc_info, prev_chapter_id, next_chapter_id):
        # 1. MOC 자체에서만 '회차 추가' 버튼 보이기
        self.add_chapter_action.setVisible(is_moc)

        # 2. 회차 문서라면, 이전/목차/다음 버튼을 "무조건" 보이게 처리
        self.moc_action.setVisible(is_chapter)
        self.prev_chapter_action.setVisible(is_chapter)
        self.next_chapter_action.setVisible(is_chapter)

        # 3. 실제 정보가 있을 때만 버튼을 "활성화"
        self.moc_action.setEnabled(bool(parent_moc_info))
        self.prev_chapter_action.setEnabled(bool(prev_chapter_id))
        self.next_chapter_action.setEnabled(bool(next_chapter_id))

        # 4. 컨트롤러로부터 받은 ID 정보 저장
        self.parent_moc_id = parent_moc_info['doc_id'] if parent_moc_info else None
        self.prev_chapter_id = prev_chapter_id
        self.next_chapter_id = next_chapter_id
        
        # 5. 툴바 강제 업데이트
        self.toolbar.update()
        self.toolbar.repaint()

    def _update_view_mode_from_stored_info(self):
        """저장된 정보를 사용하여 뷰 모드를 업데이트합니다."""
        print(f"DEBUG: _update_view_mode_from_stored_info 호출됨")
        print(f"DEBUG: parent_moc_id = {self.parent_moc_id}")
        print(f"DEBUG: prev_chapter_id = {self.prev_chapter_id}")
        print(f"DEBUG: next_chapter_id = {self.next_chapter_id}")
        
        # 현재 문서가 시리즈 문서인지 확인 (parent_moc_id가 있으면 시리즈 문서)
        is_chapter = bool(self.parent_moc_id)
        print(f"DEBUG: is_chapter = {is_chapter}")
        
        # 시리즈 문서라면 네비게이션 버튼들을 보이게 설정
        if is_chapter:
            print("DEBUG: 시리즈 문서로 인식, 네비게이션 버튼들 표시")
            self.moc_action.setVisible(True)
            self.prev_chapter_action.setVisible(True)
            self.next_chapter_action.setVisible(True)
            
            # 버튼 활성화 상태 설정
            self.moc_action.setEnabled(bool(self.parent_moc_id))
            self.prev_chapter_action.setEnabled(bool(self.prev_chapter_id))
            self.next_chapter_action.setEnabled(bool(self.next_chapter_id))
        else:
            print("DEBUG: 일반 문서로 인식, 네비게이션 버튼들 숨김")
            # 시리즈 문서가 아니라면 네비게이션 버튼들을 숨김
            self.moc_action.setVisible(False)
            self.prev_chapter_action.setVisible(False)
            self.next_chapter_action.setVisible(False)
        
        # MOC 문서인지 확인 (시리즈 문서가 아니면 MOC로 가정)
        # 시리즈 문서가 아닌 경우, MOC 문서일 가능성이 높으므로 회차 추가 버튼 표시
        if not is_chapter:
            print('DEBUG: 시리즈 문서가 아니므로 MOC로 가정, 회차 추가 버튼 표시')
            self.add_chapter_action.setVisible(True)
        else:
            print('DEBUG: 시리즈 문서이므로 회차 추가 버튼 숨김')
            self.add_chapter_action.setVisible(False)
        
        # 툴바 강제 업데이트
        self.toolbar.update()
        self.toolbar.repaint()
        print("DEBUG: 뷰 모드 업데이트 완료")

    def set_content(self, doc_id, title, html_content, view_mode_info):
        # view_mode_info가 제공된 경우 set_view_mode 호출
        if view_mode_info:
            self.set_view_mode(**view_mode_info)
        else:
            # view_mode_info가 없는 경우 (캐시된 문서 등), 기존 저장된 정보로 뷰 모드 업데이트
            self._update_view_mode_from_stored_info()
        
        self.current_doc_id = doc_id # 현재 문서 ID 저장
        self.setWindowTitle(title)
        base_url = QUrl.fromLocalFile(os.path.abspath(os.getcwd()).replace('\\', '/') + '/')
        self.content_display.setHtml(html_content, base_url)
        self.content_display.setZoomFactor(self.current_zoom_factor)
        
        # 히스토리 버튼 상태 업데이트
        self.show()
        self.activateWindow()
        self.raise_()

    def on_refresh_triggered(self):
        if self.current_doc_id:
            self.refresh_requested.emit(self.current_doc_id)
    
    def on_content_double_click(self, event):
        # 더블클릭 시 편집 모드로 전환
        self.edit_requested.emit()
        super().mouseDoubleClickEvent(event)

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

    def keyPressEvent(self, event):
        # Ctrl+E 또는 F2 키로 편집 모드 전환
        if (event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_E) or event.key() == Qt.Key_F2:
            self.edit_requested.emit()
        else:
            super().keyPressEvent(event)
    
    def closeEvent(self, event):
        self.hide()

class MarkdownEditorWindow(QWidget):
    view_requested = pyqtSignal(str)  # 편집 모드에서 보기 모드로 전환 요청
    
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
        self.setWindowTitle('새 메모 작성')
        screen_geometry = get_screen_geometry()
        self.resize(int(screen_geometry.width() * 0.6), int(screen_geometry.height() * 0.8))
        center_window(self)
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
        
        self.view_button = QPushButton(' 보기')
        self.view_button.setIcon(qta.icon('fa5s.eye', color='white'))
        self.view_button.setToolTip("보기 모드로 전환 (Ctrl+E, F2)")
        self.view_button.clicked.connect(self.on_view_button_clicked)
        
        top_layout.addWidget(self.title_input)
        top_layout.addWidget(self.add_image_button)
        top_layout.addWidget(self.add_file_button)
        top_layout.addWidget(self.view_button)
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

    def on_view_button_clicked(self):
        # 보기 버튼 클릭 시 보기 모드로 전환
        if self.current_doc_id:
            self.view_requested.emit(self.current_doc_id)
    
    def keyPressEvent(self, event):
        # Ctrl+E 또는 F2 키로 보기 모드로 전환
        if (event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_E) or event.key() == Qt.Key_F2:
            # 현재 편집 중인 문서를 보기 모드로 전환
            if self.current_doc_id:
                self.view_requested.emit(self.current_doc_id)
        else:
            super().keyPressEvent(event)
    
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

class KnowledgeGraphWindow(QWidget):
    node_clicked = pyqtSignal(str)
    tag_clicked = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("지식 그래프 뷰")
        self.setGeometry(300, 300, 1000, 700)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.webview = QWebEngineView()
        layout.addWidget(self.webview)

        # WebChannel 설정
        self.channel = QWebChannel()
        self.bridge = GraphSignalBridge()
        self.bridge.node_clicked.connect(self.node_clicked.emit)
        self.channel.registerObject("qt_bridge", self.bridge)
        self.webview.page().setWebChannel(self.channel)

        # 범례(Legend) 위젯 추가
        self.legend_scroll_area = QScrollArea(self)
        self.legend_scroll_area.setWidgetResizable(True)
        self.legend_scroll_area.setFixedWidth(200)
        self.legend_scroll_area.setFixedHeight(300)
        self.legend_scroll_area.move(10, 10)
        self.legend_scroll_area.setStyleSheet(
            """
            QScrollArea {
                background-color: rgba(255, 255, 255, 0.8);
                border-radius: 5px;
                border: 1px solid #e0e0e0;
            }
        """)
        self.legend_widget = QWidget()
        self.legend_layout = QVBoxLayout(self.legend_widget)
        self.legend_layout.setAlignment(Qt.AlignTop)
        self.legend_layout.setContentsMargins(10, 10, 10, 10)
        self.legend_scroll_area.setWidget(self.legend_widget)

        self.tag_clicked.connect(self.on_tag_clicked)

    @pyqtSlot(str)
    def on_tag_clicked(self, tag_name):
        # JavaScript 문자열로 안전하게 전달하기 위해 작은따옴표를 이스케이프
        safe_tag_name = tag_name.replace("'", "'\'")
        self.webview.page().runJavaScript(f"highlightNodesByTag('{safe_tag_name}');")

    def on_reset_highlight_clicked(self):
        self.webview.page().runJavaScript("resetHighlight();")

    def show_graph(self, graph_data, tag_info):
        # 범례 업데이트
        while self.legend_layout.count():
            child = self.legend_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
            elif child.layout():
                # 레이아웃 안의 위젯들도 재귀적으로 삭제
                while child.layout().count():
                    sub_child = child.layout().takeAt(0)
                    if sub_child.widget():
                        sub_child.widget().deleteLater()


        # 강조 해제 버튼 추가
        reset_button = QPushButton("전체 보기")
        reset_button.setStyleSheet("background-color: #f0f0f0; border: 1px solid #ccc; padding: 4px; margin-bottom: 5px;")
        reset_button.setCursor(QCursor(Qt.PointingHandCursor))
        reset_button.clicked.connect(self.on_reset_highlight_clicked)
        self.legend_layout.addWidget(reset_button)

        # 태그 버튼들 추가 (count 기준으로 정렬)
        sorted_tags = sorted(tag_info.items(), key=lambda item: item[1]['count'], reverse=True)

        for tag, info in sorted_tags:
            color_box = QLabel()
            color_box.setFixedSize(12, 12)
            color_box.setStyleSheet(f"background-color: {info['color']}; border-radius: 6px;")
            
            tag_button = QPushButton(f"{tag} ({info['count']})")
            tag_button.setCursor(QCursor(Qt.PointingHandCursor))
            tag_button.setStyleSheet(f"background-color: transparent; border: none; text-align: left; padding: 2px; color: {info['color']};")
            tag_button.clicked.connect(lambda checked, t=tag: self.tag_clicked.emit(t))

            h_layout = QHBoxLayout()
            h_layout.addWidget(color_box)
            h_layout.addWidget(tag_button)
            h_layout.addStretch()
            self.legend_layout.addLayout(h_layout)

        # 그래프 표시
        html_template_path = resource_path("resources/graph_template.html")
        try:
            with open(html_template_path, 'r', encoding='utf-8') as f:
                html_content = f.read()
        except FileNotFoundError:
            self.webview.setHtml("<h1>Error: graph_template.html not found</h1>")
            return

        base_url = QUrl.fromLocalFile(resource_path("").replace('\\', '/') + '/')
        self.webview.setHtml(html_content, baseUrl=base_url)

        graph_data_json = json.dumps(graph_data)

        # loadFinished 시그널이 여러번 연결되는 것을 방지
        try:
            self.webview.loadFinished.disconnect()
        except TypeError:
            pass # 연결이 안되어있을 때 오류 방지
        self.webview.loadFinished.connect(
            lambda: self.webview.page().runJavaScript(f"drawGraph({graph_data_json})")
        )

class GraphSignalBridge(QObject):
    node_clicked = pyqtSignal(str)

    @pyqtSlot(str)
    def on_node_clicked(self, node_id):
        self.node_clicked.emit(node_id)


class MemoListWindow(QWidget):
    navigation_selected = pyqtSignal(str);
    context_menu_requested = pyqtSignal(object);
    favorite_toggled_from_list = pyqtSignal(str);
    graph_view_requested = pyqtSignal();
    memo_selected = pyqtSignal(str);

    def __init__(self):
        super().__init__();
        self.window_name = "MemoListWindow"
        self.initUI()

    def initUI(self):
        # ===================================================================
        # 윈도우 기본 설정
        # ===================================================================
        self.setWindowTitle('메모 목록')
        screen_geometry = get_screen_geometry()
        self.resize(int(screen_geometry.width() * 0.5), int(screen_geometry.height() * 0.6))
        center_window(self)
        
        # 윈도우 스타일 설정
        self.setStyleSheet("""
            QWidget {
                background-color: #ffffff;
                color: #212529;
            }
        """)

        # ===================================================================
        # 패널 및 레이아웃 생성
        # ===================================================================
        # --- 전체를 감싸는 메인 레이아웃 ---
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        # --- 좌/우 분할을 위한 스플리터 ---
        splitter = QSplitter(Qt.Horizontal)
        splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #e9ecef;
                width: 1px;
            }
            QSplitter::handle:hover {
                background-color: #ced4da;
            }
        """)

        # --- 왼쪽 패널 (네비게이션 트리용) ---
        left_panel = QFrame()
        left_panel.setObjectName("LeftPanel")
        left_panel.setStyleSheet("""
            #LeftPanel {
                background-color: #fafbfc;
                border: 1px solid #e9ecef;
                border-radius: 6px;
            }
        """)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.setSpacing(4)

        # --- 오른쪽 패널 (메인 콘텐츠용) ---
        right_panel = QFrame()
        right_panel.setObjectName("RightPanel")
        right_panel.setStyleSheet("""
            #RightPanel {
                background-color: #ffffff;
                border: 1px solid #e9ecef;
                border-radius: 6px;
            }
        """)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(12, 12, 12, 12)
        right_layout.setSpacing(8)

        # ===================================================================
        # 왼쪽 패널 위젯 설정
        # ===================================================================
        # 네비게이션 트리 제목
        nav_title = QLabel("카테고리")
        nav_title.setStyleSheet("""
            QLabel {
                font-weight: 600;
                font-size: 11pt;
                color: #495057;
                padding: 4px 0px;
                background: transparent;
                border: none;
            }
        """)
        left_layout.addWidget(nav_title)
        
        self.nav_tree = QTreeWidget()
        self.nav_tree.setHeaderHidden(True)
        self.nav_tree.setStyleSheet("""
            QTreeWidget {
                background-color: transparent;
                border: none;
                font-size: 10pt;
            }
            QTreeWidget::item {
                padding: 6px 4px;
                border-radius: 4px;
                margin: 1px 0px;
            }
            QTreeWidget::item:selected {
                background-color: #e3f2fd;
                color: #1976d2;
            }
            QTreeWidget::item:hover {
                background-color: #f5f5f5;
            }
            /* 스크롤바 스타일링 */
            QScrollBar:vertical {
                background-color: #f8f9fa;
                width: 12px;
                border: none;
                border-radius: 6px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background-color: #dee2e6;
                border-radius: 6px;
                min-height: 20px;
                margin: 2px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #ced4da;
            }
            QScrollBar::handle:vertical:pressed {
                background-color: #adb5bd;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
                background: none;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }
        """)
        left_layout.addWidget(self.nav_tree)

        # ===================================================================
        # 오른쪽 패널 위젯 설정
        # ===================================================================
        # --- 1. 검색 바 ---
        search_container = QFrame()
        search_container.setObjectName("SearchContainer")
        search_container.setStyleSheet("""
            #SearchContainer {
                background-color: #f8f9fa;
                border: 1px solid #e9ecef;
                border-radius: 6px;
                padding: 8px;
            }
        """)
        search_layout = QHBoxLayout(search_container)
        search_layout.setContentsMargins(8, 8, 8, 8)
        search_layout.setSpacing(8)
        
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("메모 검색...")
        self.search_bar.setStyleSheet("""
            QLineEdit {
                background-color: #ffffff;
                border: 1px solid #e9ecef;
                border-radius: 6px;
                padding: 10px 12px;
                font-size: 10pt;
            }
            QLineEdit:focus {
                border: 2px solid #1976d2;
                background-color: #fafbfc;
            }
        """)
        
        self.full_text_search_check = QCheckBox("본문 포함")
        self.full_text_search_check.setStyleSheet("""
            QCheckBox {
                font-size: 10pt;
                color: #495057;
                spacing: 6px;
            }
        """)

        self.graph_button = QPushButton(qta.icon('fa5s.project-diagram', color='#495057'), "")
        self.graph_button.setObjectName("PagingButton")
        self.graph_button.setToolTip("지식 그래프 뷰 열기")
        self.graph_button.clicked.connect(self.graph_view_requested.emit)

        self.refresh_button = QPushButton(qta.icon('fa5s.sync-alt', color='#495057'), "")
        self.refresh_button.setObjectName("PagingButton")
        self.refresh_button.setToolTip("목록 새로고침")

        search_layout.addWidget(self.search_bar)
        search_layout.addWidget(self.full_text_search_check)
        search_layout.addWidget(self.graph_button)
        search_layout.addWidget(self.refresh_button)
        right_layout.addWidget(search_container)

        # --- 2. 상태 바 (검색창과 테이블 사이) ---
        self.statusBar = QStatusBar()
        self.statusBar.setStyleSheet("""
            QStatusBar {
                background-color: #f8f9fa;
                border: 1px solid #e9ecef;
                border-radius: 6px;
                color: #6c757d;
                font-size: 9pt;
                padding: 8px 12px;
                margin: 4px 0px;
                min-height: 24px;
                max-height: 24px;
            }
        """)
        right_layout.addWidget(self.statusBar)

        # --- 3. 데이터 테이블 (트리 구조 지원) ---
        table_container = QFrame()
        table_container.setObjectName("TableContainer")
        table_container.setStyleSheet("""
            #TableContainer {
                background-color: #ffffff;
                border: 1px solid #e9ecef;
                border-radius: 6px;
                padding: 4px;
            }
        """)
        table_layout = QVBoxLayout(table_container)
        table_layout.setContentsMargins(0, 0, 0, 0)
        
        self.table = QTreeWidget()
        self.table.setColumnCount(4)
        self.table.setHeaderLabels(['', '제목', '태그', '날짜'])  # 태그와 날짜 순서 변경
        self.table.setColumnWidth(0, 50)  # 즐겨찾기 컬럼 초기 너비 (더 작게)
        self.table.setColumnWidth(2, 100)  # 태그 컬럼 초기 너비 (최소한으로)
        self.table.setColumnWidth(3, 150)  # 날짜 컬럼 초기 너비 (최소한으로)
        self.table.header().setSectionResizeMode(0, QHeaderView.Fixed) # 즐겨찾기 열 고정
        self.table.header().setSectionResizeMode(1, QHeaderView.Stretch) # 제목 열 너비 확장 (가장 넓게)
        # self.table.header().setSectionResizeMode(2, QHeaderView.Fixed) # 태그 열 완전 고정
        # self.table.header().setSectionResizeMode(3, QHeaderView.Fixed) # 날짜 열 완전 고정
        self.table.header().setStretchLastSection(False)  # 마지막 섹션 자동 확장 비활성화
        self.table.setRootIsDecorated(True) # 루트 아이템에 화살표 표시
        self.table.setAlternatingRowColors(True) # 번갈아가며 색상 표시
        self.table.setStyleSheet("""
            QTreeWidget {
                background-color: transparent;
                border: none;
                font-size: 10pt;
            }
            QTreeWidget::item {
                padding: 8px 4px;
                border-bottom: 1px solid #f1f3f5;
            }
            QTreeWidget::item:selected {
                background-color: #e3f2fd;
                color: #1976d2;
            }
            QTreeWidget::item:hover {
                background-color: #f5f5f5;
            }
            /* 스크롤바 스타일링 */
            QScrollBar:vertical {
                background-color: #f8f9fa;
                width: 12px;
                border: none;
                border-radius: 6px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background-color: #dee2e6;
                border-radius: 6px;
                min-height: 20px;
                margin: 2px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #ced4da;
            }
            QScrollBar::handle:vertical:pressed {
                background-color: #adb5bd;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
                background: none;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }
            QScrollBar:horizontal {
                background-color: #f8f9fa;
                height: 12px;
                border: none;
                border-radius: 6px;
                margin: 0px;
            }
            QScrollBar::handle:horizontal {
                background-color: #dee2e6;
                border-radius: 6px;
                min-width: 20px;
                margin: 2px;
            }
            QScrollBar::handle:horizontal:hover {
                background-color: #ced4da;
            }
            QScrollBar::handle:horizontal:pressed {
                background-color: #adb5bd;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0px;
                background: none;
            }
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
                background: none;
            }
        """)
        table_layout.addWidget(self.table)
        right_layout.addWidget(table_container)

        # --- 4. 페이징 컨트롤 ---
        paging_container = QFrame()
        paging_container.setObjectName("PagingContainer")
        paging_container.setStyleSheet("""
            #PagingContainer {
                background-color: #f8f9fa;
                border: 1px solid #e9ecef;
                border-radius: 6px;
                padding: 8px;
            }
        """)
        paging_layout = QHBoxLayout(paging_container)
        paging_layout.setContentsMargins(8, 8, 8, 8)
        paging_layout.setSpacing(8)
        
        self.prev_button = QPushButton(qta.icon('fa5s.chevron-left', color='#495057'), "")
        self.prev_button.setObjectName("PagingButton")
        self.prev_button.setToolTip("이전 페이지")
        
        self.page_label = QLabel("1 페이지")
        self.page_label.setAlignment(Qt.AlignCenter)
        self.page_label.setStyleSheet("""
            QLabel {
                font-weight: 600;
                color: #495057;
                background: transparent;
                border: none;
            }
        """)
        
        self.next_button = QPushButton(qta.icon('fa5s.chevron-right', color='#495057'), "")
        self.next_button.setObjectName("PagingButton")
        self.next_button.setToolTip("다음 페이지")

        paging_layout.addWidget(self.prev_button)
        paging_layout.addWidget(self.page_label)
        paging_layout.addWidget(self.next_button)
        right_layout.addWidget(paging_container)

        # ===================================================================
        # 스플리터 및 메인 레이아웃에 위젯 배치
        # ===================================================================
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([200, 600]) # 초기 분할 크기 설정 (왼쪽 패널을 약간 넓게)
        main_layout.addWidget(splitter)

        # ===================================================================
        # 시그널(Signal) / 슬롯(Slot) 연결
        # ===================================================================
        self.nav_tree.currentItemChanged.connect(self.on_nav_selected)
        self.table.itemClicked.connect(self.on_item_clicked)
        self.table.itemDoubleClicked.connect(self.on_item_double_clicked)
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
        favorites_item.setFont(0, QFont("Segoe UI", 10, QFont.Bold))

        # 전체 메모 카운트
        all_memos_count = len(local_cache)
        all_memos_item = QTreeWidgetItem(self.nav_tree)
        all_memos_item.setText(0, f"전체 메모 ({all_memos_count})")
        all_memos_item.setIcon(0, qta.icon('fa5s.inbox', color='#495057'))
        all_memos_item.setFont(0, QFont("Segoe UI", 10, QFont.Bold))

        # --- 구분선 아이템 추가 ---
        separator = QTreeWidgetItem(self.nav_tree)
        separator.setText(0, "──────────")
        separator.setFlags(separator.flags() & ~Qt.ItemIsSelectable) # 선택 불가능하게 설정

        if all_tags:
            tags_root_item = QTreeWidgetItem(self.nav_tree)
            tags_root_item.setText(0, f"태그 ({len(all_tags)})")
            tags_root_item.setIcon(0, qta.icon('fa5s.tags', color='#495057'))
            tags_root_item.setFont(0, QFont("Segoe UI", 10, QFont.Bold))
            
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
                tag_item.setFont(0, QFont("Segoe UI", 9))
                # 하위 태그 아이콘 제거 (아이콘 설정하지 않음)
            tags_root_item.setExpanded(True)
            
        # 기본 선택은 하지 않음 (show_memo_list_window에서 처리)
        self.nav_tree.blockSignals(False)

    def populate_table(self, data, is_local, series_cache=None):
        # 페이징 버튼은 항상 표시 (로컬 캐시와 API 검색 모두 지원)
        self.prev_button.setVisible(True)
        self.next_button.setVisible(True)
        self.page_label.setVisible(True)
        
        self.table.clear()
        
        favorites = config_manager.get_favorites()
        
        # 시리즈 캐시가 제공된 경우 사용, 없으면 빈 딕셔너리
        if series_cache is None:
            series_cache = {}
        
        # MOC 문서들과 일반 문서들을 분리
        moc_docs = []
        regular_docs = []
        
        for row in data:
            title = row[0] if len(row) > 0 else ""
            date = row[1] if len(row) > 1 else ""
            doc_id = row[2] if len(row) > 2 else ""
            tags = row[3] if len(row) > 3 else ""
            
            # MOC 문서인지 확인
            if tags and '#moc' in tags.lower():
                moc_docs.append(row)
            else:
                regular_docs.append(row)
        
        # MOC 문서들을 먼저 추가하고 하위 회차들을 연결
        for moc_row in moc_docs:
            title = moc_row[0] if len(moc_row) > 0 else ""
            date = moc_row[1] if len(moc_row) > 1 else ""
            doc_id = moc_row[2] if len(moc_row) > 2 else ""
            tags = moc_row[3] if len(moc_row) > 3 else ""
            
            # MOC 아이템 생성
            moc_item = QTreeWidgetItem()
            moc_item.setText(1, f"📚 {title}")  # MOC 아이콘 추가
            moc_item.setText(2, tags)  # 태그 (2번 컬럼)
            moc_item.setText(3, date)  # 날짜 (3번 컬럼)
            moc_item.setData(0, Qt.UserRole, doc_id)
            moc_item.setData(1, Qt.UserRole, doc_id)
            moc_item.setData(2, Qt.UserRole, doc_id)
            moc_item.setData(3, Qt.UserRole, doc_id)
            
            # 컬럼 정렬 설정
            moc_item.setTextAlignment(2, Qt.AlignRight | Qt.AlignVCenter)  # 태그 오른쪽 정렬
            moc_item.setTextAlignment(3, Qt.AlignRight | Qt.AlignVCenter)  # 날짜 오른쪽 정렬
            
            # 즐겨찾기 아이콘 설정
            is_favorite = doc_id in favorites
            icon = qta.icon('fa5s.star', color='#f0c420') if is_favorite else qta.icon('fa5s.star', color='#ced4da')
            moc_item.setIcon(0, icon)
            
            # MOC 아이템 스타일 설정
            moc_item.setFont(1, QFont("Segoe UI", 10, QFont.Bold))  # 제목을 굵게
            
            # MOC 아이템을 트리에 추가
            self.table.addTopLevelItem(moc_item)
            
            # 시리즈 캐시에서 이 MOC의 회차들을 찾아서 하위 아이템으로 추가
            for chapter_doc_id, chapter_info in series_cache.items():
                if chapter_info.get('parent_moc_id') == doc_id:
                    # 해당 회차의 정보를 regular_docs에서 찾기
                    chapter_row = None
                    for row in regular_docs:
                        if len(row) > 2 and row[2] == chapter_doc_id:
                            chapter_row = row
                            break
                    
                    if chapter_row:
                        chapter_title = chapter_row[0] if len(chapter_row) > 0 else ""
                        chapter_date = chapter_row[1] if len(chapter_row) > 1 else ""
                        chapter_tags = chapter_row[3] if len(chapter_row) > 3 else ""
                        
                        # 회차 아이템 생성
                        chapter_item = QTreeWidgetItem()
                        chapter_item.setText(1, f"  📄 {chapter_title}")  # 회차 아이콘과 들여쓰기
                        chapter_item.setText(2, chapter_tags)  # 태그 (2번 컬럼)
                        chapter_item.setText(3, chapter_date)  # 날짜 (3번 컬럼)
                        chapter_item.setData(0, Qt.UserRole, chapter_doc_id)
                        chapter_item.setData(1, Qt.UserRole, chapter_doc_id)
                        chapter_item.setData(2, Qt.UserRole, chapter_doc_id)
                        chapter_item.setData(3, Qt.UserRole, chapter_doc_id)
                        
                        # 컬럼 정렬 설정
                        chapter_item.setTextAlignment(2, Qt.AlignRight | Qt.AlignVCenter)  # 태그 오른쪽 정렬
                        chapter_item.setTextAlignment(3, Qt.AlignRight | Qt.AlignVCenter)  # 날짜 오른쪽 정렬
                        
                        # 회차 즐겨찾기 아이콘
                        is_chapter_favorite = chapter_doc_id in favorites
                        chapter_icon = qta.icon('fa5s.star', color='#f0c420') if is_chapter_favorite else qta.icon('fa5s.star', color='#ced4da')
                        chapter_item.setIcon(0, chapter_icon)
                        
                        # 회차 아이템 스타일 설정
                        chapter_item.setFont(1, QFont("Segoe UI", 9))  # 회차는 일반 폰트
                        
                        moc_item.addChild(chapter_item)
        
        # 시리즈에 속하지 않은 일반 문서들 추가
        for row in regular_docs:
            doc_id = row[2] if len(row) > 2 else ""
            
            # 이미 시리즈에 포함된 문서인지 확인
            is_chapter = any(chapter_info.get('parent_moc_id') for chapter_info in series_cache.values() if chapter_info.get('parent_moc_id'))
            is_chapter = is_chapter and doc_id in series_cache
            
            if not is_chapter:
                title = row[0] if len(row) > 0 else ""
                date = row[1] if len(row) > 1 else ""
                tags = row[3] if len(row) > 3 else ""
                
                # 일반 문서 아이템 생성
                doc_item = QTreeWidgetItem()
                doc_item.setText(1, f"📄 {title}")
                doc_item.setText(2, tags)  # 태그 (2번 컬럼)
                doc_item.setText(3, date)  # 날짜 (3번 컬럼)
                doc_item.setData(0, Qt.UserRole, doc_id)
                doc_item.setData(1, Qt.UserRole, doc_id)
                doc_item.setData(2, Qt.UserRole, doc_id)
                doc_item.setData(3, Qt.UserRole, doc_id)
                
                # 컬럼 정렬 설정
                doc_item.setTextAlignment(2, Qt.AlignRight | Qt.AlignVCenter)  # 태그 오른쪽 정렬
                doc_item.setTextAlignment(3, Qt.AlignRight | Qt.AlignVCenter)  # 날짜 오른쪽 정렬
                
                # 즐겨찾기 아이콘
                is_favorite = doc_id in favorites
                icon = qta.icon('fa5s.star', color='#f0c420') if is_favorite else qta.icon('fa5s.star', color='#ced4da')
                doc_item.setIcon(0, icon)
                
                # 일반 문서 아이템 스타일 설정
                doc_item.setFont(1, QFont("Segoe UI", 10))  # 일반 폰트
                
                self.table.addTopLevelItem(doc_item)
    
    def update_paging_buttons(self, prev_enabled, next_enabled, page_num):
        self.prev_button.setEnabled(prev_enabled); self.next_button.setEnabled(next_enabled); self.page_label.setText(f"{page_num} 페이지")
    
    def show_status_message(self, message, message_type="info"):
        """상태 표시바에 메시지를 표시합니다.
        
        Args:
            message (str): 표시할 메시지
            message_type (str): 메시지 타입 ("info", "success", "warning", "error")
        """
        # 메시지 타입에 따른 아이콘과 색상 설정
        if message_type == "success":
            icon = qta.icon('fa5s.check-circle', color='#28a745')
            color = "#28a745"
        elif message_type == "warning":
            icon = qta.icon('fa5s.exclamation-triangle', color='#ffc107')
            color = "#ffc107"
        elif message_type == "error":
            icon = qta.icon('fa5s.times-circle', color='#dc3545')
            color = "#dc3545"
        else:  # info
            icon = qta.icon('fa5s.info-circle', color='#17a2b8')
            color = "#17a2b8"
        
        # 상태 표시바에 아이콘과 메시지 표시
        self.statusBar.showMessage(f"  {message}")
        
        # 아이콘을 상태 표시바에 추가 (임시로 텍스트로 표시)
        self.statusBar.setStyleSheet(f"""
            QStatusBar {{
                background-color: #f8f9fa;
                border: 1px solid #e9ecef;
                border-radius: 6px;
                color: {color};
                font-size: 9pt;
                padding: 8px 12px;
                margin: 4px 0px;
                min-height: 24px;
                max-height: 24px;
                font-weight: 500;
            }}
        """)
        
        # 3초 후 기본 스타일로 복원
        QTimer.singleShot(3000, self.reset_status_style)
    
    def reset_status_style(self):
        """상태 표시바 스타일을 기본으로 복원합니다."""
        self.statusBar.setStyleSheet("""
            QStatusBar {
                background-color: #f8f9fa;
                border: 1px solid #e9ecef;
                border-radius: 6px;
                color: #6c757d;
                font-size: 9pt;
                padding: 8px 12px;
                margin: 4px 0px;
                min-height: 24px;
                max-height: 24px;
            }
        """)
    
    def on_item_clicked(self, item, column):
        if column == 0: # 0번 열(즐겨찾기 아이콘)이 클릭되었을 때
            doc_id = item.data(0, Qt.UserRole)
            if doc_id:
                self.favorite_toggled_from_list.emit(doc_id)
        else:
            # 다른 열 클릭 시 - 시리즈 문서인지 확인
            doc_id = item.data(0, Qt.UserRole)
            if doc_id:
                # MOC 문서인지 확인 (📚 아이콘이 있으면 MOC)
                title_text = item.text(1)
                if "📚" in title_text and item.childCount() > 0:
                    # MOC 문서이고 하위 아이템이 있으면 펼치기/접기
                    item.setExpanded(not item.isExpanded())
    
    def on_item_double_clicked(self, item, column):
        # 더블클릭 시 해당 문서 열기
        doc_id = item.data(0, Qt.UserRole)
        if doc_id:
            # 시그널을 통해 컨트롤러에 알림
            self.memo_selected.emit(doc_id)

    def closeEvent(self, event):
        geometry_hex = self.saveGeometry().toHex().data().decode('utf-8')
        config_manager.save_window_state(self.window_name, geometry_hex)
        event.ignore()
        self.hide()

class SettingsWindow(QWidget):
    def __init__(self):
        super().__init__(); self.initUI(); self.load_current_settings()
    def initUI(self):
        self.setWindowTitle('설정');
        self.resize(500, 350)
        center_window(self)
        form_layout = QFormLayout(); form_layout.setSpacing(10)
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

class TodoItemWidget(QFrame):
    toggled = pyqtSignal(bool)
    link_activated = pyqtSignal()

    def __init__(self, text, source_memo, is_checked, deadline, priority, parent=None):
        super().__init__(parent)
        self.setObjectName("TodoItemFrame")
        
        # Main vertical layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 10, 12, 10)
        main_layout.setSpacing(5)

        # --- Line 1: Checkbox and Task Text ---
        line1_layout = QHBoxLayout()
        line1_layout.setContentsMargins(0, 0, 0, 0)
        line1_layout.setSpacing(10)
        
        self.checkbox = QCheckBox()
        self.checkbox.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        
        self.text_label = QLabel(text)
        self.text_label.setWordWrap(True)
        self.text_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.text_label.setFont(QFont("Segoe UI", 10))
        
        line1_layout.addWidget(self.checkbox)
        line1_layout.addWidget(self.text_label)
        main_layout.addLayout(line1_layout)

        # --- Line 2: Metadata (Priority, Deadline) ---
        line2_layout = QHBoxLayout()
        line2_layout.setContentsMargins(32, 0, 0, 0) # Indent to align with text
        line2_layout.setSpacing(10)
        line2_layout.setAlignment(Qt.AlignLeft)

        if priority:
            priority_colors = {1: '#e03131', 2: '#f08c00', 3: '#2f9e44', 4: '#1971c2', 5: '#868e96'}
            color = priority_colors.get(priority, '#868e96')
            priority_icon = QLabel()
            priority_icon.setPixmap(qta.icon('fa5s.flag', color=color).pixmap(QSize(12, 12)))
            priority_label = QLabel(f"P{priority}")
            priority_label.setStyleSheet(f"color: {color}; font-weight: bold; background: transparent;")
            line2_layout.addWidget(priority_icon)
            line2_layout.addWidget(priority_label)

        if deadline:
            is_overdue = False
            try:
                deadline_format = "%Y-%m-%d %H:%M" if ':' in deadline else "%Y-%m-%d"
                deadline_dt = datetime.strptime(deadline, deadline_format)
                if not is_checked and deadline_dt < datetime.now():
                    is_overdue = True
            except (ValueError, TypeError):
                pass
            
            color = "#e03131" if is_overdue else "#495057"
            deadline_icon = QLabel()
            deadline_icon.setPixmap(qta.icon('fa5s.calendar-alt', color=color).pixmap(QSize(12, 12)))
            deadline_label = QLabel(deadline)
            deadline_label.setStyleSheet(f"color: {color}; background: transparent;")
            line2_layout.addWidget(deadline_icon)
            line2_layout.addWidget(deadline_label)

        line2_layout.addStretch()
        main_layout.addLayout(line2_layout)

        # --- Line 3: Source Memo ---
        line3_layout = QHBoxLayout()
        line3_layout.setContentsMargins(32, 0, 0, 0)
        self.source_label = QLabel(f'<a href="#">{source_memo}</a>')
        self.source_label.setStyleSheet("color: #868e96; background: transparent; text-decoration: none;")
        self.source_label.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.source_label.setOpenExternalLinks(False)
        self.source_label.linkActivated.connect(self.on_link_activated)
        line3_layout.addWidget(self.source_label)
        main_layout.addLayout(line3_layout)

        self.checkbox.toggled.connect(self.toggled.emit)
        self.set_checked_state(is_checked)

    def on_link_activated(self, link):
        self.link_activated.emit()

    def set_checked_state(self, is_checked):
        self.checkbox.blockSignals(True)
        self.checkbox.setChecked(is_checked)
        self.checkbox.blockSignals(False)

        font = self.text_label.font()
        font.setStrikeOut(is_checked)
        self.text_label.setFont(font)
        
        if is_checked:
            self.setObjectName("TodoItemFrameChecked")
            self.text_label.setStyleSheet("color: #adb5bd;")
            self.source_label.setStyleSheet("color: #ced4da; background: transparent;")
        else:
            self.setObjectName("TodoItemFrame")
            self.text_label.setStyleSheet("color: #212529;")
            self.source_label.setStyleSheet("color: #868e96; background: transparent;")

        self.setStyleSheet("""
            #TodoItemFrame, #TodoItemFrameChecked {
                background-color: #ffffff;
                border: 1px solid #e9ecef;
                border-radius: 8px;
            }
            #TodoItemFrame:hover {
                background-color: #f8f9fa;
                border: 1px solid #dee2e6;
            }
            #TodoItemFrameChecked {
                background-color: #fcfcfc;
            }
        """)

class TodoDashboardWindow(QWidget):
    task_toggled = pyqtSignal(dict, bool)
    item_clicked = pyqtSignal(str)
    refresh_requested = pyqtSignal()
    completion_filter_changed = pyqtSignal(bool)

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        # self.setAttribute(Qt.WA_TranslucentBackground)
        self.initUI()
        self.offset = None # 창 이동을 위한 변수
        
    def initUI(self):
        self.resize(500, 600)
        center_window(self)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        self.setStyleSheet("""
            background-color: #ffffff;
            border: none;
            border-radius: 10px;
        """)

        # --- 상단 바 (제목 및 닫기 버튼) ---
        top_bar = QFrame() # 드래그 이벤트를 처리할 상단 바 프레임
        top_bar.setObjectName("TopBar")
        top_bar_layout = QHBoxLayout(top_bar)
        top_bar_layout.setContentsMargins(10, 5, 5, 5)
        top_bar_layout.setSpacing(10)
        title_label = QLabel("<b>오늘 할 일</b>")
        title_label.setStyleSheet("font-size: 14pt; color: #212529; background: transparent; border: none;")

        self.show_completed_checkbox = QCheckBox("완료 항목 표시")
        self.show_completed_checkbox.setStyleSheet("color: #495057; spacing: 5px; font-size: 10pt; background: transparent; border: none;")
        self.show_completed_checkbox.toggled.connect(self.completion_filter_changed.emit)

        
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        refresh_button = QPushButton(qta.icon('fa5s.sync-alt', color='#888'), "")
        refresh_button.setFlat(True)
        refresh_button.setStyleSheet("QPushButton { background: transparent; border: none; }")
        refresh_button.setToolTip("목록 새로고침")
        refresh_button.clicked.connect(self.refresh_requested.emit)
        
        close_button = QPushButton(qta.icon('fa5s.times', color='#888'), "")
        close_button.setFlat(True) # 버튼 배경을 투명하게
        close_button.setStyleSheet("QPushButton { background: transparent; border: none; }")
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
        scroll_area.setStyleSheet("""
            QScrollArea { border: none; background: transparent; }
            QScrollBar:vertical {
                border: none;
                background: #f1f1f1;
                width: 8px;
                margin: 0px 0px 0px 0px;
            }
            QScrollBar::handle:vertical {
                background: #c1c1c1;
                min-height: 20px;
                border-radius: 4px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }
        """) 
        
        container = QWidget()
        container.setStyleSheet("background: transparent;")
        self.content_layout = QVBoxLayout(container)
        self.content_layout.setAlignment(Qt.AlignTop)
        self.content_layout.setSpacing(8)
        
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
        label.setStyleSheet("background: transparent;")
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
                widget.link_activated.connect(lambda doc_id=task['doc_id']: self.item_clicked.emit(doc_id))
                self.content_layout.addWidget(widget)

    def on_task_toggled(self, checked):
        sender_widget = self.sender()
        if sender_widget:
            task_info = sender_widget.checkbox.property("task_info")
            if task_info:
                self.task_toggled.emit(task_info, checked)
    
    def on_item_clicked(self, doc_id):
        self.item_clicked.emit(doc_id)

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
        self.resize(380, 150)
        center_window(self)

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
        self.resize(350, 80)
        center_window(self)

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




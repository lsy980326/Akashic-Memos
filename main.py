import sys
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QFont
from app_controller import AppController
from core.utils import resource_path

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setFont(QFont("Segoe UI", 10))
    try:
        qss_path = resource_path('style.qss')
        with open(qss_path, 'r', encoding='utf-8') as f:
            app.setStyleSheet(f.read())
    except FileNotFoundError:
        print(f"경고: style.qss 파일을 찾을 수 없습니다: {qss_path}")
    
    controller = AppController(app)
    
    sys.exit(app.exec_())
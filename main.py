# main.py

import sys
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QFont
from app_controller import AppController
from core.utils import resource_path

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    
    # 기본 폰트를 전역으로 설정
    app.setFont(QFont("Segoe UI", 10))

    # 스타일시트 적용
    try:
        with open('style.qss', 'r', encoding='utf-8') as f:
            app.setStyleSheet(f.read())
    except FileNotFoundError:
        print("경고: style.qss 파일을 찾을 수 없습니다.")

    controller = AppController(app)
    
    sys.exit(app.exec_())
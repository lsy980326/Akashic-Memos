import sys
import os

def resource_path(relative_path, is_resource=True):
    try:
        base_path = sys._MEIPASS
        if not is_resource: # 리소스 폴더가 아닌 프로젝트 루트 기준일 때
            base_path = os.path.abspath(os.path.join(os.path.dirname(sys.executable), "..")) if hasattr(sys, 'frozen') else os.path.abspath(".")
            return os.path.join(base_path, relative_path)

    except Exception:
        base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    
    if is_resource:
        return os.path.join(base_path, 'resources', relative_path)
    else:
        return os.path.join(base_path, relative_path)
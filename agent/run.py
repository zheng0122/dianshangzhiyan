import os
import sys
import time
import threading
import webbrowser
import uvicorn

# 解决 PyInstaller 单文件打包释放临时目录路径问题
if hasattr(sys, '_MEIPASS'):
    os.chdir(sys._MEIPASS)


def open_browser():
    time.sleep(1.5)
    webbrowser.open("http://127.0.0.1:8000")


if __name__ == "__main__":
    # 后台开启线程自动打开网页
    threading.Thread(target=open_browser, daemon=True).start()

    # 启动应用 (根据你的 dev_server 实际入口，这里指向 agent.app.main:app)
    from app.main import app

    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")

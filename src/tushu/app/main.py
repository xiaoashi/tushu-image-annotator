from __future__ import annotations
import argparse
import sys
from PySide6.QtWidgets import QApplication
from tushu.ui.window import MainWindow


def main():
    parser=argparse.ArgumentParser(description='图枢离线图像处理与标注软件')
    parser.add_argument('--project',help='要打开的项目目录')
    parser.add_argument('--self-test',help='执行禁止网络的离线自检并写入 JSON 报告')
    parser.add_argument('--screenshot',help='开发验证：保存窗口截图后退出')
    args=parser.parse_args()
    if args.self_test:
        from tushu.app.smoke import smoke
        smoke(args.self_test)
        return 0
    app=QApplication(sys.argv[:1])
    app.setApplicationName('图枢')
    app.setOrganizationName('Tushu')
    app.setApplicationVersion('1.1.0')
    window=MainWindow()
    window.show()
    if args.project:
        window.guard(lambda:window.open_project(args.project))
    if args.screenshot:
        from PySide6.QtCore import QTimer
        def capture():
            window.grab().save(args.screenshot)
            window.close()
        QTimer.singleShot(1200,capture)
    return app.exec()


if __name__=='__main__':
    raise SystemExit(main())

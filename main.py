import sys
import os

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon

from app.config import get_icon_path
from app.window import MainWindow


if __name__ == "__main__":
    app = QApplication(sys.argv)

    icon_path = get_icon_path()
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    window = MainWindow()
    window.show()

    sys.exit(app.exec())
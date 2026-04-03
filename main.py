"""진입점 — GUI 앱 실행"""

import logging

from gui import App


def main():
    logging.basicConfig(level=logging.INFO)
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()

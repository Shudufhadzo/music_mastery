from __future__ import annotations

from mastery_native.window import MasteryWindow, create_application


def main() -> int:
    app = create_application()
    window = MasteryWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

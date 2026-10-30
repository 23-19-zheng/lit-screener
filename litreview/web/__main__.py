# -*- coding: utf-8 -*-
"""python -m litreview.web --port 8000"""
import argparse
import webbrowser

import uvicorn


def main():
    parser = argparse.ArgumentParser(description="Lit Screener 本地可视化工作台")
    parser.add_argument("--host", default="127.0.0.1", help="默认仅本机可访问")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not args.no_browser:
        import threading
        threading.Timer(1.0, lambda: webbrowser.open(f"http://{args.host}:{args.port}")).start()
    uvicorn.run("litreview.web.app:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()

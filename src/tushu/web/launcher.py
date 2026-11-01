from __future__ import annotations
import argparse
from pathlib import Path
import threading
import time
import webbrowser


def main():
    parser = argparse.ArgumentParser(description="图枢本地图像标注工作台")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    import httpx

    service_url = f"http://127.0.0.1:{args.port}"
    try:
        with httpx.Client(timeout=0.6, trust_env=False) as client:
            response = client.get(service_url + "/api/bootstrap")
            if response.status_code == 200 and response.json().get("service") == "tushu-web":
                if not args.no_browser:
                    webbrowser.open(service_url)
                return 0
    except (httpx.HTTPError, ValueError):
        pass
    import uvicorn
    from tushu.web.server import create_app

    app = create_app(args.workspace)
    if not args.no_browser:

        def open_when_ready():
            import httpx

            for _ in range(60):
                try:
                    with httpx.Client(trust_env=False, timeout=0.5) as client:
                        if client.get(f"http://127.0.0.1:{args.port}/api/bootstrap").status_code == 200:
                            webbrowser.open(f"http://127.0.0.1:{args.port}")
                            return
                except httpx.HTTPError:
                    time.sleep(0.2)

        threading.Thread(target=open_when_ready, daemon=True).start()
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=args.port,
        access_log=False,
        log_level="warning",
        loop="asyncio",
        http="h11",
        ws="none",
    )


if __name__ == "__main__":
    main()

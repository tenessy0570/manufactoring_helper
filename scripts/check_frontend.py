"""Run frontend scenarios in an isolated Chromium browser without live services."""

import argparse
import base64
import json
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx
from websockets.sync.client import connect

ROOT = Path(__file__).resolve().parents[1]


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_json(url: str) -> Any:
    for _ in range(50):
        try:
            response = httpx.get(url, timeout=1, trust_env=False)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError):
            time.sleep(0.2)
    raise RuntimeError(f"Local test service did not become ready: {url}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--browser",
        type=Path,
        default=Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
    )
    args = parser.parse_args()
    if not args.browser.is_file():
        parser.error("Pass --browser with a Chromium or Edge executable")
    port, debug_port = free_port(), free_port()
    url = f"http://127.0.0.1:{port}"
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "scripts.preview_ui:app", "--port", str(port)],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    browser = None
    try:
        wait_json(url + "/openapi.json")
        browser = subprocess.Popen(
            [
                str(args.browser),
                "--headless",
                "--disable-gpu",
                "--no-first-run",
                f"--remote-debugging-port={debug_port}",
                "--user-data-dir=" + tempfile.mkdtemp(prefix="eve-ui-check-"),
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        tabs = wait_json(f"http://127.0.0.1:{debug_port}/json")
        tab = next(tab for tab in tabs if tab["type"] == "page")
        with connect(tab["webSocketDebuggerUrl"]) as connection:
            sequence = 0
            errors = []

            def call(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
                nonlocal sequence
                sequence += 1
                connection.send(
                    json.dumps({"id": sequence, "method": method, "params": params or {}})
                )
                while True:
                    result = json.loads(connection.recv())
                    if result.get("method") == "Runtime.exceptionThrown":
                        errors.append(result["params"])
                    if result.get("id") == sequence:
                        return result

            def evaluate(code: str) -> Any:
                result = call(
                    "Runtime.evaluate",
                    {
                        "expression": code,
                        "returnByValue": True,
                        "awaitPromise": True,
                    },
                )["result"]
                if "exceptionDetails" in result:
                    raise RuntimeError(str(result["exceptionDetails"]))
                return result["result"].get("value")

            call("Runtime.enable")
            call("Page.navigate", {"url": url + "/?demo=1"})
            time.sleep(1)
            scenarios = (ROOT / "tests/frontend/browser_scenarios.js").read_text(encoding="utf-8")
            print(evaluate(scenarios + "\ncheckFrontendWorkflow()"))
            call("Page.reload", {"ignoreCache": True})
            time.sleep(1)
            print(
                evaluate("""(()=>{const a=Alpine.$data(document.body);
                if(a.form.category!=='Rigs'||a.form.tech!=='2'||!a.browserProfile
                  ||document.querySelector('[aria-label=\"Trade hub\"]').value!==a.form.hub_id)
                  throw Error('Reload persistence');return 'PASS: actual page reload';})()""")
            )
            print(
                evaluate("""(()=>{const a=Alpine.$data(document.body), original=window.confirm;
                window.confirm=()=>true;try{a.deleteBrowserProfile();
                if(a.browserProfile||a.form.category!=='Rigs')throw Error('Delete changed filters');
                }finally{window.confirm=original;}return 'PASS: profile deletion';})()""")
            )
            for width, label in ((1440, "desktop"), (390, "mobile")):
                call(
                    "Emulation.setDeviceMetricsOverride",
                    {
                        "width": width,
                        "height": 1100,
                        "deviceScaleFactor": 1,
                        "mobile": False,
                    },
                )
                evaluate("window.scrollTo(0,0)")
                time.sleep(0.2)
                print(
                    label,
                    evaluate("""(()=>{
                    if(document.documentElement.scrollWidth>innerWidth+1)throw Error('Overflow');
                    return 'PASS: no page overflow';})()"""),
                )
                shot = call("Page.captureScreenshot", {"format": "png"})["result"]["data"]
                path = Path(tempfile.gettempdir()) / f"eve-final-{label}.png"
                path.write_bytes(base64.b64decode(shot))
                print(path)
            print(
                evaluate("""(async()=>{const a=Alpine.$data(document.body);
                await a.openItem(a.page.items[0]);
                a.invention=JSON.parse(sessionStorage.getItem('inventionFixture'));
                await a.$nextTick();const panel=a.$refs.dialog;
                if(panel.scrollWidth>panel.clientWidth+1)throw Error('Dialog overflow');
                panel.querySelector('.invention-box').scrollIntoView({block:'start'});
                return 'PASS: nine invention options fit the mobile dialog';})()""")
            )
            shot = call("Page.captureScreenshot", {"format": "png"})["result"]["data"]
            path = Path(tempfile.gettempdir()) / "eve-invention-mobile.png"
            path.write_bytes(base64.b64decode(shot))
            print(path)
            call(
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": 1440,
                    "height": 1100,
                    "deviceScaleFactor": 1,
                    "mobile": False,
                },
            )
            print(
                evaluate("""(()=>{const panel=Alpine.$data(document.body).$refs.dialog;
                panel.querySelector('.invention-box').scrollIntoView({block:'start'});
                const rows=[...panel.querySelectorAll('.invention-table tbody tr')];
                const right=rows[0].cells[2].getBoundingClientRect().right;
                if(rows.some(r=>Math.abs(r.cells[2].getBoundingClientRect().right-right)>1))
                  throw Error('Misaligned costs');
                return 'PASS: desktop invention columns align';})()""")
            )
            shot = call("Page.captureScreenshot", {"format": "png"})["result"]["data"]
            path = Path(tempfile.gettempdir()) / "eve-invention-desktop.png"
            path.write_bytes(base64.b64decode(shot))
            print(path)
            call("Page.navigate", {"url": url + "/invention-shopping"})
            time.sleep(1)
            shopping_scenarios = (ROOT / "tests/frontend/shopping_scenarios.js").read_text(
                encoding="utf-8"
            )
            print(evaluate(shopping_scenarios + "\ncheckShoppingWorkflow()"))
            for width in (1440, 390):
                call(
                    "Emulation.setDeviceMetricsOverride",
                    {"width": width, "height": 1100, "deviceScaleFactor": 1, "mobile": False},
                )
                time.sleep(0.2)
                print(
                    evaluate(
                        "if(document.documentElement.scrollWidth>innerWidth+1)"
                        "throw Error('Shopping overflow'); 'PASS: shopping layout'"
                    )
                )
            call("Page.navigate", {"url": url + "/login"})
            time.sleep(1)
            print(
                evaluate("""(async()=>{const a=Alpine.$data(document.body);
            a.api=async()=>{throw Error('Invalid username or password');};
            a.username='example';a.password='bad';await a.submitLogin();
            if(!a.error||a.busy)throw Error('Login feedback');
            if(document.querySelector('input[type=password]').autocomplete!=='current-password')
              throw Error('Password autocomplete');return 'PASS: login page';})()""")
            )
            call("Page.navigate", {"url": url + "/admin"})
            time.sleep(1)
            print(
                evaluate("""(async()=>{const a=Alpine.$data(document.body);
            a.user={id:'admin',username:'admin',is_superuser:true};
            let created=false;a.api=async(path,options={})=>{
            if(path==='/users'&&options.method==='POST'){created=true;return {};}
            return [{id:'user',username:'example',is_active:true,is_superuser:false}];};
            a.newUsername='example';a.initialPassword='example-password';await a.createUser();
            if(!created||a.initialPassword||a.users.length!==1)throw Error('Admin create user');
            return 'PASS: administration page';})()""")
            )
            for width in (1440, 390):
                call(
                    "Emulation.setDeviceMetricsOverride",
                    {"width": width, "height": 1100, "deviceScaleFactor": 1, "mobile": False},
                )
                time.sleep(0.2)
                print(
                    evaluate(
                        "if(document.documentElement.scrollWidth>innerWidth+1)"
                        "throw Error('Admin overflow'); 'PASS: admin layout'"
                    )
                )
            if errors:
                raise RuntimeError(str(errors))
            print("PASS: no uncaught JavaScript errors")
    finally:
        for process in (browser, server):
            if process is not None:
                process.terminate()
                process.wait(timeout=10)


if __name__ == "__main__":
    main()

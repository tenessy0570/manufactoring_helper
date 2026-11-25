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
            print(
                evaluate("""(async()=>{const a=Alpine.$data(document.body),load=a.load;
                let reloads=0;a.load=async()=>{reloads++;};
                try{await a.excludeItem({type_id:2048,name:'Damage Control II'});
                if(reloads)throw Error('Exclusion restarted calculation');
                if(!a.params().getAll('exclude_type_ids').includes('2048'))
                    throw Error('Excluded item missing from server query');
                a.excludedItems=[];a.readExclusions();
                if(!a.excludedItems.some(v=>v.type_id===2048))throw Error('Exclusions not saved');
                await a.restoreItem(2048);
                if(reloads)throw Error('Restore restarted calculation');
                if(a.params().getAll('exclude_type_ids').includes('2048'))
                    throw Error('Restore failed');
                a.excludedItems=Array.from({length:51},(_,i)=>({type_id:i+1,name:'Item '+i}));
a.excludedPage=0;await a.$nextTick();
if(document.querySelectorAll('.excluded-row').length!==25)
throw Error('Excluded page size');
a.excludedPage=2;await a.$nextTick();
if(document.querySelectorAll('.excluded-row').length!==1)
throw Error('Excluded last page size');
await a.restoreItem(51);
if(a.excludedPage!==1)throw Error('Excluded page not clamped');
await a.changeExclusions([]);
return 'PASS: exclude, persist, restore and 25-item pagination';
                }finally{a.load=load;}})()""")
            )
            profile_controls = (ROOT / "tests/frontend/profile_controls_scenarios.js").read_text(
                encoding="utf-8"
            )
            print(evaluate(profile_controls + "\ncheckProfileControls()"))
            evaluate("""(()=>{const a=Alpine.$data(document.body);
                a.filtersOpen=false;a.saveSettings();})()""")
            call("Page.reload", {"ignoreCache": True})
            time.sleep(1)
            print(
                evaluate("""(async()=>{const a=Alpine.$data(document.body);
                if(a.filtersOpen)throw Error('Collapsed filters not restored');
                document.querySelector('[aria-controls="opportunity-filters"]').click();
                await a.$nextTick();return 'PASS: filters reopen after reload';})()""")
            )
            for width, label in (
                (1920, "wide"),
                (1440, "desktop"),
                (1399, "medium"),
                (1100, "tablet"),
                (390, "mobile"),
            ):
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
                    const groups=[...document.querySelectorAll(
                        '#opportunity-filters .filter-group')];
                    for(let i=0;i<groups.length;i++){
                        const a=groups[i].getBoundingClientRect();
                        if(!a.height)throw Error('Filters not expanded for layout check');
                        for(const other of groups.slice(i+1)){
                            const b=other.getBoundingClientRect();
                            if(Math.min(a.right,b.right)-Math.max(a.left,b.left)>1 &&
                               Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top)>1)
                                throw Error('Filter groups overlap');
                        }
                        for(const input of groups[i].querySelectorAll('input,select')){
                            if(!input.getBoundingClientRect().height)continue;
                            const r=input.getBoundingClientRect();
                            if(r.left<a.left-1||r.right>a.right+1)
                                throw Error('Filter input escapes its group');
                        }
                    }
                    return 'PASS: no overflow or overlapping filters';})()"""),
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
            a.requestApi=async()=>{throw Error('Invalid username or password');};
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
            let created=false;a.requestApi=async(path,options={})=>{
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
            call("Page.navigate", {"url": url + "/production-history"})
            time.sleep(1)
            production_scenarios = (ROOT / "tests/frontend/production_scenarios.js").read_text(
                encoding="utf-8"
            )
            print(evaluate(production_scenarios + "\ncheckProductionWorkflow()"))
            for width in (1440, 390):
                call(
                    "Emulation.setDeviceMetricsOverride",
                    {
                        "width": width,
                        "height": 1100,
                        "deviceScaleFactor": 1,
                        "mobile": False,
                    },
                )
                time.sleep(0.2)
                print(
                    evaluate(
                        "if(document.documentElement.scrollWidth>innerWidth+1)"
                        "throw Error('Production overflow'); window.scrollTo(0,0);"
                        "'PASS: production layout'"
                    )
                )
                shot = call("Page.captureScreenshot", {"format": "png"})["result"]["data"]
                (Path(tempfile.gettempdir()) / f"eve-production-{width}.png").write_bytes(
                    base64.b64decode(shot)
                )
            call("Page.navigate", {"url": url + "/blueprint-calculator"})
            time.sleep(1)
            calculator_scenarios = (ROOT / "tests/frontend/calculator_scenarios.js").read_text(
                encoding="utf-8"
            )
            print(evaluate(calculator_scenarios + "\ncheckCalculatorWorkflow()"))
            for width in (1440, 390):
                call(
                    "Emulation.setDeviceMetricsOverride",
                    {"width": width, "height": 1100, "deviceScaleFactor": 1, "mobile": False},
                )
                time.sleep(0.2)
                print(
                    evaluate(
                        "if(document.documentElement.scrollWidth>innerWidth+1)"
                        "throw Error('Calculator overflow');'PASS: calculator layout'"
                    )
                )
                evaluate("window.scrollTo(0,0)")
                shot = call("Page.captureScreenshot", {"format": "png"})["result"]["data"]
                (Path(tempfile.gettempdir()) / f"eve-calculator-{width}.png").write_bytes(
                    base64.b64decode(shot)
                )
            evaluate("""localStorage.setItem('eve.interhub.settings.v1',JSON.stringify({
                source_hub:'jita',destination_hub:'amarr',sales_tax:'3'}));
                localStorage.removeItem('eve.interhub.settings.v2');""")
            call("Page.navigate", {"url": url + "/interhub-trading"})
            time.sleep(1)
            trading_scenarios = (ROOT / "tests/frontend/trading_scenarios.js").read_text(
                encoding="utf-8"
            )
            print(evaluate(trading_scenarios + "\ncheckTradingWorkflow()"))
            for width in (1920, 1440, 390):
                call(
                    "Emulation.setDeviceMetricsOverride",
                    {
                        "width": width,
                        "height": 1100,
                        "deviceScaleFactor": 1,
                        "mobile": False,
                    },
                )
                time.sleep(0.2)
                print(
                    evaluate("""(()=>{
                    if(document.documentElement.scrollWidth>innerWidth+1)
                        throw Error('Trading page overflow');
                    window.scrollTo(0,document.body.scrollHeight);
                    const action=document.querySelector('[form="trade-filters"]');
                    const r=action.getBoundingClientRect();
                    if(r.top<0||r.bottom>innerHeight)throw Error('Trade action is hidden');
                    window.scrollTo(0,0);return 'PASS: trading layout and sticky action';})()""")
                )
                shot = call("Page.captureScreenshot", {"format": "png"})["result"]["data"]
                (Path(tempfile.gettempdir()) / f"eve-trading-{width}.png").write_bytes(
                    base64.b64decode(shot)
                )
            print(
                evaluate("""(async()=>{const a=Alpine.$data(document.body);
                a.historyItem={...a.page.items[0]};
                const fixture=JSON.parse(sessionStorage.getItem('tradingHistoryFixture'));
                a.historyData={...fixture,days:fixture.days.sort((x,y)=>x.date.localeCompare(y.date))};
                await a.$nextTick();a.$refs.historyDialog.showModal();
                return 'PASS: sale history layout opened';})()""")
            )
            time.sleep(0.2)
            print(
                evaluate("""(()=>{const d=Alpine.$data(document.body).$refs.historyDialog;
                if(d.scrollWidth>d.clientWidth+1||d.getBoundingClientRect().right>innerWidth)
                    throw Error('Sale history dialog overflow');
                if(!d.querySelector('svg')||!d.querySelector('svg').getBoundingClientRect().width)
                    throw Error('Sale history chart not visible');
                return 'PASS: mobile sale history chart fits';})()""")
            )
            shot = call("Page.captureScreenshot", {"format": "png"})["result"]["data"]
            (Path(tempfile.gettempdir()) / "eve-trading-history-mobile.png").write_bytes(
                base64.b64decode(shot)
            )
            evaluate("Alpine.$data(document.body).closeHistory()")
            call("Page.reload", {"ignoreCache": True})
            time.sleep(1)
            print(
                evaluate("""(()=>{const a=Alpine.$data(document.body);
                if('hauling_per_m3' in a.form||a.form.sales_tax!=='2'||
                    a.isColumnVisible('purchase'))
                    throw Error('Trade settings lost on reload');
                return 'PASS: trading page reload';})()""")
            )
            freshness_scenarios = (ROOT / "tests/frontend/freshness_scenarios.js").read_text(
                encoding="utf-8"
            )
            print(evaluate(freshness_scenarios + "\ncheckFreshnessHeader()"))
            for path in (
                "/",
                "/blueprint-calculator",
                "/interhub-trading",
                "/invention-shopping",
                "/production-history",
                "/account",
            ):
                call("Page.navigate", {"url": url + path})
                time.sleep(0.5)
                print(
                    evaluate("""(()=>{
                    const nav=document.querySelector('.site-navigation');
                    if(!document.querySelector('.freshness-header'))
                        throw Error('Missing shared freshness header');
                    const help=document.querySelector('.workspace-help');
                    if(help){
                        help.open=true;help.dispatchEvent(new KeyboardEvent('keydown',
                            {key:'Escape',bubbles:true}));
                        if(help.open)throw Error('Help did not close');
                    }
                    if(nav.querySelectorAll('[aria-current=page]').length!==1)
                        throw Error('Missing active navigation');
                    for(const href of ['/','/invention-shopping','/production-history','/account'])
                        if(!nav.querySelector('a[href="'+href+'"] .nav-icon'))
                            throw Error('Missing navigation link or icon');
                    nav.querySelector('.navigation-toggle').click();
                    return 'PASS: shared navigation and icons';})()""")
                )
                time.sleep(0.1)
                print(
                    evaluate("""(()=>{
                    const nav=document.querySelector('.site-navigation');
                    for(const link of nav.querySelectorAll('nav a')){
                        const r=link.getBoundingClientRect();
                        if(r.width===0||r.right>innerWidth)throw Error('Hidden mobile link');
                    }
                    if(document.documentElement.scrollWidth>innerWidth+1)
                        throw Error('Navigation overflow');
                    nav.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
                    if(Alpine.$data(nav).menuOpen)throw Error('Menu did not close');
                    return 'PASS: mobile navigation opens and closes';})()""")
                )
            print(
                evaluate("""(async()=>{
                const marker='private-password-must-not-appear';
                for(const response of [new Response(JSON.stringify({detail:marker}),{status:500}),
                    new Response(marker,{status:502}),new Response(marker,{status:422})]){
                    try{await window.readApiResponse(response);throw Error('Expected failure');}
                    catch(error){if(error.message.includes(marker))
                        throw Error('Server details leaked');}
                }
                return 'PASS: frontend hides raw server failures';})()""")
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

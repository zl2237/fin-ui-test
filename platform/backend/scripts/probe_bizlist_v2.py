"""业务订单列表可见性探针 v2（非破坏性，只搜索+截图）：
855(15:41 WX9) g2 搜索过；856 起全部失败。本探针对比搜 WX9(status=2) 与
89RJ(status=1) 的列表响应，抓 XHR 请求参数与响应 JSON，找过滤差异。"""
import json
import sys
from pathlib import Path

import requests

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(BACKEND_DIR.parent.parent))

from dotenv import load_dotenv

load_dotenv(BACKEND_DIR / ".env")
import os

os.environ.setdefault("DB_PASSWORD", "x")

DUMP_JS = r"""(async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const nz = s => (s || '').replace(/\s+/g, '');
  const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
  await sleep(1200);
  const q = {};
  q.inputs = [...document.querySelectorAll('input[placeholder]')].filter(vis)
    .slice(0, 8).map(i => ({ph: i.placeholder, val: i.value.slice(0, 40)}));
  q.tabs = [...document.querySelectorAll('.el-tabs__item, .el-radio-button')]
    .filter(vis).map(t => ({txt: nz(t.textContent).slice(0, 10),
      active: (t.className || '').toString().includes('is-active')}));
  q.rows = [...document.querySelectorAll('.el-table__body-wrapper tbody tr')]
    .map(tr => nz(tr.textContent).slice(0, 90)).slice(0, 4);
  q.pager = nz((document.querySelector('.el-pagination') || {textContent: ''}).textContent).slice(0, 80);
  q.empty = [...document.querySelectorAll('.el-table__empty-text')].filter(vis)
    .map(e => nz(e.textContent)).slice(0, 2);
  q.msgs = [...document.querySelectorAll('.el-message')].filter(vis).map(m => nz(m.textContent));
  return q;
})()"""


def main() -> int:
    from app.database import SessionLocal
    from app import models
    from app.engine.context import ExecutionContext
    from app.services.ui_runtime import UiRuntime
    from app.services.token_cache import EnvTokenCache

    db = SessionLocal()
    env = db.query(models.Environment).filter(models.Environment.id == 1).first()

    def do_login() -> str:
        body = dict((env.login_config or {}).get("login_body") or {})
        body.setdefault("code", "6666")
        r = requests.post(env.base_url.rstrip("/") + "/api/home/login/userLogin",
                          json=body, headers={"Authorization": "skip-captcha-placeholder"},
                          timeout=15)
        return r.json()["data"]["token"]

    EnvTokenCache.login_shared(env.id, do_login)

    captured = []

    def on_response(resp):
        url = resp.url
        if "/api/" not in url or any(k in url for k in ("login", "captcha", "menu")):
            return
        try:
            j = resp.json()
        except Exception:
            return
        req_post = None
        try:
            req_post = resp.request.post_data
        except Exception:
            pass
        captured.append({"url": url.split("bjyy")[-1][:110], "post": (req_post or "")[:200],
                         "resp": json.dumps(j, ensure_ascii=False)[:600]})

    def search_and_dump(rt, page, tag: str, bl: str) -> None:
        print(f"\n===== 搜索 {tag} {bl}")
        try:
            rt.run_action({"action": "search", "value": bl})
            print("  search 动作: 成功（等到行）")
        except Exception as e:
            print(f"  search 动作异常: {str(e)[:160]}")
        try:
            q = page.evaluate(DUMP_JS)
            print("  页面:", json.dumps(q, ensure_ascii=False)[:900])
        except Exception as e:
            print(f"  dump 异常: {e}")
        page.screenshot(path=str(BACKEND_DIR / f".debug_v2_{tag}.png"))
        # 只回放本次搜索相关的接口（含 order 字样的最后 3 条）
        rel = [c for c in captured if "order" in c["url"].lower() or "bl" in (c["post"] or "")]
        for c in rel[-3:]:
            print("  API:", json.dumps(c, ensure_ascii=False)[:700])

    ctx = ExecutionContext(dataset_vars={})
    rt = UiRuntime(db=db, env=env, context=ctx, project_id=1)
    try:
        page = rt.ensure_browser()
        page.on("response", on_response)
        rt.run_action({"action": "goto", "url": "#/development/orderManage/businessOrder"})
        rt.run_action({"action": "wait", "value": 800,
                       "element": {"value": "//input[@placeholder='提单号']", "strategy": "xpath"},
                       "timeout_ms": 15000})
        print("===== 初始进入列表页")
        q = page.evaluate(DUMP_JS)
        print("页面:", json.dumps(q, ensure_ascii=False)[:900])
        n0 = len(captured)
        for c in captured[:4]:
            print("初始API:", json.dumps(c, ensure_ascii=False)[:500])

        captured.clear()
        search_and_dump(rt, page, "WX9", "uitest202610231540384WX9")
        captured.clear()
        search_and_dump(rt, page, "89RJ", "uitest2026102315584489RJ")
        return 0
    finally:
        rt.close()
        db.close()


if __name__ == "__main__":
    sys.exit(main())

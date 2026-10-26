"""业务订单列表可见性探针（非破坏性）：858 生成的 89RJ 在库里但 g2 搜不到，
现场取证——搜索后行数/页脚/首行文本/截图。只读，不点任何按钮。"""
import json
import sys

import requests
from pathlib import Path

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
  await sleep(2500);
  const q = {};
  q.url = location.hash;
  q.inputs = [...document.querySelectorAll('input[placeholder]')].filter(vis)
    .slice(0, 6).map(i => ({ph: i.placeholder, val: i.value}));
  q.tabs = [...document.querySelectorAll('[role=tab], .el-tabs__item, .el-radio-button')]
    .filter(vis).map(t => ({txt: nz(t.textContent).slice(0, 12),
      active: (t.className || '').toString().includes('is-active')}));
  q.rowsText = [...document.querySelectorAll('.el-table__body-wrapper tbody tr')]
    .map(tr => nz(tr.textContent).slice(0, 100)).slice(0, 5);
  q.pager = nz((document.querySelector('.el-pagination') || {textContent: ''}).textContent).slice(0, 60);
  q.empty = [...document.querySelectorAll('.el-table__empty-text')].filter(vis)
    .map(e => nz(e.textContent)).slice(0, 3);
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
    bl = "uitest2026102315584489RJ"
    ctx = ExecutionContext(dataset_vars={"bl_no": bl})
    rt = UiRuntime(db=db, env=env, context=ctx, project_id=1)
    try:
        page = rt.ensure_browser()
        rt.run_action({"action": "goto", "url": "#/development/orderManage/businessOrder"})
        rt.run_action({"action": "wait", "value": 800,
                       "element": {"value": "//input[@placeholder='提单号']", "strategy": "xpath"},
                       "timeout_ms": 15000})
        rt.run_action({"action": "search", "value": "${bl_no}"})
        q = page.evaluate(DUMP_JS)
        print(json.dumps(q, ensure_ascii=False, indent=1)[:1800])
        page.screenshot(path=str(BACKEND_DIR / ".debug_89rj.png"))
        return 0
    finally:
        rt.close()
        db.close()


if __name__ == "__main__":
    sys.exit(main())

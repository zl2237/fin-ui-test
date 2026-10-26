"""业务自营订单列表页弹窗/遮罩基线探针（只读，不点击任何业务按钮）：
1) 直达页面（无前置弹窗场景）：守卫表达式匹配到什么
2) 复现链路很难（需生成并下载），先确认基线是否本身就有 visible 的
   .el-dialog/.el-drawer（若有，守卫 offsetParent 判定需要修正）
"""
import json
import sys
from pathlib import Path

import requests

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv

load_dotenv(BACKEND_DIR / ".env")
import os

os.environ.setdefault("DB_PASSWORD", "x")

DUMP_JS = r"""(() => {
  const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
  const out = { vmodal: document.querySelectorAll('.v-modal').length, matches: [] };
  for (const el of document.querySelectorAll('.el-dialog,.el-message-box,.el-drawer')) {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    out.matches.push({
      cls: (el.className || '').toString().slice(0, 60),
      tag: el.tagName,
      visible: vis(el),
      offsetParentNull: el.offsetParent === null,
      rect: [Math.round(r.width), Math.round(r.height)],
      display: s.display,
      position: s.position,
      text: (el.textContent || '').replace(/\s+/g, '').slice(0, 30),
    });
  }
  // offsetParent 守卫视角（与用例里的清理步一致）
  out.guardVis = [...document.querySelectorAll('.el-dialog,.el-message-box,.el-drawer')]
    .some(el => el.offsetParent !== null);
  return out;
})()"""


def main() -> int:
    from app.database import SessionLocal
    from app import models
    from playwright.sync_api import sync_playwright

    db = SessionLocal()
    env = db.query(models.Environment).filter(models.Environment.id == 1).first()
    body = dict((env.login_config or {}).get("login_body") or {})
    body.setdefault("code", "6666")
    r = requests.post(env.base_url.rstrip("/") + "/api/home/login/userLogin",
                      json=body, headers={"Authorization": "skip-captcha-placeholder"}, timeout=15)
    token = r.json()["data"]["token"]
    db.close()

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1920, "height": 1080}, locale="zh-CN")
        ctx.add_cookies([{"name": "Admin-Token", "value": token, "url": env.base_url}])
        page = ctx.new_page()
        page.goto(env.base_url.rstrip("/") + "/#/development/orderManage/ordersSelf",
                  wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        result = page.evaluate(DUMP_JS)
        print(json.dumps(result, ensure_ascii=False, indent=1)[:3000])
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""DatasetDialog 浏览器冒烟（只读）：本地前端注入平台 token → 用例列表 →
283 行 更多→数据集 → 转储弹窗渲染（数据集条目/行卡/键值）+ 截图。不保存任何修改。"""
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(BACKEND_DIR.parent.parent))

from dotenv import load_dotenv

load_dotenv(BACKEND_DIR / ".env")
import os

os.environ.setdefault("DB_PASSWORD", "x")

FRONT = "http://localhost:5173/"  # vite 仅监听 [::1]，IPv4 127.0.0.1 拒连


def main() -> int:
    from app.database import SessionLocal
    from app import models
    from app.auth import create_token
    from playwright.sync_api import sync_playwright

    db = SessionLocal()
    u = db.query(models.User).filter(models.User.id == 1).first()
    tok = create_token(u.id, u.username, u.role)
    case = db.query(models.TestCase).filter(models.TestCase.id == 283).first()
    case_name = case.name
    db.close()
    print(f"目标用例: 283 {case_name}")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1560, "height": 900}, locale="zh-CN")
        ctx.add_init_script(
            "try{localStorage.setItem('fin_ui_test_token','%s')}catch(e){}" % tok)
        page = ctx.new_page()
        page.goto(FRONT + "cases", wait_until="domcontentloaded")
        # 等用例名出现在表格（登录态注入直接进列表页）
        page.wait_for_selector(f"text={case_name}", timeout=20000)
        page.wait_for_selector(".el-table__row", timeout=10000)
        # 该行的 更多 下拉
        row = page.locator(".el-table__row", has_text=case_name).first
        row.hover()
        row.get_by_text("更多", exact=True).first.click()
        # 每行的下拉菜单都 teleport 到 body 常驻 DOM（36 个隐藏项），必须 :visible 圈定刚弹出的这份
        page.locator(".el-dropdown-menu__item:visible", has_text="数据集").first.click()
        page.wait_for_selector(".dataset-manage-dialog", timeout=8000)
        page.wait_for_selector(".ds-item", timeout=8000)
        page.wait_for_timeout(800)

        def dump(tag: str) -> None:
            items = page.locator(".ds-item")
            names = [items.nth(i).locator(".ds-name").inner_text() for i in range(items.count())]
            n = page.locator(".ds-row").count()
            first_keys = page.evaluate(
                "() => { const r = document.querySelectorAll('.ds-row')[0];"
                " return r ? [...r.querySelectorAll('.ds-kv-key input')].map(i => i.value) : []; }")
            title = page.locator(".ds-main-title").inner_text()
            print(f"[{tag}] 数据集({len(names)}): {names} | 当前: {title} 行数: {n} 首行键: {first_keys}")

        dump("默认选中")
        # 切到 5 行的合并变体数据集
        target = page.locator(".ds-item", has_text="合并变体")
        if target.count():
            target.first.click()
            page.wait_for_timeout(500)
            dump("切换后")
        page.screenshot(path=str(BACKEND_DIR / ".debug_ds_dialog.png"))
        print("截图: .debug_ds_dialog.png")
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

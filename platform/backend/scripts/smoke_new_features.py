"""新功能浏览器冒烟（任务 2/3/5/7 前端部分）：
- 任务 2：数据集行编辑器默认折叠 + 展开全部/收起全部 + 渲染量（v-if 惰性）
- 任务 3：键名下方字段字典中文名
- 任务 5：元素库「页面域语义」按钮 + 弹窗行（保存需后端重启后另行验证）
- 任务 7：元素库菜单在 测试工作台 分组下
"""
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv

load_dotenv(BACKEND_DIR / ".env")
import os

os.environ.setdefault("DB_PASSWORD", "x")

FRONT = "http://localhost:5173/"


def main() -> int:
    from app.database import SessionLocal
    from app import models
    from app.auth import create_token
    from playwright.sync_api import sync_playwright

    db = SessionLocal()
    u = db.query(models.User).filter(models.User.id == 1).first()
    tok = create_token(u.id, u.username, u.role)
    db.close()

    ok_all = True

    def check(desc: str, cond: bool, detail: str = "") -> None:
        nonlocal ok_all
        ok_all = ok_all and cond
        print(("PASS " if cond else "FAIL ") + desc + (f"  [{detail}]" if detail else ""))

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1560, "height": 900}, locale="zh-CN")
        ctx.add_init_script(
            "try{localStorage.setItem('fin_ui_test_token','%s')}catch(e){}" % tok)
        page = ctx.new_page()

        # ===== 任务 7：菜单位置（不点击——sub-menu 中心可能命中菜单项导致导航） =====
        page.goto(FRONT + "elements", wait_until="domcontentloaded")
        page.wait_for_selector(".el-menu-item", timeout=20000)
        wb = page.locator(".el-menu .el-sub-menu", has_text="测试工作台")
        cfg = page.locator(".el-menu .el-sub-menu", has_text="资源配置")
        check("元素库菜单在测试工作台下", wb.locator(".el-menu-item", has_text="元素库").count() == 1)
        check("资源配置下已无元素库", cfg.locator(".el-menu-item", has_text="元素库").count() == 0)

        # ===== 任务 2/3：数据集行编辑器 =====
        page.goto(FRONT + "datasets", wait_until="domcontentloaded")
        page.wait_for_selector(".side-node", timeout=20000)
        case_node = page.locator(".side-node", has_text="委托订单全链路").first
        case_node.click()
        page.wait_for_timeout(800)
        page.locator(".ds-chip").first.click()
        t1 = time.time()
        page.wait_for_selector(".ds-row", timeout=15000)
        rows = page.locator(".ds-row")
        n_rows = rows.count()
        collapsed = page.locator(".ds-row.is-collapsed").count()
        rendered_kv = page.locator(".ds-kv-item").count()
        render_time = time.time() - t1
        check(f"行数={n_rows}（预期 5）", n_rows == 5, f"rows={n_rows}")
        check("默认仅首行展开（其余折叠）", collapsed == n_rows - 1, f"collapsed={collapsed}")
        check(f"惰性渲染：仅首行键值在 DOM（{rendered_kv} 项，全展开应为 {n_rows}*121）",
              rendered_kv < n_rows * 100, f"kv={rendered_kv} time={render_time:.1f}s")
        check("折叠行头显示字段数", "个字段" in page.locator(".ds-row.is-collapsed .ds-row-title").first.inner_text())
        check("折叠行头有值预览", page.locator(".ds-row.is-collapsed .ds-row-preview").first.count() > 0)

        # 字典中文名（当前字典 122 条与数据集 132 键仅 3 键交集——覆盖率取决于字典内容）
        labels = page.locator(".ds-kv-label")
        nonempty = page.locator(".ds-kv-label:not(:empty)")
        check("键名下方有字典中文名", nonempty.count() >= 3, f"labels={nonempty.count()}/{labels.count()}")

        # 展开/收起全部
        page.get_by_role("button", name="展开全部").click()
        page.wait_for_timeout(600)
        kv_all = page.locator(".ds-kv-item").count()
        check("展开全部后键值全渲染", kv_all > n_rows * 100, f"kv={kv_all}")
        page.get_by_role("button", name="收起全部").click()
        page.wait_for_timeout(600)
        check("收起全部后无键值渲染", page.locator(".ds-kv-item").count() == 0)
        # 行头点击展开
        page.locator(".ds-row.is-collapsed .ds-row-head").nth(1).click()
        page.wait_for_timeout(400)
        check("点击折叠行头可展开", page.locator(".ds-row.is-collapsed").count() == n_rows - 1)

        # ===== 任务 5：页面域语义入口（保存待后端重启后验证） =====
        page.goto(FRONT + "elements", wait_until="domcontentloaded")
        page.wait_for_selector(".el-table__row", timeout=20000)
        btn = page.get_by_role("button", name="页面域语义")
        check("元素库有页面域语义按钮", btn.count() == 1)
        btn.click()
        page.wait_for_selector(".label-row", timeout=10000)
        n_scopes = page.locator(".label-row").count()
        check(f"语义弹窗列出页面域行（{n_scopes}）", n_scopes >= 6, f"rows={n_scopes}")
        page.screenshot(path=str(BACKEND_DIR / ".debug_scope_labels.png"))
        page.get_by_role("button", name="取消").click()

        browser.close()

    print("\n" + ("ALL PASS" if ok_all else "HAS FAILURES"))
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())

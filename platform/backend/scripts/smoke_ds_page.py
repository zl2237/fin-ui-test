"""DatasetManage 独立页浏览器冒烟（本地前端，临时数据闭环）：
导航 /datasets → 侧栏选 283 → 切换条/使用中/行数 → 新建临时数据集 →
改值保存 → 验证行数 → 删除临时数据集。截图留档。"""
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(BACKEND_DIR.parent.parent))

from dotenv import load_dotenv

load_dotenv(BACKEND_DIR / ".env")
import os

os.environ.setdefault("DB_PASSWORD", "x")

FRONT = "http://localhost:5173/"  # vite 仅监听 [::1]


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
        print(("✓" if cond else "✗") + f" {desc}" + (f"  [{detail}]" if detail else ""))

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1560, "height": 900}, locale="zh-CN")
        ctx.add_init_script(
            "try{localStorage.setItem('fin_ui_test_token','%s')}catch(e){}" % tok)
        page = ctx.new_page()
        page.goto(FRONT + "datasets", wait_until="domcontentloaded")
        page.wait_for_selector(".side-node", timeout=20000)

        # 1. 侧栏：用例节点（数据集计数）
        page.wait_for_timeout(800)
        case_node = page.locator(".side-node", has_text="委托订单全链路").first
        check("侧栏含用例节点 283", case_node.count() > 0)
        case_node.click()
        page.wait_for_timeout(600)

        # 2. 切换条：数据集 chip + 使用中 + 行数
        chips = page.locator(".ds-chip")
        n = chips.count()
        chip_txt = chips.first.inner_text() if n else ""
        check("数据集切换条有 chip", n >= 1, f"count={n}")
        check("chip 显示使用中", "使用中" in chip_txt, chip_txt.replace("\n", " "))
        check("chip 显示行数", "5 行" in chip_txt, chip_txt.replace("\n", " "))

        # 3. 行编辑器渲染（283 数据集 5 行）
        rows = page.locator(".ds-row")
        check("行编辑器 5 行", rows.count() == 5, f"count={rows.count()}")
        page.screenshot(path=str(BACKEND_DIR / ".debug_ds_page.png"))

        # 4. 新建临时数据集（prompt 确认；名字带时间戳保唯一）
        import time
        ds_name = f"冒烟-临时-{time.strftime('%H%M%S')}"
        page.get_by_role("button", name="新建数据集").click()
        page.wait_for_selector(".el-message-box", timeout=5000)
        mb_input = page.locator(".el-message-box input")
        mb_input.fill(ds_name)
        page.locator(".el-message-box__btns .el-button--primary").click()
        page.wait_for_timeout(1000)
        new_chip = page.locator(".ds-chip", has_text=ds_name)
        check("新建后 chip 出现", new_chip.count() == 1)

        # 5. 编辑行值并保存（新数据集 0 行起步：添加行 → 添加字段 → 填值）
        page.get_by_role("button", name="添加行（复制上行）").click()
        page.wait_for_timeout(300)
        check("添加行后 1 行", page.locator(".ds-row").count() == 1)
        page.locator(".ds-row").first.get_by_role("button", name="添加字段").click()
        page.wait_for_timeout(300)
        val = page.locator(".ds-row").first.locator(".ds-kv-val textarea").first
        check("添加字段后出现键值行", val.count() == 1)
        val.fill("smoke-page-值")
        page.get_by_role("button", name="保存行数据").click()  # 点击自带失焦 → change 先于 click
        page.wait_for_timeout(1200)
        msg = page.locator(".el-message").last.inner_text() if page.locator(".el-message").count() else ""
        check("保存成功提示", "已保存" in msg, msg)

        # 6. 删除临时数据集（确认框）
        page.locator(".main-head").get_by_role("button", name="删除").click()
        page.wait_for_selector(".el-message-box", timeout=5000)
        page.locator(".el-message-box__btns .el-button--primary").click()
        page.wait_for_timeout(1000)
        check("删除后 chip 消失", page.locator(".ds-chip", has_text=ds_name).count() == 0)

        browser.close()
    print("RESULT:", "PASS" if ok_all else "FAIL")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())

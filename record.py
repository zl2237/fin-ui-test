import re
from playwright.sync_api import Playwright, sync_playwright, expect


def run(playwright: Playwright) -> None:
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    page.goto("https://fin-tidb.21eflag.com/#/login?redirect=%2F")
    page.get_by_role("textbox", name="账号").click()
    page.get_by_role("textbox", name="账号").fill("18234337458")
    page.get_by_role("textbox", name="账号").press("Tab")
    page.get_by_role("textbox", name="密码").fill("YHD123456!")
    page.get_by_role("textbox", name="密码").press("Tab")
    page.get_by_role("textbox", name="验证码").fill("7191")
    page.get_by_role("textbox", name="验证码").press("Enter")
    page.get_by_text("客商管理").click()
    page.get_by_role("link", name="客户管理").click()
    page.get_by_role("textbox", name="请输入客户名称").click()
    page.get_by_role("textbox", name="请输入客户名称").press("ControlOrMeta+V")
    page.get_by_role("textbox", name="请输入客户名称").fill("青岛统济机电制造有限公司")
    page.get_by_role("button", name=" 查询").click()
    page.locator(".vxe-table--header-wrapper.fixed-left--wrapper > .vxe-table--header > thead > .vxe-header--row > .vxe-header--column.col_12 > .vxe-cell > .vxe-cell--title > .vxe-cell--checkbox > .vxe-checkbox--icon.vxe-checkbox--unchecked-icon").click()
    page.get_by_role("button", name="批量添加操作").click()
    page.get_by_role("textbox").nth(3).click()
    page.get_by_role("textbox").nth(3).press("CapsLock")
    page.get_by_role("textbox").nth(3).fill("ui")
    page.get_by_role("textbox").nth(3).press("CapsLock")
    page.get_by_role("textbox").nth(3).fill("ui")
    page.get_by_role("listitem").filter(has_text="张乐UI").locator("span").click()
    page.get_by_role("textbox").nth(3).press("Escape")
    page.get_by_role("button", name="确定").click()
    page.get_by_label("dialog").get_by_role("button", name="确定").click()
    page.close()

    # ---------------------
    context.close()
    browser.close()


with sync_playwright() as playwright:
    run(playwright)

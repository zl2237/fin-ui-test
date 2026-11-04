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
    page.get_by_role("textbox", name="密码").fill("yhd123456!")
    page.get_by_role("textbox", name="验证码").click()
    page.get_by_role("textbox", name="验证码").fill("7838")
    page.get_by_role("textbox", name="验证码").press("Enter")
    page.locator("div").filter(has_text=re.compile(r"^后台管理$")).click()
    page.get_by_role("link", name="用户管理").click()
    page.get_by_role("textbox", name="请输入用户名称").click()
    page.get_by_role("textbox", name="请输入用户名称").fill("张管理")
    page.get_by_role("button", name=" 查询").click()
    page.get_by_role("button", name="编辑").click()
    page.locator("div").filter(has_text=re.compile(r"^请设置一个包含数字、字母和符号（如 @\$!%\*\?&）的组合密码，且密码的长度仅限在8至20之间$")).locator("i").click()
    page.locator("div").filter(has_text=re.compile(r"^请设置一个包含数字、字母和符号（如 @\$!%\*\?&）的组合密码，且密码的长度仅限在8至20之间$")).locator("i").click()
    page.locator("div").filter(has_text=re.compile(r"^请设置一个包含数字、字母和符号（如 @\$!%\*\?&）的组合密码，且密码的长度仅限在8至20之间$")).locator("i").click()
    page.get_by_role("textbox", name="请输入密码").press("ControlOrMeta+a")
    page.get_by_role("textbox", name="请输入密码").fill("yhd123456!")
    page.get_by_role("button", name="确 定").click()
    page.get_by_role("button", name="确定").click()
    page.close()

    # ---------------------
    context.close()
    browser.close()


with sync_playwright() as playwright:
    run(playwright)

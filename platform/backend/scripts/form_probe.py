# -*- coding: utf-8 -*-
"""表单指纹探针：codegen 导入的规则发现工具（非破坏性）。

能力：
1) 指已知规则探针（--rule codegen_rules/xxx.json）：按规则 probe 配置进表单
   （可先按 prefill_picks 预填级联字段），枚举全部表单项 + 逐个打开
   「请选择」下拉读真实选项后 Esc 收起 → 表单指纹 JSON（nth→label/xpath/options）。
   供「选项反查」人工核对 nth_select_guesses。
2) 陌生表单（--route '#/xxx' --add-button 新建X [--draft form_id]）：dump 指纹，
   --draft 生成 codegen_rules/<form_id>.json 草稿规则（nth 项以 select_nth_i 登记
   为低置信待复核、增强按 保存→保存成功/暂存成功 兜底），人工/导入自测后转正。

纪律（实测教训）：
- 非破坏性：只打开下拉读选项 + Esc；prefill 仅在未保存表单里选值，绝不点保存/分发
- 单会话互踢：探针登录与平台执行共用业务系统账号，探针后立即执行会互踢，
  间隔 ≥90s 再跑执行
- 指纹/探针输出一律落盘 UTF-8（控制台只打摘要），避免 GBK 管道问题

用法（在 backend 目录或仓库根均可）：
  python scripts/form_probe.py --rule codegen_rules/entrusted_order.json
  python scripts/form_probe.py --env 1 --route '#/development/orderManage/xxx' \
      --add-button 新建X --draft xxx_order
"""
import argparse
import json
import os
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
sys.path.insert(0, os.path.dirname(os.path.dirname(BACKEND)))  # 仓库根（utils/ 所在）
from dotenv import load_dotenv

load_dotenv(os.path.join(BACKEND, ".env"))
os.environ.setdefault("DB_PASSWORD", "x")

from app.database import SessionLocal  # noqa: E402
from app import models  # noqa: E402
from app.services.runtime_service import build_http_client, login as api_login  # noqa: E402
from app.services.token_cache import EnvTokenCache  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

XP_JS = ("el => {const parts=[];let n=el;"
         "while(n&&n.nodeType===1){let i=1,sib=n.previousSibling;"
         "while(sib){if(sib.nodeType===1&&sib.tagName===n.tagName)i++;sib=sib.previousSibling;}"
         "parts.unshift(n.tagName.toLowerCase()+'['+i+']');n=n.parentNode;}"
         "return '/'+parts.join('/');}")
LABEL_JS = ("el => {let n=el; while(n && !n.classList.contains('el-form-item')) "
            "n=n.parentElement; return n?(n.querySelector('.el-form-item__label')||{}).textContent:null;}")
RULES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "codegen_rules")


def login_page(db, env_id):
    env = db.query(models.Environment).filter(models.Environment.id == env_id).first()
    if not env:
        sys.exit(f"环境 {env_id} 不存在")
    api_login(build_http_client(env), env)
    token = EnvTokenCache.get(env.id)
    if not token:
        sys.exit("业务系统登录失败：无 token")
    return env.base_url, token


def fingerprint(page, rule):
    """进表单（新建按钮）→ 枚举表单项 + 下拉选项。规则里 probe.prefill_picks 先选。"""
    probe = (rule or {}).get("probe") or {}
    page.get_by_role("button", name=probe.get("add_button", "新建")).click()
    page.wait_for_timeout(probe.get("settle_ms", 1200))

    for label_kw, value in probe.get("prefill_picks", []):
        item = page.locator(".el-form-item").filter(
            has=page.locator(".el-form-item__label", has_text=label_kw)).first
        item.locator("input").first.click()
        page.wait_for_timeout(400)
        page.locator(".el-select-dropdown:visible .el-select-dropdown__item",
                     has_text=value).first.click()
        page.wait_for_timeout(600)

    result = {"form_items": [], "selects": []}
    for it in page.locator(".el-form-item").all():
        try:
            lab = it.locator(".el-form-item__label").first
            label = (lab.inner_text(timeout=600) or "").strip()
            inp = it.locator("input,textarea").first
            if not inp.count():
                continue
            result["form_items"].append({
                "label": label, "for": lab.get_attribute("for") or "",
                "placeholder": inp.get_attribute("placeholder") or "",
                "value": inp.input_value(timeout=600), "xpath": inp.evaluate(XP_JS)})
        except Exception:
            continue

    sel = page.locator("input[placeholder='请选择']")
    for i in range(sel.count()):
        entry = {"nth": i, "xpath": sel.nth(i).evaluate(XP_JS),
                 "label": (sel.nth(i).evaluate(LABEL_JS) or "").strip() or None}
        try:
            sel.nth(i).click()
            page.wait_for_timeout(600)
            opts = page.locator(".el-select-dropdown:visible .el-select-dropdown__item").all()
            entry["options"] = [(o.inner_text(timeout=500) or "").strip() for o in opts][:40]
            page.keyboard.press("Escape")
        except Exception as e:
            entry["error"] = str(e)[:150]
        result["selects"].append(entry)
    return result


def draft_rule(form_id, route, add_button, fp):
    """指纹 → 草稿规则 json（全部低置信，转正靠导入自测）。"""
    scope = route.lstrip("#/").split("?")[0]
    guesses = {}
    for s in fp["selects"]:
        guesses[str(s["nth"])] = [f"select_nth{s['nth']}", f"{form_id}_nth{s['nth']}_selector",
                                  f"草稿：label={s['label']!r}，选项反查后改字段名并补语义"]
    return {
        "form_id": form_id,
        "proven": "草稿（form_probe 生成，未实证）",
        "detect": {"nav_link_texts": [], "route_contains": scope.split("/")[-1]},
        "case": {"name": f"{form_id}（codegen 草稿）", "description": "form_probe 草稿，待人工转正", "group_id": None},
        "page": {
            "scope": scope, "scope_label": form_id,
            "route_field": f"{form_id}_route", "route_value": route,
            "node_labels": ["导航进入", "主流程"],
            "n1_assert": {"url_contains": scope.split("/")[-1], "message": f"应到达 {form_id} 页面"},
        },
        "nav_click_texts": [],
        "elements": {f"{form_id}_nth{s['nth']}_selector":
                     {"strategies": {"full_xpath": s["xpath"]}, "description": f"nth({s['nth']}) {s['label'] or ''}"}
                     for s in fp["selects"]},
        "nth_select_guesses": guesses,
        "field_suggestions": {},
        "text_input_rules": [],
        "css_picks": {},
        "query": {"text": "查询", "placeholder": "请输入", "wait_ms": 500, "assert_field": "bl_no"},
        "button_behaviors": {
            "save_button": {"role": "confirm_watchdog", "wait_ms": 800, "watchdog": ["保存成功", "暂存成功"]},
        },
        "probe": {"add_button": add_button, "settle_ms": 1200, "prefill_picks": []},
        "_todo": ["detect.nav_link_texts 补菜单链接名", "case/group_id/node_labels 补齐",
                  "nth 字段名语义化（对照 selects[].label/options）", "text_input_rules 登记字面值",
                  "button_behaviors 按流程补（分发/提交等看门狗关键词）", "导入自测通过后 proven 更新+删 _todo"],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rule", help="已知规则文件（相对/绝对路径或 form_id）")
    ap.add_argument("--env", type=int, default=1, help="平台环境 id（默认 1=测试环境）")
    ap.add_argument("--route", help="陌生表单：hash 路由，如 '#/development/orderManage/xxx'")
    ap.add_argument("--add-button", default="新建", help="进入表单的按钮文本")
    ap.add_argument("--draft", help="陌生表单：生成草稿规则 form_id")
    args = ap.parse_args()

    rule = None
    if args.rule:
        p = args.rule if os.path.exists(args.rule) else os.path.join(RULES_DIR, args.rule)
        if not p.endswith(".json"):
            p += ".json"
        rule = json.load(open(p, encoding="utf-8"))
        route = rule["page"]["route_value"]
        add_button = (rule.get("probe") or {}).get("add_button", "新建")
        form_id = rule["form_id"]
    elif args.route and args.draft:
        route, add_button, form_id = args.route, args.add_button, args.draft
    else:
        sys.exit("需要 --rule <规则> 或 --route <hash> --draft <form_id>（见 --help）")

    db = SessionLocal()
    base, token = login_page(db, args.env)
    db.close()

    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={"width": 1920, "height": 1080})
    ctx.add_cookies([{"name": "Admin-Token", "value": token, "url": base}])
    page = ctx.new_page()
    page.goto(base + route, wait_until="load")
    page.wait_for_timeout(1500)
    try:
        fp = fingerprint(page, rule)
    finally:
        browser.close()
        pw.stop()

    out = os.path.join(RULES_DIR, f"{form_id}.fingerprint.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(fp, f, ensure_ascii=False, indent=1)
    print(f"指纹已写 {out}：表单项 {len(fp['form_items'])} 个，下拉 {len(fp['selects'])} 个")
    for s in fp["selects"]:
        print(f"  nth({s['nth']}) label={s['label']!r} options={s.get('options', [])[:5]}{'...' if len(s.get('options', [])) > 5 else ''}")

    if args.draft and not args.rule:
        dr = os.path.join(RULES_DIR, f"{form_id}.json")
        if os.path.exists(dr):
            print(f"[skip] 草稿已存在 {dr}（不覆盖）")
        else:
            with open(dr, "w", encoding="utf-8") as f:
                json.dump(draft_rule(form_id, route, add_button, fp), f, ensure_ascii=False, indent=1)
            print(f"草稿规则已生成 {dr}：按 _todo 清单转正后即可 import_codegen.py 导入")


if __name__ == "__main__":
    main()

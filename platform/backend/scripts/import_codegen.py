# -*- coding: utf-8 -*-
"""codegen 录制脚本 → UI 平台用例导入器（规则库驱动版）。

流水线：AST 解析 → 表单识别（codegen_rules/*.json 的 detect）→ 元素库对齐
（缺失按规则内 strategies 自动补建）→ 过滤（登录段/噪音/菜单折叠）→ 逐语句
映射（nth/css/字面值规则 + 元素库 crossref）→ 增强（等待/confirm/toast
watchdog/查询断言）→ 三栏清单 → dry-run / --apply 落库。

与旧 import_playwright_script.py 的差异（能力沉淀方向）：
- 映射规则外置 codegen_rules/<form>.json：一个业务表单一份，含元素定位策略
  （自包含，换环境导入时自动补建缺失元素）、nth/css/字面值规则、按钮行为、
  探针配置；新增表单 = 新增一份 JSON，不动代码
- 节点动态切分：button_behaviors[*].role=node_split 或录制中途 goto 均开新节点
  （适配长链路录制），n1 恒为导航节点（goto+wait+进入按钮）
- 按钮行为数据驱动：confirm_watchdog（等待+confirm+成功看门狗，关键词来自
  规则）/ absorb（confirm 已接管）/ row_button（行内按钮）
- 未匹配元素的点击不再静默剔除：生成 click_text 步骤并进待复核（陌生表单
  先出可跑骨架，人工/探针再收敛）

evaluate 模板纪律（2026-10-29 教训）：看门狗/断言 JS 只按关键词拼装，模板串
永不重构——本地 page.evaluate 对含中文 JS 的验证跨进程不可信，以平台执行为准。

用法：
  python scripts/import_codegen.py record.py            # dry-run（默认）
  python scripts/import_codegen.py record.py --apply    # 落库（补元素+建用例+数据集+绑定）
  可选 --api http://127.0.0.1:8000/api --user admin --password admin123 --project-id 1
清单同时写入 <脚本名>_import_report.txt（UTF-8）。新表单先跑 scripts/form_probe.py。
"""
import argparse
import ast
import json
import os
import re
import sys
import urllib.request

RULES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "codegen_rules")

# 看门狗成功文案按钮集（与模板串一体，勿改格式）
NOISE_PRESS_KEYS = {"CapsLock", "Tab", "ControlOrMeta+a", "ControlOrMeta+A",
                    "ControlOrMeta+v", "ControlOrMeta+V"}  # 录制过程键，无业务语义（fill 前全选/粘贴冗余：fill 本身整值替换）
QUERY_DEFAULT = {"text": "查询", "placeholder": "请输入", "wait_ms": 500, "assert_field": "bl_no"}


# ---------- evaluate 模板（按关键词拼装，模板本身永不重构） ----------

def _watchdog_js(success_keys: list[str]) -> str:
    """与平台实证串逐字节一致（case 313/308）：双关键词=带括号 OR，单关键词=无括号。
    不用 f-string：{{}} 转义曾致多一个 '}' 使 return 落到顶层（SyntaxError）。"""
    if len(success_keys) == 1:
        cond, keys_msg, args = "t.indexOf('%s')>=0", "%s", (success_keys[0], success_keys[0])
    else:
        a, b = success_keys
        cond, keys_msg, args = "(t.indexOf('%s')>=0||t.indexOf('%s')>=0)", "%s/%s", (a, b, a, b)
    return (
        "(async()=>{const t0=Date.now(),dl=15000,ev=[],seenT=new Set(),hit=new Map();let ok=false;"
        "while(Date.now()-t0<dl&&!ok){"
        "document.querySelectorAll('.el-message-box button,.el-dialog button,[class*=dialog] button,"
        "[class*=message-box] button').forEach(b=>{if(!b.offsetParent)return;"
        "const t=(b.textContent||'').replace(/\\s+/g,'');"
        "if((t==='确定'||t==='继续提交'||t==='确认'||t==='提交'||t==='生效')&&hit.get(b)!==t&&!b.disabled){"
        "hit.set(b,t);b.click();ev.push([(Date.now()-t0)+'ms','click:'+t]);}});"
        "document.querySelectorAll('.el-message, body > div:not(#app) > p').forEach(e=>{"
        "const t=(e.textContent||'').trim();if(t&&!seenT.has(t)){seenT.add(t);"
        "ev.push([(Date.now()-t0)+'ms','toast:'+t]);"
        "if(" + cond + "){ok=true;}}});"
        "await new Promise(r=>setTimeout(r,200));}"
        "if(!ok){throw new Error('15s内未出现「" + keys_msg + "」提示，"
        "events='+JSON.stringify(ev));}"
        "return {ok:true,events:ev,url:location.href};})()"
    ) % args


def _tolerant_click_js(text: str, timeout_ms: int = 25000, route_leave: str = "") -> str:
    """宽容弹层点击守卫：目标按钮可能延迟出现（提交接口慢，普通 click 15s 硬等
    必死，#930 实证成功询问框晚于超时窗出现）也可能已随弹层消散/路由离开。
    轮询 JS 点掉可见按钮并验证消散；路由已离开 route_leave 片段直接成功；超时抛错。
    模板纪律同 _watchdog_js：纯拼接不用 f-string，无 ${} 序列。"""
    rl = ("if(location.hash.indexOf('" + route_leave + "')<0)"
          "{return{ok:true,clicked:false,note:'route-left:" + route_leave + "'};}") if route_leave else ""
    return (
        "(async()=>{const t0=Date.now(),dl=" + str(timeout_ms) + ";"
        "const vis=el=>!!(el&&el.offsetParent&&el.getBoundingClientRect().width>0);"
        "const btn=()=>[...document.querySelectorAll('.el-message-box__wrapper button,"
        ".el-dialog__wrapper button')].filter(b=>(b.textContent||'').replace(/\\s+/g,'')==='" + text + "'"
        "&&vis(b)&&!b.disabled)[0];"
        "while(Date.now()-t0<dl){" + rl +
        "const b=btn();"
        "if(b){b.click();await new Promise(r=>setTimeout(r,800));"
        "if(!btn()){return{ok:true,clicked:true,ms:Date.now()-t0};}}"
        "else{await new Promise(r=>setTimeout(r,500));}}"
        "throw new Error('" + str(timeout_ms) + "ms内未见可点的「" + text + "」弹层按钮且未离开路由');})()"
    )


def _query_assert_js(field: str) -> str:
    """查询结果自抛式断言：${field} 由运行期 _evaluate 注入后再进浏览器。
    轮询 10s（保存落库→列表可见有延迟，单次 300ms 扫描在慢提交下误报，
    run#908 n1 实证）；%s 拼装（f-string 续行普通字符串的 }} 不转义，曾致多一个 '}'）。"""
    return (
        "(async()=>{const t0=Date.now();"
        "while(Date.now()-t0<10000){"
        "if((document.body.innerText||'').indexOf('${%s}')>=0)"
        "{return{ok:true,bl_no_in_list:true,ms:Date.now()-t0};}"
        "await new Promise(r=>setTimeout(r,500));}"
        "throw new Error('查询后 10s 列表未出现单号 ${%s}（已轮询扫描列表首屏文本）');})()"
    ) % (field, field)


def norm_text(s: str) -> str:
    """按钮/文本归一化：去全部空白（「保 存」带空格形态）+ 去图标字体字形
    （Element-UI 图标是私有区字符，如「 查询」实际 role name 为 '\\ue778 查询'）。"""
    s = re.sub(r"\s+", "", s or "")
    return re.sub("[" + chr(0xE000) + "-" + chr(0xF8FF) + "]", "", s)


# ---------- AST 解析：摊平调用链 ----------

def flat_chain(node):
    """Call/Attribute 递归摊平为 token 列表（从内到外）。
    token: str（属性/方法名）| ('call', 方法名, pos, kw)"""
    if isinstance(node, ast.Call):
        inner = flat_chain(node.func)
        kw = {}
        for k in node.keywords:
            if isinstance(k.value, ast.Constant):
                kw[k.arg] = ast.literal_eval(k.value)
            elif k.arg == "has_text" and isinstance(k.value, ast.Call) \
                    and getattr(k.value.func, "attr", "") == "compile" \
                    and k.value.args and isinstance(k.value.args[0], ast.Constant):
                # has_text=re.compile('^财务管理$')：正则源串提取为字符串，_locator_of
                # 的 filter 分支据此归 kind=filtered_text（否则裸 css 'div' 误判）
                kw[k.arg] = ast.literal_eval(k.value.args[0])
        pos = [ast.literal_eval(a) for a in node.args if isinstance(a, (ast.Constant,))]
        return inner + [("call", inner[-1] if isinstance(inner[-1], str) else "?", pos, kw)]
    if isinstance(node, ast.Attribute):
        return flat_chain(node.value) + [node.attr]
    if isinstance(node, ast.Name):
        return [node.id]
    return []


def parse_script(path: str):
    """→ 按行序的语句列表 [{line, method, args, kw, locator, raw}]。"""
    tree = ast.parse(open(path, encoding="utf-8").read())
    stmts = []
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef) and fn.name == "run":
            for st in fn.body:
                if not isinstance(st, ast.Expr) or not isinstance(st.value, ast.Call):
                    continue
                chain = flat_chain(st.value)  # 传 Call 本身：最外层动作 meta 才入链
                call_meta = [c for c in chain if isinstance(c, tuple)]
                if not call_meta:
                    continue
                _, method, pos, kw = call_meta[-1]
                stmts.append({
                    "line": st.lineno, "method": method, "args": pos, "kw": kw,
                    "locator": _locator_of(chain), "raw": ast.unparse(st.value)[:120],
                })
    return stmts


def _locator_of(chain):
    """从摊平链提取定位器信息与 nth/first 下标。"""
    loc = {"nth": 0, "kind": "page"}
    for tok in chain:
        if not isinstance(tok, tuple):
            continue
        _, m, pos, kw = tok
        if m == "get_by_role":
            loc.update(kind="role", value=pos[0] if pos else "", name=kw.get("name", ""),
                       exact=bool(kw.get("exact")))
        elif m == "get_by_text":
            loc.update(kind="text", value=pos[0] if pos else "", exact=bool(kw.get("exact")))
        elif m in ("get_by_label", "get_by_placeholder", "get_by_test_id"):
            loc.update(kind=m.split("_", 2)[-1], value=pos[0] if pos else "")
        elif m == "locator":
            # filter(has_text=X).locator("span") 选项点击链（el-select 下拉
            # get_by_role("listitem").filter(has_text=...).locator("span")）：
            # 尾挂纯标签 span 不覆盖 filtered_text——否则过滤文本丢失，选项
            # 退化为无名 css 点击（客户管理·批量添加操作 实证）
            _css = pos[0] if pos else ""
            if not (_css == "span" and loc.get("kind") == "filtered_text"):
                loc.update(kind="css", value=_css)
        elif m == "filter":
            # locator('div').filter(has_text=re.compile('^财务管理$')) → 菜单组点击：
            # 按 has_text 正则文本识别（裸 css 'div' 直接点击会误中首个 div）
            pat = kw.get("has_text") or ""
            if isinstance(pat, str) and pat:
                loc.update(kind="filtered_text", value=pat.strip("^$"))
        elif m == "nth":
            loc["nth"] = pos[0] if pos else 0
        # .first 不必处理：nth 缺省即 0
    return loc


# ---------- 规则库 ----------

def load_rules_dir():
    """→ [rule dict]；codegen_rules 下每个 json 一份（坏文件跳过并告警）。"""
    out = []
    if not os.path.isdir(RULES_DIR):
        return out
    for fn in sorted(os.listdir(RULES_DIR)):
        if fn.endswith(".json"):
            try:
                out.append(json.load(open(os.path.join(RULES_DIR, fn), encoding="utf-8")))
            except (OSError, json.JSONDecodeError) as e:
                print(f"[warn] 规则文件损坏，跳过 {fn}: {e}")
    return out


def detect_form(stmts, rules_list):
    """录制语句 → 命中的规则。识别依据：detect.nav_link_texts（菜单链接名）或
    detect.route_contains（goto URL 子串）。返回 (rule, evidence) 或 (None, 线索)。"""
    link_names = {norm_text(s["locator"].get("name") or "")
                  for s in stmts if s["method"] == "click" and s["locator"].get("kind") == "role"
                  and s["locator"].get("value") == "link"}
    goto_urls = " ".join(str(s["args"][0]) for s in stmts if s["method"] == "goto" and s["args"])
    for r in rules_list:
        if r.get("stages"):  # 链式规则不参与单表单识别（--chain 显式指定）
            continue
        det = r.get("detect") or {}
        hit_link = next((t for t in det.get("nav_link_texts", []) if norm_text(t) in link_names), None)
        if hit_link:
            return r, f"菜单链接「{hit_link}」"
        rc = det.get("route_contains")
        if rc and rc in goto_urls:
            return r, f"goto 含「{rc}」"
    return None, f"链接点击:{sorted(t for t in link_names if t)} goto:{goto_urls[:120]}"


def rule_ekeys(rule):
    """规则引用的全部元素 key（补建对齐用）。单表单规则与链式 stage 通用。"""
    keys = set()
    # stage/rule 显式定义的元素本体也入列（无人引用也补建——如仅被 textbox
    # 按名匹配的「订单操作」下拉触发元素）
    keys.update((rule.get("elements") or {}).keys())
    for arr in (rule.get("nth_select_guesses") or {}).values():
        keys.add(arr[1])
    for arr in rule.get("text_input_rules") or []:
        keys.add(arr[2])
    for arr in (rule.get("css_picks") or {}).values():
        keys.add(arr[1])
    for arr in (rule.get("text_click_rules") or {}).values():
        keys.add(arr)
    for arr in (rule.get("textbox_picks") or {}).values():
        keys.add(arr[1])
    for arr in (rule.get("textbox_fills") or {}).values():
        keys.add(arr[1])
    for arr in (rule.get("css_fills") or {}).values():
        keys.add(arr[1])
    for arr in (rule.get("date_picks") or {}).values():
        keys.add(arr[1])
    for pat, ekey in (rule.get("css_click_patterns") or []):
        keys.add(ekey)
    for arr in (rule.get("radio_picks") or {}).values():
        keys.add(arr)
    for inj in rule.get("inject_steps") or []:
        for sp in inj.get("steps") or []:
            if sp.get("element_key"):
                keys.add(sp["element_key"])
        if inj.get("after_element"):
            keys.add(inj["after_element"])
        if inj.get("before_element"):
            keys.add(inj["before_element"])
    keys.update((rule.get("button_behaviors") or {}).keys())
    return keys


# ---------- 链式规则：多阶段分段 ----------

def _stmt_label(s):
    """语句的可点击文本归一化（role name / text value / filtered_text）。"""
    loc = s["locator"]
    return norm_text(loc.get("name") or loc.get("value") or "")


def _match_marker(s, marker):
    """语句是否命中阶段起点标记。kind：nav_link / goto_contains / button / text / text_startswith。"""
    kind, val = marker.get("kind"), marker.get("value")
    m, loc = s["method"], s["locator"]
    if kind == "nav_link":
        return (m == "click" and loc.get("kind") == "role" and loc.get("value") == "link"
                and norm_text(loc.get("name") or "") == norm_text(val))
    if kind == "goto_contains":
        return m == "goto" and s["args"] and val in str(s["args"][0])
    if kind == "button":
        return (m == "click" and loc.get("kind") == "role" and loc.get("value") == "button"
                and norm_text(loc.get("name") or "") == norm_text(val))
    if kind == "text":
        return m == "click" and loc.get("kind") == "text" and norm_text(loc.get("value") or "") == norm_text(val)
    if kind == "text_startswith":
        return (m == "click" and loc.get("kind") == "text"
                and norm_text(loc.get("value") or "").startswith(norm_text(val)))
    if kind == "filtered_text":
        # locator('div').filter(has_text=^财务管理$) 菜单组点击：与普通 text 语句同形不同类，
        # 需要区分锚定（如 tail 锚 L146 财务管理 而非同文本 L142/L145 的 tags 点击）
        return (m == "click" and loc.get("kind") == "filtered_text"
                and norm_text(loc.get("value") or "") == norm_text(val))
    return False


def _is_nav_click(s):
    """菜单类点击（文本/链接/过滤文本），供导航回溯重归属。"""
    return (s["method"] == "click"
            and s["locator"].get("kind") in ("text", "filtered_text")
            or (s["method"] == "click" and s["locator"].get("kind") == "role"
                and s["locator"].get("value") == "link"))


def segment_chain(stmts, stages):
    """录制语句 → [(stage, 语句片段)]。按 stages 顺序消费标记；标记命中的叶子导航
    前面的菜单组点击（财务管理/应收管理 等）回溯重归属为新阶段的导航段一并折叠。
    首标记之前的语句 = 登录段（整段剔除）。标记语句本身开启新阶段切片。"""
    slices, cur, si = [], [], 0
    login_stmts = []
    for s in stmts:
        if si < len(stages) and _match_marker(s, stages[si].get("start") or {}):
            stage = stages[si]
            fold = {norm_text(t) for t in stage.get("nav_click_texts") or []}
            # 回溯：把当前片段尾部的菜单组点击划给新阶段（导航折叠，不生成步骤）
            while cur and _is_nav_click(cur[-1]) and _stmt_label(cur[-1]) in fold:
                cur.pop()
            if si == 0:
                # 首标记之前 = 登录段（整段剔除）
                login_stmts = cur
            else:
                # cur 由上一阶段的标记语句开启，归属上一阶段
                slices.append((stages[si - 1], cur))
            cur = [s]
            si += 1
        else:
            cur.append(s)
    if si < len(stages):
        missing = [st["key"] for st in stages[si:]]
        raise SystemExit(f"链分段失败：阶段标记未命中 {missing}（检查 start 标记与录制实际语句）")
    slices.append((stages[-1], cur))
    return slices, login_stmts


# ---------- 平台 API ----------

class Platform:
    def __init__(self, api, user, password):
        self.api = api
        req = urllib.request.Request(
            f"{api}/auth/login",
            data=json.dumps({"username": user, "password": password}).encode(),
            headers={"Content-Type": "application/json"})
        self.token = json.load(urllib.request.urlopen(req, timeout=10))["token"]

    def req(self, method, path, body=None):
        r = urllib.request.Request(
            f"{self.api}{path}", method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.token}"})
        return json.load(urllib.request.urlopen(r, timeout=30))

    def elements(self, project_id):
        els = self.req("GET", f"/ui-elements?project_id={project_id}")
        return {(e["page_scope"], e["element_key"]): e for e in els}

    def groups(self, project_id):
        return self.req("GET", f"/case-groups?project_id={project_id}")

    def create_group(self, project_id, name):
        return self.req("POST", "/case-groups", {"project_id": project_id, "name": name})

    def environments(self, project_id):
        return self.req("GET", f"/environments?project_id={project_id}")

    def scope_labels(self, project_id):
        return self.req("GET", f"/page-scope-labels/map?project_id={project_id}")

    def create_element(self, project_id, scope, key, spec):
        return self.req("POST", "/ui-elements", {
            "project_id": project_id, "page_scope": scope, "element_key": key,
            "strategies": spec["strategies"],
            "description": (spec.get("description") or "")[:200]})  # 列宽 varchar(200)，超长即 500

    def update_element(self, element_id, spec):
        return self.req("PUT", f"/ui-elements/{element_id}", {
            "strategies": spec["strategies"],
            "description": (spec.get("description") or "")[:200]})  # 同上


def ensure_elements(pf, project_id, rule, elements):
    """规则引用而库中缺失的元素 → 按规则内 strategies 补建；
    已存在但 strategies 与规则漂移 → 就地更新（规则是唯一真相源，exec972 实证：
    ib_cancel_button css 修复后 apply 报「已更新」但库里旧 strategies 纹丝不动，
    线上仍按旧 css 执行超时）。→ (elements, 建了/更新了哪些)
    单表单规则用 rule.page.scope；链式规则逐 stage 各自域内补建。"""
    created = []
    scopes = [(st["scope"], st) for st in (rule.get("stages") or [])] \
        or [(rule["page"]["scope"], rule)]
    for scope, ctx in scopes:
        for key in sorted(rule_ekeys(ctx)):
            spec = (ctx.get("elements") or {}).get(key)
            if (scope, key) in elements:
                e = elements[(scope, key)]
                if spec and (e.get("strategies") or {}) != (spec.get("strategies") or {}):
                    pf.update_element(e["id"], spec)
                    e["strategies"] = spec["strategies"]
                    created.append(f"更新css #{e['id']} {scope}/{key}")
                continue
            if not spec:
                continue  # 无策略可补建：convert 阶段会进待复核
            e = pf.create_element(project_id, scope, key, spec)
            elements[(scope, key)] = e
            created.append(f"#{e['id']} {scope}/{key}")
    return elements, created


# ---------- 转换主流程 ----------

def convert(path, rule, elements, *, stmts=None, first_goto=None, no_split=False):
    """→ (nodes_steps[list[str, list[steps]], dataset, report[三栏])
    链式模式：stmts=分段后的语句列表（登录段已由 segment_chain 剔除）、
    first_goto=段首导航折叠成的数据集路由字段、no_split=阶段即节点（goto/node_split 不切节点）。"""
    stmts = parse_script(path) if stmts is None else stmts
    page = rule["page"]
    scope = page["scope"]
    behaviors = rule.get("button_behaviors") or {}
    query_cfg = {**QUERY_DEFAULT, **(rule.get("query") or {})}
    # 键两形态：str(nth)（该 nth 全程单现，s1/s9 旧形态）或 "nth@occ"（同 nth 多现，
    # 如应付开票向导屏1 nth(3)=结算对象、屏2 nth(3)=银行账号——nth 相同下拉不同，
    # 按 nth 单键映射必撞车：后者 pick 值覆盖前者 dataset 字段且元素锚错屏）
    guesses = dict(rule.get("nth_select_guesses") or {})
    nth_seen: dict[int, int] = {}
    keep, dropped, review = [], [], []
    nodes = [[]]
    dataset = {page["route_field"]: page["route_value"]}
    in_login = False
    login_done = False

    def el_ref(key):
        e = elements.get((scope, key))
        return {"element_id": e["id"]} if e else None

    def el_desc(key):
        e = elements.get((scope, key))
        return f"#{e['id']} {e['description']}" if e else f"{key}(库中无此元素!)"

    def new_node():
        nodes.append([])
        return nodes[-1]

    cur = nodes[0]
    i = 0
    while i < len(stmts):
        s = stmts[i]
        m, loc, line = s["method"], s["locator"], s["line"]
        arg0 = s["args"][0] if s["args"] else None
        label = norm_text(loc.get("name") or loc.get("value") or "")
        # role 定位器取可访问名（如「请输入关键词」），其余取定位值（css 等）
        _nk = (loc.get("name") or loc.get("value") or "") if loc.get("kind") == "role" \
            else (loc.get("value") or loc.get("name") or "")
        nth_key = f"{_nk}@{loc.get('nth', 0)}"

        # --- 登录段：goto /login 起，到菜单导航前全剔（平台环境注入会话） ---
        if m == "goto" and "/login" in str(arg0):
            in_login = True
            dropped.append((line, s["raw"], "登录段剔除：平台按环境配置自动注入会话（EnvTokenCache→cookie），用例无需表单登录"))
            i += 1
            continue
        if in_login and not login_done:
            if m == "click" and (norm_text(loc.get("name") or loc.get("value") or "") in
                                 {norm_text(t) for t in rule["nav_click_texts"]}):
                in_login = False
                login_done = True
                nodes[0].append({"action": "goto", "url": "${" + page["route_field"] + "}"})
                dropped.append((line, s["raw"], f"菜单导航折叠：合并为 goto ${{{page['route_field']}}}"))
            else:
                dropped.append((line, s["raw"], "登录段剔除（同上）"))
            i += 1
            continue

        # --- 导航折叠残影：登录段折叠产生的 goto ${route} 直达路由，
        #     紧随其后的菜单组/链接点击（nav_click_texts 命中）是同一导航
        #     的录制残影——剔除（客户管理实证：客商管理组点击折叠为 goto
        #     后，link 客户管理 再点击属重复导航） ---
        if m == "click" and login_done and cur and isinstance(cur[-1], dict) \
                and cur[-1].get("action") == "goto" \
                and str(cur[-1].get("url") or "").startswith("${") \
                and label and label in {norm_text(t) for t in rule["nav_click_texts"]}:
            dropped.append((line, s["raw"], "导航折叠：goto 已直达路由，菜单点击剔除"))
            i += 1
            continue

        # --- 阶段显式噪音按钮（上一步回退 / 取消关窗 等） ---
        if m == "click" and label and label in {norm_text(t) for t in rule.get("noise_buttons") or []}:
            dropped.append((line, s["raw"], f"阶段噪音按钮剔除：{label}（规则 noise_buttons 登记）"))
            i += 1
            continue

        # --- 中途 goto（长链路换页）→ 单表单模式开新节点；链式模式仅作步骤 ---
        if m == "goto":
            if not no_split and nodes[0]:
                cur = new_node()
            cur.append({"action": "goto", "url": str(arg0)})
            if cur is not nodes[0] or no_split:
                cur.append({"action": "wait", "value": 500})
            keep.append((line, s["raw"], f"goto → {arg0}"))
            i += 1
            continue

        # --- 录制噪音 / 收尾 ---
        if m == "press" and arg0 in NOISE_PRESS_KEYS:
            dropped.append((line, s["raw"], f"录制噪音剔除：press({arg0}) 为录制过程键，无业务语义"))
            i += 1
            continue
        if m == "press" and arg0 == "Escape" and cur and isinstance(cur[-1], dict) \
                and cur[-1].get("action") in ("pick", "popper_pick"):
            # pick 收尾 Esc：pick 运行时自带 Esc 收起（费用管理·关联客商/供应商
            # 录制形态：点选后按 Esc 关浮层）——裸 press 步骤多余且无浮层时
            # Esc 冒泡有关上层弹层风险
            dropped.append((line, s["raw"], "pick 收尾 Esc 剔除（pick 运行时自带 Esc 收起）"))
            i += 1
            continue
        if m in ("close",):
            dropped.append((line, s["raw"], "收尾剔除：browser/context/page.close 非业务步骤"))
            i += 1
            continue
        if m == "press":
            cur.append({"action": "press", "value": arg0})
            review.append((line, "press", f"press({arg0}) 已生成步骤；若需绑定元素请在画布确认"))
            i += 1
            continue

        # --- 文件上传（set_input_files：input[type=file]，upload_rules 按 nth_key
        #     锚元素与字段；值=文件中心名/绝对路径，运行期 _resolve_file_path 解析） ---
        if m == "set_input_files":
            up = (rule.get("upload_rules") or {}).get(nth_key)
            if up:
                fname, ekey = up[0], up[1]
                # value_overrides：链级覆写数据集文件值（如名称被文件中心
                # 同名坏文件遮蔽时，改引文件 id 走 _resolve_file_path 的整数分支）
                ov = (rule.get("value_overrides") or {}).get(fname)
                dataset[fname] = str(ov) if ov is not None else arg0
                cur.append({"action": "upload", "element": el_ref(ekey), "value": "${" + fname + "}"})
                keep.append((line, s["raw"],
                             f"upload {el_desc(ekey)} → ${{{fname}}}={dataset[fname]}（文件中心名/绝对路径）"
                             + (f"（链覆写 {arg0}→{ov}）" if ov is not None else "")))
            else:
                review.append((line, "upload",
                               "set_input_files 未配 upload_rules（nth_key 锚元素+字段），未生成步骤"))
            i += 1
            continue

        # --- 命名输入框 pick（textbox_picks：按 name@nth 键，如「编辑费用@0」「请输入关键词@0」） ---
        # 与 textbox_popper_picks 共用：扫描触发器 click 之后紧随的选项点击语句
        def _scan_option(start):
            j = start
            while j < len(stmts):
                t, tl = stmts[j], stmts[j]["locator"]
                if t["method"] == "fill":
                    j += 1
                    continue
                if t["method"] == "press":
                    # 录制过程键（CapsLock 等）穿插在 检索词 fill 与选项点击之间
                    # （用户大写锁定习惯分段输入）——跳过不判终止（请选择分支同款容错）
                    j += 1
                    continue
                if t["method"] == "click":
                    if tl.get("kind") == "text" and tl.get("value"):
                        return tl["value"], j + 1
                    if tl.get("kind") == "filtered_text" and tl.get("value"):
                        # filter(has_text=X).locator("span") 选项链：X 即选项文本
                        return tl["value"], j + 1
                    if tl.get("kind") == "role" and tl.get("value") in ("listitem", "list"):
                        return "__first_option__", j + 1
                return None, j
            return None, start

        if m == "click" and loc.get("kind") == "role" and loc.get("value") == "textbox" \
                and nth_key in (rule.get("textbox_popper_picks") or {}):
            # 控件替换型下拉（编辑费用类：选中后触发器整体消失，pick 的 input
            # 回读校验必假阴性）→ click 触发器 + popper_pick 浮层点选（乐观放行）
            fname, ekey = rule["textbox_popper_picks"][nth_key]
            option, j = _scan_option(i + 1)
            val = option or ""
            if option == "__first_option__":
                val = (rule.get("field_suggestions") or {}).get(fname, "")
                review.append((line, f"popper_pick {fname}", f"录制未录选项文本（点首项），值取建议「{val}」，请在画布确认"))
            dataset[fname] = val
            cur.append({"action": "click", "element": el_ref(ekey)})
            cur.append({"action": "popper_pick", "value": "${" + fname + "}"})
            keep.append((line, s["raw"], f"click+popper_pick {el_desc(ekey)} → ${{{fname}}}={val}（控件替换型下拉）"))
            for k in range(i + 1, j):
                dropped.append((stmts[k]["line"], stmts[k]["raw"], "并入上一条 popper_pick（点选由 popper_pick 完成）"))
            i = j
            continue
        if m == "click" and loc.get("kind") == "role" and loc.get("value") == "textbox" \
                and nth_key in (rule.get("textbox_picks") or {}):
            fname, ekey = rule["textbox_picks"][nth_key]
            option, j = _scan_option(i + 1)
            val = option or ""
            if option == "__first_option__":
                val = (rule.get("field_suggestions") or {}).get(fname, "")
                review.append((line, f"pick {fname}", f"录制未录选项文本（点首项），值取建议「{val}」，请在画布确认"))
            dataset[fname] = val
            cur.append({"action": "pick", "element": el_ref(ekey), "value": "${" + fname + "}"})
            keep.append((line, s["raw"], f"pick {el_desc(ekey)} → ${{{fname}}}={val}（命名输入框）"))
            for k in range(i + 1, j):
                dropped.append((stmts[k]["line"], stmts[k]["raw"], "并入上一条 pick（检索/点选由 pick 一体完成）"))
            i = j
            continue

        # --- 日期控件（date_picks：css 日期输入 + 后续点日期数字 → date 动作 fill+Enter） ---
        if m == "click" and loc.get("kind") == "css" and nth_key in (rule.get("date_picks") or {}):
            fname, ekey, cell = rule["date_picks"][nth_key]
            j = i + 1
            while j < len(stmts):
                t, tl = stmts[j], stmts[j]["locator"]
                if t["method"] == "click" and tl.get("kind") == "text":
                    j += 1
                    break  # 日历数字点击
                if t["method"] == "press":
                    j += 1
                    continue
                break
            dataset[fname] = cell
            cur.append({"action": "date", "element": el_ref(ekey), "value": "${" + fname + "}"})
            keep.append((line, s["raw"], f"date {el_desc(ekey)} → ${{{fname}}}={cell}"))
            for k in range(i + 1, j):
                dropped.append((stmts[k]["line"], stmts[k]["raw"], "并入 date（点选日期数字由 date 动作接管）"))
            i = j
            continue

        # --- 单选（radio_picks：role=radio 审批人/审批结论，按可访问名归一匹配） ---
        if m == "click" and loc.get("kind") == "role" and loc.get("value") == "radio" \
                and (rule.get("radio_picks") or {}):
            hit = next((k for k in rule["radio_picks"] if norm_text(k) == label), None)
            if hit:
                ekey = rule["radio_picks"][hit]
                cur.append({"action": "click", "element": el_ref(ekey)})
                keep.append((line, s["raw"], f"click {el_desc(ekey)}（单选 {hit}）"))
                i += 1
                continue

        # --- 超长文本点击剔除（页面区块误点，如审批中心整块表头文本） ---
        if m == "click" and loc.get("kind") == "text" and len(loc.get("value") or "") > 40:
            dropped.append((line, s["raw"], "超长文本点击剔除（页面区块误点，无业务语义）"))
            i += 1
            continue

        # --- 列表页检索框（placeholder 精确匹配）→ 查询流 ---
        if loc.get("kind") == "role" and loc.get("exact") \
                and norm_text(loc.get("name") or "") == norm_text(query_cfg["placeholder"]) \
                and m in ("click", "fill"):
            if m == "fill":
                hit = _match_text_rule(rule, arg0)
                fname = hit[0] if hit else query_cfg["assert_field"]
                cur.append({"action": "fill",
                            "element": {"strategy": "placeholder", "value": query_cfg["placeholder"]},
                            "value": "${" + fname + "}"})
                keep.append((line, s["raw"], f"查询框 fill → ${{{fname}}}（placeholder 精确匹配检索框）"))
            else:
                dropped.append((line, s["raw"], "查询框 click 并入 fill 语义（打开由 fill 接管）"))
            i += 1
            continue

        # --- 表单「请选择」下拉 → pick ---
        if loc.get("kind") == "role" and loc.get("name") == "请选择" and m in ("click", "fill"):
            nth = loc.get("nth", 0)
            occ = nth_seen.get(nth, 0)
            nth_seen[nth] = occ + 1
            j = i + 1
            search_txt = arg0 if m == "fill" else None
            option = None
            while j < len(stmts):
                t = stmts[j]
                tl = t["locator"]
                if t["method"] == "fill" and tl.get("name") == "请选择":
                    if search_txt is None:
                        search_txt = t["args"][0] if t["args"] else None
                    j += 1
                    continue
                if t["method"] == "press":
                    # 录制过程键（CapsLock 等）打断扫描会丢选项文本（css_picks 同款容错）
                    j += 1
                    continue
                if t["method"] == "fill" and tl.get("kind") == "role" \
                        and str(tl.get("name") or "").startswith("请输入"):
                    # 远程搜索下拉：检索词（「机电」「联」）是片段非真值，真值取
                    # 选项点击文本——检索 fill 一并吞并进 pick（pick 全名包含匹配）
                    j += 1
                    continue
                if t["method"] == "click":
                    if tl.get("kind") == "text" and tl.get("value"):
                        option = tl["value"]
                        j += 1
                        break
                    if tl.get("kind") == "role" and tl.get("value") in ("listitem", "list"):
                        option = "__first_option__"
                        j += 1
                        break
                    if tl.get("kind") == "css":
                        # .el-select-dropdown__item.hover > span = 点了高亮首项（录制惯用形态）
                        if ".el-select-dropdown__item" in (tl.get("value") or ""):
                            option = "__first_option__"
                            j += 1
                            break
                        break
                    if tl.get("name") == "请选择":
                        break
                    j += 1
                    continue
                break
            guess = guesses.get(f"{nth}@{occ}") or guesses.get(str(nth))
            if not guess:
                reason = (rule.get("nth_select_unresolved") or {}).get(str(nth),
                          "无映射规则（codegen_rules 未覆盖该下标），请跑 form_probe 选项反查后补规则")
                for k in range(i, j):
                    dropped.append((stmts[k]["line"], stmts[k]["raw"], f"待复核-未生成：{reason}"))
                review.append((line, f"请选择.nth({nth})", reason))
                i = j
                continue
            fname, ekey, conf = guess
            if option == "__first_option__":
                val = (rule.get("field_suggestions") or {}).get(fname, "")
                review.append((line, f"pick {fname}", f"录制未录选项文本（点首项），值取建议「{val}」，请在画布确认"))
            elif option is None and search_txt:
                val = search_txt
            else:
                val = option or ""
            dataset[fname] = val
            cur.append({"action": "pick", "element": el_ref(ekey), "value": "${" + fname + "}"})
            keep.append((stmts[i]["line"], stmts[i]["raw"],
                         f"pick {el_desc(ekey)} → ${{{fname}}}={val}（置信：{conf}）"))
            for k in range(i + 1, j):
                dropped.append((stmts[k]["line"], stmts[k]["raw"], "并入上一条 pick（点击/输检索词由 pick 一体完成）"))
            i = j
            continue

        # --- vxe 动态列 css 点击（css_click_patterns：col_XXXX 为会话级自增 id，
        #     按结构正则归一到稳定元素，复录不依赖列号） ---
        if m == "click" and loc.get("kind") == "css" and (rule.get("css_click_patterns") or []):
            hit = next(((pat, ekey) for pat, ekey in rule["css_click_patterns"]
                        if re.search(pat, loc.get("value") or "")), None)
            if hit:
                pat, ekey = hit
                cur.append({"action": "click", "element": el_ref(ekey)})
                keep.append((line, s["raw"], f"click {el_desc(ekey)}（vxe 列号归一：{pat}）"))
                i += 1
                continue

        # --- css 定位语句（逐条：fill 头查 css_fills；click 头查 css_picks 配对选项；
        #     尾随 fill 的聚焦 click 并入 fill；未命中单独待复核，不再整段吞并） ---
        if loc.get("kind") == "css" and m in ("click", "fill", "press"):
            css_val = loc.get("value") or ""
            # css_picks 已登记该选择器 → 本 click 是 pick 触发头，不能并入紧随的
            # 同位检索词 fill（费用管理·关联客商/供应商：click + fill「机电」+
            # 点选项——fill 是过滤片段非真值，pick 点选一体完成）
            css_pick_hit = _css_lookup(rule.get("css_picks") or {}, nth_key,
                                       css_val, loc.get("nth", 0), plain=True) \
                if m == "click" else None
            # 聚焦点击 + 同位 fill → 只留 fill
            if m == "click" and css_pick_hit is None:
                nxt = stmts[i + 1] if i + 1 < len(stmts) else None
                if nxt and nxt["method"] == "fill" and nxt["locator"].get("kind") == "css" \
                        and nxt["locator"].get("value") == css_val \
                        and nxt["locator"].get("nth", 0) == loc.get("nth", 0):
                    dropped.append((line, s["raw"], "css 聚焦点击并入后续 fill"))
                    i += 1
                    continue
            if m == "fill":
                css_fill = _css_lookup(rule.get("css_fills") or {}, nth_key,
                                       css_val, loc.get("nth", 0))
                if css_fill:
                    fname, ekey, cell = css_fill
                    dataset[fname] = cell
                    cur.append({"action": "fill", "element": el_ref(ekey), "value": "${" + fname + "}"})
                    keep.append((line, s["raw"], f"fill {el_desc(ekey)} → ${{{fname}}}（css 定位，单元格：{cell}）"))
                else:
                    review.append((line, s["raw"], "css fill 无映射规则（css_fills 未登记该选择器），未生成步骤"))
                i += 1
                continue
            if m == "press":
                dropped.append((line, s["raw"], "css press 剔除（录制过程键）"))
                i += 1
                continue
            # click 头：配对紧随的选项点击（允许中间隔 press / 下拉检索框 fill 噪声）
            j = i + 1
            option = None
            while j < len(stmts):
                t, tl = stmts[j], stmts[j]["locator"]
                if t["method"] == "press":
                    j += 1
                    continue
                if t["method"] == "fill" and tl.get("kind") == "css" and (
                        ".el-select-dropdown" in (tl.get("value") or "")
                        or "is-focus" in (tl.get("value") or "")
                        or (tl.get("value") == css_val
                            and tl.get("nth", 0) == loc.get("nth", 0))):
                    # 同位检索词 fill 是过滤片段（「机电」「芜湖」），真值取
                    # 选项点击/规则登记值（与 role 请选择分支的远程搜索容错同款）
                    j += 1
                    continue
                if t["method"] == "click":
                    if tl.get("kind") == "css" and ".el-select-dropdown__item" in (tl.get("value") or ""):
                        option = "__first_option__"
                        j += 1
                        break
                    if tl.get("kind") == "filtered_text":
                        option = tl.get("value")
                        j += 1
                        break
                    if tl.get("kind") == "role" and tl.get("value") in ("listitem", "list"):
                        option = "__first_option__"
                        j += 1
                        break
                    if tl.get("kind") == "text" and tl.get("value"):
                        option = tl["value"]
                        j += 1
                        break
                break
            css_pick = _css_lookup(rule.get("css_picks") or {}, nth_key,
                                   css_val, loc.get("nth", 0), plain=True)
            if css_pick:
                fname, ekey, val = css_pick
                dataset[fname] = val
                cur.append({"action": "pick", "element": el_ref(ekey), "value": "${" + fname + "}"})
                keep.append((line, s["raw"], f"pick {el_desc(ekey)} → ${{{fname}}}={val}（css 定位）"))
                for k in range(i + 1, j):
                    dropped.append((stmts[k]["line"], stmts[k]["raw"], "并入上一条 pick（点选由 pick 一体完成）"))
                i = j
                continue
            # css_fills 认识该选择器（任意下标）→ 聚焦点击并入后续 fill
            _cf = rule.get("css_fills") or {}
            if any(_norm_css(k.rsplit("@", 1)[0]) == _norm_css(css_val) for k in _cf):
                dropped.append((line, s["raw"], "css 聚焦点击并入后续 fill（css_fills 已登记该选择器）"))
                i += 1
                continue
            reason = rule.get("css_pick_unresolved",
                              "css 点击无映射规则（css_picks/css_click_patterns 未覆盖），待复核")
            for k in range(i, j):
                dropped.append((stmts[k]["line"], stmts[k]["raw"], f"待复核-未生成：{reason}"))
            review.append((line, f"css 点击 L{line}" + (f"-L{stmts[j - 1]['line']}" if j > i + 1 else ""),
                           reason))
            i = j
            continue

        # --- 表单单值输入（fill：textbox_fills 按 name@nth 优先，其次 text_input_rules 字面值） ---
        if m == "fill":
            hit = None
            if loc.get("kind") == "role" and loc.get("value") == "textbox":
                hit = (rule.get("textbox_fills") or {}).get(nth_key)
            hit = hit or _match_text_rule(rule, arg0)
            # 误录字面值优先于字段命中：同字段连填两遍（CapsLock 分段录入
            # 「测试新费用20261104」→「…ABCD」）时片段值虽也命中 textbox_fills，
            # 仍是误录——登记进 noise_fill_literals 即剔除，终值 fill 生成步骤
            if hit and str(arg0) in (rule.get("noise_fill_literals") or []):
                hit = None
            if hit:
                fname, ekey, cell = hit
                dataset[fname] = cell
                cur.append({"action": "fill", "element": el_ref(ekey), "value": "${" + fname + "}"})
                keep.append((line, s["raw"], f"fill {el_desc(ekey)} → ${{{fname}}}（数据集单元格：{cell}）"))
            elif str(arg0) in (rule.get("noise_fill_literals") or []):
                dropped.append((line, s["raw"], f"录制误录字面值剔除：{arg0}（后续 fill 已覆盖）"))
            else:
                review.append((line, s["raw"], "fill 无映射规则（字面值未登记 text_input_rules/textbox_fills），未生成步骤"))
            i += 1
            continue
        if m == "click" and loc.get("kind") == "role" and loc.get("value") == "textbox":
            # 仅当后随同位 fill 才并入（聚焦语义）；裸 textbox click 是下拉触发
            # （如详情页「订单操作」），按元素库 role=textbox 名匹配生成 click
            # 同位 fill 判定容错中间的录制噪音键（粘贴前 ControlOrMeta+V 等，
            # 客户管理检索框实证：click → Ctrl+V → fill 被判裸 click 出待复核）
            _k = i + 1
            while _k < len(stmts) and stmts[_k]["method"] == "press" \
                    and str(stmts[_k]["args"][0] if stmts[_k]["args"] else "") in NOISE_PRESS_KEYS:
                _k += 1
            nxt = stmts[_k] if _k < len(stmts) else None
            same_fill = bool(nxt and nxt["method"] == "fill"
                             and nxt["locator"].get("kind") == "role"
                             and nxt["locator"].get("value") == "textbox"
                             and norm_text(nxt["locator"].get("name") or "")
                             == norm_text(loc.get("name") or ""))
            if same_fill:
                dropped.append((line, s["raw"], "输入框 click 并入 fill（聚焦由 fill 接管）"))
            else:
                _tb = norm_text(loc.get("name") or "")
                ekey = next((k for (sc, k), e in elements.items()
                             if sc == scope and (e.get("strategies") or {}).get("role") == "textbox"
                             and norm_text(str((e.get("strategies") or {}).get("role_extra") or "")) == _tb), None)
                if ekey:
                    cur.append({"action": "click", "element": el_ref(ekey)})
                    keep.append((line, s["raw"], f"click {el_desc(ekey)}（下拉触发：textbox 按名匹配元素库）"))
                else:
                    review.append((line, s["raw"],
                                   "textbox click 无后续同位 fill 且元素库无此命名下拉元素，未生成步骤"))
            i += 1
            continue

        # --- pick 尾巴同文本第二击吞并：录制在同一下拉里 选项text点击 + list.filter(has_text=同文本)
        #     连击两下（record L224/L225 形态），请选择扫描在 text 处 break 后第二击成孤儿
        #     click_text——运行时选项已选、下拉已关，再点同文本必超时。上一条 pick 实值
        #     与本句 label 同文本即并入（选中后无再次点击该文本的合法场景）。
        #     popper_pick（注入流选选项）同款：value 是字面选项文本，直接比对
        if m == "click" and cur:
            # 回看最近 12 步内的 pick/popper_pick 实值（注入流的多个下拉选选之间
            # 隔着 wait/click/fill，孤儿第二击未必紧贴其 pick）；注入步骤是后处理
            # 插入的，主循环处理孤儿时 cur 里还没有——同扫本 stage 的 inject_steps
            # 声明值（exec957 L225：紧跟 radio 锚的注入流孤儿第二击）
            _recent_vals = []
            for _cs in reversed(cur[-12:]):
                if isinstance(_cs, dict) and _cs.get("action") in ("pick", "popper_pick"):
                    _pv = str(_cs.get("value") or "")
                    if _cs["action"] == "pick" and _pv.startswith("${") and _pv.endswith("}"):
                        _pv = str(dataset.get(_pv[2:-1], ""))
                    if _pv:
                        _recent_vals.append(norm_text(_pv))
            for _inj in (rule.get("inject_steps") or []):
                for _cs in (_inj.get("steps") or []):
                    if isinstance(_cs, dict) and _cs.get("action") in ("pick", "popper_pick"):
                        _pv = str(_cs.get("value") or "")
                        if _cs["action"] == "pick" and _pv.startswith("${") and _pv.endswith("}"):
                            _pv = str(dataset.get(_pv[2:-1], ""))
                        if _pv:
                            _recent_vals.append(norm_text(_pv))
            if label and label in _recent_vals:
                dropped.append((line, s["raw"], "并入上一条 pick（同文本第二击：选项已点选、下拉已关）"))
                i += 1
                continue

        # --- 按钮点击 → 元素库 crossref + 行为分发 ---
        if m == "click":
            # 规则显式指定（button_overrides）：crossref 字母序命中的库键未必是运行时
            # 可用的（如 button="提交" 实际可访问名 "提 交"），规则可强制指元素。
            # 原文精确命中优先于归一化匹配：「确 认」与「确认」归一后同为「确认」，
            # 但同链路是两个不同弹窗的按钮（变更弹窗 footer vs 审批人弹窗 footer），
            # 只有原文能区分（客商关系·变更特殊账期截转规则实证）
            _raw = str(loc.get("name") or loc.get("value") or "")
            _ov = next((k for k in (rule.get("button_overrides") or {}) if k == _raw), None) \
                or next((k for k in (rule.get("button_overrides") or {}) if norm_text(k) == label), None)
            ekey = rule["button_overrides"][_ov] if _ov else _crossref_button(elements, scope, label)
            # 文本/过滤文本点击 → 规则显式指定元素（如「订单费用」tab、「合并开票」span）
            if not ekey and loc.get("kind") in ("text", "filtered_text") and (rule.get("text_click_rules") or {}):
                hit = next((k for k in rule["text_click_rules"] if norm_text(k) == label), None)
                if hit:
                    ekey = rule["text_click_rules"][hit]
            if ekey:
                # --- 连击归一（规则白名单 dedup_clicks）：紧邻重复点击同一元素
                #     只留一次。exec1047 n22 实证：录制双击「编辑」=importEl 弹窗
                #     重开重置，fill 落到被换掉的旧 textarea，确定时弹窗校验不过
                #     不关→后续步骤全被 wrapper 拦截。必须白名单：s20「确定」
                #     同为相邻双击但是真·两步确认（box1→box2），n21 四轮全绿实证
                #     静态不可分辨。仅当上一条生成步骤仍是同元素的 click/js_click
                #     才折叠——中间隔任何其他步骤（wait/fill/pick…）都不折叠 ---
                if ekey in (rule.get("dedup_clicks") or []) \
                        and cur and isinstance(cur[-1], dict) \
                        and cur[-1].get("action") in ("click", "js_click") \
                        and cur[-1].get("element") == el_ref(ekey):
                    dropped.append((line, s["raw"],
                                    f"连击归一：同一元素紧邻重复 click 只留一次（{el_desc(ekey)}）"))
                    i += 1
                    continue
                b = behaviors.get(ekey, {"role": "click"})
                role = b.get("role", "click")
                # --- confirm 主按钮回声吸收：提交按钮（确 定）触发 $confirm 二次确认
                #     弹窗（渲染需 250~500ms），录制者在弹窗里补点的「确定」与提交
                #     按钮同 label 同元素——再分发一套 click+confirm+watchdog 会在
                #     保存成功自动回列表后死等不存在的按钮。近 4 步内已有本元素的
                #     confirm 增强时按弹窗回声吸收（exec1091/1092 实证：裸
                #     click_text 确定 在弹窗渲染前落回底栏按钮，弹窗到死无人答，
                #     十余步全绿但 userEdit 从未发出）
                if role == "confirm_watchdog" \
                        and label in {"确定", "确认", "继续提交"} \
                        and any(isinstance(st, dict) and st.get("action") == "confirm"
                                for st in cur[-4:]):
                    dropped.append((line, s["raw"],
                                    "确定弹窗点击剔除：已由前置 confirm/watchdog 接管（同元素回声）"))
                    i += 1
                    continue
                if role == "node_split" and not no_split:
                    cur.append({"action": "click", "element": el_ref(ekey)})
                    keep.append((line, s["raw"], f"click {el_desc(ekey)}（节点切分点，其后进新节点）"))
                    cur = new_node()
                elif role == "absorb":
                    dropped.append((line, s["raw"], "确定弹窗点击剔除：已由 confirm 动作接管（自适应主按钮）"))
                elif role == "row_button":
                    fname = b.get("row_field", query_cfg["assert_field"])
                    cur.append({"action": "row_button", "value": b.get("value", "编辑"),
                                "row": "${" + fname + "}"})
                    keep.append((line, s["raw"], f"row_button {b.get('value', '编辑')}（row=${fname} 限定检索结果行）"))
                elif role == "confirm_watchdog":
                    cur.append({"action": "click", "element": el_ref(ekey)})
                    keep.append((line, s["raw"], f"click {el_desc(ekey)}"))
                    keys = b.get("watchdog") or ["操作成功"]
                    cur.append({"action": "wait", "value": b.get("wait_ms", 800)})
                    cur.append({"action": "confirm"})
                    cur.append({"action": "evaluate", "value": _watchdog_js(keys)})
                    keep.append((line, s["raw"] + " (增强)",
                                 f"增强：wait {b.get('wait_ms', 800)}ms + confirm + evaluate watchdog 断言「{'/'.join(keys)}」15s"))
                elif role == "watchdog_after":
                    # 本点击即弹窗确认（前置已选 radio 审批人/结论），confirm 不适用：
                    # watchdog JS 自适应点击后续 确定/确认 弹窗并断言成功文案
                    cur.append({"action": "click", "element": el_ref(ekey)})
                    keep.append((line, s["raw"], f"click {el_desc(ekey)}"))
                    keys = b.get("watchdog") or ["操作成功"]
                    cur.append({"action": "wait", "value": b.get("wait_ms", 800)})
                    cur.append({"action": "evaluate", "value": _watchdog_js(keys)})
                    keep.append((line, s["raw"] + " (增强)",
                                 f"增强：wait {b.get('wait_ms', 800)}ms + evaluate watchdog 断言「{'/'.join(keys)}」15s（自适应点后续弹窗）"))
                elif role == "js_click":
                    # 页面主按钮 stability 死等：骨架屏/加载动画让按钮持续重排
                    # （exec955 n14 实证 resolved+visible+enabled 全过但 element is
                    # not stable 15s 超时）——JS el.click() 绕过可点击性校验
                    cur.append({"action": "js_click", "element": el_ref(ekey)})
                    keep.append((line, s["raw"] + " (JS)",
                                 f"js_click {el_desc(ekey)}（绕过 stability 死等）"))
                elif role == "tolerant_click":
                    # 弹层按钮延迟出现/可能已消散：普通 click 15s 硬等会死
                    # （#930 提交接口慢，成功询问框晚于超时窗出现）。改宽容守卫：
                    # 轮询 JS 点掉可见目标+验证弹层消散；路由离开即成功。
                    cur.append({"action": "wait", "value": b.get("wait_ms", 300)})
                    cur.append({"action": "evaluate",
                                "value": _tolerant_click_js(b.get("text", label),
                                                            b.get("timeout_ms", 25000),
                                                            b.get("route_leave", ""))})
                    keep.append((line, s["raw"] + " (宽容)",
                                 "evaluate 宽容点击守卫「" + (b.get("text") or label) + "」：轮询 "
                                 + str(b.get("timeout_ms", 25000)) + "ms 点掉可见弹层按钮"
                                 + ("（route_leave=" + b["route_leave"] + "）" if b.get("route_leave") else "")))
                else:
                    cur.append({"action": "click", "element": el_ref(ekey)})
                    keep.append((line, s["raw"], f"click {el_desc(ekey)}"))
                # 跨页按钮水合等待：row_button/切分点点击常触发整页路由跳转，目标
                # 表单靠详情 API 异步水合（userDetail 类），零等待紧跟 fill+确定会
                # 撞必填校验静默失败——十步全绿但保存未落库（exec1090 实证：列表
                # 行更新戳停留早前人工操作）。按钮行为声明 wait_after_ms 即追加等待
                if b.get("wait_after_ms"):
                    cur.append({"action": "wait", "value": b["wait_after_ms"]})
                    keep.append((line, "wait",
                                 f"跨页水合等待 {b['wait_after_ms']}ms（{el_desc(ekey)} 后）"))
                i += 1
                continue
            # 查询按钮 → click_text + 查询增强
            if label == norm_text(query_cfg["text"]):
                cur.append({"action": "click_text", "value": query_cfg["text"]})
                fname = query_cfg["assert_field"]
                cur.append({"action": "wait", "value": query_cfg["wait_ms"]})
                cur.append({"action": "evaluate", "value": _query_assert_js(fname)})
                keep.append((line, s["raw"] + " (增强)",
                             f"click_text {query_cfg['text']} + wait {query_cfg['wait_ms']}ms + evaluate 断言列表出现 ${{{fname}}}"))
                i += 1
                continue
            # confirm 增强后的显式确定点击 → 吸收（含 watchdog 尾巴：
            # [...,click,wait,confirm,evaluate] 里 watchdog 的自适应点击
            # 已点掉确定弹窗，run#911 n4 实证后续显式 确认 点击成冗余死等）
            recent = [st for st in cur[-2:] if isinstance(st, dict)]
            if any(st.get("action") == "confirm" for st in recent) \
                    and label in {"确定", "确认", "继续提交"}:
                dropped.append((line, s["raw"], "确定弹窗点击剔除：已由前置 confirm/watchdog 接管"))
                i += 1
                continue
            # 未匹配 → click_text 兜底（陌生表单先出可跑骨架；literal_map 换动态变量）
            if label:
                # text_click_rules 兜底映射：kind 非 text/filtered_text 的复杂定位器
                # （如 role+filter+placeholder 链）上方 kind 门控进不来，此处按 label 精确映射
                _tcr_hit = next((k for k in (rule.get("text_click_rules") or {})
                                 if norm_text(k) == label), None)
                if _tcr_hit:
                    _ekey = rule["text_click_rules"][_tcr_hit]
                    cur.append({"action": "click", "element": el_ref(_ekey)})
                    keep.append((line, s["raw"], f"click {el_desc(_ekey)}（text_click_rules 兜底映射）"))
                    i += 1
                    continue
                # role 定位器文本=可访问名（:449 _nk 同序）；value 是角色名（link/button），
                # 先取 value 会生成 click_text "link" 这种废步骤（exec1087 实证）
                tv = (loc.get("name") or loc.get("value") or "") if loc.get("kind") == "role" \
                    else (loc.get("value") or loc.get("name") or "")
                mapped = _apply_literal_map(rule, tv)
                cur.append({"action": "click_text", "value": mapped})
                keep.append((line, s["raw"], f"click_text {mapped}（未匹配元素库，按文本点击）"))
                if mapped != tv:
                    keep.append((line, "literal_map", f"字面值 → 变量：{tv} ⇒ {mapped}"))
                else:
                    review.append((line, f"click_text {label}", "元素库无此按钮：请在元素库登记或跑 form_probe 后重导"))
            else:
                dropped.append((line, s["raw"], "点击无可用文本/元素引用，剔除"))
            i += 1
            continue

        dropped.append((line, s["raw"], "未识别语句，剔除"))
        i += 1

    # 元素库缺失引用兜底
    for nid, sts in enumerate(nodes, 1):
        for st in sts:
            if st.get("element") is None and "element" in st:
                review.append((0, f"n{nid}/{st['action']}", "元素库缺失引用（element=None）：请补齐元素或规则内 strategies 后重试"))
    if nodes and nodes[0]:
        if first_goto:
            nodes[0].insert(0, {"action": "goto", "url": "${" + first_goto + "}"})
        if nodes[0] and nodes[0][0].get("action") == "goto":
            nodes[0].insert(1, {"action": "wait", "value": 500})  # goto 后页面稳定
    # 去掉空的尾节点（node_split 后无后续语句时）
    nodes = [n for n in nodes if n]
    return nodes, dataset, (keep, dropped, review)


def _match_text_rule(rule, val):
    for lit, fname, ekey, cell in rule.get("text_input_rules") or []:
        if lit == val:
            return fname, ekey, cell
    return None


def _apply_literal_map(rule, text):
    """录制字面值 → 数据集变量（如 订单 lele1030002 ⇒ 订单 ${bl_no}），复录不依赖具体单号。"""
    for lit, var in (rule.get("literal_map") or {}).items():
        if lit and lit in str(text):
            return str(text).replace(lit, var)
    return text


def _norm_css(css):
    """css 里的会话级自增 id 归一（el-table_N / column_N / col_N），复录不依赖动态列号。"""
    s = css or ""
    s = re.sub(r"el-table_\d+", "el-table_N", s)
    s = re.sub(r"column_\d+", "column_N", s)
    s = re.sub(r"(?<![a-zA-Z_])col_\d+", "col_N", s)
    return s


def _css_lookup(table, nth_key, css_val, nth, plain=False):
    """css_picks/css_fills 键查表：nth_key（css@nth，fills 用）或整串 css（picks 用）精确优先，
    未命中按 _norm_css 归一后匹配（规则键写 el-table_3_column_18 也能匹配复录的 el-table_5_...）。"""
    if not table:
        return None
    if plain:
        if css_val in table:
            return table[css_val]
        for k, v in table.items():
            if _norm_css(k) == _norm_css(css_val):
                return v
        return None
    if nth_key in table:
        return table[nth_key]
    want = _norm_css(css_val)
    for k, v in table.items():
        head, _, tail = k.rpartition("@")
        if head and tail == str(nth) and _norm_css(head) == want:
            return v
    return None


def _crossref_button(elements, scope, label_norm):
    """归一化文本 → 元素库 key（strategies.text/button/toast 匹配，限本域）。"""
    for (esc, ekey), e in elements.items():
        if esc != scope:
            continue
        st = e.get("strategies") or {}
        for sk in ("text", "button", "toast"):
            if sk in st and norm_text(str(st[sk])) == label_norm:
                return ekey
    return None


# ---------- 清单与落库 ----------

def render_report(path, rule, keep, dropped, review, created_elements):
    scope_info = (rule.get("page") or {}).get("scope") \
        or f"链式 {len(rule.get('stages') or [])} 阶段"
    L = [f"===== codegen 导入转换清单：{path} =====",
         f"规则：{rule['form_id']}（{scope_info}）｜实证：{rule.get('proven', '未实证')}", ""]
    if created_elements:
        L.append(f"----- 元素自动补建/更新（{len(created_elements)}）-----")
        for c in created_elements:
            L.append(f"  {c}")
        L.append("")
    L.append(f"----- 保留（{len(keep)}）-----")
    for line, raw, note in keep:
        L.append(f"  L{line:<3} {raw[:70]:<72} {note}")
    L.append(f"----- 已剔除（{len(dropped)}，可回补）-----")
    for line, raw, note in dropped:
        L.append(f"  L{line:<3} {raw[:70]:<72} {note}")
    L.append(f"----- 待复核（{len(review)}）-----")
    for line, what, note in review:
        L.append(f"  L{line:<3} {what:<28} {note}")
    return "\n".join(L)


def build_case(rule, nodes_steps):
    page = rule["page"]
    scope, label = page["scope"], page["scope_label"]
    labels = page.get("node_labels") or []

    def node(nid, idx, steps):
        desc = labels[idx - 1] if idx <= len(labels) else f"阶段{idx}"
        return {"id": nid, "label": desc, "position": {"x": 80 + (idx - 1) * 260, "y": 60},
                "data": {"desc": desc, "label": label, "scope": scope,
                         "step_type": "ui", "ui_action": "steps", "ui_steps_len": len(steps)}}

    dag_nodes = [node(f"n{i}", i, sts) for i, sts in enumerate(nodes_steps, 1)]
    edges = [{"id": f"e{i}", "source": f"n{i}", "target": f"n{i + 1}"}
             for i in range(1, len(nodes_steps))]
    n1a = page.get("n1_assert") or {}
    n1_asserts = ([{"type": "json_path_contains", "path": "$.url",
                    "expected": n1a["url_contains"], "message": n1a["message"]}]
                  if n1a.get("url_contains") else [])
    configs = [{"node_id": f"n{i}", "step_type": "ui",
                "ui_params": {"scope": scope, "steps": sts},
                "pre_process": [], "post_extract": [],
                "assertions": n1_asserts if i == 1 else [], "wait_after_ms": 0}
               for i, sts in enumerate(nodes_steps, 1)]
    return {"nodes": dag_nodes, "edges": edges}, configs


def build_chain_case(rule, stage_nodes):
    """链式：[(stage, steps)] → dag/configs。每节点独立页面域（平台保存期强校验
    跨域绑定），节点 data.scope=stage.scope；n1 断言取链级 n1_assert。"""
    nodes, configs = [], []
    for idx, (stage, sts) in enumerate(stage_nodes, 1):
        desc = stage.get("label") or stage["key"]
        nodes.append({"id": f"n{idx}", "label": desc,
                      "position": {"x": 80 + (idx - 1) * 260, "y": 60},
                      "data": {"desc": desc, "label": stage.get("scope_label") or desc,
                               "scope": stage["scope"], "step_type": "ui",
                               "ui_action": "steps", "ui_steps_len": len(sts)}})
        asserts = []
        if idx == 1:
            a = rule.get("n1_assert") or {}
            if a.get("url_contains"):
                asserts = [{"type": "json_path_contains", "path": "$.url",
                            "expected": a["url_contains"], "message": a["message"]}]
        configs.append({"node_id": f"n{idx}", "step_type": "ui",
                        "ui_params": {"scope": stage["scope"], "steps": sts},
                        "pre_process": [], "post_extract": [], "assertions": asserts,
                        "wait_after_ms": stage.get("wait_after_ms", 0)})
    edges = [{"id": f"e{i}", "source": f"n{i}", "target": f"n{i + 1}"}
             for i in range(1, len(stage_nodes))]
    return {"nodes": nodes, "edges": edges}, configs


def convert_chain(script_path, rule, elements):
    """链式规则 → (stage_nodes, dataset, 分阶段三栏)。"""
    stmts = parse_script(script_path)
    slices, login_stmts = segment_chain(stmts, rule["stages"])
    stage_nodes, dataset = [], {}
    keep, dropped, review = [], [], []
    keep.append((0, f"[登录段] {len(login_stmts)} 条", "登录段剔除：平台按环境注入会话（链式首标记之前）"))
    for stage, seg in slices:
        if stage.get("skip"):
            dropped.extend((st["line"], st["raw"], f"[{stage['key']}] 截断丢弃（后续阶段未导入）")
                          for st in seg)
            continue
        # 全局键（literal_map/cell_overrides/query 等）继承进阶段，stage 同名键覆盖
        # ——否则 click_text 兜底的字面值换变量（订单 leleXXX ⇒ 订单 ${bl_no}）不生效
        pseudo = {**{k: v for k, v in rule.items() if k not in ("stages", "case")}, **stage}
        rf = stage.get("route_field") or f"{stage['key']}_route"
        pseudo["page"] = {"scope": stage["scope"], "scope_label": stage.get("scope_label") or stage["key"],
                          "route_field": rf, "route_value": stage.get("route_value") or ""}
        # 段首导航折叠：marker 为 nav_link 时剥离段首菜单点击，goto 由 first_goto 注入
        fold = {norm_text(t) for t in stage.get("nav_click_texts") or []}
        k = 0
        while k < len(seg) and _is_nav_click(seg[k]) and _stmt_label(seg[k]) in fold:
            dropped.append((seg[k]["line"], seg[k]["raw"], f"[{stage['key']}] 菜单导航折叠 → goto ${{{rf}}}"))
            k += 1
        seg = seg[k:]
        fg = rf if (stage.get("start", {}).get("kind") == "nav_link" and stage.get("route_value")) else None
        nodes, ds, (k1, d1, r1) = convert(script_path, pseudo, elements,
                                          stmts=seg, first_goto=fg, no_split=True)
        # 查询前置注入（pre_query）：录制时目标单在列表首行、段内无查询动作，
        # 复跑时列表被历史单占据 → row_button 的 vxe 兜底只认首行（run#690 实证）。
        # 注入 fill+查询+wait，把列表收敛到目标单再执行段内首个行内按钮。
        pq = stage.get("pre_query")
        if pq and nodes and nodes[0]:
            pre = [{"action": "fill",
                    "element": {"value": pq.get("placeholder", "请输入"), "strategy": "placeholder"},
                    "value": "${" + pq["field"] + "}"},
                   {"action": "click_text", "value": "查询"},
                   {"action": "wait", "value": pq.get("wait_ms", 800)}]
            j = 0
            while j < len(nodes[0]) and nodes[0][j].get("action") in ("goto", "wait"):
                j += 1
            nodes[0][j:j] = pre
            keep.append((0, f"[{stage['key']}] 查询前置注入",
                         f"fill ${{{pq['field']}}} + 查询 + wait {pq.get('wait_ms', 800)}ms"
                         f"（列表收敛到目标单，row_button 依赖首行）"))
        # 任意位置步骤注入（inject_steps）：录制漏录/校验必需的联动选择
        # （如费用表 应用子策略 未选 → 策略标识=异常 → 保 存 被必填校验拒）。
        # after_element=元素键：插到该元素 click 步之后；dataset=注入变量取值。
        for inj in stage.get("inject_steps") or []:
            anchor = inj.get("after_element")
            before = inj.get("before_element")
            a_id = (elements.get((stage["scope"], anchor or before)) or {}).get("id") \
                if (anchor or before) else None
            for sts in nodes:
                pos = next((k for k, sp in enumerate(sts)
                            if a_id and (sp.get("element") or {}).get("element_id") == a_id), None)
                if pos is None:
                    continue
                built = []
                for sp in inj.get("steps") or []:
                    sp = dict(sp)
                    ek = (sp.pop("element_key", None) or "")
                    if ek:
                        e = elements.get((stage["scope"], ek))
                        sp["element"] = {"element_id": e["id"]} if e else None
                    built.append(sp)
                at = pos if before else pos + 1
                sts[at:at] = built
                keep.append((0, f"[{stage['key']}] 步骤注入（{(before or anchor)} {'前' if before else '后'}）",
                             " + ".join(f"{s['action']} {s.get('value', '')}" for s in built)))
                for k, v in (inj.get("dataset") or {}).items():
                    dataset[k] = v
                break
        for sts in nodes:
            stage_nodes.append((stage, sts))
        dataset.update(ds)
        # 三栏记账必须留在切片循环内：曾经误缩进进 cell_overrides 循环，
        # 只剩最后阶段的 k1/d1/r1 且标签错挂（stage 为循环残留变量），按 cell_overrides
        # 条数重复入账——节点无损（stage_nodes 循环内构建），纯报告错乱
        keep.extend((ln, raw, f"[{stage['key']}] {note}") for ln, raw, note in k1)
        dropped.extend((ln, raw, f"[{stage['key']}] {note}") for ln, raw, note in d1)
        review.extend((ln, raw, f"[{stage['key']}] {note}") for ln, raw, note in r1)
    # 单元格覆盖：录制选项文案 ≠ 可用检索词（如远程搜索下拉 fill 整串无结果），
    # 规则 cell_overrides 给出短检索词（pick 按包含匹配点选项、双向包含校验）
    for k, v in (rule.get("cell_overrides") or {}).items():
        dataset[k] = v
    return stage_nodes, dataset, (keep, dropped, review)


def resolve_group(pf, project_id: int, rule: dict) -> int | None:
    """分组按名解析（跨库不依赖自增 id）：group_name 不存在则建；缺省回退 group_id。"""
    name = rule["case"].get("group_name")
    if not name:
        return rule["case"].get("group_id")
    for g in pf.groups(project_id):
        if norm_text(g.get("name") or "") == norm_text(name):
            return g["id"]
    g = pf.create_group(project_id, name)
    print(f"[group] 线上缺分组「{name}」，已创建 #{g['id']}")
    return g["id"]


def resolve_env(pf, project_id: int, rule: dict, env_id: int | None) -> int | None:
    """环境绑定：--env-id 显式优先，其次规则 case.env.base_url_contains 模糊匹配。"""
    if env_id:
        return env_id
    hint = (rule["case"].get("env") or {}).get("base_url_contains")
    if not hint:
        return None
    for e in pf.environments(project_id):
        if hint in (e.get("base_url") or ""):
            return e["id"]
    sys.exit(f"环境解析失败：project {project_id} 下无 base_url 含「{hint}」的环境"
             "（--env-id 显式指定）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("script")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--api", default="http://127.0.0.1:8000/api")
    ap.add_argument("--user", default="admin")
    ap.add_argument("--password", default="admin123")
    ap.add_argument("--project-id", type=int, default=1)
    ap.add_argument("--env-id", type=int, help="显式指定环境 id（默认按规则 env.base_url_contains 解析）")
    ap.add_argument("--chain", help="链式规则 form_id/路径（规则含 stages，一条录制 → 多阶段多节点用例）")
    ap.add_argument("--variant", help="仅应用名称包含此子串的变体（规则 variants 声明；缺省全部）")
    args = ap.parse_args()

    rules_list = load_rules_dir()
    if not rules_list:
        sys.exit(f"规则库为空：{RULES_DIR} 下无 json。新表单先跑 scripts/form_probe.py 生成草稿规则")

    if args.chain:
        p = args.chain if os.path.exists(args.chain) else os.path.join(RULES_DIR, args.chain)
        if not p.endswith(".json"):
            p += ".json"
        rule = json.load(open(p, encoding="utf-8"))
        pf = Platform(args.api, args.user, args.password)
        elements = pf.elements(args.project_id)
        elements, created = ensure_elements(pf, args.project_id, rule, elements)
        stage_nodes, dataset, (keep, dropped, review) = convert_chain(args.script, rule, elements)
        dag, configs = build_chain_case(rule, stage_nodes)

        report = render_report(args.script, rule, keep, dropped, review, created)
        out = f"{args.script}_chain_report.txt"
        with open(out, "w", encoding="utf-8") as f:
            f.write(report + "\n\n===== 预览 case JSON =====\n"
                    + json.dumps({"dag_config": dag, "node_configs": configs,
                                  "dataset_fields": dataset}, ensure_ascii=False, indent=1))
        print(report)
        print(f"\n[链式] {rule['form_id']}：{len(rule['stages'])} 阶段标记，"
              f"生成 {len(stage_nodes)} 节点：" + " | ".join(
                  f"n{i} {st.get('label', st['key'])}·{len(sts)}步" for i, (st, sts) in enumerate(stage_nodes, 1)))
        print(f"数据集字段 {len(dataset)}：{json.dumps(dataset, ensure_ascii=False)}")
        print(f"清单已写 {out}")
        # 变体：一条真源按 stop_after 截断生成多条用例（如 收款核销/付款核销/穿透核销 三条）。
        # 无 variants 声明 = 单用例全阶段（旧行为）；--variant 子串过滤仅应用匹配变体
        variants = rule.get("variants") or [{}]
        if args.variant:
            variants = [v for v in variants
                        if args.variant in (v.get("name") or rule["case"]["name"])]
            if not variants:
                sys.exit(f"--variant 无匹配变体：{args.variant}")
        if not args.apply:
            names = [v.get("name") or f"{rule['case']['name']}（全阶段）" for v in variants]
            print(f"dry-run 结束（--apply 落库；变体 {len(variants)} 条：{names}）")
            return
        group_id = resolve_group(pf, args.project_id, rule)
        env_id = resolve_env(pf, args.project_id, rule, args.env_id)
        _sync_scope_labels(pf, args.project_id, rule)
        stage_keys = [s["key"] for s in rule["stages"]]
        for v in variants:
            stop = v.get("stop_after")
            v_nodes = stage_nodes[:stage_keys.index(stop) + 1] if stop else stage_nodes
            v_rule = dict(rule)
            v_case = dict(rule["case"])
            if v.get("name"):
                v_case["name"] = v["name"]
            if v.get("description"):
                v_case["description"] = v["description"]
            v_rule["case"] = v_case
            v_dag, v_configs = build_chain_case(v_rule, v_nodes)
            print(f"[变体] {v_case['name']}：{len(v_nodes)} 节点"
                  + (f"（stop_after={stop}）" if stop else "（全阶段）"))
            _apply_case(pf, args.project_id, group_id, env_id, v_rule, v_dag, v_configs, dataset,
                        ds_desc="codegen 链式导入（值取录制字面量；生成规则在单元格）")
        return

    stmts = parse_script(args.script)
    rule, evidence = detect_form(stmts, rules_list)
    if not rule:
        sys.exit(f"未识别表单（{evidence}）。\n请在 {RULES_DIR} 补规则：可先跑 "
                 "python scripts/form_probe.py --route <hash路由> --add-button <按钮文本> --draft <form_id> 生成草稿")

    pf = Platform(args.api, args.user, args.password)
    elements = pf.elements(args.project_id)
    elements, created = ensure_elements(pf, args.project_id, rule, elements)
    nodes_steps, dataset, (keep, dropped, review) = convert(args.script, rule, elements)
    dag, configs = build_case(rule, nodes_steps)

    report = render_report(args.script, rule, keep, dropped, review, created)
    out = f"{args.script}_import_report.txt"
    with open(out, "w", encoding="utf-8") as f:
        f.write(report + "\n\n===== 预览 case JSON =====\n"
                + json.dumps({"dag_config": dag, "node_configs": configs,
                              "dataset_fields": dataset}, ensure_ascii=False, indent=1))
    print(report)
    print(f"\n[识别] {rule['form_id']} ← {evidence}")
    print(f"清单已写 {out}")
    print("节点结构：" + " | ".join(f"n{i} {len(sts)}步" for i, sts in enumerate(nodes_steps, 1))
          + f"｜数据集字段 {len(dataset)}")
    print(f"数据集字段：{json.dumps(dataset, ensure_ascii=False)}")

    if not args.apply:
        print("dry-run 结束（--apply 落库）")
        return

    group_id = resolve_group(pf, args.project_id, rule)
    env_id = resolve_env(pf, args.project_id, rule, args.env_id)
    _sync_scope_labels(pf, args.project_id, rule)
    _apply_case(pf, args.project_id, group_id, env_id, rule, dag, configs, dataset)
    print(f"复核入口：画布 /cases/designer（待复核 {len(review)} 项见清单）")


def _sync_scope_labels(pf, project_id, rule):
    """规则携带的页面域中文语义写入 page_scope_labels（仅 --apply 路径调用，dry-run 绝不写）。

    来源：全局 rule["scope_labels"]（中间段映射，如 merchantManage→客商管理）
    + 链式各 stage / 单表单 rule["page"] 的 (scope, scope_label)。
    与线上 map 比对，只提交新增或不同的项（规则为准——同 ensure_elements 语义；
    语义表本就不校验叶子，中间段路径可直接写，两处页面域树按累加路径即时显示）。"""
    cand = dict(rule.get("scope_labels") or {})
    stages = rule.get("stages")
    if stages:
        for st in stages:
            if st.get("scope") and st.get("scope_label"):
                cand[st["scope"]] = st["scope_label"]
    elif (rule.get("page") or {}).get("scope") and (rule["page"].get("scope_label")):
        cand[rule["page"]["scope"]] = rule["page"]["scope_label"]
    if not cand:
        return
    have = pf.scope_labels(project_id)
    items = [{"page_scope": s, "label": str(l)} for s, l in cand.items()
             if str(have.get(s) or "") != str(l)]
    if not items:
        return
    res = pf.req("POST", "/page-scope-labels/batch", {"project_id": project_id, "items": items})
    for it in items:
        print(f"[语义] {it['page_scope']} → {it['label']}")
    print(f"[语义] 页面域语义写入 {res.get('count', len(items))} 条")


def _apply_case(pf, project_id, group_id, env_id, rule, dag, configs, dataset, ds_desc=None):
    """幂等落库：同项目同名用例已存在则 PUT 更新 + 数据集行同步；否则 POST 新建。
    链式/单表单分支共用（调试回合反复 apply 不堆新用例）。→ (case_id, dataset_id)"""
    # 空转换守卫：总步数 0 时 PUT 会把既有用例清成空节点（dag.nodes 有壳无步），
    # 运行时 0 步执行还记 SUCCESS（exec1089 实证「空心成功」）。宁可拒绝落库
    # 也不清空——空转换几乎必是规则问题（nav_click_texts 出口锚未命中 → 整段
    # 录制被当登录段剔除；或元素全未匹配），人工核对三栏清单后再来。
    total_steps = sum(len(((c.get("ui_params") or {}).get("steps")) or []) for c in configs)
    if total_steps == 0:
        sys.exit("拒绝落库：转换结果 0 步（全部语句被剔除）。--apply 会把同名用例清空，"
                 "且 0 步执行记 SUCCESS（exec1089 实证）。排查：三栏清单里登录段是否吞了"
                 "全部语句（nav_click_texts 出口锚未命中）？规则元素/文本是否全未匹配？")
    body = {
        "project_id": project_id, "group_id": group_id, "env_id": env_id,
        "name": rule["case"]["name"], "description": rule["case"]["description"],
        "dag_config": dag, "node_configs": configs}
    existing = next((c for c in pf.req("GET", f"/testcases?project_id={project_id}")
                     if norm_text(c.get("name") or "") == norm_text(rule["case"]["name"])), None)
    if existing:
        case = pf.req("PUT", f"/testcases/{existing['id']}", body)
        ds_id = case.get("dataset_id") or existing.get("dataset_id")
        if ds_id:
            ds = pf.req("GET", f"/datasets?project_id={project_id}")
            ds_id = next((d["id"] for d in ds if d["id"] == ds_id), None) or ds_id
            pf.req("PUT", f"/datasets/{ds_id}/rows", {"rows": [dataset]})
        else:
            ds_id = _create_dataset(pf, project_id, case["id"], rule, dataset, ds_desc)
            pf.req("PUT", f"/testcases/{case['id']}", {"dataset_id": ds_id})
        print(f"APPLIED(更新): case #{case['id']} → dataset #{ds_id} 已同步"
              f"（group={group_id} env={env_id}）")
    else:
        case = pf.req("POST", "/testcases", body)
        ds_id = _create_dataset(pf, project_id, case["id"], rule, dataset, ds_desc)
        pf.req("PUT", f"/testcases/{case['id']}", {"dataset_id": ds_id})
        print(f"APPLIED: case #{case['id']} → dataset #{ds_id} 已绑定"
              f"（group={group_id} env={env_id}）")
    return case["id"], ds_id


def _create_dataset(pf, project_id, case_id, rule, dataset, ds_desc=None):
    ds = pf.req("POST", "/datasets", {
        "case_id": case_id, "name": rule["case"]["name"] + "·数据",
        "description": ds_desc or "codegen 录制导入（值取录制字面量；生成规则在单元格）"})
    pf.req("PUT", f"/datasets/{ds['id']}/rows", {"rows": [dataset]})
    return ds["id"]


if __name__ == "__main__":
    main()

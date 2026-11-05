# 用例维护手册：从一段录制到一个绿勾

> 写给谁：往平台里喂录制、想让新流程自己跑起来的人。
> 读完你能独立完成：**录一段新流程 → 导入成用例 → 首次转正 → 执行自测 → 挂了自己排障 → 防止重导入回退**。
>
> 配套阅读：`docs/codegen-import.md` 是纪律全集（22 条实测教训，偏进阶）；本手册负责把日常 90% 的
> 场景讲成人话。两边冲突时以 codegen-import.md 为准。

---

## 0. 三分钟世界观：平台怎么"读懂"一条用例

把一条 UI 用例想象成一场舞台剧，平台里有四个角色：

| 平台概念 | 剧场比喻 | 是什么 |
|---|---|---|
| **用例（画布）** | 整场剧的分幕图 | 一张 DAG 图：节点连成流程，从哪幕演到哪幕 |
| **节点 = 页面域** | 舞台分区 | 每个节点绑定一个页面（如 `merchantManage/customer` 客户管理），节点里的步骤都发生在这个页面上 |
| **元素库** | 道具登记表 | 页面上每个要操作的控件登记一条：名字 + 怎么找到它（placeholder / 按钮文字 / css）。步骤只引用登记号（element_id），不自己写定位 |
| **数据集** | 台词本 | 所有会变的值（客户名、经办人、单号……）集中成表格。步骤里写 `${字段名}`，执行时换成台词本里的真值 |

一条用例的一生：

```
你在浏览器里操作一遍            导入器翻译成平台语言              平台照着演
┌──────────────┐   ┌───────────────────────────┐   ┌──────────────────┐
│ playwright    │   │ import_codegen.py          │   │ 点「执行」按钮     │
│ codegen 录制  │ → │ 录制语句 → 步骤 + 元素 +     │ → │ 无头浏览器逐步演   │
│ (record.py)   │   │ 数据集 + 断言/看门狗        │   │ 每步留痕·截图      │
└──────────────┘   └───────────────────────────┘   └──────────────────┘
     人话剧本            平台四件套落库                  绿勾 / 红叉+现场证据
```

**两套环境，谁听谁的：**

| | 线上（唯一源） | 本地（镜像） |
|---|---|---|
| 后端 API | `<线上API地址>`（见运维记录，不写进仓库） | `http://127.0.0.1:8000/api` |
| 前端 | `<线上前端地址>` | `http://[::1]:5173` |
| 账号 | 平台登录账号（同前端登录页） | 同左 |

> ⚠️ 本仓库带公网镜像，**任何地址/密码都不落进文档**——线上 API 地址、数据库连接方式统一放运维记录。

规矩：**用例全部直接在线上做**，一轮成功后整库覆盖回本地存档。别在两边各改各的，会分叉。

---

## 1. 录制：源头录得好，后面全省心

在 fin-ui-test 仓库根目录，用 venv 里的 playwright 起录制器（URL 换成业务系统登录页）：

```bash
cd D:/CODE/PyCharm/pythonProject/fin-ui-test
.venv/Scripts/python.exe -m playwright codegen --target python <业务系统地址> -o record.py
```

会弹出浏览器，正常登录、正常操作，做完关窗，`record.py` 就生成在仓根。

**录制七军规**（每条都是为了导入器能看懂）：

1. **像给新人演示一样操作**：慢半拍、点准了再点，别滑手滑出多余 hover。
2. **只做业务动作**：登录、输验证码都正常录（导入器会自动剔掉登录段）。
3. **下拉要点选项本身**，别在选项里犹豫来回切换。
4. **确认框要点掉**（确定/继续提交），录制里没点的确认框，导入器只能靠规则猜。
5. **别中途刷新页面、别用浏览器回退**——SPA 会把录制搞乱。
6. **录到链路终点**（比如最终 toast「操作添加完成」出现）再停，最后一步的成功反馈是断言的证据。
7. 录完可肉眼扫一遍 `record.py`：一眼看到奇怪的点击（点到菜单外、点了两遍）就重录，比导入后排障省十倍时间。

**导入器会自动剔的噪音**：登录段全部语句、菜单导航（折叠成一句 goto）、`Tab`/`CapsLock`/全选粘贴等过程键、pick 收尾 Esc。
**会保留的**：其他 `press` 键会变成步骤（所以别乱按无关键）。

---

## 2. 已知表单复录：五分钟一键导入（日常 90% 场景）

表单在 `platform/backend/scripts/codegen_rules/` 里已有规则（一表单一分 json）时，就是无脑三步。

### 2.1 先 dry-run 看清单（不动库）

```bash
cd platform/backend
PYTHONUTF8=1 ../../.venv/Scripts/python.exe scripts/import_codegen.py ../../record.py
```

终端会打出**三栏清单**，同时写入 `record.py_import_report.txt`：

| 栏 | 意思 | 你要做什么 |
|---|---|---|
| **保留** | 每条录制语句 → 生成了什么步骤 | 扫一眼有没有 `(增强)` 标记（自动加的等待/看门狗是好事） |
| **已剔除** | 哪些语句被丢了 + 为什么 | 确认理由合理（登录段/噪音键），**有业务动作被剔就要查** |
| **待复核** | 导入器拿不准、按建议值填了的 | 逐条确认建议值对不对（常见：点首项的下拉，值取了 field_suggestions） |

### 2.2 apply 落库（写线上）

```bash
PYTHONUTF8=1 ../../.venv/Scripts/python.exe scripts/import_codegen.py ../../record.py \
    --apply --api <线上API地址>
```

一条命令做四件事：**补建缺失元素 → 建用例（进规则指定的分组）→ 建数据集并填值 → 绑定环境**。
元素按 strategies 内容匹配，不依赖 id，所以同一规则本地线上都能导。

### 2.3 执行自测 + 看报告

平台前端：用例详情 → 执行 → 报告页逐步看 facts、截图、录屏（环境开了录屏的话）。
或 API（排障时更顺手；以本地为例，线上把地址换掉即可）：

```bash
# 1) 登录拿 token（密码即平台登录密码，勿写进任何脚本/文档）
curl -s -X POST http://127.0.0.1:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"<账号>","password":"<密码>"}'
# 2) 执行（注意 body 必须带 case_id）
curl -s -X POST http://127.0.0.1:8000/api/testcases/298/execute \
  -H "Authorization: Bearer <token>" -H 'Content-Type: application/json' \
  -d '{"case_id":298}'
# 3) 轮询结果
curl -s http://127.0.0.1:8000/api/executions/<执行id> -H "Authorization: Bearer <token>"
```

> **案例复盘 · case298「三连挂」**：2026-11-04 一键导入的「为客户批量添加操作人员」连挂三次
> （exec1075/1076/1077）。第一挂是引擎对 fixed 定位浮层的可见性误判（当天已修，不用你管）；
> 第二、三挂才是主角——**多选下拉点完选项浮层不收起，恰好压住弹窗的「确定」按钮**，
> Playwright 的点击点落在浮层上，重试 15 秒死等超时。这个坑已经焊死在导入器里
> （规则 `popper_pick_esc` 自动在点选后补一个按 Esc 收浮层的步骤），同类表单不会再犯。
> 识别特征见第 4 章症状 A。

---

## 3. 新表单首次转正：从草稿到"已实证"

新表单没有规则，需要人工转正一次（约 30 分钟～半天），之后该表单的所有复录都回到第 2 章的五分钟流程。

### 3.1 先跑探针（非破坏，只看不动）

```bash
cd platform/backend
PYTHONUTF8=1 ../../.venv/Scripts/python.exe scripts/form_probe.py \
    --env 1 --route '#/xxx/yyy' --add-button 新建X --draft my_form
```

产出：`codegen_rules/my_form.json` 草稿 + `my_form.fingerprint.json` 表单指纹（每个下拉的真实选项清单）。
探针只开下拉读选项就 Esc，**绝不点保存**。

### 3.2 照 _todo 清单转正草稿

草稿里带 `_todo` 标记，逐项换成人话（字段语义对着指纹的选项反查）：

| 规则字段 | 人话 | 转正要点 |
|---|---|---|
| `detect.nav_link_texts` | 靠哪几个菜单名认出这个表单 | 写菜单组名+叶子名，如 `["客商管理","客户管理"]` |
| `elements` | 本表单的道具登记表 | 每个:key 一条 strategies（placeholder=输入框提示语 / button=按钮文字 / css=结构定位）+ 中文描述 |
| `textbox_fills` | 哪个输入框填哪个变量 | `"提示语@第几个": [数据集字段, 元素key, 默认值]` |
| `textbox_popper_picks` | 哪个下拉选哪个变量 | 同上格式；**多选下拉再加 `popper_pick_esc` 登记它**（点完不收浮层的都要登记） |
| `button_behaviors` | 按钮按下后会发生什么 | `confirm_watchdog`（点完弹确认框等 toast，最常用）/ `node_split`（长链路切节点）/ `absorb` / `row_button`；watchdog 关键词写**业务真实 toast 文案** |
| `field_suggestions` | 录制只点了首项时的建议值 | 写稳定选项文本（人名类选不会改名的） |
| `case`/`page` | 用例名/分组/路由 | `group_name` 按名解析，两库通用 |

### 3.3 自测到链路终点（保存过 ≠ 链路通）

用第 2 章姿势导入并执行。**转正标准：流程走到业务终点**（最终 toast/落库生效），不是"保存成功"就收工——
委托订单 314 的教训：服务项目两个下拉保存时根本不校验，到分发那步才必填，只测保存会漏雷。

### 3.4 收尾

通过后：把规则里 `proven` 字段更新成本次实证记录（时间+关键发现，给未来的自己），删掉 `_todo`。
规则文件从此入库，这张表单就"认识"了。

---

## 4. 排障 Playbook：挂了先翻这张表

### 4.0 通用三板斧（顺序别乱）

1. **看现场**：报告页逐步 facts / 失败步截图（截图里"有模态浮层悬空"是重大线索）；API 党看
   `GET /api/executions/{id}` 里 `response_body.error` 和 steps 数组。
2. **翻旧案**：查两边库的执行史，这条用例以前绿过没有？绿过的 step facts 就是标准答案
   （断言、取值直接抄历史证据，别急着重跑）：

```sql
SELECT id,status,started_at FROM execution_records WHERE case_id=298 ORDER BY id DESC LIMIT 10;
```

3. **才动刀**：改步骤/改数据集之前，先确认这次改动真的对症（问自己：改完重跑会不会有不可逆副作用？）。

### 4.1 症状速查表

| # | 症状（报错关键字） | 最可能病因 | 药方 | 真实案例 |
|---|---|---|---|---|
| A | `Timeout ... intercepts pointer events`，重试 15s 超时 | 有浮层没关，挡在要点的按钮上（最常见：**多选下拉**点完不收起；也查确认框/下拉悬空） | 点按钮前先收浮层：pick 后补 `press Escape` 步骤并**绑定触发器元素**；其他浮层用 confirm/清理步骤 | 298 exec1076/1077 |
| B | 步骤**全绿但业务没生效**（没落库/没跳转） | 确认框竞速"空心绿"：提交按钮触发的 $confirm 弹窗渲染要 250~500ms，紧跟的点击落空 | 给提交按钮挂 `confirm_watchdog`（规则 button_behaviors）；看终态截图有没有模态悬空 | 294 exec1090/1091 |
| C | `8s 内未见浮层选项`（popper_pick） | 下拉根本没被打开（检查前一步的点击）；或选项文本不精确（值必须=选项 label） | 先看开下拉的 click 步骤是否成功；数据集值改成下拉里真实存在的精确文本 | 298 exec1075 |
| D | pick 报「input 值仍为 X」，且 X 是你想要的一部分 | 下拉选中后输入框显示的是**选项 label**，不是你看到的拼接文本；验证用精确相等 | 数据集里放**选项 label 本身**（单词条），别放"名称+代码"拼接串 | carrier：`ACL` 绿、`大西洋航运ACL` 挂（exec1066） |
| E | `查询后 10s 列表未出现` | 远端检索下拉/搜索框对拼接串查不到数据（服务端按整串 LIKE） | 同上：检索词用单个可命中词 | 11-02 SUT 发版后 ds175/177/179 |
| F | toast「检测到必填项未填写」但页面上看不到缺啥 | 联动父列没选导致子列异常；或**服务端必填**（DOM 无标记） | 先查联动列（选了父列子列才正常）；服务端必填抓保存接口的响应看逐字段原因，别信 toast 笼统文案 | 293 应用子策略 / 314 补贴类别 |
| G | **昨天绿、今天红**，一批用例一起挂 | 大概率不是你的问题——SUT（业务系统）发版了 | `curl -sI <业务系统地址>` 看 Last-Modified，或比对前端 assets js 指纹；确认后按新交互改 | 11-02 16:26 SUT 发版改承运人检索 |
| H | 节点尾 url 断言**偶发**挂 | SPA 跳转竞态：点完按钮 URL 在跳转前后两态间抖 | url 断言取两态路由的**公共子串**（如 `entrustedOrder` 同时匹配列表页和建单页） | 288 run898 |
| I | goto 之后整页变登录页 | 单会话互踢：探针/执行/手工登录共用一个业务账号 | 被踢后等 ≥90s 再执行；执行在跑时**别手工登业务系统** | — |

### 4.2 破案示范：教你像查案一样读一次失败

以 298 第二挂（exec1076）为例，完整推理链：

1. `error` 说 `步骤12·click Timeout`，call log 里反复出现
   `<li class="el-select-dropdown__item"> ... intercepts pointer events`——**有个下拉选项 li 一直挡路**。
2. 往上看步骤 11 是 `popper_pick 张乐UI` 且 success——选项点中了，但这个下拉是
   `el-select-dropdown is-multiple`（**多选**）：多选下拉点完选项**不自动收起**。
3. 结论：不是元素定位错、不是等待不够，是**浮层挡路**——对症药就是症状 A 的 press Escape。
4. 反面教材：当时把 Esc 插在了点确定**之后**，既救不了第 12 步，还差点和"确定→自动 $confirm
   变更确认框"打架（Esc 可能取消确认）。**Esc 要插在 pick 和 click 之间**，并绑定下拉元素。

### 4.3 看失败的三种姿势

- **前端报告页**：最直观，逐步绿红、facts、截图、录屏（环境需开 video）。
- **API**：`GET /api/executions/{id}` → `response_body.error`（失败原因）+ `response_body.steps`（每步 facts）。
- **直查库**（两库同构，执行史线上最全；连接方式见运维记录，密码用 `MYSQL_PWD` 环境变量传，
  `%` 在各 shell 转义不一，`-p` 直传必踩坑）：

```bash
MYSQL_PWD='<密码>' mysql -h <库地址> -P <端口> -u <账号> fin_ui_test \
  --default-character-set=utf8mb4 -e "SELECT response_body FROM step_records WHERE execution_id=<执行id>\G"
```

> Windows 注意：含中文输出别走管道，先落盘再用 `PYTHONUTF8=1 python` 读。

---

## 5. 重导入防回退清单

**为什么会回退**：部分数据集值是导入器**从录制文本重新生成**的——你后来在平台上手工改过，一旦重导入
又会被录制里的旧值覆盖回去。所以：**每次 `--apply` 之后，过一遍下面的清单**。

| 项 | 症状 | 处理 | 状态 |
|---|---|---|---|
| 远端检索类下拉值 | 拼接串检索无数据（症状 D/E） | 数据集单元格改单词条（如 `ACL`） | 每次重导入后检查 |
| `p_recv_amt_b`（293 链） | 金额被重置回录制旧值 6.3 | 平台上把该数据集单元格改回 `0.90` | 每次重导入后检查 |
| 多选下拉收浮层 Esc | 症状 A 拦截 | ~~手工补~~ **已焊死**：规则 `popper_pick_esc` 生成端自动补 | 无需再管 |

**对比法验收**（重导入后快速确认没带回脏东西）：拿 dry-run 生成的步骤和库里已验证的用例做
sort_keys 逐步 JSON 对比，完全一致才算干净（工具链的老方法论）。

---

## 6. 军规红线（每条都是真金白银换的）

| 红线 | 一句话为什么 |
|---|---|
| 执行在跑时，别登业务系统、别跑探针 | 同账号单会话互踢，goto 即挂 |
| 探针只读不写，绝不点保存 | 业务库是大家的 |
| 新用例优先选**幂等**的业务动作（追加/重复执行无害） | 自测要反复跑，别把业务数据跑脏 |
| UI 用例**不支持断点续跑** | 节点重放会重复不可逆动作（按钮点一次就消失类）；失败就整条重跑 |
| 含 UI 用例的方案并发 ≤2 | 浏览器槽位就 2 个，多了 400 |
| 线上有执行 running 时**别 push main** | CI 部署会重启后端 = 杀执行 |
| 数据修复要**两库同步**（线上 API + 本地 API） | 只修一边必然分叉 |
| evaluate/看门狗模板**只按关键词拼装，永不手改结构** | 含中文 JS 跨进程行为不稳，模板改动必上平台真跑验证 |
| 对业务行为拿不准，**问，别猜** | 猜出来的步骤会让你排障一晚上（293 币制 USD≠CNY 教训） |

---

## 7. 速查卡

### 7.1 动作语义表（步骤里 action 的含义，执行引擎实测口径）

| action | 干什么 | 常用参数 |
|---|---|---|
| `goto` | 打开路由（hash 路由=BASE+'/'+route） | `url` |
| `wait` | 等待；带 element 则等元素可见 | `value`(ms) |
| `fill` | 清空后整值填入 | `value`、`element` |
| `type` | 真实键盘逐字敲（自定义组件无视 fill 时用） | `value`、`element` |
| `click` / `js_click` | 点元素 / JS 直点（绕过 stability 死等） | `element` |
| `click_text` | 按文字点按钮/链接（「保 存」空格自动归一） | `value`，可选 `match/contains`、`index` |
| `pick` | Element 下拉：点开→(可检索)→选→**自动 Esc 收起**（单选用这个） | `value`、`element` |
| `popper_pick` | 浮层选项点选（不负责开下拉也不负责收浮层；**多选必配 press Esc**，规则已自动化） | `value` |
| `press` | 按键；**绑 element 更稳**（先聚焦再按） | `value`（如 `Escape`/`Enter`）、`element` |
| `check` / `uncheck_all` | 勾选 / 批量取消勾选 | `element` |
| `confirm` | 自适应点弹窗主按钮（确定/确认/继续提交…择优）；带 `wait` 标志=轮询等晚出的弹窗，带 `optional`=只点「继续提交」类、无弹窗则跳过 | 可选 `wait`/`optional` |
| `save` | 保存一体化：点保存→弹窗就点确定→2s 补点→等成功 toast | 可选 `element`、期望 toast |
| `row_button` | 表格行内按钮（可按 `row` 关键字限定行） | `value`、`row` |
| `search` | 列表检索一体化（重置→填→查询→等结果行） | 见引擎 |
| `toast_watch` | 轮询断言 toast（异步成功提示的专用判据） | `value` |
| `evaluate` | 跑一段 JS（就绪等待/看门狗断言都靠它） | `value`(JS 串) |
| `upload` | 传文件（文件中心ID/绝对路径/文件名，逗号分隔多个） | `value`、`element` |
| `date` | Element 日期选择（fill+Enter） | `value`、`element` |
| `screenshot` | 截图留证 | — |

### 7.2 命令速查（Windows / git-bash）

```bash
# 录制（仓根，URL=业务系统登录页）
.venv/Scripts/python.exe -m playwright codegen --target python <业务系统地址> -o record.py

# 导入 dry-run（platform/backend 下）
PYTHONUTF8=1 ../../.venv/Scripts/python.exe scripts/import_codegen.py ../../record.py
# 导入落库——线上
PYTHONUTF8=1 ../../.venv/Scripts/python.exe scripts/import_codegen.py ../../record.py \
    --apply --api <线上API地址>
# 导入落库——本地（默认 --api 即本地，可省）
PYTHONUTF8=1 ../../.venv/Scripts/python.exe scripts/import_codegen.py ../../record.py --apply

# 新表单探针
PYTHONUTF8=1 ../../.venv/Scripts/python.exe scripts/form_probe.py --env 1 \
    --route '#/xxx/yyy' --add-button 新建X --draft my_form

# 本地后端起停（需要写本地库时）
cd platform/backend && ../../.venv/Scripts/python.exe -m uvicorn app.main:app --port 8000
```

### 7.3 数据集取值三句话

1. 步骤里引用变量写 `${字段名}`（数据集按用例绑定，执行取当前行的值）。
2. 数据集单元格可以整格写生成规则（如 `${generate_bl_no(prefix='UI')}`），执行时求值——适合单号类。
3. 会变的值**一律进数据集**，别写死在步骤里；重导入会重置数据集值，改完记得过第 5 章清单。

---

*手册版本：2026-11-05（基于 case298 exec1075~1078 排障实录整理；排障细节与 22 条完整纪律见
`docs/codegen-import.md`）。*

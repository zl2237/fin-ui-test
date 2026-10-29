import axios from 'axios'
import { startProgress, doneProgress } from '@/utils/requestProgress'

const http = axios.create({
  baseURL: '/api',
  timeout: 60000,
  // 数组参数序列化为重复键（key=1&key=2），匹配 FastAPI 的 List Query 解析；
  // axios 默认的 key[]=1 格式后端不识别，会导致过滤参数被静默忽略
  paramsSerializer: {
    serialize: (params) => {
      const sp = new URLSearchParams()
      for (const [key, value] of Object.entries(params)) {
        if (value === undefined || value === null) continue
        if (Array.isArray(value)) {
          value.forEach((v) => sp.append(key, String(v)))
        } else {
          sp.append(key, String(value))
        }
      }
      return sp.toString()
    },
  },
})

// 扩展 axios config：silent=true 时跳过顶部进度条（用于轮询请求避免频繁闪烁）
declare module 'axios' {
  export interface AxiosRequestConfig {
    silent?: boolean
  }
}

// ============ Token 管理 ============
const TOKEN_KEY = 'fin_ui_test_token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

// 请求拦截器：自动注入 Authorization + 启动顶部进度条
http.interceptors.request.use((config) => {
  const token = getToken()
  if (token) {
    config.headers = config.headers || {}
    config.headers.Authorization = `Bearer ${token}`
  }
  // silent 请求（如轮询）跳过进度条，避免频繁闪烁
  if (!config.silent) {
    startProgress()
  }
  return config
})

// 后端 detail 兜底折叠：主应用已有 422 handler 折叠为字符串，但数组形态
// （其他服务/旧版本网关）会退化成英文逗号串，这里统一为「字段: 原因；…」
function foldDetail(detail: unknown): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map((e: { loc?: unknown[]; msg?: unknown }) => {
        const loc = Array.isArray(e?.loc) ? e.loc.filter((x) => x !== 'body').join('.') : ''
        const msg = typeof e?.msg === 'string' ? e.msg : ''
        return loc ? `${loc}: ${msg}` : msg
      })
      .filter(Boolean)
      .join('；')
  }
  return ''
}

// 响应拦截器：401 清 token 跳登录；其他错误提取 detail；结束进度条
http.interceptors.response.use(
  (resp) => {
    if (!resp.config.silent) doneProgress()
    return resp
  },
  (error) => {
    if (!error?.config?.silent) doneProgress()
    const status = error?.response?.status
    if (status === 401) {
      clearToken()
      // history 模式：直接跳 /login，避免在登录页重复跳转
      if (!window.location.pathname.includes('/login')) {
        window.location.href = '/login'
      }
    }
    // blob 请求（文件下载/导出）失败时 body 是 Blob，需读文本后解析出后端 detail；
    // 解析完再统一 reject，保证调用方 catch 到的仍是 ApiError
    const rejectWithMsg = (msg: string) => Promise.reject(new ApiError(msg, status))
    const data = error?.response?.data
    if (typeof Blob !== 'undefined' && data instanceof Blob && data.type.includes('json')) {
      return data.text().then((txt: string) => {
        try {
          return rejectWithMsg(foldDetail(JSON.parse(txt)?.detail) || error?.message || '请求失败')
        } catch {
          return rejectWithMsg(error?.message || '请求失败')
        }
      })
    }
    const msg = foldDetail(data?.detail) || error?.message || '请求失败'
    return rejectWithMsg(msg)
  },
)

// ============ ApiError 契约 ============
// 拦截器把一切失败（HTTP 错误/blob 响应/网络错误）规整为 ApiError：
// message 必为后端 detail（缺失时回退 axios message / '请求失败'）。
// 调用方 catch 只读 e.message，不要再写 e?.response?.data?.detail 之类的对冲解析。
export class ApiError extends Error {
  /** HTTP 状态码；无响应（网络错误/超时）时为 undefined */
  status?: number
  constructor(message: string, status?: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

// ============ 类型 ============
// 响应类型优先取 OpenAPI 生成物别名（npm run gen:api，后端 Pydantic 为单一事实源）。
// 仍手写的接口分两类：嵌套结构在生成物中退化为 unknown（Environment/TestCase/
// NodeConfig/记录族/版本族——视图需要更强的领域形状），或手写 union 承载
// 领域约束（TestSchedule 的 schedule_type）；待后端模型细化后分批换。
export type User = components['schemas']['UserOut']
export type Project = components['schemas']['ProjectOut']
export interface Environment {
  id: number; project_id: number; name: string; base_url: string
  db_config: Record<string, any>
  login_config: Record<string, any>
  notify_config: Record<string, any>
  common_headers: Record<string, any>; success_codes?: string; timeout: number
  node_retry_count?: number | null  // 节点请求层失败自动重试次数（0/空=不重试）
  node_retry_interval?: number | null  // 节点重试间隔（秒）
  is_default: boolean; sort_order?: number; created_at?: string
  created_by?: number | null; updated_by?: number | null
  created_by_name?: string | null; updated_by_name?: string | null
}
export type CaseGroup = components['schemas']['CaseGroupOut']
// ============ 四来源参数模型（2026-09-30 定案：节点入参取值单选四来源） ============
export type ParamSource = 'constant' | 'func' | 'ref' | 'sql'
/** 函数入参：常量或引用（引用允许上游变量/本节点 SQL 参数，后端逐参求值） */
export interface FuncArgSpec {
  name: string
  kind: 'const' | 'ref'
  value?: any          // kind=const
  node_id?: string     // kind=ref
  var_path?: string    // kind=ref
}
export interface ParamSpec {
  source: ParamSource
  value?: any          // constant：任意 JSON 值
  func?: string        // func：函数名（见 constants/funcRegistry）
  args?: FuncArgSpec[] // func：按关键字传参
  node_id?: string     // ref：画布节点 / __dataset__ / __prev__ / 本节点（SQL 参数结果）
  var_path?: string    // ref
  as_array?: boolean   // ref/func：单值包成单元素数组
  sql?: string         // sql：{{节点.变量}} 占位引用
  column?: string      // sql：结果列名（缺省首行首列）
}
export interface NodeParams {
  body?: Record<string, ParamSpec>
  headers?: Record<string, ParamSpec>
}
// ============ 契约缺口（执行摘要回显；契约同步面已随数据集裁撤） ============
/** 契约外参数（动态来源红线：只标注不删） */
export interface ContractGapExtra {
  path: string
  source: string
  dynamic: boolean
}
export interface ContractGaps {
  missing?: string[]        // 接口字段无参数覆盖（执行按空值占位发送）
  extra?: ContractGapExtra[] // 参数路径不在接口契约内
}
/** 节点后置提取配置行（PostExtractTable 编辑形状） */
export interface PostExtractSpec {
  name: string          // 提取后产出的变量名
  source: 'response' | 'db'
  json_path?: string    // source=response：JSONPath 表达式（如 $.data.order_id）
  sql?: string          // source=db：查询语句
  field?: string        // source=db：取值字段（缺省首行首列）
}
/** 节点断言配置行（AssertionTable 编辑形状；执行后的结果记录见 AssertionRecord） */
export interface AssertionSpec {
  type: string          // 规则类型：json_path_*/db_query_*/db_vs_jsonpath_*/response_time_less_than
  path?: string         // json_path 类：目标表达式
  sql?: string          // db 类：查询语句
  field?: string        // db 类：结果字段
  expected?: string     // 期望值（可切换 引用/函数/SQL 取值）
  message?: string      // 自定义失败文案
}
// ============ UI 节点参数（step_type='ui' 时使用）：与后端 ui_runtime.py 动作词表对齐 ============
// element 支持内联单策略 {strategy, value, name?} 或元素库引用 {element_id}
/** UI 动作步骤（页面级节点 ui_params.steps 的单项；不允许再嵌套 steps） */
export interface UiStep {
  action: 'goto' | 'click' | 'fill' | 'pick' | 'select_option' | 'check' | 'press' | 'type'
    | 'date' | 'wait' | 'upload' | 'screenshot' | 'evaluate' | 'custom'
    | 'search' | 'click_text' | 'row_button'
    | 'scroll_bottom' | 'confirm' | 'popper_pick'
    | 'toast_watch' | 'save' | 'uncheck_all'
  url?: string
  element?: {
    strategy?: 'css' | 'xpath' | 'text' | 'role' | 'placeholder' | 'label' | 'test_id' | 'for'
    value?: string
    name?: string  // role 策略的可访问名（get_by_role(name=...)）
    element_id?: number  // 元素库引用（优先于内联策略）
    strategies?: Record<string, any>
  }
  value?: any
  values?: any[]
  timeout_ms?: number
  wait_for?: 'load' | 'domcontentloaded' | 'networkidle'
  force?: boolean
  files?: any[]
  index?: number  // click_text 同名按钮取第 N 个
  match?: 'exact' | 'contains'  // click_text 匹配方式（默认 exact）
  mode?: 'default' | 'js'  // click 模式（js=绕过可点击性校验）
  wait?: boolean  // confirm 轮询模式（弹窗延迟出现时持续监视）
  optional?: boolean  // confirm 只点「继续提交」类、无弹窗跳过；click_text 无则跳过；toast_watch 宽容超时
  absent?: boolean  // toast_watch 反向断言：观察窗内出现提示即失败（value 空=任何提示）
  custom_id?: number  // custom 动作引用 custom_actions.id
}
/** UI 节点参数：单动作（{action,...}）或动作组（{steps:[...]}，页面级节点，steps 优先）
 *  scope：节点页面域（编排改造——节点即页面域，动作只能操作该域下元素） */
export interface UiParams extends Partial<UiStep> {
  steps?: UiStep[]
  scope?: string
}
export interface NodeConfig {
  id?: number; case_id?: number; node_id: string; api_id?: number | null
  step_type?: string  // api 接口调用（默认/历史缺省） / ui 浏览器操作
  ui_params?: UiParams
  pre_process?: any[]  // 历史遗留：入参已收敛到数据集，仅老数据回显
  post_extract: PostExtractSpec[]; assertions: AssertionSpec[]
  wait_after_ms?: number
}
export interface TestCase {
  id: number; project_id: number; group_id?: number | null; name: string; description?: string
  env_id?: number | null  // 绑定的执行环境（严格绑定：执行一律用它）
  env_name?: string | null  // 绑定环境名（冗余展示）
  dag_config: { nodes: any[]; edges: any[] }
  node_configs: NodeConfig[]; sort_order?: number; created_at?: string; updated_at?: string
  created_by?: number | null; updated_by?: number | null
  created_by_name?: string | null; updated_by_name?: string | null
  dataset_id?: number | null  // 绑定的数据集（数据驱动），NULL=普通用例
  last_exec_at?: string | null      // 最近一次执行开始时间（终结回写；NULL=从未执行）
  last_exec_status?: string | null  // 最近一次执行终态：success/failed/terminated
}

export interface AssertionRecord {
  id: number; step_id: number; rule_type: string; rule_config?: any
  result?: boolean; actual_value?: string; expected_value?: string; message?: string
}
export interface RetryAttempt {
  attempt: number
  ts: string
  elapsed_ms: number
  status_code: number
  error: string
  response?: unknown  // 失败响应快照（超 2000 字符折叠为 {__truncated__, text}）
}
export interface StepRecord {
  id: number; execution_id: number; node_id?: string; api_name?: string
  api_path?: string; api_method?: string
  request_headers?: any; request_body?: any; response_status?: number
  response_body?: any; response_time_ms?: number
  retry_count?: number | null  // 失败自动重试实际次数（0/空=未重试）
  // 重试途中被顶替的失败尝试快照（重试成功后首次失败原因只在此；最终失败仍在主行）
  retry_history?: RetryAttempt[] | null
  resumed?: boolean  // 断点续跑段产出的步骤（顶替旧失败记录）
  replay_passed_at?: string | null  // 重放验证通过时间（「已重放通过」徽标）
  started_at?: string; ended_at?: string; status?: string
  step_kind?: string | null  // 步骤类型 api/ui（历史行 null 视为 api）
  screenshot_file_id?: number | null  // UI 步骤截图文件ID（文件中心 /api/files/{id}/preview）
  pre_process?: { type?: string; path?: string; value?: any; sql?: string }[] | null  // 历史遗留：仅老报告回显，新步骤恒 null
  post_extract?: Record<string, any>[] | null
  extracted_vars?: Record<string, any> | null
  assertions: AssertionRecord[]
}
/**
 * 执行摘要（按场景出现不同字段子集，2026-10-22 对齐后端产出）：
 * - 普通用例 dag_executor：{total, passed, failed, leftover?, error?, contract_gaps?}
 * - 启动失败 runner：{error}（用例/环境缺失、登录失败等，无步骤产出）
 */
export interface ExecutionSummary {
  total?: number
  passed?: number
  failed?: number
  leftover?: number     // DAG：上游失败未执行的节点数
  error?: string        // 执行级错误（登录失败/环境异常/兜底异常）
  contract_gaps?: Record<string, ContractGaps>  // node_id → 契约缺口（红线只标注不删）
}
export interface ExecutionRecord {
  id: number; case_id: number; env_id: number
  case_name?: string; env_name?: string
  project_id?: number | null; project_name?: string | null
  status: string
  started_at?: string; ended_at?: string; summary: ExecutionSummary
  dataset_id?: number | null
  dataset_row?: { row_index: number; data: Record<string, any>; label: string } | null
  steps: StepRecord[]
  created_by?: number | null; created_by_name?: string | null
  trigger_type?: string
  plan_id?: number | null       // 非空=执行方案触发（一键/定时/串行链成员行）
  plan_name?: string | null     // 方案名（尽力回查；方案已删时 null，显示「方案 #id」）
}

export interface TestSchedule {
  id: number; case_id: number; env_id?: number | null  // 快照（实际执行环境以用例绑定为準）
  case_name?: string | null; env_name?: string | null
  schedule_type: 'interval' | 'daily'
  interval_minutes?: number | null
  daily_time?: string | null
  enabled: boolean
  last_run_at?: string | null; next_run_at?: string | null
  created_at?: string | null; updated_at?: string | null
  created_by?: number | null; created_by_name?: string | null
  updated_by?: number | null; updated_by_name?: string | null
}

export interface ProjectVersionListItem {
  id: number; project_id: number; version_no: number
  name: string; description?: string
  created_by?: number | null; created_by_name?: string | null
  created_at?: string
}

/** 项目版本快照/对比口径（2026-10-29）：UI 平台编排资产——
 *  元素库/页面域语义/动作库 + 用例分组/用例；不再含 fork 自 API 平台的接口域 */
export interface ProjectVersion extends ProjectVersionListItem {
  snapshot?: {
    case_groups: any[]
    cases: any[]
    elements: any[]
    scope_labels: any[]
    custom_actions: any[]
  }
}

export interface ProjectVersionDiff {
  base: ProjectVersion
  target: ProjectVersion
  diff: {
    case_groups: CollectionDiff
    cases: CollectionDiff
    elements: CollectionDiff
    scope_labels: CollectionDiff
    custom_actions: CollectionDiff
  }
}

export interface CollectionDiff {
  added: { key: string; target: any }[]
  removed: { key: string; base: any }[]
  modified: { key: string; base: any; target: any }[]
}

// ============ Auth ============
export const authApi = {
  login: (username: string, password: string) =>
    http.post<{ token: string; user: User }>('/auth/login', { username, password }).then((r) => r.data),
  register: (username: string, password: string, name?: string) =>
    http.post<{ token: string; user: User }>('/auth/register', { username, password, name }).then((r) => r.data),
  me: () => http.get<User>('/auth/me').then((r) => r.data),
  changePassword: (newPassword: string) =>
    http.post<{ message: string }>('/auth/change-password', { new_password: newPassword }).then((r) => r.data),
  // 头像：上传（base64 data URL）/ 删除 / 按 id 查 / 按 username 查
  updateAvatar: (avatar: string) =>
    http.put<{ message: string }>('/auth/avatar', { avatar }).then((r) => r.data),
  removeAvatar: () => http.delete('/auth/avatar'),
  getAvatar: (userId: number) =>
    http.get<AvatarInfo>(`/auth/avatar/${userId}`).then((r) => r.data),
}

// ============ User 管理（仅管理员） ============
// 类型来源切到 OpenAPI 生成（npm run gen:api），消除手写镜像；形状与后端 SimpleUserOut 单一事实来源
import type { components } from '@/types/api.gen'

export type SimpleUser = components['schemas']['SimpleUserOut']
export type AvatarInfo = components['schemas']['AvatarOut']
export const userApi = {
  list: () => http.get<User[]>('/users').then((r) => r.data),
  simple: () => http.get<SimpleUser[]>('/users/simple').then((r) => r.data),
  create: (data: { username: string; password: string; name?: string; role?: string; department?: string }) =>
    http.post<User>('/users', data).then((r) => r.data),
  updateRole: (id: number, role: string) =>
    http.put<User>(`/users/${id}/role`, { role }).then((r) => r.data),
  update: (id: number, data: { username: string; name?: string | null; phone?: string | null; email?: string | null; department?: string | null; role: string }) =>
    http.put<User>(`/users/${id}`, data).then((r) => r.data),
  resetPassword: (id: number, password: string) =>
    http.put(`/users/${id}/password`, { password }),
  remove: (id: number) => http.delete(`/users/${id}`),
}

// ============ 操作日志（仅管理员） ============
export type OperationLog = components['schemas']['OperationLogOut']

export const logApi = {
  list: (params?: { action?: string; target_type?: string; user_id?: number; limit?: number; start_time?: string; end_time?: string }) =>
    http.get<OperationLog[]>('/operation-logs', { params }).then((r) => r.data),
  cleanup: (days: number) => http.delete<{ message: string; deleted: number; days: number }>('/operation-logs/cleanup', { params: { days } }).then((r) => r.data),
}

// ============ Project ============
export const projectApi = {
  list: (params?: { created_by?: number; updated_by?: number }) => http.get<Project[]>('/projects', { params }).then((r) => r.data),
  create: (data: Partial<Project>) => http.post<Project>('/projects', data).then((r) => r.data),
  update: (id: number, data: Partial<Project>) => http.put<Project>(`/projects/${id}`, data).then((r) => r.data),
  remove: (id: number) => http.delete(`/projects/${id}`),
  reorder: (items: { id: number; sort_order: number }[]) =>
    http.post<{ message: string; updated: number }>('/projects/reorder', { items }).then((r) => r.data),
}

// ============ Environment ============
export const envApi = {
  list: (projectId?: number, createdBy?: number, updatedBy?: number) => http.get<Environment[]>('/environments', { params: { project_id: projectId, created_by: createdBy, updated_by: updatedBy } }).then((r) => r.data),
  get: (id: number) => http.get<Environment>(`/environments/${id}`).then((r) => r.data),
  create: (data: Partial<Environment>) => http.post<Environment>('/environments', data).then((r) => r.data),
  update: (id: number, data: Partial<Environment>) => http.put<Environment>(`/environments/${id}`, data).then((r) => r.data),
  remove: (id: number) => http.delete(`/environments/${id}`),
  copy: (id: number) => http.post<Environment>(`/environments/${id}/copy`).then((r) => r.data),
  testDb: (id: number) => http.post<{ ok: boolean; message: string; test_result?: any }>(`/environments/${id}/test-db`).then((r) => r.data),
  testLogin: (id: number) => http.post<{ ok: boolean; message: string; auth_header_name?: string; auth_header_preview?: string; base_url?: string }>(`/environments/${id}/test-login`).then((r) => r.data),
  reorder: (items: { id: number; sort_order: number }[]) =>
    http.post<{ message: string; updated: number }>('/environments/reorder', { items }).then((r) => r.data),
}

// ============ CaseGroup ============
export const caseGroupApi = {
  list: (projectId: number) => http.get<CaseGroup[]>('/case-groups', { params: { project_id: projectId } }).then((r) => r.data),
  create: (data: { project_id: number; parent_id?: number | null; name: string; sort_order?: number }) => http.post<CaseGroup>('/case-groups', data).then((r) => r.data),
  update: (id: number, data: Partial<CaseGroup>) => http.put<CaseGroup>(`/case-groups/${id}`, data).then((r) => r.data),
  remove: (id: number) => http.delete(`/case-groups/${id}`),
}

// ============ TestCase ============
export const caseApi = {
  list: (projectId?: number, createdBy?: number, updatedBy?: number) => http.get<TestCase[]>('/testcases', { params: { project_id: projectId, created_by: createdBy, updated_by: updatedBy } }).then((r) => r.data),
  get: (id: number) => http.get<TestCase>(`/testcases/${id}`).then((r) => r.data),
  create: (data: Partial<TestCase>) => http.post<TestCase>('/testcases', data).then((r) => r.data),
  update: (id: number, data: Partial<TestCase>) => http.put<TestCase>(`/testcases/${id}`, data).then((r) => r.data),
  remove: (id: number) => http.delete(`/testcases/${id}`),
  copy: (id: number) => http.post<TestCase>(`/testcases/${id}/copy`).then((r) => r.data),
  batchMove: (caseIds: number[], groupId: number | null) =>
    http.post<{ message: string; updated: number }>('/testcases/batch-move', { case_ids: caseIds, group_id: groupId }).then((r) => r.data),
  reorder: (items: { id: number; sort_order: number }[]) =>
    http.post<{ message: string; updated: number }>('/testcases/reorder', { items }).then((r) => r.data),
  // 环境严格绑定：执行环境=用例绑定环境（case.env_id），不再传 env_id。
  // datasetId/rowIndex 执行时临时换数据集/选行（缺省=绑定数据集第 1 行；不改绑定与数据集内容）
  execute: (caseId: number, datasetId?: number, rowIndex?: number) =>
    http.post<ExecutionRecord>(`/testcases/${caseId}/execute`,
      { case_id: caseId, dataset_id: datasetId ?? null, dataset_row_index: rowIndex ?? null }).then((r) => r.data),
  // 用例名下数据集及全部数据行（执行面板「换套数据执行」下拉数据源；行=具名 sheet）
  datasets: (caseId: number) =>
    http.get<{ id: number; name: string; rows: DataSetSheetOut[] }[]>(`/testcases/${caseId}/datasets`).then((r) => r.data),
  batchExecute: (caseIds: number[], counts?: number[], concurrency: number = 4) =>
    http.post<ExecutionRecord[]>('/testcases/batch-execute',
      { case_ids: caseIds, counts, concurrency }).then((r) => r.data),
  // 列表导出：excel=简表 / json=全量（含 DAG 与节点配置），筛选条件与列表页一致
  exportList: (params: { project_id: number; format: 'excel' | 'json'; created_by?: number; updated_by?: number }) =>
    http.get<Blob>('/testcases/export', { responseType: 'blob', params }).then((r) => r.data),
  // 多用例组合（拼接成新用例），caseIds 顺序即拼接顺序
  combine: (caseIds: number[], name: string, groupId?: number | null) =>
    http.post<TestCase>('/testcases/combine', { case_ids: caseIds, name, group_id: groupId ?? null }).then((r) => r.data),
  // 拆分前置扫描：返回跨界变量清单（outgoing/incoming），只需 node_ids
  scanSplit: (caseId: number, nodeIds: string[]) =>
    http.post<{ outgoing: SplitVar[]; incoming: SplitVar[] }>(`/testcases/${caseId}/scan-split`, { node_ids: nodeIds }).then((r) => r.data),
  // 执行拆分：抽离节点到新用例
  split: (caseId: number, data: { node_ids: string[]; new_name: string; new_group_id?: number | null }) =>
    http.post<{ message: string; new_case: TestCase; origin_case: TestCase }>(`/testcases/${caseId}/split`, data).then((r) => r.data),
}

export interface SplitVar {
  var: string
  providers: string[]
  consumer: string
}

// ============ DataSet 数据集维护（多套数据 = 多场景；按用例 1:N 隔离） ============
/** 数据集行 = 具名 sheet（2026-10-27 sheet 化）：label 为 ${label.字段} 引用命名空间，
 *  field_desc 仅编辑器备注，field_order 显式字段顺序（MySQL JSON 列不保 key 序） */
export interface DataSetSheetOut {
  row_index: number
  data: Record<string, any>
  label: string
  field_desc?: Record<string, string> | null
  field_order?: string[] | null
}

/** 保存载荷：label/data 必带，field_desc/field_order 可选（空则不落） */
export interface DataSetSheetIn {
  label: string
  data: Record<string, any>
  field_desc?: Record<string, string> | null
  field_order?: string[] | null
}

export interface DataSetManage {
  id: number
  project_id: number
  case_id: number
  name: string
  description?: string | null
  rows: DataSetSheetOut[]
  case_bound_count?: number
}

export const datasetApi = {
  // 项目级清单（独立数据集管理页：按归属用例过滤，含绑定计数与行数据）
  list: (params: { project_id: number }) =>
    http.get<DataSetManage[]>('/datasets', { params }).then((r) => r.data),
  // 新建（copy_from_dataset_id 传本用例已有数据集 id = 值全量拷贝起步）
  create: (data: { case_id: number; name: string; description?: string; copy_from_dataset_id?: number }) =>
    http.post<DataSetManage>('/datasets', data).then((r) => r.data),
  update: (id: number, data: { name?: string; description?: string }) =>
    http.put<DataSetManage>(`/datasets/${id}`, data).then((r) => r.data),
  // 复制数据集（默认名「原名-副本」，多场景标准起步）
  copy: (id: number) => http.post<DataSetManage>(`/datasets/${id}/copy`).then((r) => r.data),
  remove: (id: number) => http.delete(`/datasets/${id}`),
  // 行整体替换（编辑完一次保存，行号后端重编 1..n；至少一行；新 sheet 形态载荷）
  replaceRows: (id: number, rows: DataSetSheetIn[]) =>
    http.put<DataSetManage>(`/datasets/${id}/rows`, { rows }).then((r) => r.data),
}

// ============ TestSchedule 定时任务 ============
export interface SchedulePayload {
  case_id?: number
  schedule_type?: 'interval' | 'daily'
  interval_minutes?: number | null
  daily_time?: string | null
  enabled?: boolean
}

export const scheduleApi = {
  list: (params?: { project_id?: number; case_id?: number }) =>
    http.get<TestSchedule[]>('/schedules', { params }).then((r) => r.data),
  create: (data: Required<Pick<SchedulePayload, 'case_id' | 'schedule_type'>> & SchedulePayload) =>
    http.post<TestSchedule>('/schedules', data).then((r) => r.data),
  update: (id: number, data: SchedulePayload) =>
    http.put<TestSchedule>(`/schedules/${id}`, data).then((r) => r.data),
  remove: (id: number) => http.delete(`/schedules/${id}`),
  run: (id: number) => http.post<{ message: string }>(`/schedules/${id}/run`).then((r) => r.data),
}

// ============ ExecutionPlan 执行方案 ============
/** 方案成员（dataset 覆盖须属于该成员用例；chain 模式按 sort_order 轮内串行） */
export interface PlanItem {
  id?: number
  case_id: number
  dataset_id?: number | null      // NULL=沿用用例自身绑定
  dataset_row_index?: number | null  // 值=DataSetRow.row_index；NULL=第 1 行（chain 按轮序取 sheet）
  run_count?: number              // 1~9999（combo 生效；chain 整链轮数在方案级 rounds，此项忽略）
  pass_vars?: string[] | null     // chain 专用：传给下一棒的输出变量名单（相邻定向传参；末棒/ combo 恒空）
  sort_order?: number
  // 展示回填（详情接口）
  case_name?: string | null
  dataset_name?: string | null
  sheet_label?: string | null
  case_dataset_id?: number | null   // 用例自身绑定（dataset_id 空时实际生效）
  case_missing?: boolean
  dataset_missing?: boolean
}

export interface ExecutionPlan {
  id: number; project_id?: number | null
  name: string; description?: string | null
  mode: 'combo' | 'chain'          // combo 并行组合 / chain 串行链（按序+相邻定向传参+失败阻断本轮下游）
  rounds: number                  // chain 整链执行轮数（轮内串行、轮间并行）；combo 恒 1
  concurrency: number             // 1~16（combo 成员并行 / chain 轮间并行）
  enabled: boolean                // 方案总开关：禁用时定时跳过本轮（手动一键不受限）
  schedule_type?: 'interval' | 'daily' | null  // NULL=未配置定时
  schedule_interval_minutes?: number | null
  schedule_daily_time?: string | null
  schedule_enabled: boolean
  last_run_at?: string | null; next_run_at?: string | null
  item_count?: number             // 列表聚合
  created_at?: string | null; updated_at?: string | null
  created_by?: number | null; created_by_name?: string | null
  updated_by?: number | null; updated_by_name?: string | null
}

export interface ExecutionPlanDetail extends ExecutionPlan {
  items: PlanItem[]
}

/** 方案基础字段 + 内嵌定时局部更新（schedule_off=true 显式清除定时） */
export interface PlanUpdatePayload {
  name?: string
  description?: string | null
  mode?: 'combo' | 'chain'
  rounds?: number
  concurrency?: number
  enabled?: boolean
  schedule_type?: 'interval' | 'daily' | null
  schedule_interval_minutes?: number | null
  schedule_daily_time?: string | null
  schedule_enabled?: boolean
  schedule_off?: boolean
}

export const planApi = {
  list: (params?: { project_id?: number }) =>
    http.get<ExecutionPlan[]>('/plans', { params }).then((r) => r.data),
  create: (data: { project_id?: number | null; name: string; description?: string; mode?: 'combo' | 'chain'; rounds?: number; concurrency?: number }) =>
    http.post<ExecutionPlanDetail>('/plans', data).then((r) => r.data),
  get: (id: number) => http.get<ExecutionPlanDetail>(`/plans/${id}`).then((r) => r.data),
  update: (id: number, data: PlanUpdatePayload) =>
    http.put<ExecutionPlanDetail>(`/plans/${id}`, data).then((r) => r.data),
  updateItems: (id: number, items: PlanItem[]) =>
    http.put<ExecutionPlanDetail>(`/plans/${id}/items`, { items }).then((r) => r.data),
  remove: (id: number) => http.delete(`/plans/${id}`),
  // 一键执行：预检失败 400 零记录；返回本次全部记录
  // （combo 并行独立轮询到终态 / chain 后台按轮驱动：轮内串行+相邻传参 __prev__+失败阻断本轮下游）
  execute: (id: number) => http.post<ExecutionRecord[]>(`/plans/${id}/execute`).then((r) => r.data),
}

// ============ ProjectVersion 项目版本 ============
export const projectVersionApi = {
  list: (projectId: number) =>
    http.get<ProjectVersionListItem[]>(`/projects/${projectId}/versions`).then((r) => r.data),
  create: (projectId: number, data: { name: string; description?: string }) =>
    http.post<ProjectVersion>(`/projects/${projectId}/versions`, data).then((r) => r.data),
  get: (versionId: number) =>
    http.get<ProjectVersion>(`/project-versions/${versionId}`).then((r) => r.data),
  diff: (baseId: number, targetId: number) =>
    http.get<ProjectVersionDiff>(`/project-versions/${baseId}/diff`, { params: { target_id: targetId } }).then((r) => r.data),
  rollback: (versionId: number) =>
    http.post<{ message: string }>(`/project-versions/${versionId}/rollback`).then((r) => r.data),
  remove: (versionId: number) => http.delete(`/project-versions/${versionId}`),
}

// ============ Execution / Report ============
export const execApi = {
  list: (params?: { case_id?: number; project_id?: number; created_by?: number; limit?: number; offset?: number; case_name?: string; status?: string; start_time?: string; end_time?: string; sort_by?: string; order?: string; plan_id?: number }) =>
    http.get<{ items: ExecutionRecord[]; total: number }>('/executions', { params }).then((r) => r.data),
  // 近 N 天执行统计（工作台）：全量聚合口径，不受列表翻页截断影响
  stats: (params?: { days?: number; project_id?: number }) =>
    http.get<{ count: number; passed: number; rate: number | null; days: number }>('/executions/stats', { params }).then((r) => r.data),
  get: (id: number, silent?: boolean) => http.get<ExecutionRecord>(`/executions/${id}`, { silent }).then((r) => r.data),
  // 手动终止（运行中记录）：僵尸记录直接落状态；活动执行由 runner 检查点提前退出
  terminate: (id: number) => http.post<ExecutionRecord>(`/executions/${id}/terminate`).then((r) => r.data),
  // 报告详情与 get 同源（后端 /executions/{id} 单一事实源，/reports 读端点保留给外部调用方）
  report: (id: number) => http.get<ExecutionRecord>(`/executions/${id}`).then((r) => r.data),
  // 报告导出（后端组装：csv=Excel 兼容 BOM+CRLF；html=自包含单文件报告）
  exportReport: (id: number, format: 'csv' | 'html') =>
    http.get<Blob>(`/reports/executions/${id}/export`, { responseType: 'blob', params: { format } }).then((r) => r.data),
  cleanup: (days: number) => http.delete<{ message: string; deleted: number; days: number }>('/executions/cleanup', { params: { days } }).then((r) => r.data),
  // 报告页节点重放：bodyOverride 为编辑后的请求体（null=用原快照重发一次）。
  // 断点续跑配套：同口径跑断言与提取，passed=断言全过且请求成功（通过时后端打 replay_passed_at）
  replayStep: (stepId: number, bodyOverride: unknown) =>
    http.post<{ status_code: number; response_body: any; error: string | null; elapsed_ms: number; request_body: any; passed: boolean; assertions: { type: string; pass: boolean; message?: string }[]; extracted: Record<string, any> }>(
      `/executions/steps/${stepId}/replay`, { body_override: bodyOverride ?? null }).then((r) => r.data),
  // 断点续跑：从首个未成功节点用当前配置+当前数据集重新执行（仅 failed 普通报告；编排结构需与报告时一致）
  resume: (execId: number) =>
    http.post<ExecutionRecord>(`/executions/${execId}/resume`).then((r) => r.data),
}

// ============ Home 工作台 ============
export interface HomeRecentExec {
  id: number; case_id: number; case_name?: string | null
  env_id?: number | null; env_name?: string | null
  status: string; summary?: Record<string, any> | null; started_at?: string | null
}

// 首页聚合（一次请求替代 4 个重列表接口的全量拉取）
export const homeApi = {
  summary: (projectId: number, days = 7) =>
    http.get<{
      element_count: number; case_count: number
      stats: { count: number; passed: number; rate: number | null; days: number }
      recent_execs: HomeRecentExec[]
      recent_cases: { id: number; name: string }[]
    }>('/home/summary', { params: { project_id: projectId, days } }).then((r) => r.data),
}

// ============ FieldDictionary 字段字典 ============
export type FieldDictionary = components['schemas']['FieldDictionaryOut']

export const dictApi = {
  list: (projectId: number, keyword?: string) =>
    http.get<FieldDictionary[]>('/field-dictionaries', { params: { project_id: projectId, keyword } }).then((r) => r.data),
  getMap: (projectId: number) =>
    http.get<Record<string, string>>('/field-dictionaries/map', { params: { project_id: projectId } }).then((r) => r.data),
  create: (data: { project_id: number; key: string; label: string }) =>
    http.post<FieldDictionary>('/field-dictionaries', data).then((r) => r.data),
  update: (id: number, data: { key?: string; label?: string }) =>
    http.put<FieldDictionary>(`/field-dictionaries/${id}`, data).then((r) => r.data),
  remove: (id: number) => http.delete(`/field-dictionaries/${id}`),
  batch: (projectId: number, items: { key: string; label: string }[]) =>
    http.post<{ message: string; count: number }>('/field-dictionaries/batch', { project_id: projectId, items }).then((r) => r.data),
}

// ============ PageScopeLabel 页面域字典 ============
export const scopeLabelApi = {
  getMap: (projectId: number) =>
    http.get<Record<string, string>>('/page-scope-labels/map', { params: { project_id: projectId } }).then((r) => r.data),
  batch: (projectId: number, items: { page_scope: string; label: string }[]) =>
    http.post<{ message: string; count: number }>('/page-scope-labels/batch', { project_id: projectId, items }).then((r) => r.data),
}

// ============ FileCenter 文件中心 ============
export type FileCategory = components['schemas']['FileCategoryOut']
export type TestFile = components['schemas']['FileOut']

export const fileApi = {
  // 文件 CRUD
  list: (projectId: number, params?: { category_id?: number | null; keyword?: string }) =>
    http.get<TestFile[]>('/files', { params: { project_id: projectId, ...params } }).then((r) => r.data),
  get: (id: number) => http.get<TestFile>(`/files/${id}`).then((r) => r.data),
  upload: (file: File, projectId: number, categoryId?: number | null) => {
    const formData = new FormData()
    formData.append('file', file)
    return http.post<TestFile>(`/files/upload?project_id=${projectId}${categoryId ? `&category_id=${categoryId}` : ''}`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }).then((r) => r.data)
  },
  update: (id: number, data: { name?: string; category_id?: number | null }) =>
    http.put<TestFile>(`/files/${id}`, data).then((r) => r.data),
  remove: (id: number) => http.delete<{ message: string; physical_removed: boolean }>(`/files/${id}`),
  // 批量删除：多条件 AND 组合；dryRun=true 仅预览命中数与样例
  batchDelete: (data: {
    project_id: number
    ids?: number[] | null
    category_id?: number | null
    name_contains?: string | null
    content_type_prefix?: string | null
    created_by?: number | null
    created_after?: string | null
    created_before?: string | null
    dry_run: boolean
  }) =>
    http.post<{ dry_run: boolean; count?: number; deleted?: number; physical_removed?: number;
                sample?: { id: number; name: string; content_type: string; created_at: string; ref_count: number }[] }>(
      '/files/batch-delete', data).then((r) => r.data),
  // 下载/预览：用 axios 获取 blob（带 token），转 object URL 供 img/iframe/a 使用
  fetchBlob: (id: number, preview = false) =>
    http.get<Blob>(`/files/${id}/${preview ? 'preview' : 'download'}`, { responseType: 'blob' }).then((r) => {
      const url = URL.createObjectURL(r.data)
      return { url, blob: r.data }
    }),
}

export const fileCategoryApi = {
  list: (projectId: number) =>
    http.get<FileCategory[]>('/file-categories', { params: { project_id: projectId } }).then((r) => r.data),
  create: (data: { project_id: number; parent_id?: number | null; name: string; sort_order?: number }) =>
    http.post<FileCategory>('/file-categories', data).then((r) => r.data),
  update: (id: number, data: { name?: string; parent_id?: number | null; sort_order?: number }) =>
    http.put<FileCategory>(`/file-categories/${id}`, data).then((r) => r.data),
  remove: (id: number) => http.delete(`/file-categories/${id}`),
}

// ============ UiElement UI 元素库 ============
// 页面元素定位器库：UI 节点可按 {page_scope, element_key} 引用（element_id），
// strategies 沿用 autotest-playwright locator JSON 的多策略字段（full_xpath 永远兜底）
export interface UiElement {
  id: number; project_id: number; page_scope: string; element_key: string
  strategies: Record<string, any>; description?: string | null
  updated_at?: string | null
  created_by?: number | null; updated_by?: number | null
  created_by_name?: string | null; updated_by_name?: string | null
}
export interface UiElementScope {
  page_scope: string; count: number
}

// ============ CustomAction 自定义 UI 动作 ============
export interface CustomAction {
  id: number
  project_id: number
  name: string
  description?: string | null
  script: string
  updated_at?: string | null
  updated_by_name?: string | null
}

export const customActionApi = {
  list: (projectId: number) =>
    http.get<CustomAction[]>('/custom-actions', { params: { project_id: projectId } }).then((r) => r.data),
  create: (data: { project_id: number; name: string; description?: string; script: string }) =>
    http.post<CustomAction>('/custom-actions', data).then((r) => r.data),
  update: (id: number, data: { name?: string; description?: string; script?: string }) =>
    http.put<CustomAction>(`/custom-actions/${id}`, data).then((r) => r.data),
  remove: (id: number) => http.delete(`/custom-actions/${id}`),
}

// ============ UiActionDoc UI 动作用法文档（项目级） ============
export interface UiActionDoc {
  id: number
  project_id: number
  action_key: string  // 预设动作名 / custom:{id}
  usage_text: string
  updated_at?: string | null
  updated_by_name?: string | null
}

export const uiActionDocApi = {
  list: (projectId: number) =>
    http.get<UiActionDoc[]>('/ui-action-docs', { params: { project_id: projectId } }).then((r) => r.data),
  /** 空文本 = 删除覆盖（回落内置说明）；成功返回覆盖对象或 null */
  upsert: (projectId: number, actionKey: string, usageText: string) =>
    http.put<UiActionDoc | null>(`/ui-action-docs/${encodeURIComponent(actionKey)}`,
      { project_id: projectId, usage_text: usageText }).then((r) => r.data),
}

export const elementApi = {
  list: (projectId: number, pageScope?: string, keyword?: string) =>
    http.get<UiElement[]>('/ui-elements', { params: { project_id: projectId, page_scope: pageScope, keyword } }).then((r) => r.data),
  scopes: (projectId: number) =>
    http.get<UiElementScope[]>('/ui-elements/scopes', { params: { project_id: projectId } }).then((r) => r.data),
  create: (data: { project_id: number; page_scope: string; element_key: string; strategies: Record<string, any>; description?: string }) =>
    http.post<UiElement>('/ui-elements', data).then((r) => r.data),
  // 覆盖式批量导入：承接 locator JSON 的 {key:{策略字段,description}} 展开结果
  batch: (data: { project_id: number; page_scope: string; items: { element_key: string; strategies: Record<string, any>; description?: string }[] }) =>
    http.post<{ message: string; count: number }>('/ui-elements/batch', data).then((r) => r.data),
  update: (id: number, data: { page_scope?: string; element_key?: string; strategies?: Record<string, any>; description?: string }) =>
    http.put<UiElement>(`/ui-elements/${id}`, data).then((r) => r.data),
  remove: (id: number) => http.delete(`/ui-elements/${id}`),
}

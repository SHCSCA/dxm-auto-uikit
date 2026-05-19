# 店小秘自动刊登助手 数据库表结构与 API 草案

> 版本：v0.1
> 目标：把 PRD、技术实现图、全量字段矩阵落到可开发的数据结构与接口草案。
> 范围：本地客户端数据库（SQLite 优先）+ 本地 IPC API + 云端轻服务 API

---

# 1. 设计目标

本设计要解决 5 个问题：

1. 如何存商品全量字段
2. 如何存模板中心与模板绑定关系
3. 如何存任务、步骤、日志、证据与异常池
4. 如何让前端和执行器通过统一接口协作
5. 如何把云端能力控制在“订阅 / AI / 配置更新”范围内

---

# 2. 数据库设计原则

1. 本地优先：核心业务数据默认存本地 SQLite
2. 模板优先：商品实例尽量引用模板，而不是重复冗余
3. 字段域拆分：基础信息、媒体、SKU、价格、物流、合规、半托管分开建模
4. 执行与商品解耦：商品数据和执行记录分表管理
5. 证据可追溯：截图、DOM 快照、日志、错误码必须落库

---

# 3. 核心实体关系图

```text
stores
├── templates
│   └── template_bindings
├── products
│   ├── product_media
│   ├── product_variants
│   ├── product_pricing
│   ├── product_shipping
│   ├── product_compliance
│   └── product_quotes
├── tasks
│   └── jobs
│       ├── job_steps
│       ├── job_evidences
│       ├── job_logs
│       └── exceptions
└── sessions
```

---

# 4. 表结构设计

以下以 SQLite 兼容字段表达。

## 4.1 stores

用途：店铺与平台连接信息。

```sql
CREATE TABLE stores (
  id TEXT PRIMARY KEY,
  platform TEXT NOT NULL,
  store_name TEXT NOT NULL,
  store_code TEXT,
  publish_scene_default TEXT, -- pop / semi_managed / managed / overseas_managed
  login_status TEXT NOT NULL DEFAULT 'unknown',
  local_session_path TEXT,
  last_login_check_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
```

关键字段：
- platform
- publish_scene_default
- local_session_path
- login_status

---

## 4.2 sessions

用途：本地浏览器会话与登录态管理。

```sql
CREATE TABLE sessions (
  id TEXT PRIMARY KEY,
  store_id TEXT NOT NULL,
  browser_profile_path TEXT NOT NULL,
  cookies_encrypted TEXT,
  session_meta_json TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  expires_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (store_id) REFERENCES stores(id)
);
```

---

## 4.3 templates

用途：模板中心主表。

```sql
CREATE TABLE templates (
  id TEXT PRIMARY KEY,
  platform TEXT NOT NULL,
  store_id TEXT,
  category_id TEXT,
  publish_scene TEXT, -- pop / semi_managed / ...
  template_type TEXT NOT NULL,
  template_name TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT 'active', -- active / inactive / archived
  is_default INTEGER NOT NULL DEFAULT 0,
  payload_json TEXT NOT NULL,
  created_by TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (store_id) REFERENCES stores(id)
);
```

template_type 建议枚举：
- title
- category
- qualification
- main_image
- white_bg_image
- marketing_image
- video
- sku
- size
- pricing
- benchmark_price
- quote
- shipping
- detail
- eu_responsible
- manufacturer
- compliance
- semi_managed

---

## 4.4 template_bindings

用途：模板绑定规则明细表。

```sql
CREATE TABLE template_bindings (
  id TEXT PRIMARY KEY,
  template_id TEXT NOT NULL,
  platform TEXT NOT NULL,
  store_id TEXT,
  category_id TEXT,
  publish_scene TEXT,
  priority INTEGER NOT NULL DEFAULT 100,
  condition_json TEXT, -- 可存品牌/国家站点/类目树等条件
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (template_id) REFERENCES templates(id),
  FOREIGN KEY (store_id) REFERENCES stores(id)
);
```

优先级建议：
- 场景专属模板 > 类目模板 > 店铺模板 > 平台默认模板

---

## 4.5 products

用途：商品主表，存基础字段。

```sql
CREATE TABLE products (
  id TEXT PRIMARY KEY,
  source_type TEXT,
  source_platform TEXT,
  source_url TEXT,
  source_shop_name TEXT,
  external_product_id TEXT,
  platform TEXT NOT NULL,
  store_id TEXT NOT NULL,
  publish_scene TEXT NOT NULL,
  product_group_id TEXT,
  internal_spu TEXT,
  brand_name TEXT,
  brand_type TEXT,
  title_raw TEXT,
  title_clean TEXT,
  title_final TEXT,
  title_lang TEXT,
  subtitle TEXT,
  source_category_path TEXT,
  target_category_id TEXT,
  target_category_path TEXT,
  category_confidence_score REAL,
  manual_category_locked INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'draft', -- draft / ready / blocked / published
  blocked_reason TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (store_id) REFERENCES stores(id)
);
```

---

## 4.6 product_template_refs

用途：记录商品实际绑定了哪些模板。

```sql
CREATE TABLE product_template_refs (
  id TEXT PRIMARY KEY,
  product_id TEXT NOT NULL,
  template_type TEXT NOT NULL,
  template_id TEXT NOT NULL,
  locked_by_user INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (product_id) REFERENCES products(id),
  FOREIGN KEY (template_id) REFERENCES templates(id)
);
```

---

## 4.7 product_qualifications

用途：类目资质、品牌资质、PDF/图片认证材料。

```sql
CREATE TABLE product_qualifications (
  id TEXT PRIMARY KEY,
  product_id TEXT NOT NULL,
  qualification_template_id TEXT,
  qualification_required INTEGER NOT NULL DEFAULT 0,
  qualification_type TEXT,
  file_type TEXT, -- pdf / image / link
  file_path TEXT,
  file_url TEXT,
  review_status TEXT,
  expires_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (product_id) REFERENCES products(id)
);
```

---

## 4.8 product_media

用途：主图、白底图、营销图、视频、说明书等素材。

```sql
CREATE TABLE product_media (
  id TEXT PRIMARY KEY,
  product_id TEXT NOT NULL,
  media_type TEXT NOT NULL, -- main_image / white_bg / marketing_image / product_video / install_video / manual_pdf
  source_type TEXT, -- local / remote / media_bank
  file_path TEXT,
  file_url TEXT,
  sort_index INTEGER NOT NULL DEFAULT 0,
  variant_key TEXT,
  width INTEGER,
  height INTEGER,
  duration_seconds REAL,
  file_size_bytes INTEGER,
  validation_status TEXT DEFAULT 'pending',
  validation_message TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (product_id) REFERENCES products(id)
);
```

---

## 4.9 product_variants

用途：SKU / 颜色 / 尺码 / 变种维度。

```sql
CREATE TABLE product_variants (
  id TEXT PRIMARY KEY,
  product_id TEXT NOT NULL,
  seller_sku TEXT NOT NULL,
  merchant_sku TEXT,
  barcode TEXT,
  color_standard_value TEXT,
  color_display_value TEXT,
  size_standard_value TEXT,
  size_display_value TEXT,
  size_system TEXT,
  variant_attributes_json TEXT,
  variant_image_id TEXT,
  stock INTEGER NOT NULL DEFAULT 0,
  cost_price REAL,
  retail_price REAL,
  compare_at_price REAL,
  quote_price REAL,
  gross_weight REAL,
  package_length REAL,
  package_width REAL,
  package_height REAL,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (product_id) REFERENCES products(id)
);
```

---

## 4.10 product_pricing

用途：计价、基准价、报价字段集中管理。

```sql
CREATE TABLE product_pricing (
  id TEXT PRIMARY KEY,
  product_id TEXT NOT NULL,
  pricing_template_id TEXT,
  benchmark_price_template_id TEXT,
  quote_template_id TEXT,
  currency TEXT NOT NULL,
  exchange_rate REAL,
  cost_price REAL,
  domestic_shipping_cost REAL,
  international_shipping_cost REAL,
  packaging_cost REAL,
  commission_rate REAL,
  service_fee_rate REAL,
  target_margin_rate REAL,
  ad_buffer_rate REAL,
  refund_loss_rate REAL,
  pricing_formula TEXT,
  benchmark_reference_price REAL,
  retail_price REAL,
  sale_price REAL,
  compare_at_price REAL,
  wholesale_price REAL,
  quoted_price REAL,
  sample_price REAL,
  ladder_quote_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (product_id) REFERENCES products(id)
);
```

---

## 4.11 product_shipping

用途：重量、尺寸、发货地、运费模板、履约参数。

```sql
CREATE TABLE product_shipping (
  id TEXT PRIMARY KEY,
  product_id TEXT NOT NULL,
  shipping_template_id TEXT,
  freight_template_id TEXT,
  shipping_from_country TEXT,
  shipping_from_region TEXT,
  shipping_method_default TEXT,
  delivery_time_min INTEGER,
  delivery_time_max INTEGER,
  gross_weight REAL,
  net_weight REAL,
  package_weight REAL,
  package_length REAL,
  package_width REAL,
  package_height REAL,
  package_unit TEXT,
  weight_unit TEXT,
  dimension_unit TEXT,
  warehouse_country TEXT,
  domestic_warehouse_code TEXT,
  fulfillment_mode TEXT,
  handover_mode TEXT,
  expected_ship_date TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (product_id) REFERENCES products(id)
);
```

---

## 4.12 product_details

用途：详情页模板与内容。

```sql
CREATE TABLE product_details (
  id TEXT PRIMARY KEY,
  product_id TEXT NOT NULL,
  detail_template_id TEXT,
  detail_pc_html TEXT,
  detail_mobile_html TEXT,
  detail_module_json TEXT,
  ai_copy_style TEXT,
  selling_points TEXT,
  package_includes TEXT,
  warranty_text TEXT,
  safety_notice_text TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (product_id) REFERENCES products(id)
);
```

---

## 4.13 product_compliance

用途：欧盟负责人、制造商、GPSR、海关与危险品等合规字段。

```sql
CREATE TABLE product_compliance (
  id TEXT PRIMARY KEY,
  product_id TEXT NOT NULL,
  eu_responsible_template_id TEXT,
  manufacturer_template_id TEXT,
  compliance_template_id TEXT,
  eu_responsible_required INTEGER NOT NULL DEFAULT 0,
  eu_responsible_name TEXT,
  eu_responsible_company TEXT,
  eu_responsible_country TEXT,
  eu_responsible_address TEXT,
  eu_responsible_city TEXT,
  eu_responsible_postcode TEXT,
  eu_responsible_phone TEXT,
  eu_responsible_email TEXT,
  manufacturer_required INTEGER NOT NULL DEFAULT 0,
  manufacturer_name TEXT,
  manufacturer_company TEXT,
  manufacturer_country TEXT,
  manufacturer_address TEXT,
  manufacturer_city TEXT,
  manufacturer_postcode TEXT,
  manufacturer_phone TEXT,
  manufacturer_email TEXT,
  customs_attribute TEXT,
  hs_code TEXT,
  gpsr_required_flag INTEGER NOT NULL DEFAULT 0,
  gpsr_doc_list_json TEXT,
  battery_type TEXT,
  battery_included_flag INTEGER NOT NULL DEFAULT 0,
  dangerous_goods_flag INTEGER NOT NULL DEFAULT 0,
  children_product_flag INTEGER NOT NULL DEFAULT 0,
  compliance_note TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (product_id) REFERENCES products(id)
);
```

---

## 4.14 product_quotes

用途：半托管 / 托管报价域。

```sql
CREATE TABLE product_quotes (
  id TEXT PRIMARY KEY,
  product_id TEXT NOT NULL,
  quote_template_id TEXT,
  semi_managed_template_id TEXT,
  quote_required INTEGER NOT NULL DEFAULT 0,
  supply_price REAL,
  quoted_price REAL,
  target_procurement_price REAL,
  quote_currency TEXT,
  quote_terms TEXT,
  supply_cycle_days INTEGER,
  return_address TEXT,
  local_return_supported INTEGER NOT NULL DEFAULT 0,
  local_warehouse_required INTEGER NOT NULL DEFAULT 0,
  quote_status TEXT DEFAULT 'draft',
  quote_remark TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (product_id) REFERENCES products(id)
);
```

---

## 4.15 tasks

用途：任务批次主表。

```sql
CREATE TABLE tasks (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  platform TEXT NOT NULL,
  store_id TEXT NOT NULL,
  publish_scene TEXT NOT NULL,
  mode TEXT NOT NULL, -- preprocess / save_draft / publish / quote_submit
  status TEXT NOT NULL,
  total_jobs INTEGER NOT NULL DEFAULT 0,
  success_jobs INTEGER NOT NULL DEFAULT 0,
  failed_jobs INTEGER NOT NULL DEFAULT 0,
  manual_jobs INTEGER NOT NULL DEFAULT 0,
  created_by TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (store_id) REFERENCES stores(id)
);
```

---

## 4.16 jobs

用途：单商品执行单元。

```sql
CREATE TABLE jobs (
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL,
  product_id TEXT NOT NULL,
  status TEXT NOT NULL, -- pending / preprocessing / opening_page / waiting_manual_action / success / failed
  current_step_code TEXT,
  retry_count INTEGER NOT NULL DEFAULT 0,
  retry_limit INTEGER NOT NULL DEFAULT 3,
  last_error_code TEXT,
  last_error_message TEXT,
  blocked_reason TEXT,
  started_at TEXT,
  finished_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (task_id) REFERENCES tasks(id),
  FOREIGN KEY (product_id) REFERENCES products(id)
);
```

---

## 4.17 job_steps

用途：执行步骤树。

```sql
CREATE TABLE job_steps (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL,
  step_code TEXT NOT NULL,
  step_name TEXT NOT NULL,
  field_domain TEXT, -- title / category_qualification / media / sku_pricing / shipping / compliance / quote
  step_order INTEGER NOT NULL,
  status TEXT NOT NULL, -- not_started / in_progress / done / error / skipped
  started_at TEXT,
  finished_at TEXT,
  message TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (job_id) REFERENCES jobs(id)
);
```

建议 step_code：
- open_dxm
- check_login
- switch_store_scene
- load_templates
- fill_title_category_qualification
- upload_media
- fill_sku_pricing
- fill_shipping
- fill_compliance
- submit_publish_or_quote

---

## 4.18 job_evidences

用途：证据面板数据。

```sql
CREATE TABLE job_evidences (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL,
  step_id TEXT,
  evidence_type TEXT NOT NULL, -- screenshot / dom_snapshot / console_log / video / network_log
  file_path TEXT,
  meta_json TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (job_id) REFERENCES jobs(id),
  FOREIGN KEY (step_id) REFERENCES job_steps(id)
);
```

---

## 4.19 job_logs

用途：执行日志流。

```sql
CREATE TABLE job_logs (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL,
  step_id TEXT,
  level TEXT NOT NULL, -- info / warn / error
  message TEXT NOT NULL,
  payload_json TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (job_id) REFERENCES jobs(id),
  FOREIGN KEY (step_id) REFERENCES job_steps(id)
);
```

---

## 4.20 exceptions

用途：异常池。

```sql
CREATE TABLE exceptions (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL,
  step_id TEXT,
  error_code TEXT NOT NULL,
  error_domain TEXT NOT NULL, -- title / category_qualification / media / sku_pricing / shipping / compliance / quote / login / page
  severity TEXT NOT NULL, -- low / medium / high / blocker
  title TEXT NOT NULL,
  detail TEXT,
  suggestion TEXT,
  screenshot_path TEXT,
  status TEXT NOT NULL DEFAULT 'open', -- open / fixed / ignored / retried
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (job_id) REFERENCES jobs(id),
  FOREIGN KEY (step_id) REFERENCES job_steps(id)
);
```

---

# 5. 关键索引建议

```sql
CREATE INDEX idx_products_store_scene ON products(store_id, publish_scene);
CREATE INDEX idx_templates_lookup ON templates(platform, store_id, category_id, publish_scene, template_type);
CREATE INDEX idx_jobs_task_status ON jobs(task_id, status);
CREATE INDEX idx_steps_job_order ON job_steps(job_id, step_order);
CREATE INDEX idx_exceptions_domain_status ON exceptions(error_domain, status);
```

---

# 6. 本地 IPC / API 草案

这里的 API 指客户端前端与本地任务引擎/执行器之间的接口。

推荐形式：
- Tauri command
- Electron IPC
- 本地 HTTP + WebSocket（也可）

我按“语义接口”来写。

## 6.1 客户端会话与店铺

### 1. 连接店小秘
`POST /local/stores/{store_id}/connect`

请求：
```json
{
  "platform": "aliexpress",
  "publish_scene": "pop"
}
```

返回：
```json
{
  "store_id": "store_001",
  "status": "opening_login_page"
}
```

### 2. 检查登录态
`GET /local/stores/{store_id}/login-status`

返回：
```json
{
  "store_id": "store_001",
  "login_status": "logged_in",
  "last_check_at": "2026-04-19T20:00:00+08:00"
}
```

### 3. 清理本地会话
`DELETE /local/stores/{store_id}/session`

---

## 6.2 商品导入与预处理

### 4. 导入 Excel/CSV
`POST /local/imports/file`

### 5. 导入链接列表
`POST /local/imports/links`

请求：
```json
{
  "store_id": "store_001",
  "publish_scene": "semi_managed",
  "links": ["https://example.com/p1", "https://example.com/p2"]
}
```

### 6. 创建商品
`POST /local/products`

### 7. 触发预处理
`POST /local/products/preprocess`

请求：
```json
{
  "product_ids": ["prod_001", "prod_002"],
  "apply_templates": true
}
```

---

## 6.3 模板中心

### 8. 查询模板列表
`GET /local/templates?template_type=pricing&store_id=store_001&publish_scene=pop`

### 9. 新建模板
`POST /local/templates`

请求：
```json
{
  "platform": "aliexpress",
  "store_id": "store_001",
  "category_id": "100003109",
  "publish_scene": "pop",
  "template_type": "pricing",
  "template_name": "速卖通鞋类标准计价模板",
  "payload": {
    "commission_rate": 0.08,
    "target_margin_rate": 0.25,
    "pricing_formula": "(cost+domestic+intl+pkg)/(1-commission-margin)"
  }
}
```

### 10. 更新模板
`PUT /local/templates/{template_id}`

### 11. 绑定模板
`POST /local/templates/{template_id}/bindings`

### 12. 预览商品模板绑定结果
`POST /local/products/{product_id}/template-preview`

---

## 6.4 任务中心

### 13. 创建任务
`POST /local/tasks`

请求：
```json
{
  "name": "6月速卖通批次",
  "platform": "aliexpress",
  "store_id": "store_001",
  "publish_scene": "semi_managed",
  "mode": "publish",
  "product_ids": ["prod_001", "prod_002"]
}
```

### 14. 获取任务列表
`GET /local/tasks`

### 15. 获取任务详情
`GET /local/tasks/{task_id}`

### 16. 启动任务
`POST /local/tasks/{task_id}/start`

### 17. 暂停任务
`POST /local/tasks/{task_id}/pause`

### 18. 恢复任务
`POST /local/tasks/{task_id}/resume`

### 19. 停止任务
`POST /local/tasks/{task_id}/stop`

---

## 6.5 作业与步骤

### 20. 获取 Job 列表
`GET /local/tasks/{task_id}/jobs`

### 21. 获取 Job 步骤树
`GET /local/jobs/{job_id}/steps`

### 22. 跳过当前商品
`POST /local/jobs/{job_id}/skip`

### 23. 重试当前步骤
`POST /local/jobs/{job_id}/retry-current-step`

### 24. 人工接管
`POST /local/jobs/{job_id}/manual-takeover`

### 25. 人工接管结束，继续执行
`POST /local/jobs/{job_id}/continue`

---

## 6.6 证据面板与日志

### 26. 获取证据列表
`GET /local/jobs/{job_id}/evidences`

### 27. 获取日志列表
`GET /local/jobs/{job_id}/logs`

### 28. 主动截图
`POST /local/jobs/{job_id}/screenshot`

### 29. 开始录屏
`POST /local/jobs/{job_id}/recording/start`

### 30. 停止录屏
`POST /local/jobs/{job_id}/recording/stop`

---

## 6.7 异常池

### 31. 获取异常列表
`GET /local/exceptions?status=open&error_domain=media`

### 32. 获取异常详情
`GET /local/exceptions/{exception_id}`

### 33. 标记已修复并重试
`POST /local/exceptions/{exception_id}/fix-and-retry`

### 34. 忽略异常
`POST /local/exceptions/{exception_id}/ignore`

---

# 7. WebSocket / 事件流草案

为了实现“RPA 实时执行区”，前端必须订阅事件流。

建议事件主题：

```text
task.updated
job.updated
job.step.updated
job.log.created
job.evidence.created
job.manual_action.required
job.error
store.login_status.changed
```

### 示例事件：步骤更新
```json
{
  "type": "job.step.updated",
  "payload": {
    "job_id": "job_001",
    "step_code": "fill_title_category_qualification",
    "status": "in_progress",
    "field_domain": "category_qualification",
    "message": "正在填写标题并检查资质要求"
  }
}
```

### 示例事件：人工接管
```json
{
  "type": "job.manual_action.required",
  "payload": {
    "job_id": "job_001",
    "reason": "captcha_detected",
    "message": "检测到验证码，请用户手工完成后继续执行"
  }
}
```

---

# 8. 云端 API 草案

云端只做轻服务。

## 8.1 认证与订阅

### 登录产品账号
`POST /cloud/auth/login`

### 获取订阅信息
`GET /cloud/subscription/me`

### 上报设备绑定
`POST /cloud/devices/bind`

---

## 8.2 AI 服务

### 生成标题
`POST /cloud/ai/title/generate`

### 生成详情
`POST /cloud/ai/detail/generate`

### 属性补全建议
`POST /cloud/ai/attributes/suggest`

---

## 8.3 配置与热更新

### 获取选择器配置
`GET /cloud/config/selectors?platform=aliexpress`

### 获取禁词库
`GET /cloud/config/forbidden-words`

### 获取版本信息
`GET /cloud/releases/latest`

---

# 9. 开发顺序建议

## Phase 1：本地最小闭环
- stores / sessions
- templates / template_bindings
- products / product_variants / product_media / product_pricing
- tasks / jobs / job_steps / exceptions / evidences / logs
- 本地 IPC：任务、模板、执行、异常

## Phase 2：RPA 可视化增强
- WebSocket 事件流
- 证据面板
- 手工接管
- 录屏与截图

## Phase 3：云端增强
- 订阅系统
- AI 服务
- 配置热更新

---

# 10. 最终结论

这套表结构和 API 草案已经够你进入开发评审：

1. 数据层边界清楚
2. 模板中心可以落库
3. POP 与半托管都能覆盖
4. RPA 实时执行区有可驱动的事件模型
5. 云端与本地职责分离明确

一句话：
现在可以基于这份文档直接开数据库设计评审和接口评审。
> 由 OpenAI GPT（Codex）AI 生成/维护。

# DXM-TX 类目节点与目录合同

**合同编号：`DXM-CATEGORY-CATALOG-001`**
**状态：版本化上游参考 + 本产品执行不变量；不是店小秘当前页面的替代真相。**
**上游观测时间：2026-07-28T02:02:18Z；本仓同步日期：2026-08-25。**

本合同把 `D:\Desktop\py\DXM-TX` 中此前遗漏的类目树、叶子身份、双向路径映射和程序数据迁入本仓。产品主合同见 [MVP 竖切主合同](../product/MVP-竖切-草稿箱批量只保存.md)，上游事实分层见 [DXM-TX 上游事实合同](DXM-TX-上游事实合同.md)。

## 1. 迁移产物

| 产物 | 作用 |
|---|---|
| [category-catalog.v1.json](../../resources/dxm/category-catalog/category-catalog.v1.json) | 规范化的 13,216 个类目节点；不含账号、店铺、商品、Cookie 或业务 raw |
| [category-catalog.manifest.json](../../resources/dxm/category-catalog/category-catalog.manifest.json) | 来源文件、SHA256、数量、漂移和敏感范围声明 |
| [sync-dxm-category-catalog.ps1](../../scripts/sync-dxm-category-catalog.ps1) | 固定源范围、归一化、冲突标记和 hash 校验 |

生成与复核：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\sync-dxm-category-catalog.ps1 -Write
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\sync-dxm-category-catalog.ps1 -Check
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\sync-dxm-category-catalog.ps1 -SelfTest
```

`-Write` 只允许读取 `DXM-TX\data\capture\categories`。脚本硬锁五个源文件 SHA256；源文件改变时输出漂移错误，不能静默覆盖 catalog。`-SelfTest` 先在内存制造目录内容漂移并输出 `RED_EXPECTED`，再对真实 catalog 重新生成、逐字节哈希比对并输出 `DXM_CATEGORY_CATALOG_OK`。

## 2. 上游读取合同

DXM-TX 已观察到：

| Method | Endpoint | 用途 |
|---|---|---|
| POST | `/api/smtCategory/list.json` | 空 form 读取根节点 |
| POST | `/api/smtCategory/list.json` | `pcid=<parent categoryId>` 读取直接子节点 |
| POST | `/api/smtCategory/getByCategoryId.json` | `categoryId=<id>` 读取单节点详情 |

目录遍历使用 BFS，停止条件是节点 `isleaf=1`。树为动态任意深度，禁止假设固定三级，也禁止把 `level===2` 当成叶子。

`searchCategory.json` 目前只属于当前代码观察接口，不是本映射文档已经证明的稳定主合同。搜索命中必须再通过 `getByCategoryId` 和祖先链水合，不能直接冻结显示文本。

## 3. `CategoryNode.v1`

每个规范节点至少包含：

```yaml
categoryId: PositiveDecimalString
parentCategoryId: PositiveDecimalString | null
observedLevel: integer
pathDepth: positiveInteger
isLeaf: boolean
executableLeaf: boolean
nameZh: string
nameEn: string
nodePath: string
nodePathIds: [PositiveDecimalString]
pathNamesZh: [string]
pathNamesEn: [string]
capabilities:
  isEuContact: boolean
  isEan: boolean
  isNewSize: boolean
  sizeChartType: string | null
  sizeChartSubTypeList: []
  features: object | null
  hasCascadeAttribute: unknown
  hasPlugAttribute: unknown
capabilitiesSha256: sha256
sourceFlags:
  isDeleted: boolean
  createTime: scalar | null
  updateTime: scalar | null
integrity:
  directParentConsistent: boolean
  fullAncestorChainConsistent: boolean
  observedLevelTrusted: boolean
  issues: []
nodeIdentitySha256: sha256
```

身份规则：

- `categoryId` 是执行主身份；中文名和显示路径只用于 UI。
- `categoryId` 必须等于 `nodePathIds` 最后一段。
- 非根节点的 `parentCategoryId` 必须等于 `nodePathIds` 倒数第二段。
- `nodeIdentitySha256` 覆盖 id、父 id、叶子状态、路径 id、中英文名称、展示路径、删除状态和上游更新时间。
- `capabilitiesSha256` 独立覆盖全部类目能力字段；节点身份或能力任一漂移都必须使旧快照失效。
- `observedLevel` 原样保留但不作为执行身份。当前源数据中它与路径深度有大量不一致，运行时必须使用父链和 `nodePathIds` 计算结构。

## 4. 当前目录快照事实

本版本以较新的 `all_nodes.json` 和 `category_leaf_mapping.json` 为准：

| 指标 | 当前观测值 |
|---|---:|
| 全部节点 | 13,216 |
| 根节点 | 36 |
| 叶子节点 | 11,864 |
| 可进入方案的无冲突叶子 | 11,852 |
| 不可执行叶子 | 12 |
| 完整祖先链与 `nodePathId` 冲突 | 12 |
| `observedLevel` 不可信节点 | 13,005 |
| 非叶但本快照未观测到子节点 | 4 |
| 重复叶子展示路径 | 1 |

按 `nodePathIds` 推导的深度分布为 `0:36 / 1:437 / 2:4,139 / 3:8,601 / 4:3`，进一步证明不得写死三层。`features` 的 13,177 个非空 JSON 字符串均被解析为对象，39 个为空；`sizeChartSubTypeList` 的 312 个非空值均被解析为数组。`hasCascadeAttribute/hasPlugAttribute` 全部为空，必须保留为 `UNKNOWN/null`，不能强制转换成 `false`。

这些数字只属于该 source hash 的 `SAMPLE_ONLY_VERSIONED_REFERENCE`，不是未来 catalog 的永久阈值。

旧 `leaf_id_to_path_compact.json` 只有 11,795 个叶子，早于当前 `all_nodes.json`。本仓没有用旧 compact 覆盖新目录；manifest 把它记录为 `EXCLUDED_STALE_11795_LEAF_SNAPSHOT`。

12 个祖先链冲突节点没有被删除或修造为“正确”：它们保留在 catalog 中用于审计，但 `executableLeaf=false`，不得进入 preview/freeze/Runner。只有新的同源目录观测能关闭冲突。

## 5. 双向映射

目录消费者必须支持：

1. `categoryId → nodePathIds/pathNamesZh/pathNamesEn`；
2. 完整路径身份 → 一个或多个叶子 `categoryId`；
3. `parentCategoryId → children[]` 的动态展开；
4. 搜索命中 → `getByCategoryId` → 祖先链重建。

`nodePath` 显示文本不保证全局唯一。出现同路径多叶子、重复 id、父链冲突或搜索/详情冲突时必须 fail-closed，不能按第一个结果猜选。

另外，1,763 个类目名称自身包含 `/`，所以绝对不能拆分 `nodePath` 文本来恢复层级；结构只来自 `nodePathIds`，名称数组按这些 ID 水合。当前同一展示路径映射到叶子 `200002401` 与 `200002402`，证明 display path → leaf 必须是一对多；同步脚本已逐项交叉核验上游 `leaf_id_to_path` 与 `path_to_leaf_ids`，规范 catalog 中每个节点携带完整 ID/名称路径，可无损重建双向索引。

## 6. 方案与快照合同

每件商品必须分别冻结源类目和目标类目：

```yaml
sourceCategory:
  categoryId: "..."
  nodeIdentitySha256: "..."
targetCategory:
  categoryId: "..."
  nodeIdentitySha256: "..."
  catalogSha256: "B79C02BACC23759E2CAFA632EEF0EAAAB53868D38C2F164408B3BD9CABCA671B"
  isLeaf: true
  executableLeaf: true
targetSchema:
  schemaSha256: "..."
targetCapabilities:
  capabilitiesSha256: "..."
```

硬门禁：

- 只有 `isLeaf=true && executableLeaf=true` 的目标可以 preview/freeze。
- `isleaf=0` 即使当前快照没有观测到 children 也仍为非叶，禁止推测升级。
- 源类目 id、目标类目 id 和目标 Schema hash 不得混成一个字段。
- 目录 catalog 用于搜索、展示和冻结参考；不能替代当前登录会话。
- 执行切类目后、写任何字段前，必须从真实可见页面和当前会话重新读取 `categoryId`、Schema 与能力，并与快照精确比较。
- 当前页面或 Schema 漂移时必须在首个字段写入前停止。
- 中文路径只能显示，不能单独作为 DOM 或执行 binding。

## 7. 会话与漂移

类目接口响应必须绑定 `session_ref`、账号上下文、观测时间和响应 schema hash。换账号、换店铺、换浏览器 generation、Reader 失败或目录漂移时：

- 清空前端类目树和目标类目；
- 使旧 preview/freeze 输入失效；
- 重新读取目录/详情/Schema/模板；
- 不把本地 catalog 的旧值当作当前可写证明。

## 8. 当前代码阻断

截至 2026-08-25，当前实现仍有以下产品阻断：

- 前端类目级联固定三层，并可能把第三级非叶节点当作目标；
- 后端响应没有完整节点、账号、会话和 catalog envelope；
- snapshot 未完整冻结 node/catalog/capability identities；
- 源类目和目标类目在冻结执行链中可能混用；
- 模板解析仍存在硬编码类目路径；
- 上游 switch-category 请求序列和旧字段失效仍缺真实闭环。

因此 catalog 同步完成不等于切类目生产可用，也不构成 `MVP_READY` 或 `PROD_READY`。

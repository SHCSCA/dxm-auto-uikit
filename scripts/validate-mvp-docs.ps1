[CmdletBinding()]
param(
    [switch]$SelfTest
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $scriptDir "..")).Path
$upstreamRoot = "D:\Desktop\py\DXM-TX"
$contractRelativePath = "docs/product/MVP-竖切-草稿箱批量只保存.md"
$aiNotice = "由 OpenAI GPT（Codex）AI 生成/维护"

$paths = [ordered]@{
    RootReadme = Join-Path $repoRoot "README.md"
    Changelog = Join-Path $repoRoot "CHANGELOG.md"
    Contract = Join-Path $repoRoot "docs\product\MVP-竖切-草稿箱批量只保存.md"
    Gold = Join-Path $repoRoot "docs\product\CODEX-GOLD-工作指令-MVP批量只保存.md"
    PlanArchitecture = Join-Path $repoRoot "docs\product\普货方案配置与执行架构.md"
    RuntimeArchitecture = Join-Path $repoRoot "docs\architecture\当前运行时架构.md"
    UnifiedDevelopmentPlan = Join-Path $repoRoot "docs\architecture\DXM-工作台与分区自动化统一开发方案.md"
    UpstreamContract = Join-Path $repoRoot "docs\integration\DXM-TX-上游事实合同.md"
    CategoryContract = Join-Path $repoRoot "docs\integration\DXM-TX-类目节点与目录合同.md"
    OperatorRunbook = Join-Path $repoRoot "docs\runbook\操作与验收手册.md"
    DetailedOperations = Join-Path $repoRoot "docs\runbook\运营操作详细文档.md"
    UserGuide = Join-Path $repoRoot "docs\user\免安装桌面版.md"
    Agents = Join-Path $repoRoot "AGENTS.md"
    Claude = Join-Path $repoRoot "CLAUDE.md"
    DocsIndex = Join-Path $repoRoot "docs\README.md"
    Progress = Join-Path $repoRoot "PROGRESS.md"
    Blocked = Join-Path $repoRoot "BLOCKED.md"
    Prototype = "D:\Desktop\py\DXM-TX\DXM-半托管工作台-可交互原型.html"
    CategoryCatalog = Join-Path $repoRoot "resources\dxm\category-catalog\category-catalog.v1.json"
    CategoryManifest = Join-Path $repoRoot "resources\dxm\category-catalog\category-catalog.manifest.json"
    CategorySyncScript = Join-Path $repoRoot "scripts\sync-dxm-category-catalog.ps1"
}

$expectedGoldSha256 = "BED0012C260AA8BF03E46CEDE33AEE3CFE9A265471DBC10CB79CA97FBCB9CB43"
$expectedPrototypeSha256 = "29B76F8F2ACC6DDA15393AB20B4D0C07A10739B94A4E8E11A8341AD0DEC4A847"
$expectedCategoryCatalogSha256 = "B79C02BACC23759E2CAFA632EEF0EAAAB53868D38C2F164408B3BD9CABCA671B"
$expectedUpstreamSources = [ordered]@{
    "README.md" = "D91145EFD018EB663473B55A712FB89D75CF758A09F899F0A999C8FE76A0AE6C"
    "PROGRESS.md" = "D5D992CC8061C979A12212ED695811F0A08EE77CE85966131D3A9FEC043C4CBE"
    "BLOCKED.md" = "4CA42044AC1477D32FCE712426FEECED715CD1AF04E06FD750BDBB2B1BF9758E"
    "docs\README.md" = "981F25B0C8C0B6919D30357D0F782F801740C32A4872DB3CAAF701E2C2D91C09"
    "docs\01-产品与混合架构.md" = "4DB90765C161CB4F9534CFB9873752F5E958975E8F4567630C4AAB77824FA403"
    "docs\02-编辑页执行与填写手册.md" = "88D7A8E5E0757BD4F116CE881C843DCCBC170424D2DDCF9109EE95CCB1D4D182"
    "docs\03-半托管全流程操作手册.md" = "7B351D36E005348EFFEB68CE0CDCEDAEB18E8E4E15AD6346B3FFA4B864B248C1"
    "docs\api\店小秘-采集箱草稿列表与选品接口.md" = "601FFF2F0105032E82393BF26B25FF69BD2B03A620CBAC221BBFE300B330AC85"
    "docs\api\店小秘-常用模板与编辑页-接口文档.md" = "B491AB60ED3E0189EB81B6DC67B842049A994C74545C3CFC62CBA1BBC9215C15"
    "docs\api\店小秘-半托管双保存路径.md" = "684F345AB62E85B2BB3941EF95C226881B77414C4040A4BFD133B1F36A8225C5"
    "docs\api\店小秘-类目路径与叶子ID映射.md" = "2E53B5394F1E3B843A06892F67E2316F18FD27A55E22344FFE1EE64B13BDF761"
    "docs\api\店小秘-接口抓包缺口与场景矩阵.md" = "78CA753BE3FED5F7AA37F7F493ADBA641F7F33ADDF6DAE15BC08BDD3403C181F"
    "docs\api\DXM-已观察私有接口总目录.md" = "6BE7347A7EEA3FE297978BADAAAE15429159437932FD752FCF7BFF2F0AD2F3AC"
    "docs\api\DXM-常用模板接口.md" = "1ECD87C0CAD6F089F1886232CD5817C2CF332C0A76962370AD99645A20027351"
    "docs\api\DXM-编辑页接口.md" = "531467886266C3603584C0CA0BC960C7F565E3E24122B9B75B8963A56C5B920C"
    "docs\api\DXM-接口字段血缘.md" = "D4085E3D1E57A0977B223E9E93B3EBE3DE322D215208E2AD844012C428153776"
    "data\capture\categories\all_nodes.json" = "25A665AFAAF34E2626F2DC43A58B3A7FB3147E85340E3B97FA7C13C461178A10"
    "data\capture\categories\category_leaf_mapping.json" = "7CC422A5E07110700597D0FC0BB03E5D74F54FED345544C39F8EF09DB6E6DB35"
    "data\capture\categories\category_leaf_mapping.csv" = "21326822B0797AFFA075DDB1A315986085403E1153E997E05D6DEA114B2AB483"
    "data\capture\categories\leaf_id_to_path_compact.json" = "B320916CDC88931DD24E5D96E0D8AB75EF5BAB7283ED89FB5A3F1461DB27D4C2"
    "data\capture\categories\root_list.json" = "913CB7C0D81E24519E37DD0450A2B63898A50544E63678EE757673C3AA448E81"
}

function Read-Utf8Text {
    param([Parameter(Mandatory = $true)][string]$LiteralPath)
    return Get-Content -LiteralPath $LiteralPath -Raw -Encoding UTF8
}

function Add-MissingTerms {
    param(
        [Parameter(Mandatory = $true)]$Errors,
        [Parameter(Mandatory = $true)][string]$Content,
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][string[]]$Terms
    )
    foreach ($term in $Terms) {
        if (-not $Content.Contains($term)) {
            $Errors.Add("$Label 缺少必需术语：$term")
        }
    }
}

function Add-MissingPatterns {
    param(
        [Parameter(Mandatory = $true)]$Errors,
        [Parameter(Mandatory = $true)][string]$Content,
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][object[]]$Rules
    )
    foreach ($rule in $Rules) {
        if (-not [regex]::IsMatch($Content, [string]$rule.Pattern)) {
            $Errors.Add("$Label 缺少必需口径：$($rule.Description)")
        }
    }
}

function Get-ContractContentErrors {
    param([Parameter(Mandatory = $true)][string]$Content)

    $errors = [System.Collections.Generic.List[string]]::new()
    Add-MissingPatterns -Errors $errors -Content $Content -Label "主合同" -Rules @(
        @{ Pattern = '(?m)^###\s+6\.1\s+.*MVP_READY.*$'; Description = '§6.1 MVP_READY' },
        @{ Pattern = '(?m)^##\s+7\.\s+E0.+E4\s+Definition of Done\s*$'; Description = '§7 E0-E4 DoD' },
        @{ Pattern = '(?m)^##\s+8\.\s+指定根原型一致性\s*$'; Description = '§8 原型一致性' },
        @{ Pattern = '(?m)^##\s+11\.\s+人工验收\s*$'; Description = '§11 人工验收' },
        @{ Pattern = '(?s)完整产品成功路径固定为\s+\*{0,2}Path B\*{0,2}'; Description = 'Path B 是完整产品成功路径' },
        @{ Pattern = '(?s)Path A.{0,120}(?:诊断|canary).{0,160}(?:不得|不能).{0,160}(?:产品完成|完整产品|MVP_READY|PROD_READY)'; Description = 'Path A 仅诊断且不能代表产品完成' },
        @{ Pattern = '(?s)中间.{0,40}“继续发布”.{0,120}允许.{0,40}自动化'; Description = '精确中间“继续发布”允许受控自动化' },
        @{ Pattern = '(?s)唯一含发布文字的允许动作.{0,100}SEMI_MANAGED_CONTINUE_TRANSITION'; Description = '唯一发布文字例外绑定独立 action kind' },
        @{ Pattern = '(?s)最终.{0,80}(?:发布|上线).{0,80}永久禁止'; Description = '最终发布永久禁止' },
        @{ Pattern = '(?s)类目树任意深度'; Description = '类目树动态任意深度' },
        @{ Pattern = '(?s)只有.{0,80}isleaf=1.{0,100}executableLeaf=true.{0,100}(?:目标|冻结)'; Description = '仅无冲突叶子可执行' }
    )

    Add-MissingTerms -Errors $errors -Content $Content -Label "主合同" -Terms @(
        "E3_OPEN / BLOCKED", "真实可见", "draft ≥3", "只读接口", "UI 写", "模板优先补差",
        "不可变 plan snapshot", "batch_draft_save", "HVD 与 runner 同源", "开始 / 暂停 / 继续 / 停止",
        "回包 + 页面成功态 + 独立未发布证明", "UNKNOWN 停批", "不得自动重试", "MVP_READY ≠ PROD_READY",
        "claim_only 非前置", "local_plan_template", "dxm_template_ref", "PASSIVE_ONLY", "SAMPLE_ONLY", "PublishGuard",
        "REQUIRED_CAPABILITY / ALWAYS_ON", "每件商品必须无条件执行", "mandatoryCapabilities", "video: true",
        "translation: true", "wholesale: true", "semiManaged: true", "rollbackPreparation: true", "不允许由方案关闭",
        '不允许 `SKIPPED_BY_FROZEN_PLAN`', "SEMI_MANAGED_CONTINUE_TRANSITION", "editFromSmt", "动态类目", "任意深度",
        "categoryId", "catalogSha256", "nodeIdentitySha256", "schemaSha256", "capabilitiesSha256",
        "当前可见页面类目和实时 Schema 才是写前执行权威", "preimage", "严格逆序恢复计划", "中文界面",
        "中文字段映射", "自动写入的自然语言内容必须为英文", "保存前校验", "240px", "56px", "#4f46e5",
        "16px", "明暗主题", "1100px/860px", "工作台", "连接店小秘", "采集箱选品", "铺货方案",
        "开始批量保存", "保存结果", "设置"
    )

    foreach ($capability in @("video", "translation", "wholesale", "semiManaged", "rollbackPreparation")) {
        if ($Content -notmatch "(?m)^\s*$([regex]::Escape($capability)):\s*true\s*$") {
            $errors.Add("主合同未把每件商品必经能力冻结为 true：$capability")
        }
        if ($Content -match "(?m)^\s*$([regex]::Escape($capability)):\s*false\s*$") {
            $errors.Add("主合同允许关闭每件商品必经能力：$capability")
        }
    }

    foreach ($narrative in @(
        "类目树固定为三级", "固定三级类目", "第三层即叶子", "仅支持三级类目",
        "支持可选的视频生成、一键翻译、批发配置和半托管流程",
        "半托管勾选、视频生成、一键翻译、批发配置为可选功能",
        "Path A 为完整产品成功路径", "Path A 是完整产品成功路径",
        "允许最终发布", "最终发布可自动化", '任意含“继续发布”按钮均允许自动化'
    )) {
        if ($Content.Contains($narrative)) { $errors.Add("主合同出现产品或安全回退叙事：$narrative") }
    }

    foreach ($patternRule in @(
        @{ Pattern = '(?im)^\s*publishAllowed\s*:\s*true\s*$'; Description = 'publishAllowed=true' },
        @{ Pattern = '(?s)(?:允许|支持)(?:关闭|跳过).{0,80}(?:视频|翻译|批发|半托管|rollback preparation)'; Description = '允许关闭或跳过必经能力' },
        @{ Pattern = '(?s)(?:视频|翻译|批发|半托管|回滚).{0,40}(?:是|为|属于)\s*(?:可选|选配)'; Description = '把必经能力定义为可选' },
        @{ Pattern = '(?s)Path A.{0,60}(?:完整成功主路径|完整产品成功路径|产品主路径)'; Description = 'Path A 被提升为完整产品主路径' },
        @{ Pattern = '(?s)任意.{0,30}继续发布.{0,30}(?:允许|可).{0,20}自动'; Description = '泛化允许继续发布' }
    )) {
        if ([regex]::IsMatch($Content, [string]$patternRule.Pattern)) {
            $errors.Add("主合同出现产品或安全回退叙事：$($patternRule.Description)")
        }
    }

    foreach ($narrative in @("MVP 人工验收数量至少 1", "draft ≥1", "MVP 验收 ≥1", "人工多选 ≥1", "至少 1 个 draft Path A")) {
        if ($Content.Contains($narrative)) { $errors.Add("主合同把 draft ≥3 人工验收降级为单品：$narrative") }
    }
    return @($errors)
}

function Get-MarkdownLinkErrors {
    param(
        [Parameter(Mandatory = $true)][string]$Content,
        [Parameter(Mandatory = $true)][string]$SourcePath
    )
    $errors = [System.Collections.Generic.List[string]]::new()
    $sourceDirectory = Split-Path -Parent $SourcePath
    $matches = [regex]::Matches($Content, '(?<!\!)\[[^\]]+\]\(\s*(?:<(?<target>[^>]+)>|(?<target>[^)\s]+))(?:\s+"[^"]*")?\s*\)')
    foreach ($match in $matches) {
        $target = $match.Groups["target"].Value.Trim()
        if ($target.StartsWith("#") -or $target.StartsWith("http://", [System.StringComparison]::OrdinalIgnoreCase) -or
            $target.StartsWith("https://", [System.StringComparison]::OrdinalIgnoreCase) -or
            $target.StartsWith("mailto:", [System.StringComparison]::OrdinalIgnoreCase)) { continue }
        $pathPart = [System.Uri]::UnescapeDataString($target.Split("#")[0])
        if ([string]::IsNullOrWhiteSpace($pathPart)) { continue }
        if ([System.IO.Path]::IsPathRooted($pathPart)) { $candidate = [System.IO.Path]::GetFullPath($pathPart) }
        else { $candidate = [System.IO.Path]::GetFullPath((Join-Path $sourceDirectory $pathPart)) }
        if (-not (Test-Path -LiteralPath $candidate)) {
            $lineNumber = ([regex]::Matches($Content.Substring(0, $match.Index), "\r?\n")).Count + 1
            $errors.Add("悬空链接：$SourcePath`:$lineNumber -> $target")
        }
    }
    return @($errors)
}

function Get-AiNoticeErrors {
    param(
        [Parameter(Mandatory = $true)][string]$Content,
        [Parameter(Mandatory = $true)][string]$Name
    )
    $firstNonEmpty = @($Content -split "\r?\n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }) | Select-Object -First 1
    if ($null -eq $firstNonEmpty -or -not $firstNonEmpty.Contains($aiNotice)) {
        return @("$Name 未在首个非空行标注：$aiNotice")
    }
    return @()
}

function Get-MarkdownStructureErrors {
    param(
        [Parameter(Mandatory = $true)][string]$Content,
        [Parameter(Mandatory = $true)][string]$Name
    )
    $errors = [System.Collections.Generic.List[string]]::new()
    if ($Content.IndexOf([char]0xFFFD) -ge 0) {
        $errors.Add("$Name 含 Unicode replacement character U+FFFD，存在乱码或解码损坏")
    }
    $lines = @($Content -split "\r?\n")
    for ($index = 1; $index -lt ($lines.Count - 1); $index++) {
        if (-not [string]::IsNullOrWhiteSpace($lines[$index])) { continue }
        if ($lines[$index - 1] -match '^\s*\|.*\|\s*$' -and $lines[$index + 1] -match '^\s*\|.*\|\s*$') {
            $errors.Add("$Name Markdown 表格被空行断裂：line $($index + 1)")
        }
    }
    return @($errors)
}

function Get-UnifiedDevelopmentPlanErrors {
    param([Parameter(Mandatory = $true)][string]$Content)
    $errors = [System.Collections.Generic.List[string]]::new()
    Add-MissingTerms -Errors $errors -Content $Content -Label "工作台与分区自动化统一开发方案" -Terms @(
        '同一时刻、同一 `shop_id` 只允许一个系统内部正式写 task 持有 writer fence',
        '每个 ledger `BEGIN` 重新验证 fencing token',
        "版本化 allowlist", "实际观察到的最严重 effect", "final_effect_class",
        "video → HVD checkpoint → wholesale → HVD checkpoint → translation → HVD checkpoint → delegated-field readback",
        "contract_version: dxm_execution_constraints.v1", "max_start_age_hours: 24", "session_refresh_allowed: false",
        "category_drift_action: ABORT", "schema_drift_action: ABORT", "catalog_drift_action: ABORT",
        "draft_presence_check: REQUIRED", "resolving", "停止/急停只记录停止意图并阻止新命令",
        "canonical_serialization:", "schema: dxm_canonical_json.v1", "unicode_normalization: NFC",
        "object_key_order: lexicographic", "arrays: preserve_contract_order", "domain_numbers: normalized_decimal_strings",
        "DISABLED_UNTIL_OBSERVED_EVIDENCE_VERSION"
    )
    Add-MissingPatterns -Errors $errors -Content $Content -Label "工作台与分区自动化统一开发方案" -Rules @(
        @{ Pattern = '(?s)inspect.{0,400}(?:before/after|前后状态).{0,400}(?:最严重 effect|final_effect_class)'; Description = 'inspect 以真实 before/after facts 和最严重 effect 裁决' },
        @{ Pattern = '(?s)resolving.{0,400}继续.{0,80}禁用.{0,400}(?:停止|急停).{0,120}(?:不得|不能).{0,120}(?:终态|成功|失败|UNKNOWN)'; Description = 'resolving 控制键不得伪造终态' },
        @{ Pattern = '(?s)direct `editFromSmt`.{0,300}DISABLED_UNTIL_OBSERVED_EVIDENCE_VERSION.{0,400}(?:只收集|只记录|采集).{0,200}(?:停批|不得现场启用)'; Description = 'direct editFromSmt 先取证、停批、版本裁决' }
    )

    foreach ($rule in @(
        @{ Pattern = '(?m)^\s*(?:category|schema|catalog)_drift_action:\s*(?:PROCEED_WITH_WARNING|WARN_ONLY|CONTINUE)\s*$'; Description = 'Schema/category/catalog 漂移被放宽' },
        @{ Pattern = '(?m)^\s*max_start_age_hours:\s*0\s*$'; Description = 'snapshot 启动有效期被设为无限' },
        @{ Pattern = '(?m)^\s*draft_presence_check:\s*(?:OPTIONAL|false|DISABLED)\s*$'; Description = '草稿存在性检查被关闭或降级' },
        @{ Pattern = '(?s)急停.{0,40}(?:立即|直接).{0,40}(?:改为|转为|标记为|写成).{0,30}(?:成功|失败|UNKNOWN|终态)'; Description = '急停伪造 resolving 终态' },
        @{ Pattern = '(?m)^\s*direct_edit_from_smt_landing:\s*ENABLED\s*$'; Description = 'direct editFromSmt 未经版本化证据即启用' }
    )) {
        if ([regex]::IsMatch($Content, [string]$rule.Pattern)) {
            $errors.Add("工作台与分区自动化统一开发方案出现安全合同回退：$($rule.Description)")
        }
    }
    return @($errors)
}

function Get-DocumentTruthErrors {
    param([Parameter(Mandatory = $true)][hashtable]$Contents)
    $errors = [System.Collections.Generic.List[string]]::new()
    foreach ($rule in @(
        @{ Name = "Gold"; Key = "Gold"; Terms = @($contractRelativePath, "每件商品无条件执行", "Path B", "SEMI_MANAGED_CONTINUE_TRANSITION", "最终发布", "动态类目") },
        @{ Name = "AGENTS.md"; Key = "Agents"; Terms = @($contractRelativePath, "五项 ALWAYS_ON", "Path B", "SEMI_MANAGED_CONTINUE_TRANSITION", "CategoryCatalog") },
        @{ Name = "CLAUDE.md"; Key = "Claude"; Terms = @($contractRelativePath, "每件商品无条件执行", "Path B", "SEMI_MANAGED_CONTINUE_TRANSITION", "CategoryCatalog") },
        @{ Name = "docs/README.md"; Key = "DocsIndex"; Terms = @("product/MVP-竖切-草稿箱批量只保存.md", "architecture/DXM-工作台与分区自动化统一开发方案.md", "runbook/运营操作详细文档.md", "五项 ALWAYS_ON", "Path B", "动态任意深度类目", "E3_OPEN / BLOCKED") }
    )) { Add-MissingTerms -Errors $errors -Content $Contents[$rule.Key] -Label "$($rule.Name) 指针" -Terms $rule.Terms }

    Add-MissingTerms -Errors $errors -Content $Contents["RootReadme"] -Label "根 README" -Terms @(
        "E3_OPEN / BLOCKED", "每件商品无条件执行", "完整产品成功路径是 Path B", "SEMI_MANAGED_CONTINUE_TRANSITION",
        "最终发布永久禁止", "动态类目目录", "UNKNOWN 停批"
    )
    Add-MissingTerms -Errors $errors -Content $Contents["PlanArchitecture"] -Label "普货方案架构" -Terms @(
        "每件商品无条件必经", "required_capabilities", "视频", "翻译", "批发", "半托管", "rollback", "Path B", "source_category", "target_category", "catalog", "capability"
    )
    Add-MissingTerms -Errors $errors -Content $Contents["RuntimeArchitecture"] -Label "当前运行时架构" -Terms @(
        "E3_OPEN / BLOCKED", "Path B", "视频", "翻译", "批发", "rollback", "未接", "UNKNOWN"
    )
    Add-MissingTerms -Errors $errors -Content $Contents["UnifiedDevelopmentPlan"] -Label "工作台与分区自动化统一开发方案" -Terms @(
        "E3_OPEN / BLOCKED", "FullProductEditOrchestrator", "SectionAutomationRegistry", "11 个分区",
        "一个 canonical Runner", "Path B", "SEMI_MANAGED_CONTINUE_TRANSITION", "UNKNOWN", "0 failed / 0 skipped"
    )
    foreach ($errorText in (Get-UnifiedDevelopmentPlanErrors -Content $Contents["UnifiedDevelopmentPlan"])) { $errors.Add($errorText) }
    Add-MissingTerms -Errors $errors -Content $Contents["OperatorRunbook"] -Label "操作与验收手册" -Terms @(
        "Path B", "视频", "翻译", "批发", "rollback", '精确“继续发布”', "editFromSmt", "最终发布"
    )
    Add-MissingTerms -Errors $errors -Content $Contents["DetailedOperations"] -Label "运营操作详细文档" -Terms @(
        "11 分区", "Path B", "视频", "批发", "一键翻译", "preimage", "editFromSmt", "UNKNOWN",
        "不得主动预检资格", "最终发布"
    )
    Add-MissingTerms -Errors $errors -Content $Contents["UpstreamContract"] -Label "上游事实合同" -Terms @(
        "DXM-BOUNDARY-001", "DXM-READER-001", "DXM-TEMPLATE-001", "DXM-WIRE-001", "DXM-EDITOR-001", "DXM-EDITOR-002",
        "DXM-SNAPSHOT-001", "DXM-SAVE-001", "DXM-PROTOTYPE-001", "DXM-PATHB-001", "DXM-CATEGORY-CATALOG-001",
        "PASSIVE_ONLY", "SAMPLE_ONLY", "STALE_REVIEW_REQUIRED", "resources/dxm/category-catalog/category-catalog.v1.json",
        "resources/dxm/category-catalog/category-catalog.manifest.json", "sync-dxm-category-catalog.ps1", "-Check",
        "任意深度", "observedLevel", "executableLeaf", "12"
    )
    Add-MissingTerms -Errors $errors -Content $Contents["CategoryContract"] -Label "类目节点与目录合同" -Terms @(
        "DXM-CATEGORY-CATALOG-001", "13,216", "11,864", "11,852", "13,005", "任意深度", "isleaf=1",
        "executableLeaf", "nodeIdentitySha256", "capabilitiesSha256", "path_to_leaf_ids", "leaf_id_to_path",
        $expectedCategoryCatalogSha256
    )
    Add-MissingTerms -Errors $errors -Content $Contents["Progress"] -Label "PROGRESS.md" -Terms @(
        "E3_OPEN / BLOCKED", "每件商品", "Path B", "rollback preparation", "最终发布"
    )
    Add-MissingTerms -Errors $errors -Content $Contents["Blocked"] -Label "BLOCKED.md" -Terms @(
        "MVP_READY / PROD_READY", "视频", "翻译", "批发", "半托管", "rollback preparation"
    )

    $obsoleteReferences = @(
        "docs/product/E2-关闭剩余清单.md", "docs/product/E2-冻结遗留与E3开工.md", "docs/product/L0-策略B-迁移计划.md",
        "docs/runbook/RUN-FLOW-运行流程详解.md", "docs/api/数据库表结构与API草案.md",
        "docs/product/CODEX-GOAL-免安装桌面版与全链路操作日志-20260814.md"
    )
    foreach ($key in $Contents.Keys) {
        foreach ($obsolete in $obsoleteReferences) {
            if ($Contents[$key].Contains($obsolete)) { $errors.Add("$key 仍引用已删除滞后文档：$obsolete") }
        }
    }
    foreach ($term in @("真实账号：", "真实密码：", "Authorization: Bearer ", "Cookie:")) {
        if ($Contents["UpstreamContract"].Contains($term)) { $errors.Add("上游事实合同包含禁止迁入的真实业务/凭据样例：$term") }
    }
    foreach ($key in @("RootReadme", "Contract", "Gold", "Agents", "Claude", "DocsIndex")) {
        foreach ($narrative in @(
            "视频、翻译、批发、半托管、回滚和新 EvidenceCollector 只是未接入生产 Runner 的实验骨架",
            "视频、翻译、批发、半托管和回滚属于可选扩展",
            '当前可交付真实写入范围仅为 `controlled_single_save_only`',
            '`claim_only` 与 `single_save` 是唯一进入受控源码路径的真实 mutation 模式'
        )) {
            if ($Contents[$key].Contains($narrative)) { $errors.Add("$key 仍含旧产品主叙事：$narrative") }
        }
    }
    return @($errors)
}

function Get-UpstreamHashErrors {
    $errors = [System.Collections.Generic.List[string]]::new()
    foreach ($entry in $expectedUpstreamSources.GetEnumerator()) {
        $sourcePath = Join-Path $upstreamRoot $entry.Key
        if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
            $errors.Add("STALE_REVIEW_REQUIRED：上游来源不存在：$sourcePath")
            continue
        }
        $actualHash = (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash.ToUpperInvariant()
        if ($actualHash -ne $entry.Value) {
            $errors.Add("STALE_REVIEW_REQUIRED：上游来源 SHA256 漂移：$($entry.Key) expected=$($entry.Value) actual=$actualHash")
        }
    }
    return @($errors)
}

function Get-CategoryCatalogErrors {
    $errors = [System.Collections.Generic.List[string]]::new()
    try {
        $manifest = Read-Utf8Text -LiteralPath $paths.CategoryManifest | ConvertFrom-Json
        $catalog = Read-Utf8Text -LiteralPath $paths.CategoryCatalog | ConvertFrom-Json
    }
    catch {
        $errors.Add("CategoryCatalog JSON 无法解析：$($_.Exception.Message)")
        return @($errors)
    }
    if ([string]$manifest.schema -ne "dxm.category_catalog_manifest.v1") { $errors.Add("CategoryCatalog manifest schema 错误：$($manifest.schema)") }
    if ([string]$catalog.schema -ne "dxm.category_catalog.v1") { $errors.Add("CategoryCatalog schema 错误：$($catalog.schema)") }
    if ([string]$catalog.status -ne "SAMPLE_ONLY_VERSIONED_REFERENCE") { $errors.Add("CategoryCatalog 未标 SAMPLE_ONLY_VERSIONED_REFERENCE") }
    if ([string]$catalog.executionAuthority -ne "CURRENT_VISIBLE_SESSION_PAGE_CATEGORY_AND_SCHEMA") {
        $errors.Add("CategoryCatalog 错误替代当前可见会话页面类目/Schema 执行权威")
    }
    $actualCatalogHash = (Get-FileHash -LiteralPath $paths.CategoryCatalog -Algorithm SHA256).Hash.ToUpperInvariant()
    if ($actualCatalogHash -ne $expectedCategoryCatalogSha256) {
        $errors.Add("CategoryCatalog SHA256 漂移：expected=$expectedCategoryCatalogSha256 actual=$actualCatalogHash")
    }
    if ($actualCatalogHash -ne ([string]$manifest.catalog.sha256).ToUpperInvariant()) {
        $errors.Add("CategoryCatalog hash 与 manifest 不一致：manifest=$($manifest.catalog.sha256) actual=$actualCatalogHash")
    }
    $expectedCounts = [ordered]@{
        nodes = 13216; leaves = 11864; executableLeaves = 11852; unexecutableLeaves = 12;
        ancestorPathConflicts = 12; observedLevelUntrusted = 13005; nonLeafWithoutObservedChild = 4; duplicateLeafDisplayPaths = 1
    }
    foreach ($entry in $expectedCounts.GetEnumerator()) {
        $actual = [int]$catalog.counts.($entry.Key)
        if ($actual -ne [int]$entry.Value) { $errors.Add("CategoryCatalog count 漂移：$($entry.Key) expected=$($entry.Value) actual=$actual") }
        $manifestActual = [int]$manifest.catalog.counts.($entry.Key)
        if ($manifestActual -ne [int]$entry.Value) { $errors.Add("CategoryCatalog manifest count 漂移：$($entry.Key) expected=$($entry.Value) actual=$manifestActual") }
    }
    if (@($catalog.nodes).Count -ne 13216) { $errors.Add("CategoryCatalog nodes 数组数量错误：expected=13216 actual=$(@($catalog.nodes).Count)") }
    $unsafeExecutableLeaves = @($catalog.nodes | Where-Object {
        $_.executableLeaf -and (-not $_.isLeaf -or -not $_.integrity.directParentConsistent -or -not $_.integrity.fullAncestorChainConsistent)
    })
    if ($unsafeExecutableLeaves.Count -ne 0) { $errors.Add("CategoryCatalog 放行了结构冲突节点：count=$($unsafeExecutableLeaves.Count)") }
    $manifestSources = @{}
    foreach ($source in @($manifest.sources)) { $manifestSources[[string]$source.relativePath] = ([string]$source.sha256).ToUpperInvariant() }
    foreach ($entry in $expectedUpstreamSources.GetEnumerator()) {
        if (-not $entry.Key.StartsWith("data\capture\categories\")) { continue }
        $relativePath = $entry.Key.Replace("\", "/")
        if (-not $manifestSources.ContainsKey($relativePath)) { $errors.Add("CategoryCatalog manifest 缺少来源：$relativePath") }
        elseif ($manifestSources[$relativePath] -ne $entry.Value) { $errors.Add("CategoryCatalog manifest 来源 hash 错误：$relativePath") }
    }
    return @($errors)
}

function Invoke-CategoryCatalogCheck {
    $errors = [System.Collections.Generic.List[string]]::new()
    $output = @(& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $paths.CategorySyncScript -Check 2>&1)
    $exitCode = $LASTEXITCODE
    $joinedOutput = ($output | ForEach-Object { [string]$_ }) -join "`n"
    if ($exitCode -ne 0) { $errors.Add("CategoryCatalog -Check 失败：exit=$exitCode output=$joinedOutput") }
    elseif ($joinedOutput -notmatch 'DXM_CATEGORY_CATALOG_OK:') { $errors.Add("CategoryCatalog -Check 未输出 DXM_CATEGORY_CATALOG_OK：$joinedOutput") }
    return @($errors)
}

function Get-RealValidationErrors {
    param([Parameter(Mandatory = $true)][hashtable]$Contents)
    $errors = [System.Collections.Generic.List[string]]::new()
    foreach ($errorText in (Get-ContractContentErrors -Content $Contents["Contract"])) { $errors.Add($errorText) }
    foreach ($spec in @(
        @{ Key = "RootReadme"; Path = $paths.RootReadme }, @{ Key = "Changelog"; Path = $paths.Changelog },
        @{ Key = "Contract"; Path = $paths.Contract }, @{ Key = "Gold"; Path = $paths.Gold },
        @{ Key = "PlanArchitecture"; Path = $paths.PlanArchitecture }, @{ Key = "RuntimeArchitecture"; Path = $paths.RuntimeArchitecture },
        @{ Key = "UnifiedDevelopmentPlan"; Path = $paths.UnifiedDevelopmentPlan },
        @{ Key = "UpstreamContract"; Path = $paths.UpstreamContract }, @{ Key = "CategoryContract"; Path = $paths.CategoryContract },
        @{ Key = "OperatorRunbook"; Path = $paths.OperatorRunbook }, @{ Key = "DetailedOperations"; Path = $paths.DetailedOperations },
        @{ Key = "UserGuide"; Path = $paths.UserGuide }, @{ Key = "Agents"; Path = $paths.Agents },
        @{ Key = "Claude"; Path = $paths.Claude }, @{ Key = "DocsIndex"; Path = $paths.DocsIndex },
        @{ Key = "Progress"; Path = $paths.Progress }, @{ Key = "Blocked"; Path = $paths.Blocked }
    )) {
        foreach ($errorText in (Get-MarkdownLinkErrors -Content $Contents[$spec.Key] -SourcePath $spec.Path)) { $errors.Add($errorText) }
    }
    foreach ($spec in @(
        @{ Key = "RootReadme"; Name = "README.md" }, @{ Key = "Changelog"; Name = "CHANGELOG.md" },
        @{ Key = "Contract"; Name = "主合同" }, @{ Key = "Gold"; Name = "Gold" },
        @{ Key = "PlanArchitecture"; Name = "普货方案架构" }, @{ Key = "RuntimeArchitecture"; Name = "当前运行时架构" },
        @{ Key = "UnifiedDevelopmentPlan"; Name = "工作台与分区自动化统一开发方案" },
        @{ Key = "UpstreamContract"; Name = "DXM-TX 上游事实合同" }, @{ Key = "CategoryContract"; Name = "DXM-TX 类目节点与目录合同" },
        @{ Key = "OperatorRunbook"; Name = "操作与验收手册" }, @{ Key = "DetailedOperations"; Name = "运营操作详细文档" },
        @{ Key = "UserGuide"; Name = "免安装桌面版说明" }, @{ Key = "Agents"; Name = "AGENTS.md" },
        @{ Key = "Claude"; Name = "CLAUDE.md" }, @{ Key = "DocsIndex"; Name = "docs/README.md" },
        @{ Key = "Progress"; Name = "PROGRESS.md" }, @{ Key = "Blocked"; Name = "BLOCKED.md" }
    )) {
        foreach ($errorText in (Get-AiNoticeErrors -Content $Contents[$spec.Key] -Name $spec.Name)) { $errors.Add($errorText) }
    }
    foreach ($spec in @(
        @{ Key = "RootReadme"; Name = "README.md" }, @{ Key = "Changelog"; Name = "CHANGELOG.md" },
        @{ Key = "Contract"; Name = "主合同" }, @{ Key = "Gold"; Name = "Gold" },
        @{ Key = "PlanArchitecture"; Name = "普货方案架构" }, @{ Key = "RuntimeArchitecture"; Name = "当前运行时架构" },
        @{ Key = "UnifiedDevelopmentPlan"; Name = "工作台与分区自动化统一开发方案" },
        @{ Key = "UpstreamContract"; Name = "DXM-TX 上游事实合同" }, @{ Key = "CategoryContract"; Name = "DXM-TX 类目节点与目录合同" },
        @{ Key = "OperatorRunbook"; Name = "操作与验收手册" }, @{ Key = "DetailedOperations"; Name = "运营操作详细文档" },
        @{ Key = "UserGuide"; Name = "免安装桌面版说明" }, @{ Key = "Agents"; Name = "AGENTS.md" },
        @{ Key = "Claude"; Name = "CLAUDE.md" }, @{ Key = "DocsIndex"; Name = "docs/README.md" },
        @{ Key = "Progress"; Name = "PROGRESS.md" }, @{ Key = "Blocked"; Name = "BLOCKED.md" }
    )) {
        foreach ($errorText in (Get-MarkdownStructureErrors -Content $Contents[$spec.Key] -Name $spec.Name)) { $errors.Add($errorText) }
    }
    foreach ($errorText in (Get-DocumentTruthErrors -Contents $Contents)) { $errors.Add($errorText) }
    foreach ($errorText in (Get-UpstreamHashErrors)) { $errors.Add($errorText) }
    foreach ($errorText in (Get-CategoryCatalogErrors)) { $errors.Add($errorText) }
    $goldHash = (Get-FileHash -LiteralPath $paths.Gold -Algorithm SHA256).Hash.ToUpperInvariant()
    if ($goldHash -ne $expectedGoldSha256) { $errors.Add("Gold SHA256 漂移：expected=$expectedGoldSha256 actual=$goldHash") }
    $prototypeHash = (Get-FileHash -LiteralPath $paths.Prototype -Algorithm SHA256).Hash.ToUpperInvariant()
    if ($prototypeHash -ne $expectedPrototypeSha256) { $errors.Add("根原型 SHA256 漂移：expected=$expectedPrototypeSha256 actual=$prototypeHash") }
    return @($errors)
}

function Assert-SelfTestError {
    param(
        [Parameter(Mandatory = $true)][object[]]$Errors,
        [Parameter(Mandatory = $true)][string]$Needle,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $matches = @($Errors | Where-Object { ([string]$_).Contains($Needle) })
    if ($matches.Count -eq 0) {
        Write-Output "MVP_DOCS_ERROR: SelfTest $Label 未命中预期错误：$Needle"
        exit 1
    }
}

$missingFiles = [System.Collections.Generic.List[string]]::new()
foreach ($entry in $paths.GetEnumerator()) {
    if (-not (Test-Path -LiteralPath $entry.Value -PathType Leaf)) { $missingFiles.Add("$($entry.Key)：$($entry.Value)") }
}
if ($missingFiles.Count -gt 0) {
    foreach ($missing in $missingFiles) { Write-Output "MVP_DOCS_ERROR: 文件不存在：$missing" }
    exit 1
}

$contents = @{
    RootReadme = Read-Utf8Text -LiteralPath $paths.RootReadme; Changelog = Read-Utf8Text -LiteralPath $paths.Changelog
    Contract = Read-Utf8Text -LiteralPath $paths.Contract; Gold = Read-Utf8Text -LiteralPath $paths.Gold
    PlanArchitecture = Read-Utf8Text -LiteralPath $paths.PlanArchitecture; RuntimeArchitecture = Read-Utf8Text -LiteralPath $paths.RuntimeArchitecture
    UnifiedDevelopmentPlan = Read-Utf8Text -LiteralPath $paths.UnifiedDevelopmentPlan
    UpstreamContract = Read-Utf8Text -LiteralPath $paths.UpstreamContract; CategoryContract = Read-Utf8Text -LiteralPath $paths.CategoryContract
    OperatorRunbook = Read-Utf8Text -LiteralPath $paths.OperatorRunbook; DetailedOperations = Read-Utf8Text -LiteralPath $paths.DetailedOperations
    UserGuide = Read-Utf8Text -LiteralPath $paths.UserGuide; Agents = Read-Utf8Text -LiteralPath $paths.Agents
    Claude = Read-Utf8Text -LiteralPath $paths.Claude; DocsIndex = Read-Utf8Text -LiteralPath $paths.DocsIndex
    Progress = Read-Utf8Text -LiteralPath $paths.Progress; Blocked = Read-Utf8Text -LiteralPath $paths.Blocked
}

if ($SelfTest) {
    $brokenPublishGuard = $contents["Contract"].Replace("PublishGuard", "")
    if ($brokenPublishGuard -eq $contents["Contract"]) { Write-Output "MVP_DOCS_ERROR: SelfTest 无法构造 PublishGuard 缺失坏合同"; exit 1 }
    $publishGuardErrors = @(Get-ContractContentErrors -Content $brokenPublishGuard)
    Assert-SelfTestError -Errors $publishGuardErrors -Needle "PublishGuard" -Label "删除 PublishGuard"
    Write-Output "RED_EXPECTED: 内存坏合同已拒绝（删除 PublishGuard；errors=$($publishGuardErrors.Count)）"

    $capabilityRedCount = 0
    foreach ($capability in @("video", "translation", "wholesale", "semiManaged", "rollbackPreparation")) {
        $enabledLine = "  ${capability}: true"; $disabledLine = "  ${capability}: false"
        $brokenCapability = $contents["Contract"].Replace($enabledLine, $disabledLine)
        if ($brokenCapability -eq $contents["Contract"]) { Write-Output "MVP_DOCS_ERROR: SelfTest 无法构造 $capability=false 坏合同"; exit 1 }
        $capabilityErrors = @(Get-ContractContentErrors -Content $brokenCapability)
        Assert-SelfTestError -Errors $capabilityErrors -Needle "允许关闭每件商品必经能力：$capability" -Label "$capability=false"
        $capabilityRedCount++
    }
    Write-Output "RED_EXPECTED: 内存必经能力关闭已拒绝（$capabilityRedCount/5）"

    $brokenFixedDepth = $contents["Contract"] + "`r`n类目树固定为三级，第三层即叶子。`r`n"
    $fixedDepthErrors = @(Get-ContractContentErrors -Content $brokenFixedDepth)
    Assert-SelfTestError -Errors $fixedDepthErrors -Needle "类目树固定为三级" -Label "固定三级"
    Assert-SelfTestError -Errors $fixedDepthErrors -Needle "第三层即叶子" -Label "第三层即叶子"
    Write-Output "RED_EXPECTED: 内存固定三级合同已拒绝（errors=$($fixedDepthErrors.Count)）"

    $missingLinkTarget = "self-test/MVP_DOCS_LINK_MUST_NOT_EXIST.md"
    $brokenDocsIndex = $contents["DocsIndex"] + "`r`n[SelfTest 悬空链接]($missingLinkTarget)`r`n"
    $linkErrors = @(Get-MarkdownLinkErrors -Content $brokenDocsIndex -SourcePath $paths.DocsIndex)
    Assert-SelfTestError -Errors $linkErrors -Needle " -> $missingLinkTarget" -Label "悬空链接"
    Write-Output "RED_EXPECTED: 内存悬空链接已拒绝（errors=$($linkErrors.Count)）"

    $pathBTruth = "完整产品成功路径固定为 **Path B**"
    $brokenPathB = $contents["Contract"].Replace($pathBTruth, "完整产品成功路径固定为 **Path A**")
    if ($brokenPathB -eq $contents["Contract"]) { Write-Output "MVP_DOCS_ERROR: SelfTest 无法构造 Path A 降级坏合同"; exit 1 }
    $pathBErrors = @(Get-ContractContentErrors -Content $brokenPathB)
    Assert-SelfTestError -Errors $pathBErrors -Needle "Path B 是完整产品成功路径" -Label "Path A 降级"
    Write-Output "RED_EXPECTED: 内存 Path A 降级合同已拒绝（errors=$($pathBErrors.Count)）"

    $brokenContinue = $contents["Contract"] + "`r`n" + '任意含“继续发布”按钮均允许自动化。' + "`r`n"
    $continueErrors = @(Get-ContractContentErrors -Content $brokenContinue)
    Assert-SelfTestError -Errors $continueErrors -Needle '任意含“继续发布”按钮均允许自动化' -Label "泛化继续发布"
    Write-Output "RED_EXPECTED: 内存泛化继续发布合同已拒绝（errors=$($continueErrors.Count)）"

    $brokenFinalPublish = $contents["Contract"] + "`r`npublishAllowed: true`r`n允许最终发布。`r`n"
    $finalPublishErrors = @(Get-ContractContentErrors -Content $brokenFinalPublish)
    Assert-SelfTestError -Errors $finalPublishErrors -Needle "publishAllowed=true" -Label "publishAllowed=true"
    Assert-SelfTestError -Errors $finalPublishErrors -Needle "允许最终发布" -Label "允许最终发布"
    Write-Output "RED_EXPECTED: 内存最终发布放宽合同已拒绝（errors=$($finalPublishErrors.Count)）"

    $brokenCategoryHash = $contents["Contract"].Replace("capabilitiesSha256", "")
    if ($brokenCategoryHash -eq $contents["Contract"]) { Write-Output "MVP_DOCS_ERROR: SelfTest 无法构造 capabilitiesSha256 缺失坏合同"; exit 1 }
    $categoryHashErrors = @(Get-ContractContentErrors -Content $brokenCategoryHash)
    Assert-SelfTestError -Errors $categoryHashErrors -Needle "capabilitiesSha256" -Label "capabilities hash 缺失"
    Write-Output "RED_EXPECTED: 内存类目能力 hash 缺失合同已拒绝（errors=$($categoryHashErrors.Count)）"

    $safeSchemaDrift = "  schema_drift_action: ABORT"
    $brokenExecutionConstraint = $contents["UnifiedDevelopmentPlan"].Replace($safeSchemaDrift, "  schema_drift_action: PROCEED_WITH_WARNING")
    if ($brokenExecutionConstraint -eq $contents["UnifiedDevelopmentPlan"]) { Write-Output "MVP_DOCS_ERROR: SelfTest 无法构造 Schema 漂移放宽坏方案"; exit 1 }
    $executionConstraintErrors = @(Get-UnifiedDevelopmentPlanErrors -Content $brokenExecutionConstraint)
    Assert-SelfTestError -Errors $executionConstraintErrors -Needle "Schema/category/catalog 漂移被放宽" -Label "execution constraint 放宽"
    Write-Output "RED_EXPECTED: 内存 execution constraint 放宽已拒绝（errors=$($executionConstraintErrors.Count)）"

    $brokenEmergencyStop = $contents["UnifiedDevelopmentPlan"] + "`r`n急停立即将 resolving 直接改为 UNKNOWN 终态。`r`n"
    $emergencyStopErrors = @(Get-UnifiedDevelopmentPlanErrors -Content $brokenEmergencyStop)
    Assert-SelfTestError -Errors $emergencyStopErrors -Needle "急停伪造 resolving 终态" -Label "急停伪造终态"
    Write-Output "RED_EXPECTED: 内存急停伪造终态已拒绝（errors=$($emergencyStopErrors.Count)）"

    $brokenEncoding = $contents["UnifiedDevelopmentPlan"] + [char]0xFFFD
    $encodingErrors = @(Get-MarkdownStructureErrors -Content $brokenEncoding -Name "SelfTest 文档")
    Assert-SelfTestError -Errors $encodingErrors -Needle "U+FFFD" -Label "U+FFFD 乱码"
    Write-Output "RED_EXPECTED: 内存 U+FFFD 乱码已拒绝（errors=$($encodingErrors.Count)）"

    $brokenTable = "| 字段 | 值 |`r`n`r`n| --- | --- |"
    $tableErrors = @(Get-MarkdownStructureErrors -Content $brokenTable -Name "SelfTest 文档")
    Assert-SelfTestError -Errors $tableErrors -Needle "Markdown 表格被空行断裂" -Label "Markdown 表格断裂"
    Write-Output "RED_EXPECTED: 内存 Markdown 表格断裂已拒绝（errors=$($tableErrors.Count)）"
}

$realErrors = @(Get-RealValidationErrors -Contents $contents)
if ($realErrors.Count -gt 0) {
    foreach ($validationError in $realErrors) { Write-Output "MVP_DOCS_ERROR: $validationError" }
    exit 1
}
$catalogCheckErrors = @(Invoke-CategoryCatalogCheck)
if ($catalogCheckErrors.Count -gt 0) {
    foreach ($catalogError in $catalogCheckErrors) { Write-Output "MVP_DOCS_ERROR: $catalogError" }
    exit 1
}
$aiDocumentCount = 17
$upstreamSourceCount = $expectedUpstreamSources.Count
Write-Output "MVP_DOCS_OK: contract=1 pointers=4 links=resolved ai_notice=$aiDocumentCount capabilities=5/5 path_b=required publish_guard=locked category_catalog=checked upstream_sources=$upstreamSourceCount hashes=locked"
exit 0

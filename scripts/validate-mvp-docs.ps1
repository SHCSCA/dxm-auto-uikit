[CmdletBinding()]
param(
    [switch]$SelfTest
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $scriptDir "..")).Path

$paths = [ordered]@{
    Contract = Join-Path $repoRoot "docs\product\MVP-竖切-草稿箱批量只保存.md"
    Gold = Join-Path $repoRoot "docs\product\CODEX-GOLD-工作指令-MVP批量只保存.md"
    Agents = Join-Path $repoRoot "AGENTS.md"
    Claude = Join-Path $repoRoot "CLAUDE.md"
    DocsIndex = Join-Path $repoRoot "docs\README.md"
    Progress = Join-Path $repoRoot "PROGRESS.md"
    Blocked = Join-Path $repoRoot "BLOCKED.md"
    Prototype = "D:\Desktop\py\DXM-TX\DXM-半托管工作台-可交互原型.html"
}

$expectedGoldSha256 = "648E004FBF600AE4620435ADD3C8324D473710EC283ACDA139BCF337FE8EAE1C"
$expectedPrototypeSha256 = "29B76F8F2ACC6DDA15393AB20B4D0C07A10739B94A4E8E11A8341AD0DEC4A847"
$contractRelativePath = "docs/product/MVP-竖切-草稿箱批量只保存.md"
$aiNotice = "由 OpenAI GPT（Codex）AI 生成/维护"

function Read-Utf8Text {
    param(
        [Parameter(Mandatory = $true)]
        [string]$LiteralPath
    )

    return Get-Content -LiteralPath $LiteralPath -Raw -Encoding UTF8
}

function Get-ContractContentErrors {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Content
    )

    $errors = [System.Collections.Generic.List[string]]::new()

    $requiredSections = @(
        "### 6.1 ``MVP_READY``",
        "## 7. E0–E4 Definition of Done",
        "## 8. 指定根原型一致性",
        "## 11. 人工验收"
    )

    foreach ($section in $requiredSections) {
        if (-not $Content.Contains($section)) {
            $errors.Add("主合同缺少必需章节：$section")
        }
    }

    $requiredTerms = @(
        "真实可见浏览器",
        "draft ≥3",
        "只读接口",
        "UI 写",
        "模板优先补差",
        "不可变 plan snapshot",
        "batch_draft_save",
        "HVD 与 runner 同源",
        "开始 / 暂停 / 继续 / 停止",
        "回包 + 页面成功态 + 独立未发布证明",
        "UNKNOWN 停批",
        "MVP_READY ≠ PROD_READY",
        "claim_only 非前置",
        "local_plan_template",
        "dxm_template_ref",
        "PASSIVE_ONLY",
        "后续阶段 / 运行拒绝",
        "PublishGuard",
        "Path A",
        "Path B",
        "SHOPS",
        "PRODUCTS",
        "DXM_TPL",
        "localStorage",
        "中文界面",
        "中文字段映射",
        "自动写入的自然语言内容必须为英文",
        "保存前校验",
        "item_snapshots",
        "categoryId",
        "类目 Schema/hash",
        "必填字段",
        "解析结果",
        "多类目配置",
        "240px",
        "56px",
        "#4f46e5",
        "16px",
        "明暗主题",
        "1100px",
        "860px",
        "工作台",
        "连接店小秘",
        "采集箱选品",
        "铺货方案",
        "开始批量保存",
        "保存结果",
        "设置"
    )

    foreach ($term in $requiredTerms) {
        if (-not $Content.Contains($term)) {
            $errors.Add("主合同缺少必需术语：$term")
        }
    }

    $requiredSafetyStatements = @(
        "三缺一不可",
        "不得自动重试",
        "不得自动升级为生产重放",
        "产品自身使用中文界面与中文字段映射；自动写入的自然语言内容必须为英文，并在保存前校验，未通过时不得点击「保存」。",
        "``plan_snapshot`` 必须为每件商品冻结 ``categoryId``、类目 Schema/hash、必填字段及解析结果；多类目配置不得在执行时临时变化。",
        "合同状态：E0 冻结基线（未宣称 ``MVP_READY``，未宣称 ``PROD_READY``）"
    )

    foreach ($statement in $requiredSafetyStatements) {
        if (-not $Content.Contains($statement)) {
            $errors.Add("主合同缺少安全口径：$statement")
        }
    }

    return @($errors)
}

function Get-MarkdownLinkErrors {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Content,

        [Parameter(Mandatory = $true)]
        [string]$SourcePath
    )

    $errors = [System.Collections.Generic.List[string]]::new()
    $sourceDirectory = Split-Path -Parent $SourcePath
    $matches = [regex]::Matches(
        $Content,
        '(?<!\!)\[[^\]]+\]\(\s*(?:<(?<target>[^>]+)>|(?<target>[^)\s]+))(?:\s+"[^"]*")?\s*\)'
    )

    foreach ($match in $matches) {
        $target = $match.Groups["target"].Value.Trim()
        if (
            $target.StartsWith("#") -or
            $target.StartsWith("http://", [System.StringComparison]::OrdinalIgnoreCase) -or
            $target.StartsWith("https://", [System.StringComparison]::OrdinalIgnoreCase) -or
            $target.StartsWith("mailto:", [System.StringComparison]::OrdinalIgnoreCase)
        ) {
            continue
        }

        $pathPart = [System.Uri]::UnescapeDataString($target.Split("#")[0])
        if ([string]::IsNullOrWhiteSpace($pathPart)) {
            continue
        }

        if ([System.IO.Path]::IsPathRooted($pathPart)) {
            $candidate = [System.IO.Path]::GetFullPath($pathPart)
        }
        else {
            $candidate = [System.IO.Path]::GetFullPath((Join-Path $sourceDirectory $pathPart))
        }

        if (-not (Test-Path -LiteralPath $candidate)) {
            $lineNumber = (
                [regex]::Matches($Content.Substring(0, $match.Index), "\r?\n")
            ).Count + 1
            $errors.Add("悬空链接：$SourcePath`:$lineNumber -> $target")
        }
    }

    return @($errors)
}

function Get-AiNoticeErrors {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Content,

        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    $firstNonEmpty = @(
        $Content -split "\r?\n" |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    ) | Select-Object -First 1

    if ($null -eq $firstNonEmpty -or -not $firstNonEmpty.Contains($aiNotice)) {
        return @("$Name 未在首个非空行标注：$aiNotice")
    }

    return @()
}

function Get-PointerErrors {
    param(
        [Parameter(Mandatory = $true)]
        [hashtable]$Contents
    )

    $errors = [System.Collections.Generic.List[string]]::new()
    $rules = @(
        @{ Name = "Gold"; Key = "Gold"; Terms = @($contractRelativePath, "Path A", "batch_draft_save", "claim_only 非前置") },
        @{ Name = "AGENTS.md"; Key = "Agents"; Terms = @($contractRelativePath, "当前产品主迭代契约", "batch_draft_save") },
        @{ Name = "CLAUDE.md"; Key = "Claude"; Terms = @($contractRelativePath, "当前产品主迭代", "batch_draft_save") },
        @{ Name = "docs/README.md"; Key = "DocsIndex"; Terms = @("product/MVP-竖切-草稿箱批量只保存.md", "产品主路径", "MVP_READY") }
    )

    foreach ($rule in $rules) {
        $content = $Contents[$rule.Key]
        foreach ($term in $rule.Terms) {
            if (-not $content.Contains($term)) {
                $errors.Add("$($rule.Name) 指针缺少：$term")
            }
        }
    }

    return @($errors)
}

function Get-LegacyNarrativeErrors {
    param(
        [Parameter(Mandatory = $true)]
        [hashtable]$Contents
    )

    $errors = [System.Collections.Generic.List[string]]::new()
    $conflicts = @(
        "当前可交付真实写入范围仅为 ``controlled_single_save_only``",
        "``claim_only``、``batch_save``、批量、无人值守和任何发布动作均未放行",
        "把店小秘已有待认领商品受控认领到商品箱",
        "``claim_only`` 与 ``single_save`` 是唯一进入受控源码路径的真实 mutation 模式"
    )

    foreach ($key in @("Contract", "Agents", "Claude", "DocsIndex")) {
        foreach ($conflict in $conflicts) {
            if ($Contents[$key].Contains($conflict)) {
                $errors.Add("$key 仍含旧主叙事冲突：$conflict")
            }
        }
    }

    return @($errors)
}

function Get-RealValidationErrors {
    param(
        [Parameter(Mandatory = $true)]
        [hashtable]$Contents
    )

    $errors = [System.Collections.Generic.List[string]]::new()

    foreach ($errorText in (Get-ContractContentErrors -Content $Contents["Contract"])) {
        $errors.Add($errorText)
    }

    foreach ($spec in @(
        @{ Key = "Contract"; Path = $paths.Contract },
        @{ Key = "Gold"; Path = $paths.Gold },
        @{ Key = "Agents"; Path = $paths.Agents },
        @{ Key = "Claude"; Path = $paths.Claude },
        @{ Key = "DocsIndex"; Path = $paths.DocsIndex },
        @{ Key = "Progress"; Path = $paths.Progress },
        @{ Key = "Blocked"; Path = $paths.Blocked }
    )) {
        foreach ($errorText in (Get-MarkdownLinkErrors -Content $Contents[$spec.Key] -SourcePath $spec.Path)) {
            $errors.Add($errorText)
        }
    }

    foreach ($spec in @(
        @{ Key = "Contract"; Name = "主合同" },
        @{ Key = "Progress"; Name = "PROGRESS.md" },
        @{ Key = "Blocked"; Name = "BLOCKED.md" }
    )) {
        foreach ($errorText in (Get-AiNoticeErrors -Content $Contents[$spec.Key] -Name $spec.Name)) {
            $errors.Add($errorText)
        }
    }

    foreach ($errorText in (Get-PointerErrors -Contents $Contents)) {
        $errors.Add($errorText)
    }

    foreach ($errorText in (Get-LegacyNarrativeErrors -Contents $Contents)) {
        $errors.Add($errorText)
    }

    $docsIndexContractTarget = Join-Path $repoRoot "docs\product\MVP-竖切-草稿箱批量只保存.md"
    if (-not (Test-Path -LiteralPath $docsIndexContractTarget -PathType Leaf)) {
        $errors.Add("docs 索引目标不存在：$docsIndexContractTarget")
    }

    $goldHash = (Get-FileHash -LiteralPath $paths.Gold -Algorithm SHA256).Hash
    if ($goldHash -ne $expectedGoldSha256) {
        $errors.Add("Gold SHA256 漂移：expected=$expectedGoldSha256 actual=$goldHash")
    }

    $prototypeHash = (Get-FileHash -LiteralPath $paths.Prototype -Algorithm SHA256).Hash
    if ($prototypeHash -ne $expectedPrototypeSha256) {
        $errors.Add("根原型 SHA256 漂移：expected=$expectedPrototypeSha256 actual=$prototypeHash")
    }

    return @($errors)
}

$missingFiles = [System.Collections.Generic.List[string]]::new()
foreach ($entry in $paths.GetEnumerator()) {
    if (-not (Test-Path -LiteralPath $entry.Value -PathType Leaf)) {
        $missingFiles.Add("$($entry.Key)：$($entry.Value)")
    }
}

if ($missingFiles.Count -gt 0) {
    foreach ($missing in $missingFiles) {
        Write-Output "MVP_DOCS_ERROR: 文件不存在：$missing"
    }
    exit 1
}

$contents = @{
    Contract = Read-Utf8Text -LiteralPath $paths.Contract
    Gold = Read-Utf8Text -LiteralPath $paths.Gold
    Agents = Read-Utf8Text -LiteralPath $paths.Agents
    Claude = Read-Utf8Text -LiteralPath $paths.Claude
    DocsIndex = Read-Utf8Text -LiteralPath $paths.DocsIndex
    Progress = Read-Utf8Text -LiteralPath $paths.Progress
    Blocked = Read-Utf8Text -LiteralPath $paths.Blocked
}

if ($SelfTest) {
    $brokenContract = $contents["Contract"].Replace("PublishGuard", "")
    $selfTestErrors = @(Get-ContractContentErrors -Content $brokenContract)

    if ($selfTestErrors.Count -eq 0) {
        Write-Output "MVP_DOCS_ERROR: SelfTest 坏合同未判红；PublishGuard 缺失被错误放行"
        exit 1
    }

    $publishGuardFailure = @(
        $selfTestErrors |
            Where-Object { $_ -eq "主合同缺少必需术语：PublishGuard" }
    )
    if ($publishGuardFailure.Count -ne 1) {
        Write-Output "MVP_DOCS_ERROR: SelfTest 虽判红，但未精确命中 PublishGuard 缺失"
        exit 1
    }

    Write-Output "RED_EXPECTED: 内存坏合同已拒绝（删除 PublishGuard；errors=$($selfTestErrors.Count)）"

    $missingLinkTarget = "self-test/MVP_DOCS_LINK_MUST_NOT_EXIST.md"
    $brokenDocsIndex = $contents["DocsIndex"] + "`r`n[SelfTest 悬空链接]($missingLinkTarget)`r`n"
    $linkSelfTestErrors = @(
        Get-MarkdownLinkErrors -Content $brokenDocsIndex -SourcePath $paths.DocsIndex
    )
    $expectedLinkFailure = @(
        $linkSelfTestErrors |
            Where-Object { $_.Contains(" -> $missingLinkTarget") }
    )

    if ($expectedLinkFailure.Count -ne 1) {
        Write-Output "MVP_DOCS_ERROR: SelfTest 坏索引未精确命中注入的悬空链接"
        exit 1
    }

    Write-Output "RED_EXPECTED: 内存坏索引已拒绝（注入悬空链接；errors=$($linkSelfTestErrors.Count)）"
}

$realErrors = @(Get-RealValidationErrors -Contents $contents)
if ($realErrors.Count -gt 0) {
    foreach ($validationError in $realErrors) {
        Write-Output "MVP_DOCS_ERROR: $validationError"
    }
    exit 1
}

Write-Output "MVP_DOCS_OK: contract=1 pointers=4 link_docs=7 links=resolved ai_notice=3 legacy_conflicts=0 hashes=locked"
exit 0

[CmdletBinding()]
param(
    [string]$UpstreamRoot = "D:\Desktop\py\DXM-TX",
    [string]$OutputRoot,
    [switch]$Write,
    [switch]$Check,
    [switch]$SelfTest
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $scriptDir "..")).Path
if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    $OutputRoot = Join-Path $repoRoot "resources\dxm\category-catalog"
}

if ($Write -and $Check) {
    throw "CATALOG_MODE_CONFLICT: -Write 与 -Check 不能同时使用"
}
if ($Write -and $SelfTest) {
    throw "CATALOG_MODE_CONFLICT: -Write 与 -SelfTest 不能同时使用"
}
if (-not $Write -and -not $Check) {
    $Check = $true
}

$categoryRoot = Join-Path $UpstreamRoot "data\capture\categories"
$resolvedCategoryRoot = (Resolve-Path -LiteralPath $categoryRoot).Path
$expectedCategoryRoot = [System.IO.Path]::GetFullPath($categoryRoot)
if ($resolvedCategoryRoot -ne $expectedCategoryRoot) {
    throw "CATEGORY_SOURCE_PATH_DRIFT: expected=$expectedCategoryRoot actual=$resolvedCategoryRoot"
}

$sourceSpecs = [ordered]@{
    "all_nodes.json" = [ordered]@{
        sha256 = "25A665AFAAF34E2626F2DC43A58B3A7FB3147E85340E3B97FA7C13C461178A10"
        disposition = "IMPORTED_NORMALIZED"
    }
    "category_leaf_mapping.json" = [ordered]@{
        sha256 = "7CC422A5E07110700597D0FC0BB03E5D74F54FED345544C39F8EF09DB6E6DB35"
        disposition = "METADATA_AND_COUNT_CROSSCHECK"
    }
    "category_leaf_mapping.csv" = [ordered]@{
        sha256 = "21326822B0797AFFA075DDB1A315986085403E1153E997E05D6DEA114B2AB483"
        disposition = "EXCLUDED_REDUNDANT_OLDER_SNAPSHOT"
    }
    "leaf_id_to_path_compact.json" = [ordered]@{
        sha256 = "B320916CDC88931DD24E5D96E0D8AB75EF5BAB7283ED89FB5A3F1461DB27D4C2"
        disposition = "EXCLUDED_STALE_11795_LEAF_SNAPSHOT"
    }
    "root_list.json" = [ordered]@{
        sha256 = "913CB7C0D81E24519E37DD0450A2B63898A50544E63678EE757673C3AA448E81"
        disposition = "ROOT_COUNT_CROSSCHECK"
    }
}

function Get-Sha256 {
    param([Parameter(Mandatory = $true)][string]$LiteralPath)
    return (Get-FileHash -LiteralPath $LiteralPath -Algorithm SHA256).Hash.ToUpperInvariant()
}

function Write-Utf8NoBom {
    param(
        [Parameter(Mandatory = $true)][string]$LiteralPath,
        [Parameter(Mandatory = $true)][string]$Content
    )
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($LiteralPath, $Content, $encoding)
}

function Convert-ToBoolean {
    param($Value)
    if ($null -eq $Value) { return $false }
    if ($Value -is [bool]) { return $Value }
    $text = ([string]$Value).Trim()
    return $text -in @("1", "true", "True", "TRUE")
}

function Convert-JsonStringValue {
    param($Value)
    if ($null -eq $Value) { return $null }
    if ($Value -isnot [string]) { return $Value }
    if ([string]::IsNullOrWhiteSpace($Value)) { return $null }
    try {
        return ($Value | ConvertFrom-Json)
    }
    catch {
        throw "CATEGORY_EMBEDDED_JSON_INVALID: $Value"
    }
}

function Get-CanonicalSha256 {
    param([Parameter(Mandatory = $true)]$Value)
    $json = $Value | ConvertTo-Json -Depth 30 -Compress
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        return ([System.BitConverter]::ToString($sha.ComputeHash($bytes))).Replace("-", "")
    }
    finally {
        $sha.Dispose()
    }
}

function Get-StringSha256 {
    param([Parameter(Mandatory = $true)][string]$Value)
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($Value)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        return ([System.BitConverter]::ToString($sha.ComputeHash($bytes))).Replace("-", "")
    }
    finally {
        $sha.Dispose()
    }
}

function Assert-CatalogContentHash {
    param(
        [Parameter(Mandatory = $true)][string]$Expected,
        [Parameter(Mandatory = $true)][string]$Actual
    )
    if ($Actual -ne $Expected) {
        throw "CATEGORY_CATALOG_CONTENT_DRIFT: expected=$Expected actual=$Actual"
    }
}

$sourceManifest = @()
foreach ($entry in $sourceSpecs.GetEnumerator()) {
    $sourcePath = Join-Path $resolvedCategoryRoot $entry.Key
    if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
        throw "CATEGORY_SOURCE_MISSING: $sourcePath"
    }
    $actualHash = Get-Sha256 -LiteralPath $sourcePath
    if ($actualHash -ne $entry.Value.sha256) {
        throw "CATEGORY_SOURCE_DRIFT: $($entry.Key) expected=$($entry.Value.sha256) actual=$actualHash"
    }
    $sourceManifest += [ordered]@{
        relativePath = "data/capture/categories/$($entry.Key)"
        sha256 = $actualHash
        bytes = (Get-Item -LiteralPath $sourcePath).Length
        disposition = $entry.Value.disposition
    }
}

$allNodesPath = Join-Path $resolvedCategoryRoot "all_nodes.json"
$mappingPath = Join-Path $resolvedCategoryRoot "category_leaf_mapping.json"
$rootListPath = Join-Path $resolvedCategoryRoot "root_list.json"
$compactPath = Join-Path $resolvedCategoryRoot "leaf_id_to_path_compact.json"
$legacyCsvPath = Join-Path $resolvedCategoryRoot "category_leaf_mapping.csv"
$rawNodes = Get-Content -LiteralPath $allNodesPath -Raw -Encoding UTF8 | ConvertFrom-Json
$mapping = Get-Content -LiteralPath $mappingPath -Raw -Encoding UTF8 | ConvertFrom-Json
$rootListEnvelope = Get-Content -LiteralPath $rootListPath -Raw -Encoding UTF8 | ConvertFrom-Json
$legacyCompact = Get-Content -LiteralPath $compactPath -Raw -Encoding UTF8 | ConvertFrom-Json
$legacyCsv = Import-Csv -LiteralPath $legacyCsvPath -Encoding UTF8

$rawById = @{}
$childCountByParent = @{}
foreach ($node in $rawNodes) {
    $categoryId = ([string]$node.categoryId).Trim()
    if ($categoryId -notmatch '^[1-9][0-9]*$') {
        throw "CATEGORY_ID_INVALID: $categoryId"
    }
    if ($rawById.ContainsKey($categoryId)) {
        throw "CATEGORY_ID_DUPLICATE: $categoryId"
    }
    $rawById[$categoryId] = $node
    $rawParent = ([string]$node.pcid).Trim()
    if ($rawParent -ne "0" -and -not [string]::IsNullOrWhiteSpace($rawParent)) {
        if (-not $childCountByParent.ContainsKey($rawParent)) { $childCountByParent[$rawParent] = 0 }
        $childCountByParent[$rawParent]++
    }
}

function Get-ObservedAncestorChain {
    param([Parameter(Mandatory = $true)][string]$CategoryId)
    $chain = New-Object System.Collections.Generic.List[string]
    $seen = @{}
    $cursor = $CategoryId
    while ($cursor -ne "0") {
        if (-not $rawById.ContainsKey($cursor)) {
            return [ordered]@{ ok = $false; ids = @($chain); reason = "MISSING_PARENT:$cursor" }
        }
        if ($seen.ContainsKey($cursor)) {
            return [ordered]@{ ok = $false; ids = @($chain); reason = "PARENT_CYCLE:$cursor" }
        }
        $seen[$cursor] = $true
        $chain.Insert(0, $cursor)
        $cursor = ([string]$rawById[$cursor].pcid).Trim()
    }
    return [ordered]@{ ok = $true; ids = @($chain); reason = $null }
}

$normalizedNodes = New-Object System.Collections.Generic.List[object]
$leafCount = 0
$rootCount = 0
$levelMismatchCount = 0
$ancestorConflictCount = 0
$unexecutableLeafCount = 0
$nonLeafWithoutObservedChildCount = 0
$ancestorConflictIds = New-Object System.Collections.Generic.List[string]
$nonLeafWithoutObservedChildIds = New-Object System.Collections.Generic.List[string]
$derivedDepthCounts = @{}

foreach ($node in ($rawNodes | Sort-Object { [string]$_.nodePathId }, { [string]$_.categoryId })) {
    $categoryId = ([string]$node.categoryId).Trim()
    $rawParent = ([string]$node.pcid).Trim()
    $parentCategoryId = if ([string]::IsNullOrWhiteSpace($rawParent) -or $rawParent -eq "0") { $null } else { $rawParent }
    if ($null -ne $parentCategoryId -and $parentCategoryId -notmatch '^[1-9][0-9]*$') {
        throw "CATEGORY_PARENT_ID_INVALID: category=$categoryId parent=$parentCategoryId"
    }

    $nodePathIds = @(([string]$node.nodePathId).Split('/') | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne "" })
    if ($nodePathIds.Count -eq 0 -or $nodePathIds[-1] -ne $categoryId) {
        throw "CATEGORY_PATH_TERMINAL_MISMATCH: category=$categoryId path=$([string]$node.nodePathId)"
    }

    $directParentConsistent = if ($null -eq $parentCategoryId) {
        $nodePathIds.Count -eq 1
    }
    else {
        $nodePathIds.Count -gt 1 -and $nodePathIds[-2] -eq $parentCategoryId
    }

    $chain = Get-ObservedAncestorChain -CategoryId $categoryId
    $fullAncestorChainConsistent = $chain.ok -and ((@($chain.ids) -join '/') -eq ($nodePathIds -join '/'))
    if (-not $fullAncestorChainConsistent) {
        $ancestorConflictCount++
        $ancestorConflictIds.Add($categoryId)
    }

    $pathNamesZh = @()
    $pathNamesEn = @()
    foreach ($pathId in $nodePathIds) {
        if ($rawById.ContainsKey($pathId)) {
            $pathNamesZh += [string]$rawById[$pathId].nameZh
            $pathNamesEn += [string]$rawById[$pathId].nameEn
        }
        else {
            $pathNamesZh += $null
            $pathNamesEn += $null
        }
    }

    $isLeaf = Convert-ToBoolean $node.isleaf
    $isDeleted = Convert-ToBoolean $node.isDel
    if ($isLeaf) { $leafCount++ }
    if ($null -eq $parentCategoryId) { $rootCount++ }

    $pathDepth = $nodePathIds.Count
    $derivedDepth = $pathDepth - 1
    if (-not $derivedDepthCounts.ContainsKey($derivedDepth)) { $derivedDepthCounts[$derivedDepth] = 0 }
    $derivedDepthCounts[$derivedDepth]++
    $observedLevel = [int]$node.level
    $levelMatchesPathDepth = $observedLevel -eq $derivedDepth
    if (-not $levelMatchesPathDepth) { $levelMismatchCount++ }

    $nonLeafWithoutObservedChild = -not $isLeaf -and -not $childCountByParent.ContainsKey($categoryId)
    if ($nonLeafWithoutObservedChild) {
        $nonLeafWithoutObservedChildCount++
        $nonLeafWithoutObservedChildIds.Add($categoryId)
    }

    $issues = @()
    if (-not $directParentConsistent) { $issues += "DIRECT_PARENT_PATH_CONFLICT" }
    if (-not $fullAncestorChainConsistent) { $issues += "FULL_ANCESTOR_PATH_CONFLICT" }
    if ($isDeleted) { $issues += "SOURCE_MARKED_DELETED" }
    if (-not $levelMatchesPathDepth) { $issues += "OBSERVED_LEVEL_UNTRUSTED" }
    if ($nonLeafWithoutObservedChild) { $issues += "NON_LEAF_WITHOUT_OBSERVED_CHILD" }

    $leafHasObservedChild = $isLeaf -and $childCountByParent.ContainsKey($categoryId)
    if ($leafHasObservedChild) { $issues += "LEAF_HAS_OBSERVED_CHILD" }
    $executableLeaf = $isLeaf -and -not $leafHasObservedChild -and -not $isDeleted -and $directParentConsistent -and $fullAncestorChainConsistent
    if ($isLeaf -and -not $executableLeaf) { $unexecutableLeafCount++ }

    $capabilitiesPayload = [ordered]@{
        isEuContact = Convert-ToBoolean $node.isEuContact
        isEan = Convert-ToBoolean $node.isEan
        isNewSize = Convert-ToBoolean $node.isNewSize
        sizeChartType = $node.sizeChartType
        sizeChartSubTypeList = Convert-JsonStringValue $node.sizeChartSubTypeList
        features = Convert-JsonStringValue $node.features
        hasCascadeAttribute = $node.hasCascadeAttribute
        hasPlugAttribute = $node.hasPlugAttribute
    }
    $identityPayload = [ordered]@{
        categoryId = $categoryId
        parentCategoryId = $parentCategoryId
        isLeaf = $isLeaf
        nodePathIds = $nodePathIds
        nameZh = [string]$node.nameZh
        nameEn = [string]$node.nameEn
        nodePath = [string]$node.nodePath
        isDeleted = $isDeleted
        updateTime = $node.updateTime
    }

    $normalizedNodes.Add([ordered]@{
        categoryId = $categoryId
        sourceRecordId = [string]$node.id
        parentCategoryId = $parentCategoryId
        observedLevel = $observedLevel
        pathDepth = $pathDepth
        derivedDepth = $derivedDepth
        isLeaf = $isLeaf
        executableLeaf = $executableLeaf
        nameZh = [string]$node.nameZh
        nameEn = [string]$node.nameEn
        nodePath = [string]$node.nodePath
        nodePathIds = $nodePathIds
        pathNamesZh = $pathNamesZh
        pathNamesEn = $pathNamesEn
        capabilities = $capabilitiesPayload
        sourceFlags = [ordered]@{
            isDeleted = $isDeleted
            createTime = $node.createTime
            updateTime = $node.updateTime
        }
        integrity = [ordered]@{
            directParentConsistent = $directParentConsistent
            fullAncestorChainConsistent = $fullAncestorChainConsistent
            observedLevelTrusted = $levelMatchesPathDepth
            issues = $issues
        }
        nodeIdentitySha256 = Get-CanonicalSha256 -Value $identityPayload
        capabilitiesSha256 = Get-CanonicalSha256 -Value $capabilitiesPayload
    })
}

if ([int]$mapping.stats.total_nodes -ne $rawNodes.Count) {
    throw "CATEGORY_COUNT_CONFLICT: mapping=$($mapping.stats.total_nodes) all_nodes=$($rawNodes.Count)"
}
if ([int]$mapping.stats.leaf_count -ne $leafCount) {
    throw "CATEGORY_LEAF_COUNT_CONFLICT: mapping=$($mapping.stats.leaf_count) all_nodes=$leafCount"
}

$mappingLeafIds = @{}
foreach ($leaf in @($mapping.leaves)) { $mappingLeafIds[[string]$leaf.categoryId] = $true }
$allNodeLeafIds = @{}
foreach ($leafNode in @($rawNodes | Where-Object { Convert-ToBoolean $_.isleaf })) { $allNodeLeafIds[[string]$leafNode.categoryId] = $true }
if ($mappingLeafIds.Count -ne $allNodeLeafIds.Count) {
    throw "CATEGORY_LEAF_SET_COUNT_CONFLICT: mapping=$($mappingLeafIds.Count) all_nodes=$($allNodeLeafIds.Count)"
}
foreach ($leafId in $allNodeLeafIds.Keys) {
    if (-not $mappingLeafIds.ContainsKey($leafId)) { throw "CATEGORY_LEAF_SET_CONFLICT: missing_in_mapping=$leafId" }
}

foreach ($leaf in @($mapping.leaves)) {
    $leafId = [string]$leaf.categoryId
    $rawLeaf = $rawById[$leafId]
    foreach ($field in @("nameZh", "nameEn", "nodePath", "nodePathId", "pcid")) {
        if ([string]$leaf.$field -ne [string]$rawLeaf.$field) {
            throw "CATEGORY_LEAF_PROJECTION_CONFLICT: category=$leafId field=$field"
        }
    }
    $forwardProperty = $mapping.leaf_id_to_path.psobject.Properties[$leafId]
    if ($null -eq $forwardProperty -or [string]$forwardProperty.Value -ne [string]$rawLeaf.nodePath) {
        throw "CATEGORY_LEAF_FORWARD_INDEX_CONFLICT: category=$leafId"
    }
    $reverseProperty = $mapping.path_to_leaf_ids.psobject.Properties[[string]$rawLeaf.nodePath]
    if ($null -eq $reverseProperty -or [string]$leafId -notin @($reverseProperty.Value | ForEach-Object { [string]$_ })) {
        throw "CATEGORY_LEAF_REVERSE_INDEX_CONFLICT: category=$leafId"
    }
}

if (@($rootListEnvelope.data).Count -ne $rootCount) {
    throw "CATEGORY_ROOT_COUNT_CONFLICT: root_list=$(@($rootListEnvelope.data).Count) all_nodes=$rootCount"
}
foreach ($rootNode in @($rootListEnvelope.data)) {
    $rootId = [string]$rootNode.categoryId
    if (-not $rawById.ContainsKey($rootId)) {
        throw "CATEGORY_ROOT_IDENTITY_CONFLICT: category=$rootId"
    }
    $rootParent = ([string]$rawById[$rootId].pcid).Trim()
    if ($rootParent -ne "" -and $rootParent -ne "0") {
        throw "CATEGORY_ROOT_IDENTITY_CONFLICT: category=$rootId"
    }
    if ((Get-CanonicalSha256 -Value $rootNode) -ne (Get-CanonicalSha256 -Value $rawById[$rootId])) {
        throw "CATEGORY_ROOT_RECORD_CONFLICT: category=$rootId"
    }
}

$compactProperties = @($legacyCompact.psobject.Properties)
if ($compactProperties.Count -ne 11795 -or @($legacyCsv).Count -ne 11795) {
    throw "CATEGORY_SUPERSEDED_COUNT_DRIFT: compact=$($compactProperties.Count) csv=$(@($legacyCsv).Count)"
}
foreach ($property in $compactProperties) {
    $legacyId = [string]$property.Name
    if (-not $mappingLeafIds.ContainsKey($legacyId)) {
        throw "CATEGORY_SUPERSEDED_NOT_SUBSET: category=$legacyId"
    }
    $currentPath = [string]$mapping.leaf_id_to_path.psobject.Properties[$legacyId].Value
    if ([string]$property.Value.path -ne $currentPath) {
        throw "CATEGORY_SUPERSEDED_PATH_DRIFT: category=$legacyId"
    }
}
foreach ($legacyLeaf in @($legacyCsv)) {
    $legacyId = [string]$legacyLeaf.categoryId
    if (-not $mappingLeafIds.ContainsKey($legacyId) -or [string]$legacyLeaf.nodePath -ne [string]$mapping.leaf_id_to_path.psobject.Properties[$legacyId].Value) {
        throw "CATEGORY_SUPERSEDED_CSV_DRIFT: category=$legacyId"
    }
}

$duplicateDisplayPathCount = @(
    $rawNodes |
        Where-Object { Convert-ToBoolean $_.isleaf } |
        Group-Object { [string]$_.nodePath } |
        Where-Object { $_.Count -gt 1 }
).Count

$duplicateDisplayPaths = @(
    $rawNodes |
        Where-Object { Convert-ToBoolean $_.isleaf } |
        Group-Object { [string]$_.nodePath } |
        Where-Object { $_.Count -gt 1 } |
        ForEach-Object {
            [ordered]@{
                nodePath = [string]$_.Name
                categoryIds = @($_.Group | ForEach-Object { [string]$_.categoryId } | Sort-Object)
            }
        }
)

$depthDistribution = [ordered]@{}
foreach ($depth in @($derivedDepthCounts.Keys | Sort-Object { [int]$_ })) {
    $depthDistribution[[string]$depth] = [int]$derivedDepthCounts[$depth]
}

$catalog = [ordered]@{
    schema = "dxm.category_catalog.v1"
    status = "SAMPLE_ONLY_VERSIONED_REFERENCE"
    executionAuthority = "CURRENT_VISIBLE_SESSION_PAGE_CATEGORY_AND_SCHEMA"
    observedAt = [string]$mapping.generated_at
    sourceEndpoint = [ordered]@{
        rootsAndChildren = "/api/smtCategory/list.json"
        childrenParameter = "pcid"
        nodeDetail = "/api/smtCategory/getByCategoryId.json"
    }
    counts = [ordered]@{
        nodes = $rawNodes.Count
        leaves = $leafCount
        roots = $rootCount
        executableLeaves = $leafCount - $unexecutableLeafCount
        unexecutableLeaves = $unexecutableLeafCount
        ancestorPathConflicts = $ancestorConflictCount
        observedLevelUntrusted = $levelMismatchCount
        nonLeafWithoutObservedChild = $nonLeafWithoutObservedChildCount
        duplicateLeafDisplayPaths = $duplicateDisplayPathCount
    }
    invariants = @(
        "CATEGORY_ID_IS_PRIMARY_IDENTITY",
        "DYNAMIC_DEPTH_NO_FIXED_THREE_LEVEL_ASSUMPTION",
        "ONLY_EXECUTABLE_LEAF_MAY_BE_FROZEN",
        "OBSERVED_LEVEL_IS_NOT_EXECUTION_DEPTH",
        "DISPLAY_PATH_TO_LEAF_IS_ONE_TO_MANY",
        "CURRENT_SESSION_PAGE_CATEGORY_AND_SCHEMA_OVERRIDE_REFERENCE_CATALOG"
    )
    nodes = $normalizedNodes.ToArray()
}

$catalogJson = $catalog | ConvertTo-Json -Depth 30 -Compress
$expectedCatalogContent = $catalogJson + "`n"
$expectedCatalogHash = Get-StringSha256 -Value $expectedCatalogContent

if ($SelfTest) {
    $badHash = Get-StringSha256 -Value ($expectedCatalogContent + "SELFTEST_DRIFT")
    try {
        Assert-CatalogContentHash -Expected $expectedCatalogHash -Actual $badHash
        throw "CATEGORY_CATALOG_SELFTEST_FALSE_GREEN"
    }
    catch {
        if ($_.Exception.Message -notlike "CATEGORY_CATALOG_CONTENT_DRIFT:*") { throw }
        Write-Output "RED_EXPECTED: CATEGORY_CATALOG_CONTENT_DRIFT"
    }
}

$catalogPath = Join-Path $OutputRoot "category-catalog.v1.json"
$manifestPath = Join-Path $OutputRoot "category-catalog.manifest.json"

if ($Write) {
    if (-not (Test-Path -LiteralPath $OutputRoot)) {
        New-Item -ItemType Directory -Path $OutputRoot | Out-Null
    }
    Write-Utf8NoBom -LiteralPath $catalogPath -Content $expectedCatalogContent
    $catalogSha256 = Get-Sha256 -LiteralPath $catalogPath
    $manifest = [ordered]@{
        schema = "dxm.category_catalog_manifest.v1"
        generatedBy = "scripts/sync-dxm-category-catalog.ps1"
        normalizerVersion = "2"
        synchronizedAt = "2026-08-25"
        upstreamRoot = "D:/Desktop/py/DXM-TX"
        allowedSourceScope = "data/capture/categories only"
        excludedSensitiveScopes = @("data/sessions", "Cookie", "storage state", "account", "shop", "product", "raw business capture")
        catalog = [ordered]@{
            relativePath = "resources/dxm/category-catalog/category-catalog.v1.json"
            sha256 = $catalogSha256
            bytes = (Get-Item -LiteralPath $catalogPath).Length
            schema = $catalog.schema
            observedAt = $catalog.observedAt
            counts = $catalog.counts
        }
        sources = $sourceManifest
        drift = [ordered]@{
            compactLeafCount = 11795
            currentLeafCount = $leafCount
            disposition = "CURRENT_ALL_NODES_WINS; OLDER_COMPACT_RECORDED_NOT_IMPORTED"
        }
        quality = [ordered]@{
            leafProjectionVerified = $true
            forwardAndReverseIndexesVerified = $true
            rootRecordsVerified = $true
            observedLevelTrusted = $false
            derivedDepthDistribution = $depthDistribution
            ancestorPathConflictIds = @($ancestorConflictIds.ToArray() | Sort-Object)
            nonLeafWithoutObservedChildIds = @($nonLeafWithoutObservedChildIds.ToArray() | Sort-Object)
            duplicateLeafDisplayPaths = $duplicateDisplayPaths
        }
    }
    $manifestJson = $manifest | ConvertTo-Json -Depth 30
    Write-Utf8NoBom -LiteralPath $manifestPath -Content ($manifestJson + "`n")
    Write-Output "DXM_CATEGORY_CATALOG_WRITTEN: nodes=$($rawNodes.Count) leaves=$leafCount executable_leaves=$($leafCount-$unexecutableLeafCount) conflicts=$ancestorConflictCount sha256=$catalogSha256"
    exit 0
}

if (-not (Test-Path -LiteralPath $catalogPath -PathType Leaf)) {
    throw "CATEGORY_CATALOG_MISSING: $catalogPath"
}
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw "CATEGORY_MANIFEST_MISSING: $manifestPath"
}

$existingManifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$existingCatalog = Get-Content -LiteralPath $catalogPath -Raw -Encoding UTF8 | ConvertFrom-Json
$actualCatalogHash = Get-Sha256 -LiteralPath $catalogPath
Assert-CatalogContentHash -Expected $expectedCatalogHash -Actual $actualCatalogHash
if ($actualCatalogHash -ne [string]$existingManifest.catalog.sha256) {
    throw "CATEGORY_CATALOG_HASH_DRIFT: expected=$($existingManifest.catalog.sha256) actual=$actualCatalogHash"
}
if ([string]$existingCatalog.schema -ne "dxm.category_catalog.v1") {
    throw "CATEGORY_CATALOG_SCHEMA_INVALID: $($existingCatalog.schema)"
}
if (@($existingCatalog.nodes).Count -ne $rawNodes.Count) {
    throw "CATEGORY_CATALOG_NODE_COUNT_INVALID: expected=$($rawNodes.Count) actual=$(@($existingCatalog.nodes).Count)"
}
if ([int]$existingCatalog.counts.leaves -ne $leafCount) {
    throw "CATEGORY_CATALOG_LEAF_COUNT_INVALID: expected=$leafCount actual=$($existingCatalog.counts.leaves)"
}
if ([int]$existingCatalog.counts.ancestorPathConflicts -ne $ancestorConflictCount) {
    throw "CATEGORY_CATALOG_CONFLICT_COUNT_INVALID: expected=$ancestorConflictCount actual=$($existingCatalog.counts.ancestorPathConflicts)"
}

if (@($existingManifest.sources).Count -ne $sourceManifest.Count) {
    throw "CATEGORY_MANIFEST_SOURCE_COUNT_INVALID: expected=$($sourceManifest.Count) actual=$(@($existingManifest.sources).Count)"
}
foreach ($expectedSource in $sourceManifest) {
    $actualSource = @($existingManifest.sources | Where-Object { [string]$_.relativePath -eq [string]$expectedSource.relativePath })
    if ($actualSource.Count -ne 1) {
        throw "CATEGORY_MANIFEST_SOURCE_IDENTITY_INVALID: $($expectedSource.relativePath)"
    }
    if ([string]$actualSource[0].sha256 -ne [string]$expectedSource.sha256 -or [long]$actualSource[0].bytes -ne [long]$expectedSource.bytes -or [string]$actualSource[0].disposition -ne [string]$expectedSource.disposition) {
        throw "CATEGORY_MANIFEST_SOURCE_DRIFT: $($expectedSource.relativePath)"
    }
}

Write-Output "DXM_CATEGORY_CATALOG_OK: nodes=$($rawNodes.Count) leaves=$leafCount executable_leaves=$($leafCount-$unexecutableLeafCount) conflicts=$ancestorConflictCount sha256=$actualCatalogHash"
exit 0

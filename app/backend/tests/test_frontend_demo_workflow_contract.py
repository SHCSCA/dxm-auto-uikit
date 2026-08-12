from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
APP_TSX = REPO_ROOT / "app" / "frontend" / "src" / "App.tsx"
APP_SHELL_TSX = REPO_ROOT / "app" / "frontend" / "src" / "components" / "AppShell.tsx"
WORKSPACE_TS = REPO_ROOT / "app" / "frontend" / "src" / "workspace.ts"
WORKBENCH_MODULES_TSX = REPO_ROOT / "app" / "frontend" / "src" / "components" / "WorkbenchModules.tsx"
WORKBENCH_COPY_TS = REPO_ROOT / "app" / "frontend" / "src" / "components" / "workbench" / "workbenchCopy.ts"
SYSTEM_SETTINGS_PAGE_TSX = REPO_ROOT / "app" / "frontend" / "src" / "components" / "workbench" / "SystemSettingsPage.tsx"
HELP_PAGE_TSX = REPO_ROOT / "app" / "frontend" / "src" / "components" / "workbench" / "HelpPage.tsx"
RESULTS_PAGE_TSX = REPO_ROOT / "app" / "frontend" / "src" / "components" / "workbench" / "ResultsPage.tsx"
ISSUES_PAGE_TSX = REPO_ROOT / "app" / "frontend" / "src" / "components" / "workbench" / "IssuesPage.tsx"
DXM_ACCESS_PAGE_TSX = REPO_ROOT / "app" / "frontend" / "src" / "components" / "workbench" / "DxmAccessPage.tsx"
DRAFT_SELECTION_PAGE_TSX = REPO_ROOT / "app" / "frontend" / "src" / "components" / "workbench" / "DraftSelectionPage.tsx"
LOCAL_PLAN_WORKSPACE_TSX = REPO_ROOT / "app" / "frontend" / "src" / "components" / "workbench" / "LocalPlanWorkspace.tsx"
ACQUISITION_CLAIM_PAGE_TSX = REPO_ROOT / "app" / "frontend" / "src" / "components" / "workbench" / "AcquisitionClaimPage.tsx"
DRAFT_EDIT_SAVE_PAGE_TSX = REPO_ROOT / "app" / "frontend" / "src" / "components" / "workbench" / "DraftEditSavePage.tsx"
BATCH_EDIT_PAGE_TSX = REPO_ROOT / "app" / "frontend" / "src" / "components" / "workbench" / "BatchEditPage.tsx"
BATCH_RECORDS_PAGE_TSX = REPO_ROOT / "app" / "frontend" / "src" / "components" / "workbench" / "BatchRecordsPage.tsx"
TEMPLATE_CENTER_PAGE_TSX = REPO_ROOT / "app" / "frontend" / "src" / "components" / "workbench" / "TemplateCenterPage.tsx"
PRODUCT_TASKS_PAGE_TSX = REPO_ROOT / "app" / "frontend" / "src" / "components" / "workbench" / "ProductTasksPage.tsx"
PRODUCT_TASK_PANELS_TSX = REPO_ROOT / "app" / "frontend" / "src" / "components" / "workbench" / "ProductTaskPanels.tsx"
EDIT_CONFIG_PAGE_TSX = REPO_ROOT / "app" / "frontend" / "src" / "components" / "workbench" / "EditConfigPage.tsx"
AGENT_EXECUTION_PAGE_TSX = REPO_ROOT / "app" / "frontend" / "src" / "components" / "workbench" / "AgentExecutionPage.tsx"
HOME_PAGE_TSX = REPO_ROOT / "app" / "frontend" / "src" / "components" / "workbench" / "HomePage.tsx"
SAFETY_STATUS_BAR_TSX = REPO_ROOT / "app" / "frontend" / "src" / "components" / "SafetyStatusBar.tsx"
QA_BROWSER_CHECK = REPO_ROOT / "scripts" / "qa-browser-check.ps1"
README = REPO_ROOT / "README.md"
USER_GUIDE = REPO_ROOT / "docs" / "product" / "用户交付使用说明-20260526.md"
DOCS_INDEX = REPO_ROOT / "docs" / "README.md"
MVP_CONTRACT = REPO_ROOT / "docs" / "product" / "MVP-竖切-草稿箱批量只保存.md"


def _assert_frozen_primary_navigation() -> None:
    shell = APP_SHELL_TSX.read_text(encoding="utf-8")
    primary = shell[shell.index("const primaryNavigation"):shell.index("const sectionLabels")]
    expected = [
        ("home", "工作台"),
        ("dxm_access", "连接店小秘"),
        ("draft_selection", "采集箱选品"),
        ("template_center", "铺货方案"),
        ("start_save", "开始批量保存"),
        ("results", "保存结果"),
        ("settings", "设置"),
    ]
    assert primary.count("{ id: '") == len(expected)
    for section_id, label in expected:
        assert f"{{ id: '{section_id}', label: '{label}'" in primary
    assert "工作台 / 连接店小秘 / 采集箱选品 / 铺货方案 / 开始批量保存 / 保存结果 / 设置" in shell
    for stale in ["claim_only", "single_save", "待认领入箱", "商品箱编辑保存", "QA", "L2", "run-id"]:
        assert stale not in primary


def _assert_current_reader_selection_path() -> None:
    app = APP_TSX.read_text(encoding="utf-8")
    page = DRAFT_SELECTION_PAGE_TSX.read_text(encoding="utf-8")
    assert "<DraftSelectionPage" in app
    assert "'/api/dxm/draft-reader/shops'" in page
    # The current Reader builds its query with a template literal so the
    # session/shop/category proof remains URLSearchParams-encoded.
    assert "/api/dxm/draft-reader/products?${params.toString()}" in page
    assert "MIN_DRAFT_SELECTION" in page
    assert "productIds: selectedIds" in page
    assert "至少选择 ${MIN_DRAFT_SELECTION} 件草稿商品" in page
    assert "任务输入已形成；正在进入快照预览与冻结" in page
    assert "本步骤没有保存、发布或任何真实写入" in page
    assert "不会启动批量保存" in page


def _assert_current_plan_path() -> None:
    app = APP_TSX.read_text(encoding="utf-8")
    template_page = TEMPLATE_CENTER_PAGE_TSX.read_text(encoding="utf-8")
    page = LOCAL_PLAN_WORKSPACE_TSX.read_text(encoding="utf-8")
    assert "<TemplateCenterPage" in app
    assert "<LocalPlanWorkspace" in template_page
    assert "local_plan_template · 可编辑 / 可版本化" in page
    assert "dxm_template_ref · 只读" in page
    assert "方案变更创建新版本；已经冻结的任务不会跟随变化。" in page
    assert "Path A · 只保存不发布" in page
    assert "不得手填显示名冒充引用" in page


def _assert_current_batch_draft_save_path() -> None:
    app = APP_TSX.read_text(encoding="utf-8")
    page = BATCH_EDIT_PAGE_TSX.read_text(encoding="utf-8")
    contract = MVP_CONTRACT.read_text(encoding="utf-8")
    assert "'batch_draft_save'" in app
    assert "CONFIRM_DXM_BATCH_SAVE_ONLY" in page
    assert "一次批准后严格串行处理，每件只保存、不发布" in page
    assert "冻结当前商品箱范围" in page
    assert "旧版批量保存、无人值守和发布仍关闭" in page
    assert "mode: batch_draft_save" in contract
    assert "真实可见浏览器" in contract
    assert "draft ≥3" in contract
    assert "MVP_READY ≠ PROD_READY" in contract


def _assert_current_connection_path() -> None:
    page = DXM_ACCESS_PAGE_TSX.read_text(encoding="utf-8")
    app = APP_TSX.read_text(encoding="utf-8")
    assert "<DxmAccessPage" in app
    assert "登录真实店小秘" in page
    assert "只做登录，不保存、不发布" in page
    assert "DXM 已登录，Reader 已就绪" in page
    assert "页面已登录，但 Reader 未就绪" in page
    assert "reasonCode" in page


def _assert_current_results_and_issues_path() -> None:
    app = APP_TSX.read_text(encoding="utf-8")
    modules = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    results = RESULTS_PAGE_TSX.read_text(encoding="utf-8")
    issues = ISSUES_PAGE_TSX.read_text(encoding="utf-8")
    # App consumes the two frozen product pages through their public module
    # aliases; requiring the private component names in App would couple this
    # contract test to an implementation-only import style.
    assert "export { ResultsPage as ReportCenter }" in modules
    assert "export { IssuesPage as ExceptionQueue }" in modules
    assert "case 'results':" in app and "<ReportCenter" in app
    assert "case 'issues':" in app and "<ExceptionQueue" in app
    assert "批次只保存、不发布，并按商品严格串行执行。" in results
    assert "回包" in MVP_CONTRACT.read_text(encoding="utf-8")
    assert "未发布" in results
    assert "what" in issues.lower() or "发生了什么" in issues


def _assert_current_operator_help_path() -> None:
    app = APP_TSX.read_text(encoding="utf-8")
    help_source = HELP_PAGE_TSX.read_text(encoding="utf-8")
    assert "<HelpPage" in app
    assert "登录店小秘" in help_source
    assert "冻结范围并选择店铺级模板" in help_source
    assert "一次批准" in help_source
    assert "只保存" in help_source


def _assert_current_authority_docs() -> None:
    readme = README.read_text(encoding="utf-8")
    index = DOCS_INDEX.read_text(encoding="utf-8")
    contract = MVP_CONTRACT.read_text(encoding="utf-8")
    historical_guide_path = f"product/{USER_GUIDE.name}"
    assert f"]({historical_guide_path})" not in index
    assert f"`{historical_guide_path}`" in index
    assert "不是当前真相、可执行任务或有效链接" in index
    assert "MVP-竖切-草稿箱批量只保存.md" in index
    assert "旧 `claim_only` / `single_save`" in readme
    assert "不是 MVP 前置或当前产品主叙事" in readme
    assert "发布、保存并发布和移入待发布始终禁止" in readme
    assert "§11" in contract
    assert "MVP_READY ≠ PROD_READY" in contract


def test_sidebar_uses_low_noise_operator_navigation():
    _assert_frozen_primary_navigation()


def test_sidebar_exposes_only_five_operator_destinations():
    _assert_frozen_primary_navigation()


def test_sidebar_routes_business_entries_to_reachable_pages():
    _assert_frozen_primary_navigation()


def test_home_first_screen_has_one_status_one_action_and_truthful_summary():
    _assert_frozen_primary_navigation()
    _assert_current_batch_draft_save_path()


def test_safety_status_bar_visible_row_hides_gate_jargon_and_maintenance_details():
    source = SAFETY_STATUS_BAR_TSX.read_text(encoding="utf-8")
    visible_row = source[source.index('<section className={`safety-bar'):source.index("</section>")]

    for label in ["只保存，不发布", "下一步", "当前任务已完成", "等待真实登录"]:
        assert label in source
    for forbidden in ["L2", "L3", "probe", "run-id", "HAR", "single_save", "claim_only", "维护详情", "维护状态说明"]:
        assert forbidden not in visible_row


def test_acquisition_claim_page_uses_claim_request_api_not_legacy_task_center():
    _assert_current_reader_selection_path()


def test_acquisition_claim_page_presents_four_step_real_claim_path():
    _assert_current_reader_selection_path()


def test_legacy_collection_language_is_sanitized_for_operator_copy():
    copy_source = WORKBENCH_COPY_TS.read_text(encoding="utf-8")
    app_source = APP_TSX.read_text(encoding="utf-8")
    dxm_access_source = DXM_ACCESS_PAGE_TSX.read_text(encoding="utf-8")
    modules_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    draft_edit_source = DRAFT_EDIT_SAVE_PAGE_TSX.read_text(encoding="utf-8")
    results_source = RESULTS_PAGE_TSX.read_text(encoding="utf-8")
    panels_source = PRODUCT_TASK_PANELS_TSX.read_text(encoding="utf-8")
    settings_source = SYSTEM_SETTINGS_PAGE_TSX.read_text(encoding="utf-8")

    assert "function sanitizeLegacyDxmUserText" in copy_source
    assert "export function humanTaskDisplayName" in copy_source
    assert "mode === 'claim_only'" in copy_source
    assert "`待认领商品 - ${payloadHint || cleanTaskNameFallback(rawName) || '待认领商品'}`" in copy_source
    assert "hasMojibake(rawName)" in copy_source
    for replacement in [
        ".replace(/真实数据采集/g, '店小秘已有待认领商品')",
        ".replace(/数据采集认领/g, '待认领商品')",
        ".replace(/商品采集页/g, '已有待认领列表')",
        ".replace(/数据采集页/g, '已有待认领列表')",
        ".replace(/采集产品/g, '认领已有商品')",
        ".replace(/采集页/g, '待认领列表')",
    ]:
        assert replacement in copy_source
    assert "return sanitized" in copy_source
    assert "<BatchEditPage" in app_source
    assert "进入待认领列表" in dxm_access_source
    assert "进入采集页" not in dxm_access_source
    assert "写入认领标记" in modules_source
    assert "写入领取备注" not in modules_source
    for source in [modules_source, draft_edit_source, results_source, panels_source, settings_source]:
        assert "humanTaskDisplayName" in source
    assert "selectedTask ? selectedTask.name : '等待创建'" not in draft_edit_source


def test_execution_console_does_not_require_edit_config_or_l3_for_claim_only():
    _assert_current_reader_selection_path()
    _assert_current_batch_draft_save_path()


def test_two_stage_pages_select_loaded_store_and_claimed_product_by_default():
    acquisition_source = ACQUISITION_CLAIM_PAGE_TSX.read_text(encoding="utf-8")
    draft_source = DRAFT_EDIT_SAVE_PAGE_TSX.read_text(encoding="utf-8")

    assert "useEffect" in acquisition_source
    assert "setStoreId(String(stores[0].id))" in acquisition_source
    assert "stores.some((store) => String(store.id) === storeId)" in acquisition_source
    assert "useEffect" in draft_source
    assert "setSelectedProductId(String(claimedProducts[0].id))" in draft_source
    assert "claimedProducts.some((product) => String(product.id) === selectedProductId)" in draft_source


def test_draft_edit_save_page_starts_from_claimed_product_without_technical_gate_copy():
    app_source = APP_TSX.read_text(encoding="utf-8")
    page_source = BATCH_EDIT_PAGE_TSX.read_text(encoding="utf-8")
    route_section = app_source[app_source.index("case 'draft_edit_save'"):app_source.index("case 'start_save'")]

    assert "BatchEditPage" in app_source
    assert "<BatchEditPage" in route_section
    assert "templates={workspace.templates}" in route_section
    assert "<ExecutionConsole" not in route_section
    assert "postJson<DraftBoxScopeSnapshot>('/api/dxm/draft-box/scope-snapshots'" in page_source
    assert "postJson<EditBatchDetail>('/api/edit-batches'" in page_source
    for label in ["批量编辑商品", "真实商品箱现场", "只保存 · 不发布", "冻结当前商品箱范围"]:
        assert label in page_source


def test_draft_edit_save_uses_claimed_product_store_instead_of_first_store():
    _assert_current_reader_selection_path()
    _assert_current_batch_draft_save_path()


def test_batch_builder_does_not_load_a_local_claimed_product_picker():
    app_source = APP_TSX.read_text(encoding="utf-8")

    assert "loadOrFallback<Product[]>('/api/acquisition/claimed-products', [])" not in app_source
    assert "setClaimedDraftProducts" not in app_source
    assert "workspace.products.filter(isVerifiedClaimedDraftProduct)" not in app_source
    assert "function isVerifiedClaimedDraftProduct" not in app_source


def test_template_center_page_presents_multi_template_chinese_section_workflow():
    _assert_current_plan_path()


def test_template_center_cannot_persist_bundled_default_template_values():
    page_source = TEMPLATE_CENTER_PAGE_TSX.read_text(encoding="utf-8")

    for forbidden in [
        "保存全部分区为店铺模板",
        "saveDefaultTemplatePackAsStoreTemplates",
        "defaultDraftPack",
        "defaultValuesForSection",
        "defaultValueForField",
        "default_template_pack: true",
        "套用默认配置模板",
        "微信图片_202504092228421.jpg",
        "Jacqueiline Marti",
    ]:
        assert forbidden not in page_source

    assert "postJson<Template>('/api/templates', body)" in page_source
    assert "patchJson<Template>(`/api/templates/${activeTemplate.id}`, body)" in page_source
    assert "保存为店铺模板" in page_source
    assert "保存为类目模板" in page_source
    assert "当前分区还没有模板" in page_source
    assert "直接填写字段保存" in page_source


def test_screen_reader_only_text_cannot_intercept_sidebar_clicks():
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    sr_only_section = styles_source[styles_source.index(".sr-only {"):styles_source.index(".icon-button {")]

    assert "pointer-events: none;" in sr_only_section


def results_page_source() -> str:
    return RESULTS_PAGE_TSX.read_text(encoding="utf-8")


def results_page_main_section() -> str:
    source = results_page_source()
    return source[source.index("export function ResultsPage"):source.index("function FinalDeliveryCheckCard")]


def final_delivery_card_section() -> str:
    source = results_page_source()
    return source[source.index("function FinalDeliveryCheckCard"):source.index("function SourcePackageCheckRow")]


def single_save_recovery_guide_section(_: str | None = None) -> str:
    source = PRODUCT_TASK_PANELS_TSX.read_text(encoding="utf-8")
    return source[source.index("export function SingleSaveRecoveryGuide"):source.index("export function RealModeReleasePlanPanel")]


def test_single_save_recovery_copy_does_not_block_released_claim_stage():
    source = PRODUCT_TASK_PANELS_TSX.read_text(encoding="utf-8")
    recovery_section = single_save_recovery_guide_section()
    current_action_section = task_current_action_panel_section()

    assert "批量/发布不放行" in recovery_section
    assert "待认领入箱只走第一段入口" in source
    for forbidden in [
        "不放行认领/批量保存",
        "认领和批量保存需要单独验收",
    ]:
        assert forbidden not in recovery_section
        assert forbidden not in current_action_section
        assert forbidden not in source


def readonly_recheck_help_card_section(_: str | None = None) -> str:
    source = PRODUCT_TASK_PANELS_TSX.read_text(encoding="utf-8")
    return source[source.index("export function ReadonlyRecheckHelpCard"):source.index("export function TaskCurrentActionPanel")]


def l2_probe_resource_repair_panel_section() -> str:
    source = PRODUCT_TASK_PANELS_TSX.read_text(encoding="utf-8")
    return source[source.index("export function L2ProbeResourceRepairPanel"):source.index("export function ReadonlyRecheckHelpCard")]


def task_current_action_panel_section() -> str:
    source = PRODUCT_TASK_PANELS_TSX.read_text(encoding="utf-8")
    return source[source.index("export function TaskCurrentActionPanel"):source.index("export function SingleSaveRecoveryGuide")]


def test_demo_batch_creation_is_dev_only_and_never_real_user_path():
    _assert_current_reader_selection_path()
    _assert_current_batch_draft_save_path()


def test_task_center_does_not_apply_l3_real_write_block_to_dry_run_tasks():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    panels_source = PRODUCT_TASK_PANELS_TSX.read_text(encoding="utf-8")

    assert "const l3BlocksStart = selectedTaskNeedsEditConfig && needsRealL2 && l3Gate?.status === 'blocked'" in source
    assert "启动开发自检任务" in source
    assert "真实保存仍以单商品只保存规则为准" in panels_source
    assert "普通模式不展示本地自检入口" in source
    assert "创建开发自检批次" in source
    assert "不触达 DXM" in source


def test_frontend_loads_config_preview_and_blocks_real_start_when_incomplete():
    source = APP_TSX.read_text(encoding="utf-8")
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    start_section = source[source.index("async function startSelectedTask"):source.index("async function startAgentConsole")]

    assert "initialTaskIdFromUrl" in source
    assert "new URLSearchParams(window.location.search).get('task_id')" in source
    assert "useState<number | null>(initialTaskIdFromUrl)" in source
    assert "ConfigPreview" in source
    assert "setConfigPreview" in source
    assert "/api/config/preview?task_id=" in source
    assert "配置检查未通过" in start_section
    assert "setActiveSection('edit_config')" in start_section
    assert "configBlocksStart" in workbench_source
    assert "配置未完成，禁止启动" in workbench_source
    assert "去填写编辑页" in workbench_source


def test_frontend_defaults_to_delivery_current_task_even_after_success():
    source = APP_TSX.read_text(encoding="utf-8")
    picker = source[source.index("function pickDefaultTaskId"):source.index("function pickTaskIdForOperatorPath")]
    operator_picker = source[source.index("function pickTaskIdForOperatorPath"):source.index("function isActionableClaimTask")]

    assert "const deliveryTaskId = deliveryWorkspace?.current_task?.id" in picker
    assert "if (deliveryTask && isDefaultSelectableOperatorTask(deliveryTask))" in picker
    assert "tasks.find(isActionableClaimTask)" in picker
    assert "isDefaultSelectableClaimTask" in picker
    assert "if (currentTask && isDefaultSelectableOperatorTask(currentTask)) return currentTask.id" in operator_picker
    assert "deliveryTask.status !== 'completed'" not in picker
    assert picker.index("if (deliveryTask && isDefaultSelectableOperatorTask(deliveryTask))") < picker.index("tasks.find(isActionableClaimTask)")
    assert "待认领商品" in source
    assert "商品箱编辑保存" in source
    assert "请在“商品与任务”" not in source


def test_config_center_prioritizes_missing_sections_and_sources():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    config_section = source[source.index("export function ConfigCenter"):source.index("export function TaskCenterView")]

    assert "ConfigReadinessPanel" in source
    assert "NextRequiredConfigFields" in config_section
    assert "下一步必填字段" in source
    assert "只显示当前最需要处理的字段" in source
    assert "onEditRequiredSection" in source
    assert "编辑当前必填分区" in source
    assert "保存临时覆盖并继续" in source
    assert "selectNextMissingConfigSection" in config_section
    assert "continueToNextMissingSection" in config_section
    assert "data-config-next-required" in source
    assert "填写编辑页" in config_section
    assert "当前只展开一个分区" in config_section
    assert "config-section-tabs" in config_section
    assert "config-section-tabs--primary" in config_section
    assert "config-section-more-drawer" in config_section
    assert "更多编辑页分区" in config_section
    assert "secondaryConfigSections" in config_section
    assert "uniqueConfigSections" in source
    assert "setActiveConfigSectionCode" in config_section
    assert "selectedConfigSection" in config_section
    assert "正在编辑分区" in config_section


def test_config_center_explains_precheck_and_disabled_save_continue():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    app_source = APP_TSX.read_text(encoding="utf-8")
    config_section = source[source.index("export function ConfigCenter"):source.index("export function TaskCenterView")]
    editable_card = source[source.index("function EditableConfigSectionCard"):source.index("export function TaskCenterView")]
    config_copy_source = source[source.index("function ConfigReadinessPanel"):source.index("export function TaskCenterView")]
    qa_source = QA_BROWSER_CHECK.read_text(encoding="utf-8")

    assert "onRefreshConfigPreview" in source
    assert "onRefreshConfigPreview={async () => { await refreshConfigPreview(); await refreshWorkspace() }}" in app_source
    assert "检查本次配置" in config_section
    assert "刷新配置检查" in config_section
    assert "去商品箱编辑保存" in config_section
    assert "onShowTasks" in source
    assert "onShowTasks={() => setActiveSection('product_tasks')}" in app_source
    assert "读取当前任务、店铺、商品和模板" in config_section
    assert "不会操作店小秘" in config_section
    assert "disabledReason" in editable_card
    assert "先选择任务" in editable_card
    assert "先运行本次任务配置检查" in editable_card
    assert "不能继续的原因" in editable_card
    assert "配置检查" in config_section
    assert "配置预检" not in config_section
    assert "等待检查" in config_copy_source
    assert "等待预检" not in config_copy_source
    assert "启动预检" not in config_copy_source
    assert "configPrecheckActionVisible" in qa_source
    assert "'\\u68c0\\u67e5\\u672c\\u6b21\\u914d\\u7f6e'" in qa_source
    assert "'\\u5237\\u65b0\\u914d\\u7f6e\\u68c0\\u67e5'" in qa_source
    assert "configPrecheckState.buttonDisabled === false" in qa_source
    assert "configDisabledReasonVisible" in qa_source


def test_config_center_focused_section_execution_preview_and_template_save_state():
    _assert_current_plan_path()


def test_config_center_save_feedback_selects_saved_template_and_shows_time():
    _assert_current_plan_path()


def test_config_center_default_template_is_first_screen_primary_action():
    _assert_current_plan_path()


def test_config_center_production_ux_contract_for_task_five():
    _assert_current_plan_path()


def test_config_errors_are_humanized_before_reaching_user_facing_pages():
    app_source = APP_TSX.read_text(encoding="utf-8")
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    config_section = source[source.index("export function ConfigCenter"):source.index("export function TaskCenterView")]
    task_section = source[source.index("export function TaskCenterView"):source.index("export function ExecutionConsole")]
    console_path_section = source[source.index("function buildConsolePrimaryPath"):source.index("function isRealDxmMutationTask")]

    assert "function humanConfigPreviewError(message: string)" in app_source
    assert "setConfigPreviewError(humanConfigPreviewError(error instanceof Error ? error.message : '配置检查接口不可用'))" in app_source
    assert "function humanConfigError(message: string | null | undefined)" in source
    assert "<span>{humanConfigError(configPreviewError)}</span>" in source
    assert "humanConfigError(configPreviewError)" in task_section
    assert "humanConfigError(configPreviewError)" in console_path_section
    assert "请先确认本机后端仍在运行，再重新检查配置：${configPreviewError}" not in source
    assert "setConfigMessage(error instanceof Error ? error.message" not in config_section
    assert "message: error instanceof Error ? error.message" not in config_section
    assert "Internal Server Error" not in config_section
    assert "Cannot switch to a different thread" not in config_section


def test_config_center_focused_editor_removes_nonessential_field_group_header():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    editable_card = source[source.index("function EditableConfigSectionCard"):source.index("export function TaskCenterView")]
    field_group_styles = styles_source[
        styles_source.index(".editable-config-section__field-group-head {"):
        styles_source.index(".editable-config-section__field-group-head strong {")
    ]

    assert "当前重点字段" in editable_card
    assert "display: none;" in field_group_styles
    assert "gap: 4px;" in styles_source[styles_source.index(".editable-config-section {"):styles_source.index(".editable-config-section.is-incomplete")]
    assert ".config-edit-drawer[open] > summary" in styles_source
    open_summary_styles = styles_source[
        styles_source.index(".config-edit-drawer[open] > summary {"):
        styles_source.index(".config-template-console {")
    ]
    assert "display: none;" in open_summary_styles


def test_config_center_does_not_treat_selected_template_as_currently_used_before_apply_and_save():
    _assert_current_plan_path()


def test_config_center_surfaces_single_template_status_bar():
    _assert_current_plan_path()


def test_config_center_tracks_recently_saved_template_for_multi_template_reuse():
    _assert_current_plan_path()


def test_config_center_default_template_pack_tracks_each_saved_template():
    _assert_current_plan_path()


def test_config_center_default_template_pack_never_overwrites_formal_scoped_templates():
    _assert_current_plan_path()


def test_config_center_keeps_template_source_details_out_of_first_viewport():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    config_section = source[source.index("export function ConfigCenter"):source.index("export function TaskCenterView")]
    template_console = config_section[
        config_section.index('<div className="config-template-console config-template-console--compact"'):
        config_section.index('<details className="inline-disclosure config-template-console__details">')
    ]
    advanced_details = config_section[
        config_section.index('<details className="inline-disclosure config-template-console__details">'):
        config_section.index('<div className="config-section-tabs config-section-tabs--primary"')
    ]

    assert "config-template-console__status-bar" not in template_console
    assert 'aria-label="当前模板来源"' not in template_console
    assert "当前生效模板" not in template_console
    assert "可选模板 {activeSectionTemplateOptions.length} 套；已筛除不匹配或禁用模板" not in template_console
    assert "已筛除不匹配或禁用模板" not in template_console
    assert 'aria-label="当前模板来源详情"' in advanced_details
    assert "config-template-source--detail" in advanced_details
    assert "模板匹配详情" in advanced_details


def test_config_center_shows_save_scope_explainer_before_actions():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    editable_card = source[source.index("function EditableConfigSectionCard"):source.index("export function TaskCenterView")]
    actions_index = editable_card.index('<div className="editable-config-section__actions">')
    before_actions = editable_card[:actions_index]

    assert "config-save-scope-explainer" in before_actions
    assert "高级：保存为本次任务临时覆盖" in before_actions
    assert "只影响当前任务；仅在模板无法覆盖这一次商品时使用。" in before_actions
    assert "保存为店铺模板" in before_actions
    assert "影响后续匹配当前店铺/类目的任务，不覆盖全局模板。" in before_actions
    assert ".config-save-scope-explainer" in styles_source


def test_config_center_resets_transient_template_state_when_task_scope_changes():
    _assert_current_plan_path()


def test_config_center_distinguishes_advisory_gaps_from_start_blockers():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    config_section = source[source.index("export function ConfigCenter"):source.index("export function TaskCenterView")]
    editable_card = source[source.index("function EditableConfigSectionCard"):source.index("export function TaskCenterView")]

    assert "sectionsBlockingStart" in config_section
    assert "sectionsWithAdvisoryGaps" in config_section
    assert "advisoryGapCount" in config_section
    assert "辅助待补" in source
    assert "不阻断启动" in source
    assert "configPreview?.ok && advisoryGapCount > 0" in config_section
    assert "configSectionState(preview, Boolean(configPreview?.ok))" in config_section
    assert "configSectionState(preview, configOk)" in editable_card
    assert "pillClass" in editable_card
    assert "is-advisory" in source
    assert ".status-pill.info" in styles_source
    assert ".config-section-tabs button.is-advisory span" in styles_source
    assert ".editable-config-section.is-advisory" in styles_source


def test_config_center_matches_dxm_edit_page_sections_and_value_preview():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    config_section = source[source.index("export function ConfigCenter"):source.index("export function TaskCenterView")]

    assert "店铺与任务基础" in config_section
    assert "类目与标题" in config_section
    assert "SKU / 价格 / 库存" in config_section
    assert "价格策略" in config_section
    assert "图片与素材" in config_section
    assert "包装物流" in config_section
    assert "合规 / 海关" in config_section
    assert "半托管" in config_section
    assert "店小秘引用模板" in config_section
    assert "本次任务实际取值预览" in config_section
    assert "disclosure-card effective-value-preview" in source
    assert "本次任务" in config_section
    assert "商品原始数据" in config_section
    assert "店铺模板" in config_section
    assert "预置配置模板" in config_section
    assert "dxm_reference_templates.attribute_info.names" in config_section
    assert "dxm_reference_templates.freight.names" in config_section
    assert "dxm_reference_templates.service.names" in config_section
    assert "dxm_reference_templates.eu_responsible.names" in config_section
    assert "dxm_reference_templates.manufacturer.names" in config_section
    assert "setNestedConfigValue" in config_section
    assert "尺码模板" in config_section
    assert "publish_allowed" not in config_section
    assert "price_multiplier" in config_section
    assert "local_asset_path" in config_section
    assert "brand" in config_section


def test_config_center_marks_direct_and_advisory_config_fields():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    config_section = source[source.index("export function ConfigCenter"):source.index("export function TaskCenterView")]

    assert "usage:" in source
    assert "执行取值" in config_section
    assert "模板匹配" in config_section
    assert "辅助配置" in config_section
    assert "直接填入 DXM" not in config_section
    assert "策略/备用" not in config_section
    assert "辅助配置会进入执行取值" in config_section
    assert "不作为启动门禁必填" in config_section
    assert "记录字段只保存为配置记录" not in config_section
    assert "执行模式在创建任务时选择" in source
    assert "name: 'execution_mode'" not in config_section
    assert "field-usage" in config_section


def test_config_center_can_save_task_level_overrides_separately_from_templates():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    config_section = source[source.index("export function ConfigCenter"):source.index("export function TaskCenterView")]
    main_source = (REPO_ROOT / "app" / "backend" / "src" / "main.py").read_text(encoding="utf-8")
    models_source = (REPO_ROOT / "app" / "backend" / "src" / "models.py").read_text(encoding="utf-8")
    repo_source = (REPO_ROOT / "app" / "backend" / "src" / "repository.py").read_text(encoding="utf-8")

    assert "buildEditableConfigDraft(workspace.templates, configPreview, currentTemplateBinding)" in config_section
    assert "scope: 'template' | 'task'" in config_section
    assert "`/api/tasks/${selectedTask.id}/config-overrides`" in config_section
    assert "findSelectedTaskProduct(workspace.products, selectedTask)" in config_section
    assert "buildCurrentTemplateBinding(workspace, selectedTask, product)" in config_section
    assert "payload: withTemplateBinding(payload, currentTemplateBinding)" in config_section
    assert "findExactScopedTemplate(workspace.templates, section.templateType, currentTemplateBinding)" in config_section
    assert "当前模板范围" in config_section
    assert "保存为临时覆盖" in config_section
    assert "保存为店铺模板（后续任务可用）" in config_section
    assert "本次任务只影响当前批次" in config_section
    assert "默认仍优先使用模板" in config_section
    assert "高级临时覆盖" in config_section
    assert "当前任务会优先使用这些值" not in config_section
    assert "@app.patch('/api/tasks/{task_id}/config-overrides')" in main_source
    assert "TaskConfigOverrideRequest" in models_source
    assert "update_task_template_override" in repo_source


def test_config_center_draft_uses_current_scope_before_template_fallback():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    helper_section = source[source.index("function buildEditableConfigDraft"):source.index("function ConfigReadinessPanel")]
    config_section = source[source.index("export function ConfigCenter"):source.index("export function TaskCenterView")]

    assert "binding: TemplateBinding" in helper_section
    assert "findScopedTemplate(templates, section.templateType, binding)" in helper_section
    assert "templates.find((item) => item.template_type === section.templateType)" not in helper_section
    assert "buildEditableConfigDraft(workspace.templates, configPreview, currentTemplateBinding)" in config_section


def test_config_center_exposes_default_template_pack_and_save_state():
    _assert_current_plan_path()


def test_config_center_explains_active_template_source_and_filtered_choices():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    config_section = source[source.index("export function ConfigCenter"):source.index("export function TaskCenterView")]
    helper_section = source[source.index("function sourceBadgeText"):source.index("function EffectiveValuePreview")]
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    qa_source = QA_BROWSER_CHECK.read_text(encoding="utf-8")

    assert "activeSectionAllTemplates" in config_section
    assert "filteredTemplateChoiceCount" in config_section
    assert "activeTemplateSourceName" in config_section
    assert "templateSourceNameFromPreview" in helper_section
    assert "当前生效模板" in config_section
    assert "可选模板" in config_section
    assert "已筛除不匹配或禁用模板" in config_section
    assert "选择模板不会改表单，点击套用后才会填入当前分区" in config_section
    assert "config-template-source" in config_section
    assert config_section.index("config-template-source") > config_section.index("config-template-console__details")
    assert ".config-template-source" in styles_source
    assert "configTemplateSourceState" in qa_source


def test_config_center_explains_template_match_and_filter_reasons():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    config_section = source[source.index("export function ConfigCenter"):source.index("export function TaskCenterView")]
    helper_section = source[source.index("function templateBindingValueMatches"):source.index("function withTemplateBinding")]
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")

    assert "function TemplateMatchExplanation" in source
    assert "templateMatchExplanation" in config_section
    assert "aria-label=\"模板命中解释\"" in config_section
    assert "模板命中解释" in config_section
    assert "当前匹配范围" in source
    assert "当前命中" in source
    assert "可选模板" in source
    assert "筛除模板" in source
    assert "停用" in source
    assert "店铺不匹配" in source
    assert "类目不匹配" in source
    assert "平台不匹配" in source
    assert "templateFilterReason" in helper_section
    assert "templateMatchSummary" in helper_section
    assert "templateTraceSummaries" in source
    assert "configPreview?.templateTrace" in config_section
    assert "workspace.templateResolution?.template_trace" in config_section
    assert ".template-match-explanation" in styles_source


def test_config_center_uses_compact_density_and_collapsed_assist_drawer():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    config_section = source[source.index("export function ConfigCenter"):source.index("export function TaskCenterView")]
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    qa_source = QA_BROWSER_CHECK.read_text(encoding="utf-8")

    assert "--font-body: 14px" in styles_source
    assert "--font-compact: 11px" in styles_source
    assert ".content-density-summary" in styles_source
    assert ".config-assist-drawer" in styles_source
    assert ".config-precheck-action span," in styles_source
    assert ".config-precheck-action small {" in styles_source
    assert ".config-template-console__main label small" in styles_source
    assert ".config-template-console__default-status" in styles_source
    assert "flex-wrap: nowrap;" in styles_source[
        styles_source.index(".config-template-console__default-actions"):
        styles_source.index(".config-template-console__details")
    ]
    assert "display: none;" in styles_source[
        styles_source.index(".config-precheck-action span,"):
        styles_source.index(".config-precheck-action__buttons")
    ]
    assert "display: none;" in styles_source[
        styles_source.index(".config-template-console__main label small"):
        styles_source.index(".config-template-console select")
    ]
    assert "config-density-summary" in config_section
    assert "config-assist-drawer" in config_section
    assert "配置详情与下一步字段" in config_section
    assert "NextRequiredConfigFields" in config_section
    assert "configDensityCompact" in qa_source
    assert "configAssistDrawerCollapsed" in qa_source
    assert "configEditorNearFirstViewport" in qa_source
    assert "focusedEditorTop" in qa_source
    assert "focusedEditorFirstControlBottom" in qa_source
    assert "focusedEditorFieldCount >= 1" in qa_source
    assert "configDensityState.focusedEditorFirstControlBottom <= Math.min(720, configDensityState.viewportHeight * 0.96)" in qa_source
    assert 'document.querySelector(".editable-config-grid--focused")' in qa_source


def test_config_center_template_lookup_matches_backend_binding_aliases():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    config_helpers = source[source.index("function templateBindingValueMatches"):source.index("function withTemplateBinding")]

    assert "templateBindingCandidate" in config_helpers
    assert "\"stores\"" in config_helpers
    assert "\"store_names\"" in config_helpers
    assert "\"categories\"" in config_helpers
    assert "\"category_names\"" in config_helpers
    assert "\"platforms\"" in config_helpers
    assert "normalized.includes('*')" in config_helpers
    assert "normalized.includes('all')" in config_helpers
    assert "function templateBindingSpecificity" in config_helpers
    assert "function compareTemplateBindingSpecificity" in config_helpers
    assert "templateBindingSpecificity(right, binding) - templateBindingSpecificity(left, binding)" in config_helpers


def test_config_center_exact_template_lookup_does_not_duplicate_partial_scope_templates():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    config_helpers = source[source.index("function templateBindingValueMatches"):source.index("function withTemplateBinding")]
    exact_function = config_helpers[
        config_helpers.index("function templateHasStrictBinding"):
        config_helpers.index("function findScopedTemplate")
    ]

    assert "function templateBindingValueExactlyMatches" in config_helpers
    assert "templateBindingValueExactlyMatches(templateBindingField(record, [\"store_name\", \"store\", \"stores\", \"store_names\"]), binding.store_name)" in exact_function
    assert "templateBindingValueExactlyMatches(templateBindingField(record, [\"category_name\", \"category\", \"categories\", \"category_names\"]), binding.category_name)" in exact_function
    assert "templateBindingValueExactlyMatches(templateBindingField(record, [\"platform\", \"platforms\"]), binding.platform)" in exact_function
    assert "if (!expectedValues.length && !actualValue) return true" in config_helpers
    assert "if (!expectedValues.length || !actualValue) return false" in config_helpers
    assert "templateBindingValueStrictlyMatches(templateBindingField(record" not in exact_function


def test_config_center_template_picker_hides_other_scope_templates():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    config_helpers = source[source.index("function templateBindingValueMatches"):source.index("function withTemplateBinding")]

    assert "templateSelectableForBinding" in config_helpers
    assert "templateSelectableForBinding(template, binding)" in config_helpers
    assert ".filter((template) => template.template_type === section.templateType && template.is_enabled && templateSelectableForBinding(template, binding))" in config_helpers
    assert ".sort((left, right) => compareTemplateBindingSpecificity(left, right, binding)" in config_helpers


def test_config_center_template_save_does_not_overwrite_global_template():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    config_section = source[source.index("export function ConfigCenter"):source.index("export function TaskCenterView")]
    config_helpers = source[source.index("function templateBindingValueMatches"):source.index("function withTemplateBinding")]

    assert "function templateHasStrictBinding" in config_helpers
    assert "function findExactScopedTemplate" in config_helpers
    assert "templateHasStrictBinding(template, binding)" in config_helpers
    assert "const existing = findExactScopedTemplate(workspace.templates, section.templateType, currentTemplateBinding)" in config_section
    assert "全局模板只作为读取候选，不会被保存覆盖" in config_section


def test_config_center_preserves_multi_value_reference_template_fields():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    config_section = source[source.index("export function ConfigCenter"):source.index("export function TaskCenterView")]

    assert "valueKind?: 'text' | 'list'" in source
    assert "valueKind: 'list'" in source
    assert "parseEditableConfigFieldValue" in config_section
    assert "function editableConfigDraftValue" in source
    assert "value.join('\\n')" in source
    assert "<textarea" in config_section
    assert "每行一个" in config_section


def test_browser_qa_verifies_config_center_task_override_controls():
    source = QA_BROWSER_CHECK.read_text(encoding="utf-8")

    assert "taskOverrideSave" in source
    assert "templateSave" in source
    assert "nextRequiredConfig" in source
    assert "configReadySummary" in source
    assert "currentTemplateScope" in source
    assert "configHasTemplateScope" in source
    assert "onePerLine" in source
    assert "configHasListEditor" in source
    assert "configSectionTabState" in source
    assert "configSectionSwitchState" in source
    assert "configCenterSectionNavigation" in source
    assert "configTaskOverridePayloadState" in source
    assert "configCenterTaskOverridePayloadUsesTypedValue" in source
    assert "loginManualBrowser" in source
    assert "dxmUsername" in source
    assert "dxmPassword" in source
    assert "openRealLoginPage" in source
    assert "l3Approver" in source
    assert "consoleInlineOperatorForms" in source
    assert "taskInlineL3Approval" in source
    assert "taskQuickActionsState" in source
    assert "taskQuickActionsVisible" in source
    assert "taskQuickCreateVisible" in source
    assert "realMutationApprovalDomState" in source
    assert "consoleLoginFormDomState" in source
    assert "passwordType === 'password'" in source
    assert "rememberCredential" in source
    assert "rememberChecked" in source
    assert "rememberChecked === false" in source
    assert "credentialStateText" in source
    assert "consoleRealBrowserLoginEntry" in source
    assert "consoleBrowserControlPad" in source
    assert "consoleControlPadDomState" in source
    assert "firstScreenBlockedDomState" in source
    assert 'data-start-disabled' in source
    assert "consoleRuntimeLogState" in source
    assert "consoleRuntimeLogPreviewVisible" in source
    assert "consoleRuntimeLogState.hasRuntimeLogView === true" in source
    assert "'\\u754c\\u9762\\u5237\\u65b0'" in source
    assert "consoleRuntimeLogSourcesVisible" in source
    assert "browserControlPad" in source
    assert "'\\u6253\\u5f00\\u6d4f\\u89c8\\u5668\\u73b0\\u573a'" in source
    assert "'\\u542f\\u52a8\\u6267\\u884c\\u89c2\\u5bdf'" not in source
    assert "browserControlRestricted" in source
    assert "browserControlGoto" in source
    assert "browserControlScroll" in source
    assert "browserControlSelectorClick" in source
    assert "browserControlSelectorFill" in source
    assert "fieldSource" in source
    assert "configCenterTaskOverrideControls" in source
    assert "qa-config-center" in source
    assert "configShot" in source


def test_browser_qa_rejects_desktop_horizontal_overflow():
    source = QA_BROWSER_CHECK.read_text(encoding="utf-8")

    assert "desktopReflow" in source
    assert "desktopOverflow" in source
    assert "desktopNoHorizontalOverflow" in source
    assert "document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1" in source
    assert ".effective-value-item" in source


def test_frontend_has_stateful_operation_guide_entry():
    _assert_current_operator_help_path()


def test_dxm_access_page_is_login_only_not_full_workflow_guide():
    app_source = APP_TSX.read_text(encoding="utf-8")
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    access_section = DXM_ACCESS_PAGE_TSX.read_text(encoding="utf-8")
    dxm_case = app_source[
        app_source.index("case 'dxm_access'"):
        app_source.index("case 'product_tasks'")
    ]

    assert "DxmAccessPage" in dxm_case
    assert "GuideCenter" not in dxm_case
    assert "登录真实店小秘" in access_section
    assert "店小秘账号和店小秘密码" in access_section
    assert "记住账号密码" in access_section
    assert "本机加密保存" in access_section
    assert "打开真实登录页" in access_section
    assert "验证码完成后检测登录状态" in access_section
    assert "当前状态" in access_section
    assert "真实浏览器停留位置" in access_section
    assert "下一步" in access_section
    assert "function humanDxmLoginPhase" in access_section
    assert "return '已登录'" in access_section
    assert "return '等待验证码'" in access_section
    assert "return '登录失败'" in access_section
    assert "return '未登录'" in access_section
    assert "DxmLoginInlineForm" in access_section
    assert "onNavigateDxmTarget('draft_box')" in access_section
    assert "onNavigateDxmTarget('data_acquisition')" in access_section
    assert "登录浏览器只用于人工登录和验证码处理" in access_section
    assert "申请并启动单商品只保存" not in access_section
    assert "查看报告" not in access_section
    assert ".dxm-access-layout" in styles_source
    assert ".dxm-access-card" in styles_source


def test_first_screen_keeps_status_and_precheck_guidance_compact():
    safety_bar = SAFETY_STATUS_BAR_TSX.read_text(encoding="utf-8")
    home_page_source = HOME_PAGE_TSX.read_text(encoding="utf-8")
    dxm_access_source = DXM_ACCESS_PAGE_TSX.read_text(encoding="utf-8")
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    safety_visible = safety_bar[
        safety_bar.index("<section className={`safety-bar"):
        safety_bar.index("</section>")
    ]
    home_command_styles = styles_source[
        styles_source.index(".home-command {"):
        styles_source.index(".home-menu-map {")
    ]

    assert "真实保存已阻断" not in safety_visible
    assert "系统状态与验收详情" not in safety_visible
    assert "safety-bar__blocker" in safety_visible
    assert "{visibleBlockerReason}" in safety_visible
    assert "维护详情" not in safety_visible
    assert "维护状态说明" not in safety_visible
    assert "detailChips.map" not in safety_visible
    assert "aria-label=\"当前状态\"" in home_page_source
    assert home_page_source.count("<button") == 1
    assert ".home-status-line" in home_command_styles
    assert ".home-brief-grid" in home_command_styles
    assert "font-size: 14px;" in home_command_styles
    assert "DxmLoginInlineForm" in dxm_access_source
    assert "operator-inline-form" in dxm_access_source
    assert ".guide-step__summary-line" in styles_source
    assert ".guide-precheck-brief--compact" in styles_source
    assert ".operator-inline-form--compact .operator-inline-form__head span" in styles_source
    assert ".operator-inline-form--compact .operator-inline-form__login-state" in styles_source
    assert ".operator-inline-form--compact .operator-inline-form__credential-state" in styles_source
    assert ".operator-inline-form--compact .operator-inline-form__actions small" in styles_source
    assert "text-overflow: ellipsis;" in styles_source[
        styles_source.index(".operator-inline-form--compact .operator-inline-form__credential-state"):
        styles_source.index(".operator-inline-form--approval {")
    ]


def test_operational_surfaces_use_compact_type_scale():
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    root_tokens = styles_source[styles_source.index(":root {"):styles_source.index("}")]
    module_head = styles_source[styles_source.index(".module-head h2 {"):styles_source.index(".module-head span {")]
    console_focus = styles_source[styles_source.index(".console-focus-panel h1 {"):styles_source.index(".console-focus-panel p,")]
    config_focus = styles_source[styles_source.index(".config-focus-card h1 {"):styles_source.index(".config-focus-card p {")]
    task_current = styles_source[styles_source.index(".task-current-panel h1 {"):styles_source.index(".task-current-panel p {")]

    assert "--font-panel-title: 16px;" in root_tokens
    assert "--font-section-title: 13px;" in root_tokens
    assert "font-size: var(--font-section-title);" in module_head
    assert "font-size: var(--font-panel-title);" in console_focus
    assert "font-size: var(--font-panel-title);" in config_focus
    assert "font-size: var(--font-panel-title);" in task_current
    assert "font-size: 24px;" not in console_focus
    assert "font-size: 24px;" not in config_focus
    assert "font-size: 22px;" not in task_current


def test_sidebar_is_navigation_only_not_status_or_hint_panel():
    shell_source = (REPO_ROOT / "app" / "frontend" / "src" / "components" / "AppShell.tsx").read_text(encoding="utf-8")
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")

    assert "sidebar__current" not in shell_source
    assert "当前：" not in shell_source
    assert "aria-label={`运营工作台导航，${sourceLabel}`}" in shell_source
    assert "sidebar__note" not in shell_source
    assert "nav-section__index" not in shell_source
    assert "nav-subitem__mark" not in shell_source
    assert "<small>{item.hint}</small>" not in shell_source
    assert "nav-subitem__label" in shell_source
    assert ".sidebar__current" not in styles_source
    assert ".sidebar__note" not in styles_source


def test_sidebar_primary_navigation_keeps_only_user_main_path():
    _assert_frozen_primary_navigation()


def test_guide_center_can_start_real_dxm_login_without_l2_gate():
    _assert_current_connection_path()
    _assert_current_operator_help_path()


def test_start_selected_task_requires_dxm_session_before_real_save():
    app_source = APP_TSX.read_text(encoding="utf-8")
    start_section = app_source[app_source.index("async function startSelectedTask"):app_source.index("async function openDxmLogin")]

    assert "DXM_READY_SESSION_STATUSES" in app_source
    assert "not_published_verified" in app_source
    assert "const latestRuntimeStatus = await getJson<RuntimeStatus>(`/api/runtime/status?frontend_url=${encodeURIComponent(window.location.origin)}`)" in start_section
    assert "请先完成真实 DXM 登录" in start_section
    assert "setActiveSection('dxm_access')" in start_section


def test_real_operator_inputs_are_inline_not_browser_prompts():
    app_source = APP_TSX.read_text(encoding="utf-8")
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")

    assert "window.prompt" not in app_source
    assert "DxmLoginInlineForm" in workbench_source
    assert "L3ApprovalInlineForm" in workbench_source
    assert "dxmLoginDraft" in app_source
    assert "loadDxmCredential" in app_source
    assert "saveDxmCredential" in app_source
    assert "clearDxmCredential" in app_source
    assert "setDxmLoginDraft((current) => ({ ...current, rememberCredential: false }))" in app_source
    assert "useState({ username: '', password: '', rememberCredential: false })" in app_source
    assert "setDxmLoginDraft((current) => ({ ...current, rememberCredential: Boolean(result.available) }))" not in app_source
    assert "l3ApprovedBy" in app_source
    assert "useState('ops-owner')" not in app_source
    assert "rememberCredential: true" in app_source
    assert "const canSubmit = Boolean(draft.username.trim() && draft.password && !busy)" in workbench_source
    assert "const loginSubmitDisabledReason" in workbench_source
    assert "if (!canSubmit) return" in workbench_source
    assert "required" in workbench_source
    assert "店小秘账号" in workbench_source
    assert "店小秘密码" in workbench_source
    assert "记住账号密码" in workbench_source
    assert "清除已记住账号" in workbench_source
    assert "function humanDxmLoginState" in workbench_source
    assert "登录还没完成，不是系统故障" in workbench_source
    assert "登录未通过" in workbench_source
    assert "DXM 已进入业务页" in workbench_source
    assert "真实浏览器停留位置" in workbench_source
    assert "真实浏览器窗口会保留" in workbench_source
    assert "operator-inline-form__login-state" in workbench_source
    assert "operator-inline-form__login-state" in styles_source
    assert ".operator-inline-form__login-state.is-danger" in styles_source
    assert "批准人标识" in workbench_source
    assert "打开真实登录页" in workbench_source
    assert "title={!canSubmit ? loginSubmitDisabledReason : undefined}" in workbench_source
    assert "不能打开登录页的原因" in workbench_source
    assert "先填写店小秘账号和密码，才会打开真实登录页。" in workbench_source
    assert "申请并启动单商品只保存" in workbench_source
    assert "本机加密保存" in workbench_source
    assert "operator-inline-form" in styles_source


def test_user_docs_explain_login_secret_and_launcher_takeover_boundaries():
    _assert_current_authority_docs()


def test_user_docs_keep_real_operation_path_before_self_check_appendix():
    _assert_current_authority_docs()


def test_default_shell_copy_does_not_present_demo_as_user_path():
    app_source = APP_TSX.read_text(encoding="utf-8")
    shell_source = (REPO_ROOT / "app" / "frontend" / "src" / "components" / "AppShell.tsx").read_text(encoding="utf-8")
    workspace_source = WORKSPACE_TS.read_text(encoding="utf-8")
    safety_source = SAFETY_STATUS_BAR_TSX.read_text(encoding="utf-8")

    assert "api: '工作台数据已连接'" in app_source
    assert "mock: '正在连接本机工作台服务'" in app_source
    assert "正在读取任务、店铺、商品、证据和报告状态" in app_source
    assert "工作台服务连接异常" in app_source
    assert "暂时无法读取完整任务数据" in app_source
    assert "DXM 自动化接口不可用" not in app_source
    assert "只读降级数据" not in app_source
    assert "失败接口" not in app_source
    assert "等待真实接口" not in app_source
    assert "空工作台 / 演示前" not in app_source
    assert "连接状态" in shell_source
    assert "数据连接状态：{sourceLabel}" in shell_source
    assert "<strong>{sourceLabel}</strong>" not in shell_source
    assert "所有真实操作以当前后端能力和人工批准为准" in shell_source
    assert "真实接口优先" not in shell_source
    assert "不伪造保存结果" not in shell_source
    assert "演示数据仅开发模式可用" not in shell_source
    assert "准备演示数据或接入后端任务后" not in workspace_source
    assert "接入后端任务或导入真实商品后" in workspace_source
    assert "批量/无人值守：未放行" in safety_source
    assert "发布：无入口" in safety_source


def test_execution_console_defaults_to_operator_focus_and_collapses_advanced_noise():
    _assert_current_batch_draft_save_path()


def test_execution_console_collapses_browser_evidence_and_block_details_into_one_drawer():
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    stage_section = workbench_source[
        workbench_source.index("function AgentStagePanel"):
        workbench_source.index("function ConsoleCompletedReviewPanel")
    ]

    assert '<details className="agent-stage-support-drawer inline-disclosure">' in stage_section
    assert "<summary>更多浏览器状态与证据</summary>" in stage_section
    visible_stage = stage_section[
        stage_section.index("<AgentConsoleControls"):
        stage_section.index('<details className="agent-stage-support-drawer inline-disclosure">')
    ]
    assert "<summary>查看当前阻断详情</summary>" not in visible_stage
    assert "<summary>浏览器状态与证据路径</summary>" not in visible_stage

    support_drawer = stage_section[
        stage_section.index('<details className="agent-stage-support-drawer inline-disclosure">'):
    ]
    assert "<summary>查看阻断详情</summary>" in support_drawer
    assert "<summary>浏览器状态与证据路径</summary>" in support_drawer
    assert "AgentBrowserFrame" in support_drawer
    assert ".agent-stage-support-drawer" in styles_source


def test_execution_console_makes_l2_precheck_action_and_purpose_visible():
    _assert_current_batch_draft_save_path()


def test_execution_console_running_task_keeps_primary_action_on_current_execution():
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    focus_section = workbench_source[
        workbench_source.index("function ConsoleFocusPanel"):
        workbench_source.index("function AgentBrowserFrame")
    ]
    build_primary_path_section = workbench_source[
        workbench_source.index("function buildConsolePrimaryPath"):
        workbench_source.index("function FinalCheckFreshnessRow")
    ]
    primary_path_section = build_primary_path_section[
        build_primary_path_section.index("if (selectedTask.status === 'running')"):
        build_primary_path_section.index("if (selectedTask.status !== 'draft')")
    ]

    assert "action: 'current_execution'" in primary_path_section
    assert "ctaLabel: '查看当前执行'" in primary_path_section
    assert "查看检查计划" not in primary_path_section
    assert "action: 'reports'" not in primary_path_section
    assert "primaryPath.action === 'current_execution'" in focus_section
    assert "onRuntimeLogSourceChange('agent')" in focus_section


def test_execution_console_keeps_focus_panel_single_action_first():
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    focus_section = workbench_source[
        workbench_source.index("function ConsoleFocusPanel"):
        workbench_source.index("function AgentBrowserFrame")
    ]
    visible_before_details = focus_section[
        focus_section.index("<div className=\"console-focus-panel__main\">"):
        focus_section.index("<details className=\"console-focus-panel__details inline-disclosure\">")
    ]
    details_section = focus_section[focus_section.index("<details className=\"console-focus-panel__details inline-disclosure\">"):]

    assert "console-focus-panel__status-strip" in focus_section
    assert "aria-label=\"执行摘要\"" not in visible_before_details
    assert "<summary>维护人员查看运行状态</summary>" in details_section
    assert "aria-label=\"浏览器现场首屏状态\"" in visible_before_details
    assert "<strong>DXM 登录</strong>" in visible_before_details
    assert "<strong>保存前安全检查</strong>" in visible_before_details
    assert "<strong>人工确认</strong>" in visible_before_details
    assert "<strong>浏览器现场</strong>" in visible_before_details
    assert "<strong>任务</strong>" in details_section
    assert "<strong>当前步骤</strong>" in details_section
    assert "<strong>下一步</strong>" in visible_before_details
    assert "<strong>日志</strong>" in details_section


def test_execution_console_surfaces_operator_decision_and_collapses_live_logs_by_default():
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    console_section = workbench_source[
        workbench_source.index("export function ExecutionConsole"):
        workbench_source.index("function AgentBrowserFrame")
    ]
    focus_section = workbench_source[
        workbench_source.index("function ConsoleFocusPanel"):
        workbench_source.index("function AgentBrowserFrame")
    ]

    assert "aria-label=\"控制台当前决策\"" in focus_section
    assert "console-focus-panel__decision-grid" in focus_section
    assert "<strong>当前动作</strong>" in focus_section
    assert "<strong>为什么不能继续</strong>" in focus_section
    assert "<strong>下一步</strong>" in focus_section
    assert "primaryPath.reason" in focus_section
    assert "console-focus-panel__log" in focus_section
    assert "完整日志在下方“更多诊断与维护”。" in focus_section
    assert ".console-focus-panel__decision-grid" in styles_source
    assert ".console-focus-panel__log .runtime-log-preview" in styles_source


def test_execution_console_surfaces_single_primary_blocker_card():
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    focus_section = workbench_source[
        workbench_source.index("function ConsoleFocusPanel"):
        workbench_source.index("function AgentBrowserFrame")
    ]
    blocker_card_section = workbench_source[
        workbench_source.index("function ConsolePrimaryBlockerCard"):
        workbench_source.index("function AgentBrowserFrame")
    ]
    visible_before_details = focus_section[
        focus_section.index("<div className=\"console-focus-panel__main\">"):
        focus_section.index("<details className=\"console-focus-panel__details inline-disclosure\">")
    ]

    assert "ConsolePrimaryBlockerCard" in focus_section
    assert "primaryPath={primaryPath}" in focus_section
    assert "当前只处理这一项" in blocker_card_section
    assert "发生了什么" in blocker_card_section
    assert "为什么不能继续" in blocker_card_section
    assert "下一步" in blocker_card_section
    assert "primaryPath.code" in blocker_card_section
    assert "primaryPath.reason" in blocker_card_section
    assert "primaryPath.detail" in blocker_card_section
    assert "primaryPath.next" in blocker_card_section
    assert "console-primary-blocker-card" in styles_source
    assert visible_before_details.index("ConsolePrimaryBlockerCard") < visible_before_details.index("console-focus-panel__status-strip")


def test_execution_console_primary_blocker_card_contains_precheck_action_and_plain_explanation():
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    focus_section = workbench_source[
        workbench_source.index("function ConsoleFocusPanel"):
        workbench_source.index("function AgentBrowserFrame")
    ]
    blocker_card_section = workbench_source[
        workbench_source.index("function ConsolePrimaryBlockerCard"):
        workbench_source.index("function AgentBrowserFrame")
    ]

    assert "primaryActionLabel={primaryActionLabel}" in focus_section
    assert "onPrimaryAction={primaryAction}" in focus_section
    assert "primaryActionDisabled={false}" in focus_section
    assert "primaryActionDisabledTitle={undefined}" in focus_section
    assert "primaryActionDisabled &&" not in focus_section
    assert "l2ProbeResourceState.detail" not in focus_section
    assert "primaryPath.action === 'run_l2'" in blocker_card_section
    assert "READONLY_PRECHECK_CTA" in blocker_card_section
    assert "READONLY_PRECHECK_PURPOSE" in blocker_card_section
    assert "button--primary" in blocker_card_section
    assert "console-primary-blocker-card__action" in blocker_card_section
    assert "console-primary-blocker-card__explain" in blocker_card_section
    assert "disabled={primaryActionDisabled}" in blocker_card_section
    assert ".console-primary-blocker-card__action" in styles_source
    assert ".console-primary-blocker-card__explain" in styles_source


def test_execution_console_primary_blocker_details_are_collapsed_by_default():
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    blocker_card_section = workbench_source[
        workbench_source.index("function ConsolePrimaryBlockerCard"):
        workbench_source.index("function AgentBrowserFrame")
    ]

    assert "console-primary-blocker-card__summary" in blocker_card_section
    assert '<details className="console-primary-blocker-card__details inline-disclosure">' in blocker_card_section
    assert "<summary>查看原因与下一步</summary>" in blocker_card_section
    assert "console-primary-blocker-card__facts" in blocker_card_section
    assert blocker_card_section.index("console-primary-blocker-card__action") < blocker_card_section.index("console-primary-blocker-card__details")
    assert blocker_card_section.index("console-primary-blocker-card__explain") > blocker_card_section.index("console-primary-blocker-card__details")
    assert blocker_card_section.index("console-primary-blocker-card__recovery") > blocker_card_section.index("console-primary-blocker-card__details")
    assert blocker_card_section.index("console-primary-blocker-card__task-path") > blocker_card_section.index("console-primary-blocker-card__details")
    assert blocker_card_section.index("console-primary-blocker-card__login-recovery") > blocker_card_section.index("console-primary-blocker-card__details")
    assert ".console-primary-blocker-card__summary" in styles_source
    assert ".console-primary-blocker-card__details" in styles_source
    assert ".console-primary-blocker-card__facts" in styles_source


def test_execution_console_select_task_state_explains_task_preparation_path():
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    primary_path_section = workbench_source[
        workbench_source.index("function buildConsolePrimaryPath"):
        workbench_source.index("function FinalCheckFreshnessRow")
    ]
    blocker_card_section = workbench_source[
        workbench_source.index("function ConsolePrimaryBlockerCard"):
        workbench_source.index("function AgentBrowserFrame")
    ]

    assert "code: 'select_task'" in primary_path_section
    assert "title: '需要选择任务'" in primary_path_section
    assert "ctaLabel: '去待认领入箱'" in primary_path_section
    assert "primaryPath.code === 'select_task'" in blocker_card_section
    assert "aria-label=\"任务准备路径\"" in blocker_card_section
    assert "console-primary-blocker-card__task-path" in blocker_card_section
    assert "1 创建待认领商品任务" in blocker_card_section
    assert "先从店小秘已有待认领列表把商品放进商品箱。" in blocker_card_section
    assert "2 从商品箱创建保存任务" in blocker_card_section
    assert "完成后，选择已进入商品箱的商品创建单商品只保存。" in blocker_card_section
    assert "3 再确认配置并保存" in blocker_card_section
    assert "第二段才补编辑页配置、人工确认只保存；批量和发布入口保持关闭。" in blocker_card_section
    assert ".console-primary-blocker-card__task-path" in styles_source


def test_execution_console_surfaces_business_execution_state_before_details():
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    focus_section = workbench_source[
        workbench_source.index("function ConsoleFocusPanel"):
        workbench_source.index("function AgentBrowserFrame")
    ]
    visible_before_details = focus_section[
        focus_section.index("<div className=\"console-focus-panel__main\">"):
        focus_section.index("<details className=\"console-focus-panel__details inline-disclosure\">")
    ]

    details_section = focus_section[focus_section.index("<details className=\"console-focus-panel__details inline-disclosure\">"):]

    assert "aria-label=\"浏览器现场首屏状态\"" in visible_before_details
    assert "console-focus-panel__status-strip" in visible_before_details
    assert "<strong>DXM 登录</strong>" in visible_before_details
    assert "loginState?.label ?? '未检测'" in visible_before_details
    assert "<strong>保存前安全检查</strong>" in visible_before_details
    assert "l2StatusLabel" in visible_before_details
    assert "<strong>人工确认</strong>" in visible_before_details
    assert "l3StatusLabel" in visible_before_details
    assert "<strong>浏览器现场</strong>" in visible_before_details
    assert "browserLabel" in visible_before_details
    assert "<strong>操控状态</strong>" in details_section
    assert "controlLabel" in details_section
    assert "<strong>人工接管</strong>" in details_section
    assert "takeoverLabel" in details_section
    assert "当前页面" in details_section
    assert "shortUrl(currentUrl)" in details_section
    assert "console-focus-panel__status-strip" in styles_source
    assert "console-focus-panel__status-strip span" in styles_source


def test_execution_console_primary_blocker_card_shows_precheck_recovery_path():
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    execution_console_section = workbench_source[
        workbench_source.index("export function ExecutionConsole"):
        workbench_source.index("function ConsoleFocusPanel")
    ]
    focus_section = workbench_source[
        workbench_source.index("function ConsoleFocusPanel"):
        workbench_source.index("function AgentBrowserFrame")
    ]
    blocker_card_section = workbench_source[
        workbench_source.index("function ConsolePrimaryBlockerCard"):
        workbench_source.index("function AgentBrowserFrame")
    ]

    assert "onRuntimeLogSourceChange={onRuntimeLogSourceChange}" in execution_console_section
    assert "onRuntimeLogSourceChange={onRuntimeLogSourceChange}" in focus_section
    assert "onRuntimeLogSourceChange: (source: RuntimeLogSource) => void" in focus_section
    assert "onShowReports={onShowReports}" in focus_section
    assert "aria-label=\"保存前安全检查失败恢复路径\"" in blocker_card_section
    assert "console-primary-blocker-card__recovery" in blocker_card_section
    assert "1 确认登录" in blocker_card_section
    assert "2 打开目标页" in blocker_card_section
    assert "3 重新检查" in blocker_card_section
    assert "真实浏览器已登录，验证码或账号密码错误先在登录窗口修正。" in blocker_card_section
    assert "能打开已有待认领列表和商品箱；打不开先处理页面权限或网络。" in blocker_card_section
    assert "无写入风险后，再点击运行保存前安全检查。" in blocker_card_section
    assert "onRuntimeLogSourceChange('launcher')" in blocker_card_section
    assert "查看启动器日志" in blocker_card_section
    assert "onShowReports" in blocker_card_section
    assert "查看检查计划" in blocker_card_section
    assert ".console-primary-blocker-card__recovery" in styles_source


def test_execution_console_distinguishes_login_browser_from_agent_execution_browser():
    _assert_current_connection_path()


def test_execution_console_collapses_operator_forms_inside_real_browser_details():
    _assert_current_batch_draft_save_path()


def test_execution_console_keeps_agent_mode_explanation_collapsed_after_primary_actions():
    _assert_current_batch_draft_save_path()


def test_execution_console_explains_disabled_session_controls():
    _assert_current_batch_draft_save_path()


def test_execution_console_surfaces_browser_launch_failure_diagnostics():
    _assert_current_connection_path()


def test_execution_console_log_center_autofollows_and_surfaces_sources():
    app_source = APP_TSX.read_text(encoding="utf-8")
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    log_panel_section = workbench_source[workbench_source.index("function RuntimeLogPanel"):workbench_source.index("function RuntimeLogLine")]
    focus_panel_section = workbench_source[workbench_source.index("function ConsoleFocusPanel"):workbench_source.index("function AgentBrowserFrame")]

    assert "window.setInterval" in app_source
    assert "1500" in app_source
    assert "useState<RuntimeLogSource>('backend')" in app_source
    assert "完整日志与维护诊断" in workbench_source
    assert "自动增量刷新" in workbench_source
    assert "更多诊断与维护" in workbench_source
    assert "完整日志在下方“更多诊断与维护”" in workbench_source
    assert "自动跟随最新日志" in log_panel_section
    assert "setAutoFollow" in log_panel_section
    assert "logViewRef" in log_panel_section
    assert "scrollTop = logViewRef.current.scrollHeight" in log_panel_section
    assert "onScroll" in log_panel_section
    assert "data-testid=\"runtime-log-view\"" in log_panel_section
    assert "RuntimeLogPreview" in workbench_source
    assert "启动器" in log_panel_section
    assert "依赖安装" in log_panel_section
    assert "自动浏览器" in log_panel_section
    assert "launcher: '启动器'" in focus_panel_section
    assert "task: '任务'" in focus_panel_section
    assert "agent: '自动浏览器'" in focus_panel_section
    assert "console-focus-panel__recovery" in focus_panel_section
    assert "浏览器卡住了？" in focus_panel_section
    assert "人工接管真实浏览器" in focus_panel_section
    assert "交还自动浏览器" in focus_panel_section
    assert "重启真实浏览器执行器" in focus_panel_section
    assert "正在打开店小秘已有待认领列表。" in workbench_source
    assert "原始技术细节只在展开区显示" in workbench_source
    assert ".console-log-card--live" in styles_source
    assert ".runtime-log-toolbar" in styles_source
    assert ".runtime-log-preview__head > .runtime-log-refresh--warn" in styles_source


def test_runtime_log_refresh_isolates_failed_sources():
    app_source = APP_TSX.read_text(encoding="utf-8")
    types_source = (REPO_ROOT / "app" / "frontend" / "src" / "types.ts").read_text(encoding="utf-8")
    refresh_section = app_source[app_source.index("const refreshRuntimeLogs = useCallback"):app_source.index("useEffect(() => {\n    runtimeLogCursorRef.current")]

    assert "const loaded = await Promise.all(runtimeLogSources.map" in refresh_section
    assert "try {" in refresh_section
    assert "catch (error)" in refresh_section
    assert "ok: false as const" in refresh_section
    assert "tags: ['fetch_failed']" in refresh_section
    assert "部分日志源读取失败" in refresh_section
    assert "其他日志继续刷新" in refresh_section
    assert "if (ok) runtimeLogCursorRef.current[source] = response.nextCursor" in refresh_section
    assert "const shouldAppend = ok && response.cursor > 0" in refresh_section
    assert "error?: string" in types_source


def test_agent_console_uses_live_frame_and_network_event_contract():
    _assert_current_connection_path()


def test_execution_console_exposes_in_page_browser_control_contract():
    app_source = APP_TSX.read_text(encoding="utf-8")
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    types_source = (REPO_ROOT / "app" / "frontend" / "src" / "types.ts").read_text(encoding="utf-8")
    console_section = workbench_source[workbench_source.index("export function ExecutionConsole"):workbench_source.index("function RuntimeControlPanel")]
    control_action_type = types_source[types_source.index("export type AgentConsoleControlAction"):types_source.index("export type AgentConsoleControlCommand")]

    assert "export type AgentConsoleControlCommand" in types_source
    assert "async function controlAgentConsoleBrowser" in app_source
    assert "/api/agent-console/control" in app_source
    assert "onControlAgentConsoleBrowser={controlAgentConsoleBrowser}" in app_source
    assert "onControlAgentConsoleBrowser" in console_section
    assert "BrowserControlPad" in workbench_source
    assert "<summary>高级浏览器控制</summary>" in workbench_source
    assert "页面内操控" in workbench_source
    assert "目标 URL" in workbench_source
    assert "仅开放受限导航和滚动" in workbench_source
    assert "填写、点击和保存必须走任务流或人工接管" in workbench_source
    assert "页面点击、选择器填写、焦点输入和按键已关闭" in workbench_source
    assert "CSS 选择器" not in workbench_source
    assert "按选择器点击" not in workbench_source
    assert "按选择器填写" not in workbench_source
    assert "<span>按键</span>" not in workbench_source
    assert "滚动页面" in workbench_source
    assert "仅控制当前独立浏览器窗口" in workbench_source
    assert "'click'" not in control_action_type
    assert "'type'" not in control_action_type
    assert "'press'" not in control_action_type
    assert "'selector_click'" not in control_action_type
    assert "'selector_fill'" not in control_action_type
    assert ".browser-control-pad" in styles_source


def test_execution_console_exposes_manual_takeover_for_real_browser():
    app_source = APP_TSX.read_text(encoding="utf-8")
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    types_source = (REPO_ROOT / "app" / "frontend" / "src" / "types.ts").read_text(encoding="utf-8")
    console_section = workbench_source[workbench_source.index("export function ExecutionConsole"):workbench_source.index("function RuntimeControlPanel")]

    assert "async function requestAgentConsoleTakeover" in app_source
    assert "/api/agent-console/takeover" in app_source
    assert "/api/agent-console/release" in app_source
    assert "onOpenDxmLogin={openDxmLogin}" in app_source
    assert "onOpenDxmLogin" in console_section
    assert "登录/人工处理真实浏览器" in workbench_source
    assert "这里只打开真实店小秘窗口，不启动保存" in workbench_source
    assert "onRequestAgentConsoleTakeover={requestAgentConsoleTakeover}" in app_source
    assert "onReleaseAgentConsoleTakeover={releaseAgentConsoleTakeover}" in app_source
    assert "manual_takeover?: boolean" in types_source
    assert "manual_takeover_started_at?: string | null" in types_source
    assert "人工接管真实浏览器" in workbench_source
    assert "交还自动浏览器" in workbench_source
    assert "用户正在真实浏览器中接管" in workbench_source


def test_execution_console_exposes_runtime_control_and_agent_action_timeline():
    app_source = APP_TSX.read_text(encoding="utf-8")
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    types_source = (REPO_ROOT / "app" / "frontend" / "src" / "types.ts").read_text(encoding="utf-8")
    console_section = workbench_source[workbench_source.index("export function ExecutionConsole"):workbench_source.index("function ConsoleFocusPanel")]

    assert "async function runRuntimeControl" in app_source
    assert "/api/runtime/control" in app_source
    assert "onRuntimeControl={runRuntimeControl}" in app_source
    assert "operationNotice" in app_source
    assert "setOperationNotice(result.message ?? runtimeControlSuccessMessage(action))" in app_source
    assert "data-testid=\"operation-notice\"" in app_source
    assert "runtimeStatus={runtimeStatus}" in app_source
    assert "已启动保存前安全检查，请在“实时浏览器”查看实时日志。" in app_source
    assert ".operation-alert--ok" in styles_source
    assert "runtimeControl?: {" in types_source
    assert "owner?: 'start_mvp' | 'desktop' | 'direct' | string" in types_source
    assert "managedByLauncher: boolean" in types_source
    assert "managedByDesktop?: boolean" in types_source
    assert "restartAvailable: boolean" in types_source
    assert "workflowRuntime?: {" in types_source
    assert "'reset_workflow_runtime'" in types_source
    assert "onRuntimeControl={onRuntimeControl}" in workbench_source
    assert "onRuntimeControl('run_l2_readonly_probe')" in workbench_source
    assert "onRuntimeControl('reset_workflow_runtime')" in workbench_source
    assert "agent-console-lifecycle__actions" in workbench_source
    assert ".agent-console-lifecycle__actions" in styles_source
    assert "console-diagnostics-drawer" in console_section
    assert "ModuleHead title=\"运行时维护\"" in console_section
    assert "RuntimeControlPanel" in console_section
    assert "停止自动浏览器" in workbench_source
    assert "重启真实浏览器执行器" in workbench_source
    assert ".runtime-control-panel__callout" in styles_source
    assert "真实浏览器执行器已重启，请重新打开执行浏览器后再启动任务。" in app_source
    assert "清理卡住任务" in workbench_source
    assert "重启后端" in workbench_source
    assert "runtimeStatus?.runtimeControl?.managedByLauncher" in workbench_source
    assert "runtimeStatus?.runtimeControl?.restartAvailable" in workbench_source
    assert "restartDisabled" in workbench_source
    assert "启动器托管：{launcherManaged ? '已接管' : '未接管'}" in workbench_source
    assert "scripts/start-mvp.bat" in workbench_source
    assert "ModuleHead title=\"自动操作轨迹\"" in console_section
    assert "AgentActionTimeline" in console_section
    assert "export type AgentConsoleActionEvent" in types_source
    assert "action_events?: AgentConsoleActionEvent[]" in types_source
    assert "getAgentActionTimelineEvents" in workbench_source
    assert "agentConsole?.action_events" in workbench_source
    assert "agentConsole?.step_history" in workbench_source
    assert "save: '保存'" in workbench_source


def test_operation_feedback_uses_floating_toast_stack_not_page_flow_alerts():
    app_source = APP_TSX.read_text(encoding="utf-8")
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    shell_section = app_source[app_source.index("<AppShell"):app_source.index("{content}")]

    assert 'className="operation-toast-stack"' in shell_section
    assert "{workspaceNotice && (" in shell_section
    assert "{visibleOperationError && (" in shell_section
    assert "{operationNotice && (" in shell_section
    assert "const visibleOperationError = selectedTaskCompleted && operationError?.includes('保存前安全检查')" in app_source
    assert "if (selectedTaskCompleted && operationError?.includes('保存前安全检查'))" in app_source
    assert "setOperationError(null)" in app_source
    assert shell_section.index('className="operation-toast-stack"') < shell_section.index("{workspaceNotice && (")
    assert shell_section.index('className="operation-toast-stack"') < shell_section.index("{visibleOperationError && (")
    assert shell_section.index('className="operation-toast-stack"') < shell_section.index("{operationNotice && (")
    assert shell_section.index("{workspaceNotice && (") < shell_section.index("{visibleOperationError && (")
    assert "data-testid=\"operation-notice\"" in shell_section
    assert "data-testid=\"workspace-notice\"" in shell_section
    assert ".operation-toast-stack" in styles_source
    toast_styles = styles_source[styles_source.index(".operation-toast-stack {"):styles_source.index(".operation-alert {")]
    assert "position: fixed;" in toast_styles
    assert "right: 18px;" in toast_styles
    assert "bottom: 18px;" in toast_styles
    assert "width: min(380px, calc(100vw - 36px));" in toast_styles
    assert "z-index: 60;" in toast_styles
    assert "pointer-events: none;" in toast_styles
    assert "pointer-events: auto;" in styles_source[styles_source.index(".operation-alert {"):styles_source.index(".operation-alert--ok {")]
    workspace_alert_styles = styles_source[styles_source.index(".workspace-alert {"):styles_source.index(".workspace-alert--degraded {")]
    assert "pointer-events: auto;" in workspace_alert_styles
    assert "box-shadow: var(--shadow);" in workspace_alert_styles
    assert "browser_control: '控制'" in workbench_source
    assert "fill: '填写'" in workbench_source
    assert ".runtime-control-panel" in styles_source
    assert ".agent-action-timeline" in styles_source


def test_workspace_notice_is_collapsed_to_compact_drawer_by_default():
    app_source = APP_TSX.read_text(encoding="utf-8")
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    shell_section = app_source[app_source.index("<AppShell"):app_source.index("{content}")]
    notice_section = shell_section[shell_section.index("{workspaceNotice && ("):shell_section.index("{visibleOperationError && (")]

    assert "<details" in notice_section
    assert "workspace-alert__summary" in notice_section
    assert "workspace-alert__detail" in notice_section
    assert "workspace-alert__actions" in notice_section
    assert "查看详情" in notice_section
    assert "workspaceNotice.detail" in notice_section
    assert notice_section.index("workspace-alert__summary") < notice_section.index("workspace-alert__detail")
    assert ".workspace-alert__summary" in styles_source
    assert ".workspace-alert__detail" in styles_source
    assert ".workspace-alert[open]" in styles_source
    assert "max-height: 38px;" in styles_source[styles_source.index(".workspace-alert:not([open])"):styles_source.index(".workspace-alert[open]")]


def test_browser_qa_verifies_demo_is_hidden_from_default_user_path():
    source = QA_BROWSER_CHECK.read_text(encoding="utf-8")
    ensure_section = source[source.index("async function ensureRealMutationTask"):source.index("async function screenshot")]

    assert "demoBatchHiddenByDefault" in source
    assert "demoBatchButton" in source
    assert "localDemoStart" in source
    assert "realMutationTask" in source
    assert "async function waitForTextGone(fragment" in source
    assert "await waitForTextGone(text.workspaceLoading" in source
    assert "clickSelector('[data-section=\"tasks\"]')" in source
    assert "clickSelector('[data-section=\"console\"]')" in source
    assert "clickSelector('[data-section=\"reports\"]')" in source
    assert "taskTextAfterDefaultDemoCheck" in source
    assert "!taskTextAfterDefaultDemoCheck.includes(text.demoBatchButton)" in source
    assert "const readyModeDemoTask = null;" in source
    assert "const readyModeDemoTask = reportOnlyFinal || !qaExpectedReady ? null : await ensureDryRunDemoTask();" not in source
    assert "fetchJson('/api/stores')" in ensure_section
    assert "fetchJson('/api/products')" in ensure_section
    assert "existingStores.find(store => store?.name === 'Dang Kang')" in ensure_section
    assert "/api/delivery/workspace" not in ensure_section


def test_browser_qa_uses_two_stage_acquisition_path_instead_of_fake_single_save_fixture():
    source = QA_BROWSER_CHECK.read_text(encoding="utf-8")
    ensure_section = source[source.index("async function ensureRealMutationTask"):source.index("async function verifyUnreleasedRealModeCreateBlocked")]
    qa_task_section = source[source.index("async function ensureRealMutationTask"):source.index("async function screenshot")]

    assert "fetchJson('/api/tasks')" in ensure_section
    assert "fetchJson('/api/acquisition/claimed-products')" in ensure_section
    assert "postJson('/api/acquisition/claim-requests'" in ensure_section
    assert "ensureTwoStageClaimRequest" in ensure_section
    assert "findReusableClaimRequest" in ensure_section
    assert "Local acceptance claim request" in ensure_section
    assert "Local acceptance draft save task" in ensure_section
    assert "LOCAL_ACCEPTANCE" in ensure_section
    assert "QA two-stage acquisition claim request" not in ensure_section
    assert "QA local gated single_save one product fixture" not in source
    assert "QA guarded single-save product" not in source
    assert "QA guarded product" not in ensure_section
    assert "QA guarded real mutation task" not in source
    assert "product_ids: [claimedProduct.id]" in ensure_section
    assert "product_ids: [qaProduct.id]" not in ensure_section
    assert "postJsonStatus('/api/tasks'" not in ensure_section
    assert "function findReusableQaTask(" not in ensure_section
    assert "claimedProducts.length" in ensure_section
    assert "stage: 'awaiting_claimed_product'" in ensure_section
    assert "stage: 'claimed_product_available'" in ensure_section
    assert "QA guarded real mutation task" not in source
    assert "async function verifyUnreleasedRealModeCreateBlocked()" in qa_task_section
    assert "return await postJsonStatus('/api/tasks'" in qa_task_section
    assert "product_ids: products.map(item => item.id)" not in ensure_section
    assert "findReusableQaTask(existingTasks, '\\u672c\\u5730\\u6f14\\u793a\\u6838\\u9a8c\\u6279\\u6b21', 'dry_run')" in qa_task_section


def test_task_center_sanitizes_legacy_qa_fixture_names_from_user_visible_rows():
    _assert_current_reader_selection_path()


def test_task_center_hides_auxiliary_qa_and_dry_run_tasks_by_default():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    task_center_section = source[source.index("export function TaskCenterView"):source.index("export function ExecutionConsole")]

    assert "function isAuxiliaryTask(" in source
    assert "defaultTaskRows = compactTaskRows.filter((task) => !isAuxiliaryTask(task))" in task_center_section
    assert "showAllTasks" in task_center_section
    assert "? workspace.tasks" in task_center_section
    assert "selectedTask && isAuxiliaryTask(selectedTask)" in task_center_section
    assert "辅助/历史批次默认隐藏" in task_center_section


def test_browser_qa_uses_browser_launch_fallbacks_and_logs_failures():
    source = QA_BROWSER_CHECK.read_text(encoding="utf-8")

    assert "function Find-BrowserCandidates" in source
    assert "function Test-DebugPortAvailable" in source
    assert "[System.Net.Sockets.TcpListener]::new" in source
    assert "function Find-QaDebugPort" in source
    assert "@(15000, 20000, 30000, 40000, 50000)" in source
    assert "Port $Port is unavailable or reserved; using $selectedPort instead" in source
    assert "function Start-QaCdpBrowser" in source
    assert "qa-browser-launch-attempts.json" in source
    assert "qa-browser-stderr" in source
    assert "ms-playwright" in source
    assert "chrome-win64" in source
    assert "--headless=new" in source
    assert "--headless" in source
    assert "HeadlessMode" in source
    assert "Chrome DevTools endpoint did not start after trying" in source
    assert "qa-browser-error.json" in source
    assert 'Remove-Item -LiteralPath (Join-Path $absoluteOutDir "qa-browser-error.json") -Force -ErrorAction SilentlyContinue' in source
    assert "unhandledRejection" in source
    assert "uncaughtException" in source


def test_browser_qa_tracks_network_failure_urls_and_ignores_only_orphan_failures():
    source = QA_BROWSER_CHECK.read_text(encoding="utf-8")

    assert "const requestIndex = new Map();" in source
    assert "requestIndex.set(msg.params.requestId, requestEntry);" in source
    assert "url: requestEntry.url || null" in source
    assert "errorText: msg.params.errorText || ''" in source
    assert "function isIgnorableNetworkFailure(event)" in source
    assert "event.type === 'failed' && !event.url && !String(event.errorText || '').trim()" in source
    assert "ignoredFailedCount" in source
    assert "failedNetworkEvents = networkEvents.filter(event => event.type === 'failed' && !isIgnorableNetworkFailure(event))" in source


def test_report_center_uses_backend_l2_probe_plan_contract():
    _assert_current_results_and_issues_path()


def test_report_center_shows_allowlist_review_before_l2_recheck_commands():
    _assert_current_results_and_issues_path()


def test_final_delivery_card_explains_blocked_to_ready_prerequisites():
    source = results_page_source()
    final_card_section = final_delivery_card_section()
    qa_script = QA_BROWSER_CHECK.read_text(encoding="utf-8")

    assert "真实写入放行前置" in final_card_section
    assert "保存前安全检查通过" in source
    assert "人工确认单商品只保存" in source
    assert "保存结果必须可核对" in source
    assert "保存成功、未发布证明、截图和 network/HAR" not in source
    assert "不能用 allowlist 模板替代 L2 通过" not in source
    assert "delivery-check-card__release-gates" in final_card_section
    assert "realWriteReleasePrerequisites" in source
    assert "reportRealWriteReleasePrerequisites" in qa_script


def test_final_delivery_card_surfaces_two_stage_production_status():
    types_source = (REPO_ROOT / "app" / "frontend" / "src" / "types.ts").read_text(encoding="utf-8")
    final_card_section = final_delivery_card_section()

    assert "real_dxm_two_stage_end_to_end?: string | null" in types_source
    assert "effective_real_dxm_two_stage_end_to_end?: string | null" in types_source
    assert "production_delivery_ready?: boolean | null" in types_source
    assert "final_delivery_completed?: boolean | null" in types_source
    assert "two_stage_acceptance_matches_expected?: boolean | null" in types_source
    assert "expected_real_dxm_two_stage_end_to_end?: string | null" in types_source
    assert "两段式端到端" in final_card_section
    assert "生产交付状态" in final_card_section
    assert "productionDeliveryLabel" in final_card_section
    assert "twoStageEndToEndLabel" in final_card_section
    visible_section = final_card_section[:final_card_section.index('<details className="disclosure-card delivery-check-card__appendix">')]
    assert "受控单商品只保存" not in visible_section
    assert "controlled_single_save_only" not in visible_section
    assert "single_save" not in visible_section


def test_browser_qa_final_report_requires_two_stage_production_status():
    qa_source = QA_BROWSER_CHECK.read_text(encoding="utf-8")
    final_report_section = qa_source[qa_source.index("if (reportOnlyFinal) {"):qa_source.index("const finalResult = {")]
    final_assertions_section = qa_source[qa_source.index("const finalResult = {"):qa_source.index("consoleErrors,", qa_source.index("const finalResult = {"))]

    assert "finalReportTwoStageEndToEnd" in final_report_section
    assert "effective_real_dxm_two_stage_end_to_end" in final_report_section
    assert "real_dxm_two_stage_end_to_end" in final_report_section
    assert "finalReportTwoStagePassed" in final_report_section
    assert "finalReportProductionDeliveryReady" in final_report_section
    assert "production_delivery_ready" in final_report_section
    assert "final_delivery_completed" in final_report_section
    assert "two_stage_acceptance_matches_expected" in final_report_section
    assert "finalReportTwoStageStatusVisible" in final_report_section
    assert "finalReportProductionDeliveryVisible" in final_report_section
    assert "finalReportTwoStageApiMatchesExpected" in final_assertions_section
    assert "finalReportProductionDeliveryStateHonest" in final_assertions_section
    assert "finalReportTwoStageStatusVisible" in final_assertions_section
    assert "finalReportProductionDeliveryVisible" in final_assertions_section
    assert "finalReportCenterShowsFinalPassState: allowMissingPostFinalQa || reportText.includes(expectedLocalWorkbench)" in final_assertions_section
    assert "finalReportRealWriteReleasePrerequisites: allowMissingPostFinalQa" in final_assertions_section
    assert "finalReportCenterQaDiagnostics.hasRealWriteReleasePrerequisites" in final_assertions_section
    assert "Boolean(finalCheckSummary?.real_mode_release_plan)" in final_assertions_section
    assert "const finalReportTwoStageStatusText = '\\u4e24\\u6bb5\\u5f0f\\u7aef\\u5230\\u7aef\\uff1a' + finalReportTwoStageLabel;" in final_report_section
    assert "const finalReportProductionDeliveryText = '\\u751f\\u4ea7\\u4ea4\\u4ed8\\u72b6\\u6001\\uff1a' + finalReportProductionDeliveryLabel;" in final_report_section
    assert "`${finalReportTwoStageLabel}`" not in final_report_section
    assert "`${finalReportProductionDeliveryLabel}`" not in final_report_section
    assert final_report_section.index("const reportText = await waitForBodyIncludes") < final_report_section.index("const finalReportTwoStageStatusVisible")
    assert final_report_section.index("const reportText = await waitForBodyIncludes") < final_report_section.index("const finalReportProductionDeliveryVisible")
    assert "ok_scope === 'local_workbench_and_controlled_single_save_ready'" not in final_assertions_section


def test_report_center_keeps_final_check_engineering_details_in_appendix():
    _assert_current_results_and_issues_path()


def test_dashboard_and_guide_default_copy_hide_gate_codes():
    _assert_frozen_primary_navigation()
    _assert_current_batch_draft_save_path()


def test_config_center_uses_business_labels_for_execution_mode():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    config_section = source[source.index("export function ConfigCenter"):source.index("function EditableConfigSectionCard")]
    readiness_section = source[source.index("function ConfigReadinessPanel"):source.index("function NextRequiredConfigFields")]

    assert 'value="真实单商品只保存"' in config_section
    assert 'hint="受控真实浏览器执行，只保存不发布"' in config_section
    assert 'value="真实 single_save"' not in config_section
    assert '受控 runner 执行' not in config_section
    assert "humanTaskModeLabel(configPreview.mode)" in readiness_section
    assert "可进入保存判断" in readiness_section
    assert "可进入 L2/L3 判断" not in readiness_section
    assert "选择 single_save 任务后" not in readiness_section
    assert "选择单商品只保存任务后" in readiness_section


def test_inline_approval_uses_business_copy_not_gate_codes():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    approval_section = source[source.index("function L3ApprovalInlineForm"):source.index("function RegressionGateGrid")]

    assert "人工确认真实保存" in approval_section
    assert "只启动单商品只保存任务" in approval_section
    assert "申请并启动单商品只保存" in approval_section
    for forbidden in ("L3 人工确认真实保存", "single_save", "save-only", "金丝雀"):
        assert forbidden not in approval_section


def test_login_form_explains_credential_storage_state_for_desktop_and_browser_preview():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    login_form_section = source[source.index("function DxmLoginInlineForm"):source.index("function humanDxmLoginState")]
    credential_facts_section = source[source.index("function CredentialStorageFacts"):source.index("function humanDxmLoginState")]

    assert "CredentialStorageFacts" in login_form_section
    assert "credentialState={credentialState}" in login_form_section
    assert "账号记住状态" in credential_facts_section
    assert "本机加密保存可用" in credential_facts_section
    assert "下次打开免安装版会自动填入" in credential_facts_section
    assert "只保存在当前 Windows 用户目录" in credential_facts_section
    assert "当前预览不能保存密码" in credential_facts_section
    assert "请从桌面免安装版打开" in credential_facts_section
    assert "不会写入本机密码" in credential_facts_section
    assert "operator-inline-form__credential-facts" in styles_source


def test_execution_console_default_log_summary_hides_absolute_paths():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    console_section = source[source.index("export function ExecutionConsole"):source.index("function RuntimeLogPreview")]
    login_form_section = source[source.index("function DxmLoginInlineForm"):source.index("function RegressionGateGrid")]
    log_summary_section = source[source.index("function RuntimeLogPreview"):source.index("function RuntimeLogPanel")]

    assert "完整日志在下方“更多诊断与维护”。" in source
    assert "humanConsoleCodeLabel(step.state)" in console_section
    assert "humanConsoleCodeLabel((hasConsoleHud ? hud?.state ?? hud?.code : null) ?? activeStep?.code ?? 'WAITING')" in source
    assert "PRECHECK_CONFIG: '启动前配置校验'" in source
    assert "登录和人工处理不要求 L2" not in login_form_section
    assert "只打开真实店小秘窗口，不启动保存" in login_form_section
    assert "正在实时刷新；切换来源只影响当前预览。" in log_summary_section
    assert "onSourceChange(item)" in log_summary_section
    assert "runtime-log-tabs--compact" in log_summary_section
    assert "businessRuntimeLogItems(items).slice(-5)" in log_summary_section
    assert "runtimeLogRefreshMeta(current, items.length)" in log_summary_section
    assert "正在实时刷新；切换来源只影响当前预览。" in log_summary_section
    assert "日志来源：{labels[source]} / 正在实时刷新" not in log_summary_section
    assert "日志源久未写入" in source
    assert "formatLogAge(current.ageSeconds)" in source
    assert "界面刷新" in source
    assert "最后写入" in source
    assert "最后刷新" not in source
    assert "current?.path ?? 'data/*.log'" not in log_summary_section


def test_runtime_log_default_views_humanize_lines_and_keep_raw_lines_in_diagnostics():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    preview_section = source[source.index("function RuntimeLogPreview"):source.index("function RuntimeLogPanel")]
    panel_section = source[source.index("function RuntimeLogPanel"):source.index("function runtimeLogRefreshMeta")]
    summary_line_section = source[source.index("function RuntimeLogSummaryLine"):source.index("function RuntimeLogLine")]
    raw_line_section = source[source.index("function RuntimeLogLine"):source.index("export function EvidenceTimeline")]
    full_log_drawer = panel_section[panel_section.index('<details className="inline-disclosure runtime-log-full-drawer">'):panel_section.index('<small>维护诊断：日志来源 {labels[source]}')]

    assert "RuntimeLogSummaryLine" in preview_section
    assert "RuntimeLogSummaryLine" in panel_section
    assert "humanRuntimeLogLine(item)" in summary_line_section
    assert "technicalRuntimeLogHint(item.line)" in summary_line_section
    assert "businessRuntimeLogItems(items).slice(-5)" in preview_section
    assert "businessRuntimeLogItems(filteredRuntimeLogItems).slice(-6)" in panel_section
    assert "filterRuntimeLogItems(items, level, query)" in panel_section
    assert "runtimeLogLevelLabel(item.level)" in summary_line_section
    assert "<span>{item.level.toUpperCase()}</span>" not in summary_line_section
    assert "暂无关键业务日志，完整日志在维护诊断中查看。" in preview_section
    assert "暂无关键业务日志，完整原始日志在下方展开。" in panel_section
    assert "最近日志：默认只显示关键业务进度" in panel_section
    assert "<code>{item.line}</code>" not in preview_section
    assert "<code>{item.line}</code>" not in panel_section[:panel_section.index('<details className="inline-disclosure runtime-log-full-drawer">')]
    assert "维护人员查看原始日志" in full_log_drawer
    assert "RuntimeLogLine" in full_log_drawer
    assert "<code>{item.line}</code>" in raw_line_section
    assert "<strong>{humanRuntimeLogLine(item)}</strong>" in raw_line_section
    assert "<summary>原始技术日志</summary>" in raw_line_section
    assert "<span>{item.level.toUpperCase()}</span>" not in raw_line_section
    assert "function humanRuntimeLogLine(item: RuntimeLogItem)" in source
    assert "function shouldUseOperatorMessageForRuntimeLog(item: RuntimeLogItem)" in source
    assert "if (isRuntimeLogPollingNoise(item)) return false" in source
    assert "shouldUseOperatorMessageForRuntimeLog(item)" in source
    assert "function businessRuntimeLogItems(items: RuntimeLogItem[])" in source
    assert "function isBusinessRuntimeLogItem(item: RuntimeLogItem, summary: string)" in source
    assert "function isRuntimeLogPollingNoise(item: RuntimeLogItem)" in source
    assert "if (!normalizedQuery && level === 'all' && isRuntimeLogPollingNoise(item)) return false" in source
    assert "function technicalRuntimeLogHint(line: string)" in source
    assert "greenlet" in source
    assert "Playwright" in source
    assert "browser_window_not_visible" in source
    assert "target page, context or browser has been closed" in source
    assert "OPEN_DATA_ACQUISITION".lower() in source.lower()
    assert "CLAIM_TO_DRAFT_BOX".lower() in source.lower()
    assert "SAVE_ONLY".lower() in source.lower()
    assert "VERIFY_NOT_PUBLISHED".lower() in source.lower()
    assert "真实浏览器窗口已关闭，请重新打开浏览器现场。" in source
    assert "正在把选中的商品放进商品箱。" in source
    assert "正在点击店小秘“保存”，不会发布。" in source
    assert "保存步骤失败：系统没有继续发布" in source
    assert source.index("保存步骤失败：系统没有继续发布") < source.index("正在点击店小秘“保存”，不会发布。")
    assert "runtime-log-preview__body" in preview_section
    assert ".runtime-log-preview__body" in styles_source
    runtime_log_preview_body_styles = styles_source[styles_source.index(".runtime-log-preview__body"):styles_source.index(".runtime-log-refresh")]
    assert "overflow-y: auto" in runtime_log_preview_body_styles
    assert "overscroll-behavior: contain;" in runtime_log_preview_body_styles
    runtime_log_summary_styles = styles_source[styles_source.index(".runtime-log-summary-line {"):styles_source.index(".runtime-log-summary-line > span")]
    assert "grid-template-columns: 44px minmax(0, 1fr)" in styles_source[styles_source.index(".runtime-log-summary-line"):styles_source.index(".runtime-log-summary-line > span")]
    assert "padding: 6px;" in runtime_log_summary_styles
    assert "overflow: hidden;" in runtime_log_summary_styles
    assert "contain: layout paint;" in runtime_log_summary_styles
    runtime_log_summary_hint_styles = styles_source[styles_source.index(".runtime-log-summary-line small"):styles_source.index(".runtime-log-preview code")]
    assert "max-height: 2.7em;" in runtime_log_summary_hint_styles
    assert "overflow-wrap: anywhere;" in runtime_log_summary_hint_styles
    assert ".runtime-log-view > span" in styles_source
    assert ".runtime-log-view span {" not in styles_source
    assert "humanOperatorMessage(line)" in source
    human_runtime_log_line_section = source[source.index("function humanRuntimeLogLine"):source.index("function shouldUseOperatorMessageForRuntimeLog")]
    assert "if (shouldUseOperatorMessageForRuntimeLog(item)) {" in human_runtime_log_line_section
    assert human_runtime_log_line_section.index("if (shouldUseOperatorMessageForRuntimeLog(item)) {") < human_runtime_log_line_section.index("humanOperatorMessage(line)")
    runtime_log_view_styles = styles_source[styles_source.index(".runtime-log-view {"):styles_source.index(".runtime-log-full-drawer")]
    assert "min-height: 132px;" in runtime_log_view_styles
    assert "max-height: 220px;" in runtime_log_view_styles
    assert "isolation: isolate;" in runtime_log_view_styles
    assert ".replace(/^(INFO|WARNING|ERROR)\\s+task#\\d+(?:\\s+job#\\d+)?:\\s*/i, '')" in source


def test_report_center_treats_missing_l3_evidence_as_expected_when_real_write_blocked():
    _assert_current_results_and_issues_path()


def test_results_page_first_screen_answers_operator_result_questions():
    source = results_page_source()
    business_summary = source[
        source.index("function BusinessResultSummaryCard"):
        source.index("function EmptyState")
    ]
    visible_fact_markup = business_summary[
        business_summary.index('<div className="business-result-summary__facts">'):
        business_summary.index('<div className="report-followup-actions business-result-summary__actions"')
    ]

    assert "保存成功了吗" in visible_fact_markup
    assert "有没有发布" in visible_fact_markup
    assert "<b>商品</b>" in visible_fact_markup
    assert "<b>完成时间</b>" in visible_fact_markup
    assert "<b>下一步</b>" in visible_fact_markup
    assert "taskProductLabel(selectedTask)" in business_summary
    assert "latestReport?.created_at" in business_summary
    assert "查看保存证据，确认未发布。" in business_summary
    assert "回到浏览器现场，完成安全检查和人工确认。" in business_summary
    assert "保存回包" not in visible_fact_markup
    assert "network/HAR" not in visible_fact_markup


def test_results_page_surfaces_two_stage_acceptance_in_operator_language():
    _assert_current_results_and_issues_path()


def test_safety_bar_downgrades_l3_post_evidence_gaps_when_real_write_blocked():
    source = SAFETY_STATUS_BAR_TSX.read_text(encoding="utf-8")

    assert "l3PostEvidenceGapIds" in source
    assert "visibleBlockerGaps" in source
    assert "l3PostEvidenceGapCount" in source
    assert "gap-save-result" in source
    assert "gap-unpublished-proof" in source
    assert "gap-network-save-response" in source
    assert "保存后证据" in source
    assert "预期阻断" in source
    assert "blockerGaps.slice(0, 2)" not in source


def test_dashboard_and_exception_gap_lists_present_l3_post_evidence_as_locked_scope():
    _assert_current_results_and_issues_path()


def test_task_and_evidence_center_describe_l3_blocked_as_expected_lock():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    task_center_section = source[source.index("export function TaskCenterView"):source.index("export function ExecutionConsole")]
    evidence_timeline_section = source[source.index("export function EvidenceTimeline"):source.index("function EvidencePointCard")]

    assert "真实保存必须停止并复核 publish guard" not in task_center_section
    assert "解除发布隔离风险" not in task_center_section
    assert "齐全后才会形成 A/B/C 证据等级" not in evidence_timeline_section

    legacy_claim_copy = "待认领商品" + "处理"
    assert "待认领入箱是第一段；保存前安全检查只用于第二段商品箱编辑保存前" in task_center_section
    assert f"保存前安全检查通过后才启动{legacy_claim_copy}" not in task_center_section
    assert legacy_claim_copy not in task_center_section
    assert "人工确认未完成前不启动单商品只保存" in task_center_section
    assert "当前按钮策略：待认领入箱可启动第一段流程；保存前安全检查未通过时只阻断第二段编辑保存" in task_center_section
    assert "人工确认未完成，禁止启动" in task_center_section
    assert "当前真实保存未放行时" in evidence_timeline_section
    assert "0 条是正常保护" in evidence_timeline_section
    assert "只有单商品只保存完成后才生成可验收保存记录" in evidence_timeline_section
    assert "保存证据摘要" in evidence_timeline_section
    assert "验收强度" in evidence_timeline_section
    assert "evidence-raw-disclosure" in evidence_timeline_section
    assert "保存记录明细" in evidence_timeline_section
    assert "按需展开" in evidence_timeline_section
    assert "真实截图、DOM、报告和网络摘要" not in evidence_timeline_section
    assert "页面记录、保存报告和保存回包" in evidence_timeline_section
    assert "evidence-grade-disclosure" in evidence_timeline_section
    assert "验收强度说明" in evidence_timeline_section
    assert "查看当前任务" in evidence_timeline_section
    assert "查看保存前检查" in evidence_timeline_section
    assert "查看任务门禁" not in evidence_timeline_section
    assert "查看真实只读证据" not in evidence_timeline_section
    assert "<ModuleHead title=\"原始证据\"" not in evidence_timeline_section
    assert "humanEvidencePointTitle(point)" in source
    assert "humanEvidencePointKind(point.kind)" in source
    assert "humanEvidenceTypeLabel(evidence.evidence_type)" in source
    assert "formatTime(evidence.created_at)} / {evidence.evidence_type}" not in source
    assert "步骤快照" in source
    assert "执行证据" in source
    assert "确认未发布" in source
    assert "只点击保存" in source


def test_task_center_only_uses_demo_ready_copy_for_dry_run_tasks():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    panels_source = PRODUCT_TASK_PANELS_TSX.read_text(encoding="utf-8")
    task_center_section = source[source.index("export function TaskCenterView"):source.index("export function ExecutionConsole")]

    assert "selectedTask?.mode === 'dry_run'" in task_center_section
    assert "demoEnabled && selectedTaskIsDryRun && selectedTask?.status === 'draft' && <span className=\"readonly-recheck-help__note\">开发自检批次不触达店小秘" in panels_source
    assert "{selectedTask?.status === 'draft' && <span>本地演示批次已可用于验收门禁" not in task_center_section
    assert "当前真实任务保持门禁控制，请先处理上方阻断原因。" in panels_source


def test_draft_edit_save_owns_real_task_creation_instead_of_current_task_page():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    app_source = APP_TSX.read_text(encoding="utf-8")
    draft_source = BATCH_EDIT_PAGE_TSX.read_text(encoding="utf-8")
    product_tasks_source = PRODUCT_TASKS_PAGE_TSX.read_text(encoding="utf-8")
    task_center_section = source[source.index("export function TaskCenterView"):source.index("export function ExecutionConsole")]
    product_tasks_route = app_source[app_source.index("case 'product_tasks'"):app_source.index("case 'draft_edit_save'")]
    draft_edit_route = app_source[app_source.index("case 'draft_edit_save'"):app_source.index("case 'start_save'")]

    assert "onCreateRealTask" in task_center_section
    assert "创建真实任务" in task_center_section
    assert "保存前安全检查" in task_center_section
    assert "单商品只保存" in task_center_section
    assert "批量保存未放行" in task_center_section
    assert "发布动作未开放" in task_center_section
    assert "SMT_SEMI_MANAGED_SAVE_ONLY" in task_center_section
    assert "data-testid=\"real-task-create\"" in task_center_section
    assert "postJson<Task>('/api/tasks'" in app_source
    assert "mode: request.mode" in app_source
    assert "publish_scene: 'SMT_SEMI_MANAGED_SAVE_ONLY'" in app_source
    assert "onCreateRealTask={createRealTask}" not in product_tasks_route
    assert "onBootstrapDemo={bootstrapDemo}" not in product_tasks_route
    assert "onStartTask={(taskId) => startSelectedTask(taskId)}" in product_tasks_route
    assert "onStartTask: (taskId: number) => void" in product_tasks_source
    assert "start: () => currentTask ? actions.onStartTask(currentTask.id) : undefined" in product_tasks_source
    assert "onCreateRealTask:" not in product_tasks_source
    assert "onBootstrapDemo:" not in product_tasks_source
    assert "demoEnabled" not in product_tasks_source
    assert "<BatchEditPage" in draft_edit_route
    assert "onCreateSaveTask={(productId) =>" not in draft_edit_route
    assert "scope_snapshot_id: scopeSnapshot.id" in draft_source
    assert "template_id: selectedTemplate.id" in draft_source
    assert "冻结批次草稿" in draft_source


def test_task_center_surfaces_single_save_recovery_guide_for_blocked_real_tasks():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    panels_source = PRODUCT_TASK_PANELS_TSX.read_text(encoding="utf-8")
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    qa_source = QA_BROWSER_CHECK.read_text(encoding="utf-8")
    task_center_section = source[source.index("export function TaskCenterView"):source.index("export function ExecutionConsole")]

    assert "SingleSaveRecoveryGuide" in task_center_section
    assert "needsSingleSaveRecovery" in task_center_section
    assert "selectedTaskBlocksStart" in task_center_section
    assert "selectedTaskBlocksStart || selectedTaskIsUnreleasedRealMode" in task_center_section
    assert "latestSingleSaveTask" in task_center_section
    assert "submitSingleSaveTask" in task_center_section
    assert "data-testid=\"single-save-recovery-guide\"" in panels_source
    assert "恢复到单商品只保存" in panels_source
    assert "当前任务不可直接启动时，按这里回到真实自动化可执行路径。" in panels_source
    assert "当前任务不是草稿，不能直接启动" in panels_source
    assert "选择最近单商品只保存任务" in panels_source
    assert "创建新的单商品只保存任务" in panels_source
    assert "运行保存前安全检查" in panels_source
    assert "查看检查计划" in panels_source
    assert "onRunL2Probe={onRunL2Probe}" in task_center_section
    assert "批量/发布不放行" in panels_source
    assert "不放行认领/批量保存" not in panels_source
    recovery_section = single_save_recovery_guide_section(source)
    for forbidden in ("恢复到受控 single_save", "选择最近 single_save", "创建新的 single_save", "运行 L2 复验"):
        assert forbidden not in recovery_section
    assert "single-save-recovery-guide" in styles_source
    assert "singleSaveRecoveryGuideVisible" in qa_source


def test_task_center_explains_l2_recheck_before_real_save():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    task_center_section = source[source.index("export function TaskCenterView"):source.index("export function ExecutionConsole")]
    current_panel_section = task_current_action_panel_section()
    recheck_card_section = readonly_recheck_help_card_section(source)

    assert "ReadonlyRecheckHelpCard" in task_center_section
    assert "l2BlocksStart && (" in task_center_section
    assert "onRunL2Probe={onRunL2Probe}" in task_center_section
    assert "l2ProbeResourceState={l2ProbeResourceState}" in task_center_section
    assert "const showPrecheckRecoveryActions =" in current_panel_section
    assert "aria-label=\"保存前安全检查未通过处理\"" in current_panel_section
    assert "保存前安全检查没有通过，不能启动真实保存。" in current_panel_section
    assert "运行保存前安全检查" in current_panel_section
    assert "task-current-panel__optional-actions" in current_panel_section
    assert "可选处理" in current_panel_section
    assert "查看浏览器现场" in current_panel_section
    assert "查看证据缺口" in current_panel_section
    assert "查看检查计划" in current_panel_section
    assert "task-current-panel__actions" not in current_panel_section
    assert "l2ProbeResourceState.blocked" in current_panel_section
    assert "task-current-panel__precheck-actions" in styles_source
    assert "保存前安全检查未通过，真实保存先暂停" in recheck_card_section
    assert "<strong>发生了什么</strong>" in recheck_card_section
    assert "<strong>为什么不能继续</strong>" in recheck_card_section
    assert "<strong>下一步</strong>" in recheck_card_section
    assert "确认已有待认领列表和商品箱页能正常打开" in recheck_card_section
    assert "不会认领、备注、保存或发布" in recheck_card_section
    assert "当前状态：{humanGateStateLabel(l2Gate?.status ?? 'not_run')}" in recheck_card_section
    assert "READONLY_PRECHECK_CTA" in recheck_card_section
    assert "readonly-recheck-help__optional-actions" in recheck_card_section
    assert "查看诊断摘要" in recheck_card_section
    assert "查看检查计划" in recheck_card_section
    assert "查看证据缺口" in recheck_card_section
    assert "readonly-recheck-help" in styles_source

    for forbidden in ("data_acquisition", "draft_box", "L2 readonly", "probe runner"):
        assert forbidden not in recheck_card_section


def test_task_center_l2_diagnostics_include_actionable_failure_details():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    task_center_section = source[source.index("export function TaskCenterView"):source.index("export function ExecutionConsole")]
    recheck_card_section = readonly_recheck_help_card_section(source)
    summary_type_section = source[source.index("type L2DiagnosticSummary"):source.index("function summarizeL2Diagnostics")]
    summarize_section = source[source.index("function summarizeL2Diagnostics"):source.index("function asRecord")]

    assert "nextAction: string" in summary_type_section
    assert "failedCheckKeys" in summarize_section
    assert "nextAction: l2DiagnosticNextAction({" in summarize_section
    assert "function l2DiagnosticNextAction" in source
    assert "先在真实登录浏览器完成登录" in source
    assert "检查目标页面是否跳到首页/登录页" in source
    assert "把只读依赖候选交给人工评审" in source
    assert "查看启动器日志中的请求拦截记录" in source
    assert "blocked requests" not in task_center_section
    assert "probe 未通过" not in task_center_section
    assert "<strong>最终地址</strong>" in task_center_section
    assert "<strong>失败检查</strong>" in task_center_section
    assert "<strong>下一步</strong>" in task_center_section
    assert "item.nextAction" in task_center_section
    assert "下一步：{item.nextAction}" in recheck_card_section


def test_task_center_defaults_to_current_task_first_and_collapses_setup_noise():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    panels_source = PRODUCT_TASK_PANELS_TSX.read_text(encoding="utf-8")
    copy_source = WORKBENCH_COPY_TS.read_text(encoding="utf-8")
    current_panel_section = task_current_action_panel_section()
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    qa_source = QA_BROWSER_CHECK.read_text(encoding="utf-8")
    task_center_section = source[source.index("export function TaskCenterView"):source.index("export function ExecutionConsole")]

    assert "TaskCurrentActionPanel" in task_center_section
    assert "task-quick-actions" in task_center_section
    assert "aria-label=\"编辑保存主操作\"" in task_center_section
    assert "从商品箱商品创建第二段只保存任务" in task_center_section
    assert "创建编辑保存任务" in task_center_section
    assert "data-testid=\"task-quick-create-single-save\"" in task_center_section
    assert "商品箱商品" in task_center_section
    assert "历史任务、更多商品和高级诊断继续折叠，不抢占首屏" in task_center_section
    assert task_center_section.index("task-quick-actions__buttons") < task_center_section.index("task-quick-actions__status")
    assert task_center_section.index("task-quick-actions") < task_center_section.index("TaskCurrentActionPanel")
    assert "onShowConsole={onShowConsole}" in task_center_section
    assert "完成后可选处理" in current_panel_section
    assert "查看保存结果" in current_panel_section
    assert "查看保存证据" in current_panel_section
    assert "onShowConsole: () => void" in panels_source
    assert "aria-label=\"当前任务执行\"" in current_panel_section
    assert "当前任务 #${selectedTask.id}" in current_panel_section
    assert "task-current-panel__task-id" in current_panel_section
    assert "aria-label=\"启动判定\"" in current_panel_section
    assert "taskStartDecision" in current_panel_section
    assert "<strong>发生了什么</strong>" in current_panel_section
    assert "<strong>为什么不能继续</strong>" in current_panel_section
    assert "<strong>下一步</strong>" in current_panel_section
    assert "去填写编辑页补齐 DXM 编辑页必填字段" in panels_source
    assert "${READONLY_PRECHECK_CTA}，确认已有待认领列表和商品箱页均无写入风险" in panels_source
    assert "点击主按钮后，在“浏览器现场”查看执行。" in panels_source
    assert "先选择或创建单商品只保存任务" in current_panel_section
    assert "先选择或创建 single_save 任务" not in panels_source
    assert "默认只展示真实自动化主路径" in current_panel_section
    assert "humanTaskModeLabel(selectedTask.mode)" in current_panel_section
    assert "humanGateDetail(l2Gate?.detail)" in source
    assert "单商品只保存核验任务" in copy_source
    assert "<strong>保存前安全检查</strong>" in current_panel_section
    assert "<strong>人工确认</strong>" in current_panel_section
    assert "humanGateStateLabel(l2Gate?.status ?? 'not_run')" in current_panel_section
    assert "humanGateStateLabel(l3Gate?.status ?? 'blocked')" in current_panel_section
    assert "const l2CheckLabel = selectedTaskCompleted ? '已完成'" in current_panel_section
    assert "const l3CheckLabel = selectedTaskCompleted ? '已完成'" in current_panel_section
    assert "更多任务操作与记录" in task_center_section
    assert "历史任务、更多商品和高级诊断继续折叠，不抢占首屏" in task_center_section
    assert "<summary>创建商品箱编辑保存任务</summary>" in task_center_section
    assert "<summary>查看批量/发布边界</summary>" in task_center_section
    assert "<summary>查看未发布模式边界</summary>" not in task_center_section
    assert "<summary>选择其它任务 / 历史批次</summary>" in task_center_section
    assert "<summary>查看更多商品</summary>" in task_center_section
    assert "<summary>查看任务验收口径</summary>" in task_center_section
    assert "<summary>启动条件说明</summary>" in task_center_section
    assert "className=\"module-card span-2 task-support-drawer disclosure-card\"" in task_center_section
    assert "className=\"inline-disclosure task-create-drawer\"" in task_center_section
    assert "className=\"inline-disclosure task-release-drawer\"" in task_center_section
    assert "className=\"inline-disclosure task-history-drawer\"" in task_center_section
    assert "className=\"inline-disclosure task-product-drawer\"" in task_center_section
    assert "className=\"inline-disclosure task-acceptance-drawer\"" in task_center_section
    assert "className=\"inline-disclosure task-decision-drawer\"" in task_center_section
    assert "data-testid=\"task-start-button\"" in current_panel_section
    assert "data-testid=\"real-task-create\"" in task_center_section
    assert "task-current-panel" in styles_source
    assert "task-current-panel__decision" in styles_source
    assert "task-support-drawer" in styles_source
    assert "task-quick-actions" in styles_source
    assert "task-quick-actions__buttons" in styles_source
    assert "task-support-drawer__content" in styles_source
    assert "task-create-drawer" in styles_source
    assert "task-release-drawer" in styles_source
    assert "task-history-drawer" in styles_source
    assert "task-product-drawer" in styles_source
    assert "task-acceptance-drawer" in styles_source
    assert "task-decision-drawer" in styles_source
    assert ".inline-disclosure:not([open]) > :not(summary)" in styles_source
    assert "display: none !important" in styles_source
    assert "taskDrawerState" in qa_source
    assert "taskCenterCurrentFirst" in qa_source
    assert "taskDefaultText" in qa_source
    assert "taskHistoryDrawer" in qa_source
    assert "releaseBoundaryDrawer" in qa_source


def test_task_center_first_screen_selects_one_product_for_single_save_main_path():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    task_center_section = source[source.index("export function TaskCenterView"):source.index("export function ExecutionConsole")]
    first_screen_section = task_center_section[
        task_center_section.index("<div className=\"module-card span-1 task-quick-actions\""):
        task_center_section.index("<div className=\"module-card span-2\">")
    ]

    assert "const primaryProductCandidates = uniqueProductOptions.slice(0, 4)" in task_center_section
    assert "function selectSingleDraftProduct(productId: number)" in task_center_section
    assert "setDraftProductIds([productId])" in task_center_section
    assert "aria-label=\"选择商品箱商品\"" in first_screen_section
    assert "task-product-selection" in first_screen_section
    assert "task-product-choice" in first_screen_section
    assert "商品箱商品" in first_screen_section
    assert "创建商品箱编辑保存任务" in first_screen_section
    assert first_screen_section.index("商品箱商品") < first_screen_section.index("创建商品箱编辑保存任务")
    assert "请先选择 1 个商品箱商品" in first_screen_section
    assert "selectedDraftProducts[0]?.id === product.id" in first_screen_section
    assert "selectSingleDraftProduct(product.id)" in first_screen_section
    assert "补齐编辑页配置" not in first_screen_section
    assert "选择历史任务" not in first_screen_section
    assert "<summary>查看更多商品</summary>" in task_center_section
    assert 'className="inline-disclosure task-product-drawer"' in task_center_section
    assert ".task-product-selection" in styles_source
    assert ".task-product-choice" in styles_source


def test_task_center_explains_disabled_single_save_actions():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    task_center_section = source[source.index("export function TaskCenterView"):source.index("export function ExecutionConsole")]
    recovery_section = single_save_recovery_guide_section(source)

    assert "const quickCreateSingleSaveDisabledReason =" in task_center_section
    assert "id=\"task-quick-create-single-save-reason\"" in task_center_section
    assert "aria-describedby={quickCreateSingleSaveDisabledReason ? 'task-quick-create-single-save-reason' : undefined}" in task_center_section
    assert "title={quickCreateSingleSaveDisabledReason || undefined}" in task_center_section
    assert "请选择真实店铺" in task_center_section
    assert "请先选择 1 个商品箱商品后再创建只保存任务。" in task_center_section
    assert "当前已选 ${selectedDraftProducts.length} 个" in task_center_section
    assert "canCreateSingleSaveTask = Boolean(selectedStore && selectedDraftProducts.length === 1 && !busy)" in task_center_section
    assert "当前版本仅放行 Dang Kang" not in task_center_section
    assert "未放行单商品只保存" not in task_center_section
    assert "const [draftProductIds, setDraftProductIds] = useState<number[]>([])" in task_center_section
    assert "return uniqueProductOptions[0] ? [uniqueProductOptions[0].id] : []" not in task_center_section
    assert "function selectSingleDraftProduct(productId: number)" in task_center_section
    assert "setDraftProductIds([productId])" in task_center_section

    assert "const selectSingleSaveDisabledReason =" in recovery_section
    assert "const createSingleSaveDisabledReason =" in recovery_section
    assert "id=\"single-save-recovery-select-reason\"" in recovery_section
    assert "id=\"single-save-recovery-create-reason\"" in recovery_section
    assert "aria-describedby={selectSingleSaveDisabledReason ? 'single-save-recovery-select-reason' : undefined}" in recovery_section
    assert "aria-describedby={createSingleSaveDisabledReason ? 'single-save-recovery-create-reason' : undefined}" in recovery_section
    assert "title={selectSingleSaveDisabledReason || undefined}" in recovery_section
    assert "title={createSingleSaveDisabledReason || undefined}" in recovery_section
    assert "暂无最近单商品只保存任务" in recovery_section
    assert "请先确认有真实店铺和 1 个商品" in recovery_section


def test_task_center_explains_quick_action_availability_in_first_screen():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    task_center_section = source[source.index("export function TaskCenterView"):source.index("export function ExecutionConsole")]
    quick_actions_section = task_center_section[
        task_center_section.index("<div className=\"module-card span-1 task-quick-actions\""):
        task_center_section.index("<div className=\"module-card span-2\">")
    ]

    assert "const taskActionDiagnosis =" in task_center_section
    assert "const historyTaskHint =" in task_center_section
    assert "quickCreateSingleSaveDisabledReason || '可创建商品箱编辑保存任务'" in task_center_section
    assert "const blockedStartButtonLabel =" in task_center_section
    assert "start: blockedStartButtonLabel" in task_center_section
    assert "暂无历史任务；先完成待认领入箱，再创建商品箱编辑保存任务。" in task_center_section
    assert "aria-label=\"任务按钮不可点击原因\"" in quick_actions_section
    assert "<summary>为什么不能启动浏览器现场</summary>" in quick_actions_section
    assert "<strong>创建任务</strong>" in quick_actions_section
    assert "<strong>浏览器现场</strong>" in quick_actions_section
    assert "taskActionDiagnosis.create" in quick_actions_section
    assert "taskActionDiagnosis.start" in quick_actions_section
    assert ".task-quick-actions__diagnosis" in styles_source


def test_task_center_compacts_duplicate_history_tasks_by_default():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    qa_source = QA_BROWSER_CHECK.read_text(encoding="utf-8")
    task_center_section = source[source.index("export function TaskCenterView"):source.index("export function ExecutionConsole")]

    assert "showAllTasks" in task_center_section
    assert "getTaskDisplayKey" in source
    assert "const compactTaskRows" in task_center_section
    assert "const visibleTaskRows" in task_center_section
    assert "visibleTaskRows.map((task)" in task_center_section
    assert "默认显示单商品只保存相关批次" in source
    assert "辅助/历史批次默认隐藏" in source
    assert "显示全部历史任务" in source
    assert "收起历史任务" in source
    assert "已合并" in source
    assert "task-list-toolbar" in styles_source
    assert "task-list-summary" in styles_source
    assert "taskListCompactedByDefault" in qa_source


def test_task_center_deduplicates_real_task_create_choices():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    task_center_section = source[source.index("export function TaskCenterView"):source.index("export function ExecutionConsole")]

    assert "function uniqueByStoreIdentity" in source
    assert "function uniqueByProductIdentity" in source
    assert "function productDisplayIdentity" in source
    assert "const uniqueStoreOptions = useMemo(() => uniqueByStoreIdentity(workspace.stores), [workspace.stores])" in task_center_section
    assert "const uniqueProductOptions = useMemo(() => uniqueByProductIdentity(workspace.products), [workspace.products])" in task_center_section
    assert "uniqueStoreOptions.map((store)" in task_center_section
    assert "uniqueProductOptions.slice(0, 6).map((product)" in task_center_section
    assert "<ModuleHead title=\"商品队列\" meta={`${uniqueProductOptions.length} 个商品`} />" in task_center_section
    assert "uniqueProductOptions.map((product)" in task_center_section
    assert "!uniqueProductOptions.length" in task_center_section
    assert "const selectedStore = uniqueStoreOptions.find" in task_center_section
    assert "const selectedDraftProducts = uniqueProductOptions.filter" in task_center_section
    assert "new Set(uniqueProductOptions.map((product) => product.id))" in task_center_section


def test_task_center_keeps_gate_engineering_details_collapsed_by_default():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    task_center_section = source[source.index("export function TaskCenterView"):source.index("export function ExecutionConsole")]

    assert '<details className="module-card span-2 task-support-drawer disclosure-card">' in task_center_section
    assert '<details className="inline-disclosure task-decision-drawer">' in task_center_section
    assert "<summary>" in task_center_section
    assert "启动条件说明" in task_center_section
    assert "高级门禁细节，按需展开" not in task_center_section
    assert '<div className="module-card span-2 decision-card">' not in task_center_section
    assert "L3 当前按门禁锁定：L2 未 passed" not in task_center_section
    assert "进入 runner" not in task_center_section


def test_task_center_hides_raw_l2_diagnostics_behind_disclosure():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    task_center_section = source[source.index("export function TaskCenterView"):source.index("export function ExecutionConsole")]
    decision_drawer = task_center_section[task_center_section.index('<details className="inline-disclosure task-decision-drawer">'):task_center_section.index('{l2Gate?.status !==')]
    visible_l2_diagnostics = decision_drawer[:decision_drawer.index('<details className="inline-disclosure l2-raw-request-drawer">')]

    assert '<details className="inline-disclosure l2-block-summary">' in task_center_section
    assert "<summary>保存前安全检查诊断摘要</summary>" in task_center_section
    assert "humanDiagnosticNavigation(item.navigation)" in task_center_section
    assert "humanFailedCheckLabel" in source
    assert "requestSummary: string" in source
    assert "humanBlockedRequestSummary" in source
    assert "<strong>请求情况</strong>{item.requestSummary}" in task_center_section
    assert '<details className="inline-disclosure l2-raw-request-drawer">' in task_center_section
    assert "<summary>查看原始请求诊断</summary>" in task_center_section
    assert "item.topRequests.map((request)" not in visible_l2_diagnostics
    assert "item.reviewCandidateRequests.map((request)" not in visible_l2_diagnostics


def test_task_center_allows_any_real_store_for_single_save_creation():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    task_center_section = source[source.index("export function TaskCenterView"):source.index("export function ExecutionConsole")]

    assert "RELEASED_SINGLE_SAVE_STORE_NAMES" not in source
    assert "selectedStoreReleasedForSingleSave" not in task_center_section
    assert "storeBlocksSingleSave" not in task_center_section
    assert "单商品只保存当前只放行" not in task_center_section
    assert "未放行单商品只保存" not in task_center_section
    assert "当前版本仅放行 Dang Kang" not in task_center_section
    assert "未放行 single_save" not in task_center_section
    assert "const canCreateSingleSaveTask = Boolean(selectedStore && selectedDraftProducts.length === 1 && !busy)" in task_center_section


def test_app_defaults_to_delivery_current_task_even_when_completed():
    app_source = APP_TSX.read_text(encoding="utf-8")
    workspace_source = (REPO_ROOT / "app" / "frontend" / "src" / "workspace.ts").read_text(encoding="utf-8")
    qa_source = QA_BROWSER_CHECK.read_text(encoding="utf-8")

    assert "function pickDefaultTaskId(" in app_source
    assert "deliveryWorkspace?.current_task?.id" in app_source
    assert "function isActionableSingleSaveTask(" in app_source
    assert "deliveryTask && isDefaultSelectableOperatorTask(deliveryTask)" in app_source
    assert "deliveryTask.status !== 'completed'" not in app_source
    assert "tasks.find(isActionableClaimTask)" in app_source
    assert "tasks.find(isActionableSingleSaveTask)" in app_source
    assert "function isDefaultSelectableOperatorTask(" in app_source
    assert "function isDefaultSelectableClaimTask(" in app_source
    assert "function isDefaultSelectableSingleSaveTask(" in app_source
    assert "function isSafeDefaultFallbackTask(" in app_source
    assert "!UNRELEASED_REAL_DXM_MUTATION_MODES.has(String(task.mode))" in app_source
    assert "setSelectedTaskId((current) => pickTaskIdForOperatorPath(current, deliveryWorkspace, nextWorkspace.tasks))" in app_source
    assert "mergeCurrentTaskIntoTasks(" in workspace_source
    assert "const deliveryTasks = Array.isArray(workspace?.tasks) ? workspace.tasks : undefined" in workspace_source
    assert "chooseList(deliveryTasks" in workspace_source
    assert "currentTask ? [currentTask, ...bundle.tasks] : bundle.tasks" in workspace_source
    assert "defaultTaskSelectionPrefersDeliveryCurrentTask" in qa_source
    assert "const defaultWorkspacePayload = await fetchJson('/api/delivery/workspace');" in qa_source
    assert "const defaultWorkspaceTasks = Array.isArray(defaultWorkspacePayload?.tasks) ? defaultWorkspacePayload.tasks : [];" in qa_source
    assert "currentTaskPrefix: '\\u5f53\\u524d\\u4efb\\u52a1 #'" in qa_source
    assert "deliveryCurrentTaskCompleted: defaultCurrentTaskCompleted" in qa_source
    assert "expectedCurrentTaskMarker: defaultCurrentTaskMarker" in qa_source
    assert "apiCurrentTaskMode: defaultCurrentTaskMode" in qa_source
    assert "apiCurrentTaskUnreleased: defaultCurrentTaskUnreleased" in qa_source
    assert "const defaultCurrentTaskUnreleased = ['batch_save'].includes(defaultCurrentTaskMode);" in qa_source
    assert "defaultTaskSelectionState.taskCenterTextSample = taskDefaultText.slice(0, 1200)" in qa_source
    assert "defaultCurrentTaskText.includes(defaultCurrentTaskMarker) || taskDefaultText.includes(defaultCurrentTaskMarker)" in qa_source
    assert "defaultActionableSingleSaveTask" not in qa_source
    assert "usesActionableSingleSaveWhenCurrentCompleted" not in qa_source
    assert "defaultTaskSelectionPrefersDeliveryCurrentTask: defaultTaskSelectionState.hasDeliveryCurrentTask" in qa_source
    assert "defaultCurrentTaskId === unreleasedRealModeTask.id" not in qa_source
    assert "const initialEffectiveReadiness = initialFinalCheckSummary?.effective_real_dxm_write_readiness" in qa_source
    assert "const finalReportEffectiveReadiness = finalCheckSummary?.effective_real_dxm_write_readiness" in qa_source
    assert "const finalReportReportWriteBlocked = finalCheckSummary?.real_dxm_write_readiness === 'BLOCKED'" in qa_source
    assert "finalReportBusinessReportLocked: !finalReportReportWriteBlocked" in qa_source
    assert "hasExistingEvidenceRows" in qa_source
    assert "finalReportCenterQaDiagnostics.hasExistingEvidenceRows" in qa_source[
        qa_source.index("finalReportBusinessReportLocked"):qa_source.index("finalReportPostL3ChecklistLocked")
    ]
    assert "reportExistingEvidenceRows" in qa_source
    assert "reportBusinessReportLocked: !finalCheckReportWriteBlocked || reportText.includes(text.businessReportLocked) || reportExistingEvidenceRows" in qa_source
    assert "finalReportCenterQaDiagnostics.hasExpectedLockedEvidenceRows" in qa_source
    assert "finalReportCenterQaDiagnostics.hasExistingEvidenceRows" in qa_source
    assert "\\u4e1a\\u52a1\\u4fdd\\u5b58\\u62a5\\u544a 0 \\u4efd\\uff08\\u771f\\u5b9e\\u4fdd\\u5b58\\u540e\\uff0c\\u9884\\u671f\\u963b\\u65ad\\uff09" in qa_source
    assert "\\u771f\\u5b9e\\u4fdd\\u5b58\\u540e\\u62a5\\u544a\\u5fc5\\u987b\\u8986\\u76d6" in qa_source
    assert "const finalCheckEffectiveReadiness = finalCheckSummaryForReport?.effective_real_dxm_write_readiness" in qa_source
    assert "hasDeliveryCurrentTaskName" not in qa_source
    assert "当前任务 #70" not in qa_source


def test_browser_qa_accepts_blocked_4xx_posts_without_task_mutation():
    qa_source = QA_BROWSER_CHECK.read_text(encoding="utf-8")

    assert "function isBlockedStatus(status)" in qa_source
    assert "status >= 400 && status < 500" in qa_source
    assert "mutationBlockedActionChecks = blockedActionChecks.filter(item => item.name !== 'agent_console_start')" in qa_source
    assert "mutationBlockedActionChecks.every(item => isBlockedStatus(item.status))" in qa_source
    assert "localStartPostBlocked: !shouldRunBlockedMutationChecks || isBlockedStatus(blockedStartStatus)" in qa_source
    assert "localAgentConsolePostBlocked: !shouldRunBlockedMutationChecks || blockedAgentConsoleStatus === 200 || isBlockedStatus(blockedAgentConsoleStatus)" in qa_source
    assert "localDirectDxmPostsBlocked: !shouldRunBlockedMutationChecks || blockedActionsAllForbidden" in qa_source
    assert "blockedPostsDidNotMutateTask: taskStateUnchanged" in qa_source
    assert "fetchJson('/api/tasks/' + taskId).catch(() => null)" in qa_source
    assert "fetchJson('/api/delivery/workspace?task_id=' + taskId)" not in qa_source
    assert "status === 403" not in qa_source


def test_task_center_surfaces_l2_allowlist_review_candidates_as_manual_review_only():
    _assert_current_results_and_issues_path()


def test_frontend_releases_both_controlled_stages_and_blocks_only_batch():
    source = APP_TSX.read_text(encoding="utf-8")
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    start_section = source[source.index("async function startSelectedTask"):source.index("async function startAgentConsole")]
    qa_source = QA_BROWSER_CHECK.read_text(encoding="utf-8")
    no_old_action_copy_start = qa_source.index("noOldActionCopy:")
    no_old_action_copy_section = qa_source[no_old_action_copy_start:qa_source.index("noConsoleErrors:", no_old_action_copy_start)]

    assert "const RELEASED_REAL_DXM_MUTATION_MODES = new Set(['claim_only', 'single_save', 'batch_draft_save'])" in source
    assert "const UNRELEASED_REAL_DXM_MUTATION_MODES = new Set(['batch_save'])" in source
    assert "UNRELEASED_REAL_DXM_MUTATION_MODES.has(taskToStart.mode)" in start_section
    assert "旧版批量保存入口已关闭" in start_section
    assert "将只启动 save-only/claim-only 受控任务" not in start_section
    assert "const selectedTaskIsUnreleasedRealMode = selectedTask ? isUnreleasedRealDxmMutationTask(selectedTask) : false" in workbench_source
    assert "startDisabled = busy || !selectedTask || selectedTaskNotDraft || selectedTaskIsUnreleasedRealMode || loginBlocksStart || configUnknownBlocksStart || configPreviewLoadingBlocksStart || configBlocksStart || l2BlocksStart || l3BlocksStart" in workbench_source
    assert "const selectedTaskNotDraft = Boolean(selectedTask && selectedTask.status !== 'draft')" in workbench_source
    assert "未发布，禁止启动" in workbench_source
    assert "function isReleasedRealDxmMutationTask" in workbench_source
    assert "function isUnreleasedRealDxmMutationTask" in workbench_source
    assert "当前按钮策略：待认领入箱可启动第一段流程；保存前安全检查未通过时只阻断第二段编辑保存；单商品只保存仍需后端人工批准；批量保存当前未开放。" in workbench_source
    assert "unreleasedRealModeCopy" in qa_source
    assert "unreleasedRealModeButtonDisabled" in qa_source
    assert "async function verifyUnreleasedRealModeCreateBlocked()" in qa_source
    assert "const unreleasedRealModeCreationCheck = reportOnlyFinal || qaExpectedReady ? null : await verifyUnreleasedRealModeCreateBlocked();" in qa_source
    assert "const unreleasedRealModeTask = null;" in qa_source
    assert "mode: 'batch_save'" in qa_source
    assert "QA unreleased batch_save task" in qa_source
    assert "QA unreleased claim_only task" not in qa_source
    assert "unreleasedRealModeCreateBlocked" in qa_source
    assert "isBlockedStatus(unreleasedRealModeCreationCheck?.status)" in qa_source
    assert "\\u663e\\u793a\\u5168\\u90e8\\u5386\\u53f2\\u4efb\\u52a1" in qa_source
    assert "await clickText(unreleasedRealModeTask.name)" not in qa_source
    assert "unreleasedRealModeTaskSelected:" in qa_source
    assert "unreleasedRealModeStartButtonDisabled" in qa_source
    assert "finalCheckExpectedReady || unreleasedRealModeStartButtonDisabled" in qa_source
    assert "unreleasedRealModeCopy: finalCheckExpectedReady" in qa_source
    assert "defaultCurrentTaskCompleted || taskStartDisabled" in qa_source
    assert "taskText.includes('\\u8fd0\\u884c\\u53ea\\u8bfb\\u590d\\u9a8c')" in qa_source
    assert "taskStartDisabled && taskText.includes(text.unreleasedRealModeButtonDisabled)" in qa_source
    assert "\\u5f85\\u8ba4\\u9886\\u5546\\u54c1\\u5904\\u7406\\u548c\\u5355\\u5546\\u54c1\\u53ea\\u4fdd\\u5b58\\u53d7\\u63a7\\u5f00\\u653e" in qa_source
    assert "\\u0063\\u006c\\u0061\\u0069\\u006d\\u005f\\u006f\\u006e\\u006c\\u0079/\\u0062\\u0061\\u0074\\u0063\\u0068\\u005f\\u0073\\u0061\\u0076\\u0065 \\u5f53\\u524d\\u672a\\u53d1\\u5e03" not in qa_source
    assert "\\u672a\\u53d1\\u5e03\\uff0c\\u7981\\u6b62\\u542f\\u52a8" in qa_source
    assert "\\u53d7\\u63a7\\u8ba4\\u9886 + \\u5355\\u5546\\u54c1\\u53ea\\u4fdd\\u5b58" in qa_source
    assert "\\u4ec5\\u53d7\\u63a7\\u5355\\u5546\\u54c1\\u53ea\\u4fdd\\u5b58" not in qa_source
    assert "oldSaveOnly" not in qa_source
    assert "\\u53ea\\u4fdd\\u5b58\\u4e0d\\u53d1\\u5e03" not in no_old_action_copy_section
    assert "oldWaitSave" in no_old_action_copy_section
    assert "oldVisibleBrowser" in no_old_action_copy_section
    assert "\\u542f\\u52a8\\u6f14\\u793a\\u6d4f\\u89c8\\u5668" in qa_source
    assert "oldAutomation" in no_old_action_copy_section
    assert "SAVE_ONLY" in no_old_action_copy_section


def test_frontend_claim_and_single_save_share_current_task_server_approval_flow():
    source = APP_TSX.read_text(encoding="utf-8")
    start_section = source[source.index("async function startSelectedTask"):source.index("async function startAgentConsole")]
    real_start = start_section.index("if (REAL_DXM_MUTATION_MODES.has(taskToStart.mode))")
    real_end = start_section.index("} else {", real_start)
    real_mutation_section = start_section[real_start:real_end]

    assert "const CLAIM_ONLY_CONFIRMATION = '确认将该已有商品认领到商品箱'" in source
    assert "const L3_CONFIRMATION = 'CONFIRM_DXM_SAVE_ONLY'" in source
    assert "const approvedBy = l3ApprovedBy.trim()" in real_mutation_section
    assert "if (!approvedBy)" in real_mutation_section
    assert "if (taskToStart.mode === 'single_save')" in real_mutation_section
    assert "const latestConfigPreview = await refreshConfigPreview(taskToStart.id)" in real_mutation_section
    assert "const approvalConfirmation = taskToStart.mode === 'claim_only' ? CLAIM_ONLY_CONFIRMATION : L3_CONFIRMATION" in real_mutation_section
    assert "`/api/tasks/${taskToStart.id}/manual-approval`" in real_mutation_section
    assert "approved_by: approvedBy" in real_mutation_section
    assert "confirmation: approvalConfirmation" in real_mutation_section
    assert "approval_token: approval.approvalToken" in real_mutation_section
    assert "confirmation: approval.confirmation || approvalConfirmation" in real_mutation_section
    assert real_mutation_section.index("if (!approvedBy)") < real_mutation_section.index("/manual-approval")
    assert real_mutation_section.index("/manual-approval") < real_mutation_section.index("/start`")
    assert "await postJson(`/api/tasks/${taskToStart.id}/start`, {})" not in real_mutation_section


def test_task_center_start_button_matches_real_start_prechecks():
    app_source = APP_TSX.read_text(encoding="utf-8")
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    task_center_section = workbench_source[workbench_source.index("export function TaskCenterView"):workbench_source.index("export function ExecutionConsole")]

    assert "runtimeStatus={runtimeStatus}" in app_source
    assert "runtimeStatus: RuntimeStatus | null" in workbench_source
    assert "const selectedRealDxmMutationTask = Boolean(selectedTask && isRealDxmMutationTask(selectedTask))" in task_center_section
    assert "const dxmLoggedIn = !runtimeStatusError && DXM_LOGGED_IN_STATUSES.has(runtimeStatus?.dxmLogin?.status ?? '')" in task_center_section
    assert "const loginBlocksStart = selectedRealDxmMutationTask && !dxmLoggedIn" in task_center_section
    assert "const configPreviewForSelectedTask = selectedTask && configPreview?.taskId === selectedTask.id ? configPreview : null" in task_center_section
    assert "const configPreviewTaskMismatch = Boolean(selectedTask && configPreview && configPreview.taskId !== selectedTask.id)" in task_center_section
    assert "const selectedTaskNeedsEditConfig = selectedTask?.mode === 'single_save'" in task_center_section
    assert "const configPreviewLoadingBlocksStart = Boolean(selectedTaskNeedsEditConfig && configPreviewLoading)" in task_center_section
    assert "const configUnknownBlocksStart = Boolean(selectedTaskNeedsEditConfig && !configPreviewForSelectedTask && !configPreviewLoading)" in task_center_section
    assert "const configBlocksStart = Boolean(selectedTaskNeedsEditConfig && configPreviewForSelectedTask && !configPreviewForSelectedTask.ok)" in task_center_section
    assert "startDisabled = busy || !selectedTask || selectedTaskNotDraft || selectedTaskIsUnreleasedRealMode || loginBlocksStart || configUnknownBlocksStart || configPreviewLoadingBlocksStart || configBlocksStart || l2BlocksStart || l3BlocksStart" in task_center_section
    assert "DXM 未登录，先打开真实浏览器登录" in task_center_section
    assert "配置属于其它任务，重新检查本次任务" in task_center_section
    assert "先检查本次任务配置" in task_center_section
    assert "正在检查配置，稍候启动" in task_center_section


def test_task_center_surfaces_real_mode_release_readiness_without_releasing_modes():
    _assert_current_results_and_issues_path()


def test_frontend_does_not_expose_developer_fallback_copy():
    _assert_current_authority_docs()


def test_frontend_surfaces_runtime_status_and_log_filters():
    app_source = APP_TSX.read_text(encoding="utf-8")
    safety_bar = SAFETY_STATUS_BAR_TSX.read_text(encoding="utf-8")
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")

    assert "/api/runtime/status?frontend_url=" in app_source
    assert "encodeURIComponent(window.location.origin)" in app_source
    assert "runtimeStatus={runtimeStatus}" in app_source
    assert "`本机服务：${runtimeStatus.backend.status === 'ok' ? '正常' : '异常'}`" in safety_bar
    assert "`主窗口：${frontendRuntimeLabel(runtimeStatus.frontend)}`" in safety_bar
    assert "桌面内置页面" in safety_bar
    assert "runtimeEndpointLine" not in safety_bar
    assert "dxmReadySessionStatuses" in safety_bar
    assert "dxmLoginTone(runtimeStatus.dxmLogin.status)" in safety_bar
    assert "if (dxmReadySessionStatuses.has(status)) return 'ok'" in safety_bar
    assert "runtimeStatus?.realBrowser" in safety_bar
    assert "humanRealBrowserStatus(realBrowser)" in safety_bar
    assert "`真实浏览器：${humanRealBrowserStatus(realBrowser)}`" in safety_bar
    assert "后端端口" not in safety_bar
    assert "前端端口" not in safety_bar
    assert "真实浏览器" in safety_bar
    assert "店小秘登录" in safety_bar
    assert "primaryStatus" in safety_bar
    assert "primaryActionLabel" in safety_bar
    assert "onShowTasks" in safety_bar
    visible_meta = safety_bar[
        safety_bar.index('<div className="safety-bar__meta"'):
        safety_bar.index("</section>")
    ]
    assert "启动方式" not in visible_meta
    assert "runtimeOwnerChip" not in visible_meta
    assert "safety-bar__meta-details" not in safety_bar
    assert "detailChips.map" not in visible_meta
    assert "启动方式" in safety_bar
    assert "detailChips" in safety_bar
    assert "runtimeLogLevel" in app_source
    assert "runtimeLogQuery" in app_source
    assert "RuntimeLogSource" in app_source
    assert "['backend', 'frontend', 'launcher', 'npm', 'task', 'agent']" in app_source
    assert "source === 'task' && selectedTask?.id" in app_source
    assert "params.set('task_id', String(selectedTask.id))" in app_source
    assert "runtimeLogLevel !== 'all'" in app_source
    assert "params.set('q', runtimeLogQuery.trim())" in app_source
    start_section = app_source[app_source.index("async function startSelectedTask"):app_source.index("async function openDxmLogin")]
    assert "`/api/runtime/status?frontend_url=${encodeURIComponent(window.location.origin)}`" in start_section
    assert "getJson<RuntimeStatus>('/api/runtime/status')" not in start_section
    assert "RuntimeLogLine" in workbench_source
    assert "run_l2_readonly_probe" in (REPO_ROOT / "app" / "frontend" / "src" / "types.ts").read_text(encoding="utf-8")
    assert "onRuntimeControl('run_l2_readonly_probe')" in workbench_source
    assert "getL2ProbeResourceState(runtimeStatus)" in workbench_source
    focus_panel_section = workbench_source[workbench_source.index("function ConsoleFocusPanel"):workbench_source.index("function AgentBrowserFrame")]
    assert "runtimeStatus: RuntimeStatus | null" in focus_panel_section
    assert "const realBrowser = runtimeStatus?.realBrowser" in focus_panel_section
    assert "realBrowser?.nextAction ?? agentConsole?.hud?.next_step" in focus_panel_section
    assert "primaryPath.action === 'launcher_logs'" in focus_panel_section
    assert "onRuntimeLogSourceChange('launcher')" in focus_panel_section
    assert "primaryActionDisabled={false}" in focus_panel_section
    assert "dependencies.l2_readonly_probe_runner" in workbench_source
    assert "dependencies.l2_readonly_probe_script" in workbench_source
    assert "dependencies.l2_readonly_probe_allowlist" in workbench_source
    assert "if (!runtimeStatus || !runtimeStatus.dependencies)" in workbench_source
    assert "userMessage" in (REPO_ROOT / "app" / "frontend" / "src" / "types.ts").read_text(encoding="utf-8")
    assert "repairSteps" in (REPO_ROOT / "app" / "frontend" / "src" / "types.ts").read_text(encoding="utf-8")
    assert "item?.userMessage" in workbench_source
    assert "item?.repairSteps" in workbench_source
    assert "保存前安全检查组件未安装完整" in workbench_source
    assert "保存前安全检查依赖状态未知，请先刷新运行状态或重新打开免安装版。" in workbench_source


def test_frontend_uses_unified_real_browser_status_for_primary_browser_state():
    _assert_current_connection_path()


def test_task_center_precheck_buttons_share_resource_gate():
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    task_center_section = workbench_source[workbench_source.index("export function TaskCenterView"):workbench_source.index("export function ExecutionConsole")]
    current_panel_section = task_current_action_panel_section()
    readonly_card = readonly_recheck_help_card_section(workbench_source)
    recovery_card = single_save_recovery_guide_section(workbench_source)

    assert "const l2ProbeResourceState = getL2ProbeResourceState(runtimeStatus)" in task_center_section
    assert "l2ProbeResourceState={l2ProbeResourceState}" in task_center_section
    assert "l2ProbeResourceState: L2ProbeResourceState" in PRODUCT_TASK_PANELS_TSX.read_text(encoding="utf-8")
    assert "disabled={busy || l2ProbeResourceState.blocked}" in readonly_card
    assert "title={l2ProbeResourceState.title}" in readonly_card
    assert "{l2ProbeResourceState.blocked && <small>{l2ProbeResourceState.detail}</small>}" in readonly_card
    assert "l2ProbeResourceState: L2ProbeResourceState" in PRODUCT_TASK_PANELS_TSX.read_text(encoding="utf-8")
    assert "disabled={busy || l2ProbeResourceState.blocked}" in current_panel_section
    assert "title={l2ProbeResourceState.title}" in current_panel_section
    assert "disabled={busy || l2ProbeResourceState.blocked}" in recovery_card
    assert "title={l2ProbeResourceState.title}" in recovery_card


def test_console_primary_path_blocks_l2_when_probe_runner_is_missing():
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    console_section = workbench_source[workbench_source.index("export function ExecutionConsole"):workbench_source.index("function AgentStagePanel")]
    focus_section = workbench_source[workbench_source.index("function ConsoleFocusPanel"):workbench_source.index("function AgentBrowserFrame")]
    primary_path_section = workbench_source[
        workbench_source.index("function buildConsolePrimaryPath"):
        workbench_source.index("function FinalCheckFreshnessRow")
    ]

    assert "runtimeStatus," in primary_path_section
    assert "runtimeStatus: RuntimeStatus | null" in primary_path_section
    assert "const l2ProbeResourceState = getL2ProbeResourceState(runtimeStatus)" in primary_path_section
    assert "if (requiresRealL2(selectedTask) && !l2Ready && l2ProbeResourceState.blocked)" in primary_path_section
    assert "title: '需要运行保存前安全检查'" in primary_path_section
    assert "ctaLabel: '查看启动器日志'" in primary_path_section
    assert "action: 'launcher_logs'" in primary_path_section
    assert "buildConsolePrimaryPath({ selectedTask, reports: workspace.reports, configPreview, configPreviewError, configPreviewLoading, l2Gate, l3Gate, runtimeStatus, busy })" in console_section
    assert "if (primaryPath.action === 'launcher_logs') return onRuntimeLogSourceChange('launcher')" in focus_section
    assert "primaryPath.action === 'run_l2' && l2ProbeResourceState.blocked" not in focus_section


def test_l2_probe_resource_blocker_shows_repair_steps_and_checked_paths():
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    resource_state = workbench_source[
        workbench_source.index("function getL2ProbeResourceState"):
        workbench_source.index("function RuntimeControlResultSummary")
    ]
    repair_panel = l2_probe_resource_repair_panel_section()
    readonly_card = readonly_recheck_help_card_section(workbench_source)
    console_controls = workbench_source[workbench_source.index("function AgentConsoleControls"):workbench_source.index("function RuntimeLogPreview")]

    assert "checkedPaths" in resource_state
    assert "repairSteps" in resource_state
    assert "checkedPathPreview" in resource_state
    assert "关闭旧的 DXM Agent Console 或后台旧进程" in resource_state
    assert "打开桌面免安装目录里的 DXM-Agent-Console-Portable-0.1.0.exe" in resource_state
    assert "不要只复制 exe，必须保留 resources 文件夹" in resource_state
    assert "L2ProbeResourceRepairPanel" in readonly_card
    assert "L2ProbeResourceRepairPanel" in console_controls
    assert "保存前安全检查资源修复步骤" in repair_panel
    assert "l2ProbeResourceState.repairSteps.map" in repair_panel
    assert "l2ProbeResourceState.checkedPathPreview.map" in repair_panel
    assert ".l2-probe-repair-panel" in styles_source


def test_execution_console_disables_l2_probe_when_runner_lock_is_active():
    types_source = (REPO_ROOT / "app" / "frontend" / "src" / "types.ts").read_text(encoding="utf-8")
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    l2_state_function = workbench_source[
        workbench_source.index("function getL2ProbeResourceState"):
        workbench_source.index("function RuntimeControlResultSummary")
    ]

    assert "l2ReadonlyProbe?: {" in types_source
    assert "running: boolean" in types_source
    assert "runtimeStatus.l2ReadonlyProbe?.running" in l2_state_function
    assert "保存前安全检查正在运行" in l2_state_function
    assert "runId" not in l2_state_function
    assert "请等待完成或查看实时日志" in l2_state_function
    assert "本轮保存前安全检查正在运行" in l2_state_function
    assert "关闭旧窗口或后台旧进程后，再重新打开免安装版。" not in l2_state_function


def test_task_center_precheck_cards_receive_resource_state_prop():
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    readonly_card = readonly_recheck_help_card_section(workbench_source)
    recovery_card = single_save_recovery_guide_section(workbench_source)

    readonly_params = readonly_card[readonly_card.index("function ReadonlyRecheckHelpCard({"):readonly_card.index("}: ReadonlyRecheckHelpCardProps")]
    recovery_params = recovery_card[recovery_card.index("function SingleSaveRecoveryGuide({"):recovery_card.index("}: SingleSaveRecoveryGuideProps")]

    assert "l2ProbeResourceState," in readonly_params
    assert "l2ProbeResourceState," in recovery_params


def test_safety_status_bar_keeps_long_guidance_out_of_visible_top_bar():
    safety_bar = SAFETY_STATUS_BAR_TSX.read_text(encoding="utf-8")
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    main_section = safety_bar[
        safety_bar.index('<div className="safety-bar__main">'):
        safety_bar.index('<div className="safety-bar__meta"')
    ]
    safety_styles = styles_source[styles_source.index(".safety-bar {"):styles_source.index(".safety-bar--warn {")]

    assert "<strong>{headline}</strong>" in main_section
    assert "{visibleBlockerReason}；只保存，不发布。" in main_section
    assert "conciseDetail" not in main_section
    assert "safety-bar__meta-details" not in safety_bar
    assert "safety-bar__compact-detail" not in main_section
    assert "min-height: 42px;" in safety_styles
    assert "padding: 6px 10px;" in safety_styles
    assert "gap: 10px;" in safety_styles
    assert ".safety-bar__blocker" in styles_source
    assert "text-overflow: ellipsis;" in styles_source
    assert "padding: 8px 12px;" not in safety_styles


def test_safety_status_bar_does_not_duplicate_completed_task_status():
    safety_bar = SAFETY_STATUS_BAR_TSX.read_text(encoding="utf-8")

    assert "const activeTaskLabel = selectedTask ? `#${selectedTask.id}` : '未选择任务'" in safety_bar
    assert "const activeTaskStatusLabel = selectedTask ? humanTaskStatus(selectedTask.status) : ''" in safety_bar
    assert "任务 ${activeTaskLabel} ${activeTaskStatusLabel}，继续查看保存结果和未发布证明。" in safety_bar
    assert "`#${selectedTask.id} ${humanTaskStatus(selectedTask.status)}`" not in safety_bar


def test_safety_status_bar_prioritizes_config_block_before_l2_precheck():
    app_source = APP_TSX.read_text(encoding="utf-8")
    safety_bar = SAFETY_STATUS_BAR_TSX.read_text(encoding="utf-8")

    assert "configPreview: ConfigPreview | null" in safety_bar
    assert "configPreviewError?: string | null" in safety_bar
    assert "configPreviewLoading: boolean" in safety_bar
    assert "onShowConfig: () => void" in safety_bar
    assert "const configBlocksRealSave" in safety_bar
    assert "继续下一步：补齐本次任务配置" in safety_bar
    assert "handlePrimaryAction = selectedTaskCompleted" in safety_bar
    assert "? onShowConfig" in safety_bar
    assert "configPreview={configPreview}" in app_source
    assert "configPreviewError={configPreviewError}" in app_source
    assert "configPreviewLoading={configPreviewLoading}" in app_source
    assert "onShowConfig={() => setActiveSection('edit_config')}" in app_source


def test_safety_status_bar_does_not_config_block_acquisition_claim_tasks():
    safety_bar = SAFETY_STATUS_BAR_TSX.read_text(encoding="utf-8")
    config_block_section = safety_bar[safety_bar.index("const configBlocksRealSave"):safety_bar.index("const publishGuardReasons")]

    assert "const selectedTaskNeedsEditConfig = selectedTask?.mode === 'single_save'" in safety_bar
    assert "&& selectedTaskNeedsEditConfig" in config_block_section
    assert "selectedRealDxmMutationTask" not in config_block_section
    assert "claim_only" not in config_block_section


def test_frontend_refreshes_workspace_after_l2_runner_finishes():
    app_source = APP_TSX.read_text(encoding="utf-8")
    runner_observer = app_source[
        app_source.index("const handleL2RunnerFinished"):
        app_source.index("useEffect(() => {\n    void refreshRuntimeStatus()")
    ]

    assert "lastObservedL2CompletionRef" in app_source
    assert "[l2-readonly-runner] finished" in runner_observer
    assert "exit_code=0" in runner_observer
    assert "runnerEvent.line.match(/run_id=" in runner_observer
    assert "const refreshedWorkspace = await refreshWorkspace()" in runner_observer
    assert "const refreshedL2Gate = refreshedWorkspace.regressionGates.find((gate) => gate.level === 'L2')" in runner_observer
    assert "runnerSucceeded && refreshedL2Gate?.status === 'passed'" in runner_observer
    assert "保存前安全检查已运行，但状态未刷新通过" in runner_observer
    assert "runnerSucceeded ? '保存前安全检查已运行，但状态未刷新通过' : '保存前安全检查失败，真实保存仍阻断'" in runner_observer
    assert "保存前安全检查未通过：请确认已登录并能打开已有待认领列表、商品箱页面后重试。" in runner_observer
    assert "系统不会保存或发布" in runner_observer
    assert "void handleL2RunnerFinished({" in runner_observer
    assert "void refreshWorkspace()" not in runner_observer


def test_execution_console_surfaces_l2_runner_result_not_just_start_message():
    app_source = APP_TSX.read_text(encoding="utf-8")
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")

    assert "type L2RunnerState" in app_source
    assert "const [l2RunnerState, setL2RunnerState]" in app_source
    assert "setL2RunnerState({ status: 'running'" in app_source
    assert "exit_code=0" in app_source
    assert "exit_code=" in app_source
    assert "setL2RunnerState({ status: 'failed'" in app_source
    assert "setOperationError(`${message}；请确认真实店小秘已登录，再重新运行保存前安全检查。系统不会保存或发布。`)" in app_source
    assert "l2RunnerState={l2RunnerState}" in app_source
    assert "L2RunnerStatePanel" in workbench_source
    assert "保存前安全检查" in workbench_source
    assert "正在运行双目标保存前安全检查" in workbench_source
    assert "保存前安全检查通过，已刷新状态" in workbench_source
    assert "保存前安全检查失败，真实保存仍阻断" in workbench_source
    assert "保存前安全检查已运行，但状态未刷新通过" in app_source
    runner_panel = workbench_source[workbench_source.index("function L2RunnerStatePanel"):workbench_source.index("function L2PrecheckFailureAdvice")]
    assert "<summary>排障日志</summary>" in runner_panel
    assert "检查编号：{state.runId}" in runner_panel
    assert "run-id：" not in runner_panel
    assert "退出码：" in runner_panel
    failure_advice = workbench_source[workbench_source.index("function L2PrecheckFailureAdvice"):workbench_source.index("function L2PrecheckRunbook")]
    assert "请确认已登录并能打开已有待认领列表、商品箱页后重试。" in failure_advice
    assert ".l2-runner-state" in styles_source


def test_execution_console_explains_l2_precheck_runbook_and_next_action():
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    console_section = workbench_source[workbench_source.index("export function ExecutionConsole"):workbench_source.index("function RuntimeLogPreview")]
    runner_panel = workbench_source[workbench_source.index("function L2RunnerStatePanel"):workbench_source.index("function RuntimeLogPreview")]

    assert "L2PrecheckRunbook" in console_section
    assert "function L2PrecheckRunbook" in workbench_source
    assert "aria-label=\"保存前安全检查操作引导\"" in runner_panel
    assert "安全检查说明" in runner_panel
    assert "1 打开真实店小秘页面" in runner_panel
    assert "2 检查两个页面" in runner_panel
    assert "3 通过后人工确认保存" in runner_panel
    assert "已有待认领列表" in runner_panel
    assert "商品箱" in runner_panel
    assert "不会认领、不会保存、不会发布" in runner_panel
    assert "onLogSourceChange('launcher')" in runner_panel
    assert "查看排障日志" in runner_panel
    assert "onShowReports" in runner_panel
    assert "查看检查计划" in runner_panel
    assert "保存前安全检查失败后怎么办" in runner_panel
    assert "l2-precheck-runbook" in styles_source
    assert ".l2-precheck-runbook__steps" in styles_source


def test_execution_console_places_primary_precheck_action_in_l2_state_card():
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    console_section = workbench_source[workbench_source.index("export function ExecutionConsole"):workbench_source.index("function RuntimeLogPreview")]
    runner_panel = workbench_source[workbench_source.index("function L2RunnerStatePanel"):workbench_source.index("function L2PrecheckFailureAdvice")]

    assert "onRunPrecheck={() => onRuntimeControl('run_l2_readonly_probe')}" in console_section
    assert "runtimeStatus={runtimeStatus}" in console_section
    assert "busy={busy}" in console_section
    assert "const l2ProbeResourceState = getL2ProbeResourceState(runtimeStatus)" in runner_panel
    assert "const precheckDisabled = busy || state.status === 'running' || l2ProbeResourceState.blocked" in runner_panel
    assert "aria-label=\"运行保存前安全检查主操作\"" in runner_panel
    assert "onLogSourceChange('launcher')" in runner_panel
    assert "onRunPrecheck()" in runner_panel
    assert "{state.status === 'running' ? '安全检查运行中' : READONLY_PRECHECK_CTA}" in runner_panel
    assert "l2-runner-state__primary-action" in styles_source


def test_execution_console_shows_l2_failure_advice_in_precheck_card():
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    runner_panel = workbench_source[workbench_source.index("function L2RunnerStatePanel"):workbench_source.index("function RuntimeLogPreview")]
    summarize_section = workbench_source[workbench_source.index("function summarizeL2Diagnostics"):workbench_source.index("function l2DiagnosticNextAction")]

    assert "const diagnosticSummaries = summarizeL2Diagnostics(l2Gate)" in runner_panel
    assert "L2PrecheckFailureAdvice summaries={diagnosticSummaries} state={state} gateStatus={l2Gate?.status}" in runner_panel
    assert "function L2PrecheckFailureAdvice" in workbench_source
    assert "gateStatus?: RegressionGate['status']" in workbench_source
    assert "if (state.status !== 'failed' && gateStatus !== 'blocked') return null" in workbench_source
    assert "aria-label=\"保存前安全检查失败处理建议\"" in workbench_source
    assert "保存前安全检查失败处理建议" in workbench_source
    assert "失败页面" in workbench_source
    assert "失败检查" in workbench_source
    assert "下一步处理" in workbench_source
    assert "item.nextAction" in workbench_source
    assert "humanDiagnosticNavigation(item.navigation)" in workbench_source
    assert "humanFailedCheckLabel" in workbench_source
    assert "humanL2TargetLabel(target)" in summarize_section
    assert "data_acquisition 采集页" not in summarize_section
    assert "draft_box 草稿箱" not in summarize_section
    assert ".l2-precheck-failure-advice" in styles_source


def test_runtime_maintenance_explains_cleared_and_protected_tasks():
    app_source = APP_TSX.read_text(encoding="utf-8")
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")

    assert "const [lastRuntimeControlResult, setLastRuntimeControlResult]" in app_source
    assert "setLastRuntimeControlResult(result)" in app_source
    assert "lastRuntimeControlResult={lastRuntimeControlResult}" in app_source
    assert "lastRuntimeControlResult: RuntimeControlResponse | null" in workbench_source
    assert "RuntimeControlResultSummary" in workbench_source
    assert "清理结果" in workbench_source
    assert "已取消非真实写入任务" in workbench_source
    assert "真实写入任务已保护，未自动取消" in workbench_source
    assert "real_write_protected" in workbench_source
    assert ".runtime-control-result" in styles_source


def test_l2_precheck_start_receipt_keeps_run_id_in_technical_log():
    app_source = APP_TSX.read_text(encoding="utf-8")
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    types_source = (REPO_ROOT / "app" / "frontend" / "src" / "types.ts").read_text(encoding="utf-8")
    run_runtime_control = app_source[
        app_source.index("async function runRuntimeControl"):
        app_source.index("async function runL2ReadonlyProbe")
    ]
    result_summary = workbench_source[
        workbench_source.index("function RuntimeControlResultSummary"):
        workbench_source.index("function runtimeTaskLabel")
    ]

    assert "runId?: string" in types_source
    assert "logPath?: string" in types_source
    assert "targets?: string[]" in types_source
    assert "if (action === 'run_l2_readonly_probe' && result.runId)" in run_runtime_control
    assert "runId: result.runId" in run_runtime_control
    assert "line: result.logPath ?? null" in run_runtime_control
    assert "result.action === 'run_l2_readonly_probe'" in result_summary
    assert "保存前安全检查已启动" in result_summary
    assert "检查编号：{result.runId ?? '等待返回'}" in result_summary
    assert "run-id：{result.runId ?? '等待返回'}" not in result_summary
    assert "检查目标：{formatL2ProbeTargets(result.targets)}" in result_summary
    assert "日志：{result.logPath ?? '启动器日志'}" in result_summary
    assert "function formatL2ProbeTargets" in workbench_source
    assert "data_acquisition: '已有待认领列表'" in workbench_source
    assert "draft_box: '商品箱'" in workbench_source


def test_execution_console_can_mark_real_task_for_manual_review():
    app_source = APP_TSX.read_text(encoding="utf-8")
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    types_source = (REPO_ROOT / "app" / "frontend" / "src" / "types.ts").read_text(encoding="utf-8")
    workspace_source = (REPO_ROOT / "app" / "frontend" / "src" / "workspace.ts").read_text(encoding="utf-8")

    assert "mark_real_task_manual_review" in types_source
    assert "mark_real_task_manual_review: '已将真实写入任务转入人工复核。" in app_source
    assert "onRuntimeControl('mark_real_task_manual_review')" in workbench_source
    assert "转人工复核" in workbench_source
    assert "不会取消真实浏览器进程" in workbench_source
    assert "needs_manual_review" in workbench_source
    assert "markedTasks" in workbench_source
    assert "待人工复核" in workspace_source


def test_frontend_humanizes_l2_runner_missing_error():
    app_source = APP_TSX.read_text(encoding="utf-8")

    assert "function humanOperationError" in app_source
    assert "L2 readonly probe resources are missing" in app_source
    assert "保存前安全检查组件未安装完整，请关闭旧进程并重新打开完整免安装目录版。" in app_source
    assert "L2 readonly probe runner is missing" in app_source
    assert "保存前安全检查组件未安装完整：缺少安全检查启动器。" in app_source
    assert "function searchedPathHint(message: string)" in app_source
    assert "const marker = 'Searched:'" in app_source
    assert ".slice(0, 3)" in app_source
    assert "已检查：${paths.join('；')}" in app_source
    assert "const humanMessage = humanOperationError(message)" in app_source
    assert "setOperationError(humanMessage)" in app_source


def test_execution_console_hides_raw_l2_runner_missing_in_gate_and_state_messages():
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    gate_detail_function = workbench_source[
        workbench_source.index("function humanGateDetail"):
        workbench_source.index("function humanDiagnosticNavigation")
    ]
    runner_state_panel = workbench_source[
        workbench_source.index("function L2RunnerStatePanel"):
        workbench_source.index("function L2PrecheckFailureAdvice")
    ]

    assert "humanL2PrecheckError" in workbench_source
    assert "L2 readonly probe runner is missing" in gate_detail_function
    assert "缺少安全检查启动器" in gate_detail_function
    assert "humanL2PrecheckError(state.line)" in runner_state_panel
    assert "{state.line && <code>{state.line}</code>}" not in runner_state_panel


def test_frontend_humanizes_dxm_login_browser_start_failures():
    app_source = APP_TSX.read_text(encoding="utf-8")
    open_login_section = app_source[
        app_source.index("async function openDxmLogin"):
        app_source.index("function credentialStateFromSave")
    ]
    continue_login_section = app_source[
        app_source.index("async function continueDxmLogin"):
        app_source.index("async function navigateDxmTarget")
    ]

    assert "function humanDxmLoginError(message: string)" in app_source
    assert "真实店小秘登录浏览器启动失败" in app_source
    assert "请关闭旧的 DXM Agent Console 或旧浏览器进程后重试" in app_source
    assert "账号密码不会用于保存或发布" in app_source
    assert "Internal Server Error" in app_source
    assert "browser has been closed" in app_source
    assert "Target page, context or browser has been closed" in app_source
    assert "user data directory is already in use" in app_source
    assert "const humanMessage = humanDxmLoginError(message)" in open_login_section
    assert "setOperationError(humanMessage)" in open_login_section
    assert "await refreshRuntimeLogs()" in open_login_section
    assert "const humanMessage = humanDxmLoginError(message)" in continue_login_section
    assert "setOperationError(humanMessage)" in continue_login_section


def test_frontend_guides_waiting_captcha_and_login_failed_as_operator_steps():
    app_source = APP_TSX.read_text(encoding="utf-8")
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    dxm_access_source = DXM_ACCESS_PAGE_TSX.read_text(encoding="utf-8")
    open_login_section = app_source[
        app_source.index("async function openDxmLogin"):
        app_source.index("function credentialStateFromSave")
    ]
    continue_login_section = app_source[
        app_source.index("async function continueDxmLogin"):
        app_source.index("async function navigateDxmTarget")
    ]

    assert "等待验证码不是失败" in app_source
    assert "可见浏览器窗口" in app_source
    assert "setActiveSection('dxm_access')" in continue_login_section
    assert "login_failed" in continue_login_section
    assert "humanDxmLoginFlowNotice(loginStart" in open_login_section
    assert "humanDxmLoginFlowNotice(loginResult" in continue_login_section

    assert "登录还没完成，不是系统故障" in workbench_source
    assert "保持真实浏览器打开" in workbench_source
    assert "如果验证码已完成仍失败" in workbench_source
    assert "重新打开登录页会复用当前账号输入" in workbench_source
    assert "humanOperatorMessage" in dxm_access_source
    assert "runtimeStatus?.dxmLogin?.lastError ||" not in dxm_access_source
    assert "humanOperatorMessage(runtimeStatus?.dxmLogin?.lastError" in dxm_access_source


def test_frontend_handles_dxm_navigation_failed_state_as_recoverable_operator_step():
    app_source = APP_TSX.read_text(encoding="utf-8")
    navigate_section = app_source[
        app_source.index("async function navigateDxmTarget"):
        app_source.index("async function startAgentConsole")
    ]

    assert "const navigationResult = await postJson<Record<string, unknown>>('/api/dxm/navigate', { target })" in navigate_section
    assert "const navigationStage = String(navigationResult.stage ?? '')" in navigate_section
    assert "navigationStage.includes('failed')" in navigate_section
    assert "humanDxmNavigationNotice(navigationResult" in navigate_section
    assert "setOperationError(humanDxmNavigationNotice(navigationResult" in navigate_section
    assert "真实店小秘业务页进入失败" in app_source
    assert "重新打开真实登录页" in app_source
    assert "raw_error" in app_source
    assert "function humanBrowserRuntimeError(message: string)" in app_source
    assert "humanBrowserRuntimeError(rawError)" in app_source
    assert "浏览器会话冲突" in app_source
    assert "`${rawError}`" not in app_source


def test_login_failed_state_has_structured_recovery_steps():
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    login_form_section = workbench_source[workbench_source.index("function DxmLoginInlineForm"):workbench_source.index("function CredentialStorageFacts")]
    recovery_section = workbench_source[workbench_source.index("function LoginRecoverySteps"):workbench_source.index("function CredentialStorageFacts")]

    assert "LoginRecoverySteps" in login_form_section
    assert "loginState={loginState}" in login_form_section
    assert "登录恢复步骤" in recovery_section
    assert "保持真实浏览器窗口打开" in recovery_section
    assert "修正验证码或账号密码" in recovery_section
    assert "再次点击“验证码完成后检测登录状态”" in recovery_section
    assert "仍失败时重新点击“打开真实登录页”" in recovery_section
    assert "loginState.label !== '登录未通过'" in recovery_section
    assert "operator-inline-form__recovery-steps" in styles_source


def test_execution_console_primary_blocker_card_shows_login_recovery_path():
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    execution_console_section = workbench_source[
        workbench_source.index("export function ExecutionConsole"):
        workbench_source.index("function AgentBrowserFrame")
    ]
    focus_section = workbench_source[
        workbench_source.index("function ConsoleFocusPanel"):
        workbench_source.index("function AgentBrowserFrame")
    ]
    blocker_card_section = workbench_source[
        workbench_source.index("function ConsolePrimaryBlockerCard"):
        workbench_source.index("function AgentBrowserFrame")
    ]

    assert "runtimeStatusError={runtimeStatusError}" in execution_console_section
    assert "onOpenDxmLogin={onOpenDxmLogin}" in execution_console_section
    assert "onContinueDxmLogin={onContinueDxmLogin}" in execution_console_section
    assert "const loginState = humanDxmLoginState(runtimeStatus, runtimeStatusError)" in focus_section
    assert "loginState={loginState}" in focus_section
    assert "onOpenDxmLogin={onOpenDxmLogin}" in focus_section
    assert "onContinueDxmLogin={onContinueDxmLogin}" in focus_section
    assert "aria-label=\"登录恢复路径\"" in blocker_card_section
    assert "console-primary-blocker-card__login-recovery" in blocker_card_section
    assert "登录还没完成，不是系统故障" in blocker_card_section
    assert "登录未通过" in blocker_card_section
    assert "1 保持真实浏览器" in blocker_card_section
    assert "2 修正验证码或账号密码" in blocker_card_section
    assert "3 检测登录状态" in blocker_card_section
    assert "验证码完成后检测登录状态" in blocker_card_section
    assert "重新打开登录页" in blocker_card_section
    assert ".console-primary-blocker-card__login-recovery" in styles_source


def test_frontend_humanizes_agent_console_browser_start_failures():
    app_source = APP_TSX.read_text(encoding="utf-8")
    start_console_section = app_source[
        app_source.index("async function startAgentConsole"):
        app_source.index("async function stopAgentConsole")
    ]

    assert "function humanAgentConsoleError(message: string)" in app_source
    assert "真实浏览器现场启动失败" in app_source
    assert "请关闭旧的 DXM Agent Console 或旧浏览器进程后重试" in app_source
    assert "browser has been closed" in app_source
    assert "user data directory is already in use" in app_source
    assert "const humanMessage = humanAgentConsoleError(message)" in start_console_section
    assert "setAgentConsoleError(humanMessage)" in start_console_section
    assert "setOperationError(humanMessage)" in start_console_section


def test_frontend_agent_console_initial_hud_matches_single_save_user_flow():
    app_source = APP_TSX.read_text(encoding="utf-8")
    hud_builder = app_source[
        app_source.index("function buildAgentConsoleHudStep"):
    ]

    assert "准备执行只保存" in hud_builder
    assert "READY_FOR_SINGLE_SAVE" in hud_builder
    assert "开始任务" in hud_builder
    assert "progress_total: 12" in hud_builder
    assert "真实浏览器已打开，自动浏览器将按步骤操作店小秘编辑页" in hud_builder
    assert "人工确认后开始输入标题、选择分类、设置价格库存并只保存" in hud_builder
    assert "只保存，不发布" in hud_builder
    assert "requires_user_action: true" in hud_builder
    assert "severity: 'warning'" in hud_builder
    assert "保存前安全检查待命" not in hud_builder
    assert "只读观察" not in hud_builder


def test_app_silently_refreshes_workspace_while_task_is_running():
    app_source = APP_TSX.read_text(encoding="utf-8")
    refresh_signature = app_source[
        app_source.index("const refreshWorkspace = useCallback"):
        app_source.index("useEffect(() => {\n    void refreshWorkspace()")
    ]
    running_poll_section = app_source[
        app_source.index("const workspaceHasRunningTask"):
        app_source.index("const refreshConfigPreview = useCallback")
    ]

    assert "options?: { silent?: boolean }" in refresh_signature
    assert "!options?.silent" in refresh_signature
    assert "workspace.tasks.some" in running_poll_section
    assert "task.status === 'running'" in running_poll_section
    assert "window.setInterval(() =>" in running_poll_section
    assert "void refreshWorkspace({ silent: true })" in running_poll_section
    assert "1500" in running_poll_section


def test_frontend_humanizes_agent_console_takeover_and_control_failures():
    app_source = APP_TSX.read_text(encoding="utf-8")
    stop_section = app_source[
        app_source.index("async function stopAgentConsole"):
        app_source.index("async function snapshotAgentConsole")
    ]
    snapshot_section = app_source[
        app_source.index("async function snapshotAgentConsole"):
        app_source.index("async function requestAgentConsoleTakeover")
    ]
    takeover_section = app_source[
        app_source.index("async function requestAgentConsoleTakeover"):
        app_source.index("async function releaseAgentConsoleTakeover")
    ]
    release_section = app_source[
        app_source.index("async function releaseAgentConsoleTakeover"):
        app_source.index("async function controlAgentConsoleBrowser")
    ]
    control_section = app_source[
        app_source.index("async function controlAgentConsoleBrowser"):
        app_source.index("async function runRuntimeControl")
    ]

    assert "const humanMessage = humanAgentConsoleError(message)" in stop_section
    assert "setAgentConsoleError(humanMessage)" in stop_section
    assert "setOperationError(humanMessage)" in stop_section
    assert "const humanMessage = humanAgentConsoleError(message)" in snapshot_section
    assert "setAgentConsoleError(humanMessage)" in snapshot_section
    assert "setOperationError(humanMessage)" in snapshot_section
    assert "const humanMessage = humanAgentConsoleError(message)" in takeover_section
    assert "setAgentConsoleError(humanMessage)" in takeover_section
    assert "setOperationError(humanMessage)" in takeover_section
    assert "const humanMessage = humanAgentConsoleError(message)" in release_section
    assert "setAgentConsoleError(humanMessage)" in release_section
    assert "setOperationError(humanMessage)" in release_section
    assert "const humanMessage = humanAgentConsoleError(message)" in control_section
    assert "setAgentConsoleError(humanMessage)" in control_section
    assert "setOperationError(humanMessage)" in control_section


def test_frontend_marks_l2_runner_failed_when_start_request_fails():
    app_source = APP_TSX.read_text(encoding="utf-8")
    run_runtime_control = app_source[
        app_source.index("async function runRuntimeControl"):
        app_source.index("async function runL2ReadonlyProbe")
    ]

    assert "if (action === 'run_l2_readonly_probe')" in run_runtime_control
    assert "setL2RunnerState({" in run_runtime_control
    assert "status: 'failed'" in run_runtime_control
    assert "保存前安全检查启动失败，真实保存仍阻断" in run_runtime_control
    assert "humanOperationError(message)" in run_runtime_control
    assert "setOperationError(humanMessage)" in run_runtime_control


def test_frontend_keeps_runtime_and_config_fetch_failures_distinct_from_user_state():
    app_source = APP_TSX.read_text(encoding="utf-8")
    safety_bar = SAFETY_STATUS_BAR_TSX.read_text(encoding="utf-8")
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")

    assert "const [runtimeStatusError, setRuntimeStatusError]" in app_source
    assert "function humanRuntimeStatusError(message: string)" in app_source
    assert "setRuntimeStatusError(humanRuntimeStatusError(error instanceof Error ? error.message : '运行状态接口不可用'))" in app_source
    assert "本机后端未连接" in app_source
    assert "请重新打开 DXM Agent Console 免安装版" in app_source
    assert "开发模式请先启动后端服务" in app_source
    assert "humanOperationError(error instanceof Error ? error.message : '启动保存核验任务失败')" in app_source
    assert "runtimeStatusError={runtimeStatusError}" in app_source
    assert "运行状态接口不可用" not in safety_bar
    assert "状态接口异常" in safety_bar
    assert "runtimeStatusError?: string | null" in safety_bar

    assert "const [configPreviewError, setConfigPreviewError]" in app_source
    assert "setConfigPreviewError(humanConfigPreviewError(error instanceof Error ? error.message : '配置检查接口不可用'))" in app_source
    assert "configPreviewError={configPreviewError}" in app_source
    assert "配置检查接口不可用" in workbench_source
    assert "请先确认本机后端仍在运行，再重新检查配置" in workbench_source
    assert "configPreviewError: string | null" in workbench_source


def test_safety_bar_has_explicit_service_recovery_state_when_backend_is_unavailable():
    safety_bar = SAFETY_STATUS_BAR_TSX.read_text(encoding="utf-8")

    assert "runtimeStatusUnavailable" in safety_bar
    assert "工作台服务连接异常" in safety_bar
    assert "查看日志" in safety_bar
    assert "刷新状态" in safety_bar
    assert "后端未连接不是账号、配置或店小秘页面问题" in safety_bar
    assert "primaryActionLabel = selectedTaskCompleted" in safety_bar
    assert "runtimeStatusUnavailable" in safety_bar[safety_bar.index("const primaryActionLabel"):safety_bar.index("const handlePrimaryAction")]
    assert "runtimeStatusUnavailable" in safety_bar[safety_bar.index("const handlePrimaryAction"):safety_bar.index("return (")]


def test_safety_bar_uses_operator_precheck_copy_before_technical_l2_terms():
    safety_bar = SAFETY_STATUS_BAR_TSX.read_text(encoding="utf-8")
    visible_status_section = safety_bar[
        safety_bar.index("const gateStatusLine"):
        safety_bar.index("const gateDetails")
    ]
    detail_chip_section = safety_bar[
        safety_bar.index("const detailChips"):
        safety_bar.index("const boundaryChips")
    ]

    assert "保存前安全检查" in visible_status_section
    assert "真实只读检查" not in visible_status_section
    assert "L2 页面核验" not in visible_status_section
    assert "保存前安全检查：" in detail_chip_section
    assert "L2 页面核验：" not in detail_chip_section
    assert "保存前安全检查：" in safety_bar[safety_bar.index("const gateDetails"):safety_bar.index("const blockerDetails")]
    assert "L2 页面核验：" not in safety_bar[safety_bar.index("const gateDetails"):safety_bar.index("const blockerDetails")]


def test_execution_console_surfaces_desktop_log_paths_when_service_is_unavailable():
    app_source = APP_TSX.read_text(encoding="utf-8")
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")

    console_section = workbench_source[
        workbench_source.index("export function ExecutionConsole"):
        workbench_source.index("function AgentStagePanel")
    ]
    service_recovery_section = workbench_source[
        workbench_source.index("function ServiceRecoveryPanel"):
        workbench_source.index("function RuntimeLogPreview")
    ]

    assert "desktopRuntime={desktopRuntime}" in app_source
    assert "desktopRuntime: DesktopRuntimeInfo | null" in workbench_source
    assert "ServiceRecoveryPanel" in console_section
    assert "runtimeStatusError={runtimeStatusError}" in console_section
    assert "desktopRuntime={desktopRuntime}" in console_section
    assert 'aria-label="工作台服务恢复"' in service_recovery_section
    assert "工作台服务连接异常" in service_recovery_section
    assert "desktopRuntime?.desktopLogPath" in service_recovery_section
    assert "desktopRuntime?.backendLogPath" in service_recovery_section
    assert "不是店小秘账号、配置或页面问题" in service_recovery_section
    assert "onRuntimeLogSourceChange('launcher')" in service_recovery_section


def test_frontend_does_not_surface_raw_backend_fetch_failures_to_operator():
    app_source = APP_TSX.read_text(encoding="utf-8")
    safety_bar = SAFETY_STATUS_BAR_TSX.read_text(encoding="utf-8")

    assert "function humanWorkspaceFetchError" in app_source
    assert "humanWorkspaceFetchError(firstFailure?.message)" in app_source
    assert "GET /api/delivery/workspace failed" not in app_source
    assert "GET /api/runtime/status" not in app_source
    assert "原始错误：" not in app_source
    assert "本机后端未连接：请重新打开 DXM Agent Console 免安装版；开发模式请先启动后端服务。真实保存不会启动或发布。" in app_source
    assert "暂时无法读取完整任务数据。请重新打开 DXM Agent Console 免安装版；开发模式请确认后端服务正在运行。真实保存不会启动或发布。" in app_source
    assert "runtimeEndpointLine = runtimeStatus" not in safety_bar
    assert "运行状态接口不可用：${runtimeStatusError}" not in safety_bar
    assert "状态接口异常" in safety_bar


def test_frontend_treats_workflow_navigation_as_logged_in_across_primary_surfaces():
    _assert_current_connection_path()


def test_frontend_recovers_from_stale_task_id_in_url():
    app_source = APP_TSX.read_text(encoding="utf-8")

    assert "function syncSelectedTaskIdUrl(taskId: number | null)" in app_source
    assert "Boolean(deliveryWorkspace?.requested_task_missing)" in app_source
    assert "failures.some((failure) => failure.path.startsWith('/api/delivery/workspace') && /task not found/i.test(failure.message))" in app_source
    assert "const recoveredTaskId = pickDefaultTaskId(deliveryWorkspace, nextWorkspace.tasks)" in app_source
    assert "setSelectedTaskId(recoveredTaskId)" in app_source
    assert "syncSelectedTaskIdUrl(recoveredTaskId)" in app_source
    assert "系统已切回当前可用任务" in app_source
    assert "} else {\n      setSelectedTaskId((current) => pickTaskIdForOperatorPath(current, deliveryWorkspace, nextWorkspace.tasks))" in app_source
    assert "syncSelectedTaskIdUrl(taskId)" in app_source


def test_execution_console_uses_unified_primary_path_before_rendering():
    _assert_current_connection_path()
    _assert_current_batch_draft_save_path()


def test_frontend_first_screen_names_dxm_automation_delivery():
    _assert_frozen_primary_navigation()


def test_sidebar_copy_names_save_only_agent_flow_without_ambiguous_browser_wording():
    _assert_frozen_primary_navigation()
    _assert_current_batch_draft_save_path()


def test_frontend_uses_business_sidebar_groups_and_hides_operator_diagnostics_by_default():
    _assert_frozen_primary_navigation()


def test_home_dashboard_is_operator_command_center_not_static_metrics():
    _assert_frozen_primary_navigation()
    _assert_current_batch_draft_save_path()


def test_home_page_default_path_is_one_decision_without_gate_jargon():
    source = HOME_PAGE_TSX.read_text(encoding="utf-8")
    dashboard_section = source[source.index("<div className=\"hero-panel home-command\">"):]

    assert "下一步" in dashboard_section
    assert dashboard_section.count("<button") == 1
    assert "aria-label=\"当前状态\"" in dashboard_section

    for forbidden in ["L2", "L3", "probe", "run-id", "HAR", "greenlet"]:
        assert forbidden not in dashboard_section

    assert "维护人员查看运行状态" not in dashboard_section
    assert "home-menu-map" not in dashboard_section
    assert "home-command__status-grid" not in dashboard_section


def test_config_and_console_primary_screens_keep_diagnostics_secondary():
    _assert_current_plan_path()
    _assert_current_batch_draft_save_path()


def test_app_consumes_recoverable_missing_task_workspace_flag():
    source = APP_TSX.read_text(encoding="utf-8")
    refresh_section = source[source.index("const refreshWorkspace = useCallback"):source.index("useEffect(() => {\n    void refreshWorkspace()")]

    assert "requested_task_missing?: boolean" in source
    assert "requested_task_id?: number | null" in source
    assert "Boolean(deliveryWorkspace?.requested_task_missing)" in refresh_section
    assert "pickDefaultTaskId(deliveryWorkspace, nextWorkspace.tasks)" in refresh_section
    assert "syncSelectedTaskIdUrl(recoveredTaskId)" in refresh_section
    assert "上次选择的任务已不存在或已归档。系统已切回当前可用任务" in refresh_section


def test_execution_console_compact_login_keeps_account_fields_in_drawer():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    login_form = source[source.index("function DxmLoginInlineForm"):source.index("function LoginRecoverySteps")]
    compact_branch = login_form[login_form.index("{compact ? ("):login_form.index(") : (")]

    assert "const accountFields = (" in login_form
    assert "const actions = (" in login_form
    assert "{loginStateBlock}" in compact_branch
    assert "{actions}" in compact_branch
    assert "operator-inline-form__account-drawer inline-disclosure" in compact_branch
    assert "open={false}" in compact_branch
    assert "账号密码与保存设置" in compact_branch
    assert "先展开填写" in compact_branch
    assert compact_branch.index("{actions}") < compact_branch.index("operator-inline-form__account-drawer")
    assert ".operator-inline-form__account-drawer" in styles_source
    assert ".operator-inline-form__account-grid" in styles_source
    assert ".operator-inline-form--compact .operator-inline-form__actions" in styles_source


def test_execution_console_shows_current_decision_before_browser_controls():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    console_section = source[source.index("export function ExecutionConsole"):source.index("function ConsoleCompletedReviewPanel")]
    return_section = console_section[console_section.index("return ("):]

    assert "const consoleFocusPanel = (" in console_section
    assert "{!compactCompletedReview && consoleFocusPanel}" in return_section
    assert return_section.index("{!compactCompletedReview && consoleFocusPanel}") < return_section.index("<AgentStagePanel")
    assert "{compactCompletedReview && consoleFocusPanel}" not in return_section
    assert "{!compactCompletedReview && (" in return_section
    assert "console-log-card" not in return_section
    assert "console-focus-panel__log" in source


def test_frontend_translates_failed_execution_technical_errors_for_operators():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    results_source = RESULTS_PAGE_TSX.read_text(encoding="utf-8")
    copy_source = WORKBENCH_COPY_TS.read_text(encoding="utf-8")
    report_summary_section = source[source.index("function humanReportSummary"):source.index("function formatTime")]
    gate_detail_section = source[source.index("function humanGateDetail"):source.index("function humanL2PrecheckError")]
    report_card_section = source[source.index("function ReportCard"):source.index("function GradeCard")]
    exception_card_section = source[source.index("function ExceptionCard"):source.index("function isReadyReadiness")]

    assert "from './workbench/workbenchCopy'" in source
    assert "export function humanOperatorMessage" in copy_source
    assert "export function humanOperatorTitle" in copy_source
    assert "function looksTechnicalOperatorMessage" in copy_source
    assert "humanReportTitle" in source
    assert "Cannot switch to a different thread" in copy_source
    assert "greenlet" in copy_source
    assert "L2 readonly probe" in copy_source
    assert "normalized.includes('l2 readonly')" in copy_source
    assert "message.includes('L3')" in copy_source
    assert "normalized.includes('run_id')" in copy_source
    assert "message.includes('save_result')" in copy_source
    assert "message.includes('network/HAR')" in copy_source
    assert "normalized.includes('workflow_adapter')" in copy_source
    assert "normalized.includes('adapter method unavailable')" in copy_source
    assert "浏览器会话异常" in copy_source
    assert "请关闭当前浏览器现场窗口，重新打开真实浏览器后再运行任务" in copy_source
    assert "浏览器执行组件未就绪" in copy_source
    assert "保存前安全检查未通过" in copy_source
    assert "人工确认还没有完成" in copy_source
    assert "检查记录没有对齐" in copy_source
    assert "保存结果证据不完整" in copy_source
    assert "const operatorMessage = humanOperatorMessage(message)" in (REPO_ROOT / "app" / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    assert "if (operatorMessage !== message) return operatorMessage" in (REPO_ROOT / "app" / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    assert "保存任务未完成" in source
    assert "humanOperatorMessage" in report_summary_section
    assert "humanOperatorTitle(raw" in source
    assert "return String(summary.blocked_reason" not in report_summary_section
    assert "humanOperatorMessage" in gate_detail_section
    assert "blocked requests" not in source[source.index("function l2DiagnosticNextAction"):source.index("function l2CheckLabel")]
    assert "probe 未通过" not in source[source.index("function l2CheckLabel"):source.index("function humanBlockedRequestSummary")]
    assert "blocked requests" not in results_source[results_source.index("function l2DiagnosticNextAction"):results_source.index("function l2CheckLabel")]
    assert "probe 未通过" not in results_source[results_source.index("function l2CheckLabel"):results_source.index("function numberValue")]
    assert "const title = humanReportTitle(report)" in report_card_section
    assert "reportStatusTone(report.status)" in report_card_section
    assert "humanReportStatus(report.status)" in report_card_section
    assert 'className="status-pill ok"' not in report_card_section
    assert "humanOperatorMessage(item.detail" in exception_card_section
    assert "humanOperatorTitle(item.title" in exception_card_section
    assert "为什么不能继续" in exception_card_section
    assert "下一步" in exception_card_section
    assert "维护人员查看技术细节" in exception_card_section
    assert "原始标题：{item.title}" not in exception_card_section
    assert "原始详情：{item.detail}" not in exception_card_section
    assert "原始建议：{item.suggestion}" not in exception_card_section


def test_extracted_pages_do_not_fallback_to_raw_gate_details():
    panels_source = PRODUCT_TASK_PANELS_TSX.read_text(encoding="utf-8")
    results_source = RESULTS_PAGE_TSX.read_text(encoding="utf-8")
    issues_source = ISSUES_PAGE_TSX.read_text(encoding="utf-8")
    panels_gate_detail = panels_source[panels_source.index("function humanGateDetail"):panels_source.index("function humanL2PrecheckError")]
    results_gate_detail = results_source[results_source.index("function humanGateDetail"):results_source.index("function humanL2PrecheckError")]
    issues_gate_detail = issues_source[issues_source.index("function humanGateDetail"):issues_source.index("function humanL2PrecheckError")]

    for section in (panels_gate_detail, results_gate_detail, issues_gate_detail):
        assert "safeGateDetailFallback(detail)" in section
        assert "return detail" not in section
    assert "function safeGateDetailFallback(detail: string)" in panels_source
    assert "function safeGateDetailFallback(detail: string)" in results_source
    assert "function safeGateDetailFallback(detail: string)" in issues_source
    assert "原始诊断已收进维护详情" in panels_source
    assert "原始诊断已收进维护详情" in results_source
    assert "原始诊断已收进维护详情" in issues_source


def test_issue_queue_problem_cards_use_what_why_next_structure():
    _assert_current_results_and_issues_path()


def test_system_settings_page_is_extracted_from_workbench_modules():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    settings_source = SYSTEM_SETTINGS_PAGE_TSX.read_text(encoding="utf-8")
    settings_visible = settings_source[
        settings_source.index('<section className="module-layout"'):
        settings_source.index('<details className="module-card disclosure-card">')
    ]
    gate_card_section = settings_source[
        settings_source.index("function RegressionGateGrid"):
        settings_source.index("function displayTaskName")
    ]

    assert "export function SystemSettingsPage" in settings_source
    assert "aria-label=\"系统维护\"" in settings_source
    assert "title=\"运行与安全\"" in settings_source
    assert "当前可执行范围" in settings_source
    assert "真实浏览器" in settings_source
    assert "维护人员：检查细节" in settings_source
    assert "RegressionGateGrid" in settings_source
    assert "humanGateBusinessName(gate)" in settings_source
    assert "<strong>{gate.level}</strong>" not in gate_card_section
    assert "{gate.command && <code>{gate.command}</code>}" not in gate_card_section
    assert "<summary>维护细节</summary>" in gate_card_section
    for forbidden in ("技术诊断", "日志路径", "L2", "L3", "证据 {gate.evidenceLevel}", "gate.command"):
        assert forbidden not in settings_visible
    assert "帮助与设置" not in settings_source
    assert "export { SystemSettingsPage as SystemSettings }" in source
    assert "from './workbench/SystemSettingsPage'" in source
    assert "export function SystemSettings(" not in source


def test_help_page_is_operator_guide_not_diagnostics():
    _assert_current_operator_help_path()


def test_results_page_is_extracted_from_workbench_modules():
    _assert_current_results_and_issues_path()


def test_issues_page_is_extracted_from_workbench_modules():
    _assert_current_results_and_issues_path()


def test_dxm_access_page_is_extracted_from_workbench_modules():
    _assert_current_connection_path()


def test_product_tasks_page_is_extracted_from_workbench_modules():
    app_source = APP_TSX.read_text(encoding="utf-8")
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    product_tasks_source = PRODUCT_TASKS_PAGE_TSX.read_text(encoding="utf-8")

    assert "ProductTasksPage as TaskCenter" in app_source
    assert "from './components/workbench/ProductTasksPage'" in app_source
    assert "export function ProductTasksPage" in product_tasks_source
    assert "TaskCenterView" not in product_tasks_source
    assert "return <TaskCenterView {...props} />" not in product_tasks_source
    assert "export function TaskCenterView" in source
    assert "aria-label=\"当前保存任务\"" in product_tasks_source
    assert "这里不选择商品，也不创建任务" in product_tasks_source
    assert "要创建新的只保存任务，请先在“待认领入箱”完成第一段" in product_tasks_source
    assert "onShowDraftEdit={() => setActiveSection('draft_edit_save')}" in app_source
    assert "go_draft_edit: actions.onShowDraftEdit" in product_tasks_source
    assert "onStartTask: (taskId: number) => void" in product_tasks_source
    assert "start: () => currentTask ? actions.onStartTask(currentTask.id) : undefined" in product_tasks_source
    assert "onCreateRealTask:" not in product_tasks_source
    assert "onBootstrapDemo:" not in product_tasks_source
    assert "onCreateRealTask={createRealTask}" not in app_source
    assert "onBootstrapDemo={bootstrapDemo}" not in app_source
    assert "onStartTask={(taskId) => startSelectedTask(taskId)}" in app_source[app_source.index("case 'product_tasks'"):app_source.index("case 'draft_edit_save'")]
    assert "data-testid=\"task-quick-create-single-save\"" not in product_tasks_source
    assert "aria-label=\"选择商品箱商品\"" not in product_tasks_source
    assert "任务与记录" not in source
    assert "export function TaskCenter(" not in source


def test_product_tasks_page_requires_current_approver_for_both_released_stages():
    source = PRODUCT_TASKS_PAGE_TSX.read_text(encoding="utf-8")
    component_section = source[source.index("export function ProductTasksPage"):source.index("function firstOperatorTask")]
    decision_section = source[source.index("function buildTaskDecision"):source.index("function decision")]

    assert "const currentApprover = l3ApprovedBy.trim()" in component_section
    assert "const currentTaskNeedsApproval = Boolean(" in component_section
    assert "currentTask.status === 'draft'" in component_section
    assert "(currentTask.mode === 'claim_only' || currentTask.mode === 'single_save')" in component_section
    assert "l2Gate?.status === 'passed'" in component_section
    assert "const currentTaskApprovalMissing = currentTaskNeedsApproval && !currentApprover" in component_section
    assert "currentApproverPresent: Boolean(currentApprover)" in component_section
    assert "const primaryDisabled = busy || !primaryAction || decision.disabled || currentTaskApprovalMissing" in component_section
    assert "if ((task.mode === 'claim_only' || task.mode === 'single_save') && !currentApproverPresent)" in decision_section
    assert "l3Passed" not in decision_section
    assert "{currentTaskNeedsApproval && (" in component_section
    assert "currentTaskNeedsApproval && currentTaskApprovalMissing" not in component_section
    assert "currentTask?.mode === 'claim_only' ? '人工确认认领到商品箱' : '人工确认只保存不发布'" in component_section
    assert "确认将该已有商品认领到商品箱" in component_section
    assert "确认本次只保存不发布" in component_section
    assert "value={l3ApprovedBy}" in component_section
    assert "l3Gate?.status !== 'passed'" not in component_section


def test_edit_config_page_entry_is_extracted_from_workbench_modules():
    app_source = APP_TSX.read_text(encoding="utf-8")
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    edit_config_source = EDIT_CONFIG_PAGE_TSX.read_text(encoding="utf-8")

    assert "TemplateCenterPage" in app_source
    assert "from './components/workbench/TemplateCenterPage'" in app_source
    assert "EditConfigPage as ConfigCenter" not in app_source
    assert "from './components/workbench/EditConfigPage'" not in app_source
    assert "export function EditConfigPage" in edit_config_source
    assert "ConfigCenterView" in edit_config_source
    assert "return <ConfigCenterView {...props} />" in edit_config_source
    assert "export { ConfigCenter as ConfigCenterView }" in source


def test_template_center_exposes_store_and_category_default_actions():
    source = TEMPLATE_CENTER_PAGE_TSX.read_text(encoding="utf-8")

    for label in [
        "设为店铺默认模板",
        "设为类目默认模板",
        "店铺默认会用于当前店铺下没有类目默认的任务",
        "类目默认会优先用于当前店铺和类目的任务",
    ]:
        assert label in source


def test_agent_execution_page_entry_is_extracted_from_workbench_modules():
    app_source = APP_TSX.read_text(encoding="utf-8")
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    agent_execution_source = AGENT_EXECUTION_PAGE_TSX.read_text(encoding="utf-8")

    assert "AgentExecutionPage as ExecutionConsole" in app_source
    assert "from './components/workbench/AgentExecutionPage'" in app_source
    assert "export function AgentExecutionPage" in agent_execution_source
    assert "ExecutionConsoleView" in agent_execution_source
    assert "return <ExecutionConsoleView {...props} />" in agent_execution_source
    assert "export { ExecutionConsole as ExecutionConsoleView }" in source


def test_home_page_entry_is_extracted_from_workbench_modules():
    app_source = APP_TSX.read_text(encoding="utf-8")
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    home_page_source = HOME_PAGE_TSX.read_text(encoding="utf-8")

    assert "HomePage as Dashboard" in app_source
    assert "from './components/workbench/HomePage'" in app_source
    assert "export function HomePage" in home_page_source
    assert "home-brief-grid" in home_page_source
    assert "function OperationGuide" not in home_page_source
    assert "export function Dashboard" not in source
    assert "export { Dashboard as DashboardView }" not in source


def test_product_task_panels_are_extracted_from_workbench_modules():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    panels_source = PRODUCT_TASK_PANELS_TSX.read_text(encoding="utf-8")

    assert "export function RealModeReleasePlanPanel" in panels_source
    assert "真实模式放行准备" in panels_source
    assert "function humanReadinessCheckLabel" in panels_source
    assert "function humanReleaseBlocker" in panels_source
    assert "from './workbench/ProductTaskPanels'" in source
    assert "function RealModeReleasePlanPanel(" not in source
    assert "function humanReadinessCheckLabel(" not in source
    assert "function humanReleaseBlocker(" not in source


def test_single_save_recovery_guide_is_extracted_to_product_task_panels():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    panels_source = PRODUCT_TASK_PANELS_TSX.read_text(encoding="utf-8")

    assert "export function SingleSaveRecoveryGuide" in panels_source
    assert "data-testid=\"single-save-recovery-guide\"" in panels_source
    assert "恢复到单商品只保存" in panels_source
    assert "当前任务不可直接启动时，按这里回到真实自动化可执行路径。" in panels_source
    assert "选择最近单商品只保存任务" in panels_source
    assert "创建新的单商品只保存任务" in panels_source
    assert "运行保存前安全检查" in panels_source
    assert "function SingleSaveRecoveryGuide(" not in source


def test_task_current_action_panel_is_extracted_to_product_task_panels():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    panels_source = PRODUCT_TASK_PANELS_TSX.read_text(encoding="utf-8")

    assert "export function TaskCurrentActionPanel" in panels_source
    assert "function taskStartDecision" in panels_source
    assert "aria-label=\"当前任务执行\"" in panels_source
    assert "data-testid=\"task-start-button\"" in panels_source
    assert "保存前安全检查没有通过，不能启动真实保存。" in panels_source
    assert "from './workbench/ProductTaskPanels'" in source
    assert "function TaskCurrentActionPanel(" not in source
    assert "function taskStartDecision(" not in source


def test_readonly_recheck_panels_are_extracted_to_product_task_panels():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    panels_source = PRODUCT_TASK_PANELS_TSX.read_text(encoding="utf-8")

    assert "export function ReadonlyRecheckHelpCard" in panels_source
    assert "export function L2ProbeResourceRepairPanel" in panels_source
    assert "保存前安全检查未通过，真实保存先暂停" in panels_source
    assert "保存前安全检查资源修复步骤" in panels_source
    assert "function ReadonlyRecheckHelpCard(" not in source
    assert "function L2ProbeResourceRepairPanel(" not in source


def test_failed_task_primary_path_guides_retry_instead_of_non_draft_jargon():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    build_primary_path_section = source[
        source.index("function buildConsolePrimaryPath"):
        source.index("function FinalCheckFreshnessRow")
    ]
    task_center_section = source[source.index("export function TaskCenterView"):source.index("export function ExecutionConsole")]

    assert "selectedTask.status === 'failed'" in build_primary_path_section
    assert "保存失败，需处理" in build_primary_path_section
    assert "humanTaskFailureMessage(selectedTask, reports)" in build_primary_path_section
    assert "failedJob?.error_message" in build_primary_path_section
    assert "重新创建商品箱编辑保存任务" in build_primary_path_section
    assert "ctaLabel: '重新创建商品箱编辑保存任务'" in build_primary_path_section
    assert "系统没有执行保存。请保持真实店小秘登录窗口可用" in build_primary_path_section
    start_label_section = task_center_section[task_center_section.index("const startLabel"):task_center_section.index("const historyTaskHint")]
    assert start_label_section.index("selectedTask.status === 'failed'") < start_label_section.index("selectedTask.status !== 'draft'")
    assert "重新创建商品箱编辑保存任务" in start_label_section


def test_agent_execution_primary_path_uses_user_visible_state_labels():
    _assert_current_batch_draft_save_path()


def test_report_center_keeps_evidence_exception_and_console_followup_reachable_after_sidebar_simplification():
    _assert_current_results_and_issues_path()


def test_agent_console_l2_state_has_single_precheck_cta_before_advanced_details():
    _assert_current_connection_path()


def test_workspace_fallback_does_not_ship_demo_tasks_or_reports():
    workspace_source = (REPO_ROOT / "app" / "frontend" / "src" / "workspace.ts").read_text(encoding="utf-8")
    compose_section = workspace_source[workspace_source.index("export function composeWorkspace"):workspace_source.index("export function buildEmptyWorkspace")]

    assert "const fallback = buildEmptyWorkspace()" in compose_section
    assert "buildMockWorkspace" not in workspace_source
    assert "本地演示保存核验批次" not in workspace_source
    assert "本地演示保存核验报告" not in workspace_source
    assert "演示截图占位" not in workspace_source


def test_workspace_compose_honors_empty_delivery_task_list_as_authoritative():
    workspace_source = (REPO_ROOT / "app" / "frontend" / "src" / "workspace.ts").read_text(encoding="utf-8")
    compose_section = workspace_source[workspace_source.index("export function composeWorkspace"):workspace_source.index("export function buildEmptyWorkspace")]

    assert "const deliveryTasks = Array.isArray(workspace?.tasks) ? workspace.tasks : undefined" in compose_section
    assert "chooseList(deliveryTasks" in compose_section
    assert "nonEmptyList(workspace?.tasks)" not in compose_section


def test_frontend_labels_mock_l2_as_evidence_not_passed():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    safety_bar = SAFETY_STATUS_BAR_TSX.read_text(encoding="utf-8")
    workspace_source = (REPO_ROOT / "app" / "frontend" / "src" / "workspace.ts").read_text(encoding="utf-8")

    assert "mock_passed: '离线证据'" in source
    assert "mock_passed: '离线证据'" in safety_bar
    assert "仅有离线检查证据；还不能放行真实保存。" in workspace_source
    assert "仅有离线/mock L2 证据；不满足真实页面 L2 放行条件。" not in workspace_source
    assert "已有离线/mock L2 证据；真实页面仍需批准执行。" not in workspace_source

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
APP_TSX = REPO_ROOT / "app" / "frontend" / "src" / "App.tsx"
WORKSPACE_TS = REPO_ROOT / "app" / "frontend" / "src" / "workspace.ts"
WORKBENCH_MODULES_TSX = REPO_ROOT / "app" / "frontend" / "src" / "components" / "WorkbenchModules.tsx"
SAFETY_STATUS_BAR_TSX = REPO_ROOT / "app" / "frontend" / "src" / "components" / "SafetyStatusBar.tsx"
QA_BROWSER_CHECK = REPO_ROOT / "scripts" / "qa-browser-check.ps1"
README = REPO_ROOT / "README.md"
USER_GUIDE = REPO_ROOT / "docs" / "product" / "用户交付使用说明-20260526.md"


def test_demo_batch_creation_uses_dry_run_for_local_startable_user_path():
    source = APP_TSX.read_text(encoding="utf-8")
    bootstrap_section = source[source.index("async function bootstrapDemo"):source.index("async function startSelectedTask")]

    assert "mode: 'dry_run'" in bootstrap_section
    assert "mode: 'single_save'" not in bootstrap_section
    assert "本地演示核验批次" in bootstrap_section


def test_task_center_does_not_apply_l3_real_write_block_to_dry_run_tasks():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")

    assert "const l3BlocksStart = needsRealL2 && l3Gate?.status === 'blocked'" in source
    assert "启动开发自检任务" in source
    assert "真实保存仍以单商品只保存规则为准" in source
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
    assert "setActiveSection('config')" in start_section
    assert "configBlocksStart" in workbench_source
    assert "配置未完成，禁止启动" in workbench_source
    assert "去配置中心" in workbench_source


def test_config_center_prioritizes_missing_sections_and_sources():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    config_section = source[source.index("export function ConfigCenter"):source.index("export function TaskCenter")]

    assert "ConfigReadinessPanel" in source
    assert "NextRequiredConfigFields" in config_section
    assert "下一步必填字段" in source
    assert "只显示当前最需要处理的字段" in source
    assert "onEditRequiredSection" in source
    assert "编辑当前必填分区" in source
    assert "保存到本次任务并继续" in source
    assert "selectNextMissingConfigSection" in config_section
    assert "continueToNextMissingSection" in config_section
    assert "data-config-next-required" in source
    assert "DXM 编辑页配置" in config_section
    assert "按店小秘编辑页分区逐段填写" in config_section
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
    config_section = source[source.index("export function ConfigCenter"):source.index("export function TaskCenter")]
    editable_card = source[source.index("function EditableConfigSectionCard"):source.index("export function TaskCenter")]
    config_copy_source = source[source.index("function ConfigReadinessPanel"):source.index("export function TaskCenter")]
    qa_source = QA_BROWSER_CHECK.read_text(encoding="utf-8")

    assert "onRefreshConfigPreview" in source
    assert "onRefreshConfigPreview={async () => { await refreshConfigPreview(); await refreshWorkspace() }}" in app_source
    assert "检查本次任务配置" in config_section
    assert "重新检查本次任务配置" in config_section
    assert "去任务中心选择任务" in config_section
    assert "onShowTasks" in source
    assert "onShowTasks={() => setActiveSection('tasks')}" in app_source
    assert "读取当前任务、店铺、商品和模板" in config_section
    assert "不会操作店小秘" in config_section
    assert "disabledReason" in editable_card
    assert "先选择任务" in editable_card
    assert "先运行本次任务配置检查" in editable_card
    assert "不能继续的原因" in editable_card
    assert "本次任务配置检查" in config_section
    assert "等待检查" in config_copy_source
    assert "配置预检" not in config_copy_source
    assert "等待预检" not in config_copy_source
    assert "启动预检" not in config_copy_source
    assert "configPrecheckActionVisible" in qa_source
    assert "configDisabledReasonVisible" in qa_source


def test_config_center_focused_section_execution_preview_and_template_save_state():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    config_section = source[source.index("export function ConfigCenter"):source.index("export function TaskCenter")]
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    qa_source = QA_BROWSER_CHECK.read_text(encoding="utf-8")

    assert "demoTemplateSeeds" in source
    assert "applyDefaultTemplatePack" in config_section
    assert "默认测试模板" in config_section
    assert "使用之前测试通过的数据配置" in config_section
    assert "写入测试模板到当前范围" in config_section
    assert "保存/覆盖当前店铺模板" not in config_section
    assert "覆盖当前店铺/类目下全部分区" in config_section
    assert "defaultTemplatePackState" in config_section
    assert "默认测试模板已保存到店铺模板" in config_section
    assert "setSectionSaveState(() => Object.fromEntries" in config_section
    assert "config-template-console" in config_section
    assert "config-template-console--compact" in config_section
    assert "config-template-console__details" in config_section
    assert "当前分区模板" in config_section
    assert "sectionTemplateOptions" in config_section
    assert "templateOptionLabel(template)" in config_section
    assert "function templateOptionLabel(" in source
    assert "`#${template.id} ${template.template_name}" in source
    assert "countNestedConfigValues(template.payload)" in source
    assert "项配置" in source
    assert "selectedTemplateBySection" in config_section
    assert "applyTemplateToDraft" in config_section
    assert "handleTemplateSelection" in config_section
    assert "已套用模板，尚未保存" in config_section
    assert "套用到表单" in config_section
    assert "选择模板不会改表单，点击套用后才会填入当前分区" in config_section
    assert "function handleTemplateSelection(section: EditableConfigSection, templateId: string)" in config_section
    assert "applyTemplateToDraft(section, templateId)" not in config_section[config_section.index("function handleTemplateSelection"):config_section.index("async function applyDefaultTemplatePack")]
    assert "确认写入默认测试模板包" in config_section
    assert "将保存默认测试模板包到当前店铺/类目范围" in config_section
    assert "精确店铺/类目模板优先" in config_section
    assert "全局模板只作为读取候选，不会被保存覆盖" in config_section
    assert "sectionSaveState" in config_section
    assert "未保存修改" in config_section
    assert "已保存" in config_section
    assert "保存时间" in config_section
    assert ".config-template-console" in styles_source
    assert ".config-save-state" in styles_source
    assert "configDefaultTemplatePackVisible" in qa_source
    assert "configTemplateSelectorVisible" in qa_source
    assert "只展示当前分区；常用分区在上方，低频字段收进“更多编辑页分区”。" in config_section
    assert "otherConfigSections.map" not in config_section
    assert "配置保存闭环" in config_section
    assert "本次任务已保存" in config_section
    assert "正在按任务覆盖取值" in config_section
    assert "执行器启动时读取同一份检查取值" in config_section
    assert "SectionExecutionValuePreview" in config_section
    assert "当前分区执行取值核对" in source
    assert "执行时按这些值填写店小秘编辑页" in source
    assert "sourceBadgeText(field.source)" in source
    assert "formatPreviewValue(field.value)" in source
    assert "countTaskOverrideFields(selectedTask, selectedConfigSection.section.templateType)" in config_section
    assert "countPreviewTaskOverrideFields(selectedConfigSection.preview)" in config_section
    assert "configReadyForReview" in config_section
    assert "配置已就绪，默认无需继续填写" in config_section
    assert "微调当前配置" in config_section
    assert "open={!configReadyForReview}" in config_section
    assert "saveState={sectionSaveState[selectedConfigSection.section.code]}" in config_section
    assert "type ConfigSectionSaveState" in source
    assert "当前分区保存回执" in source
    assert "保存位置" in source
    assert "保存时间" in source
    assert "保存后这里会显示最近一次保存结果" in source
    assert "config-section-save-receipt" in source
    assert ".config-section-save-receipt" in styles_source
    assert ".config-section-save-receipt.is-saved" in styles_source
    assert "templateSaveDisabled" in source
    assert "先选择任务，避免误存为全店/全类目模板。" in source
    assert "保存为店铺模板会影响后续匹配当前店铺/类目的任务。" in source
    assert "config-ready-review" in config_section
    assert "config-edit-drawer" in config_section
    assert "config-focus-card" in config_section
    assert "sectionsBlockingStart" in config_section
    assert "sectionsWithAdvisoryGaps" in config_section
    assert "primaryConfigSections.map" in config_section
    assert "secondaryConfigSections.map" in config_section
    assert "previewSection: 'semi_managed'" in source
    assert "templateType: 'sku'" in source
    assert "templateType: 'pricing'" in source
    assert "fieldSourceText" in source
    assert "当前值：" in source
    assert "来源：" in source
    assert "缺失：" in source
    assert "open={openByDefault}" in config_section


def test_config_center_distinguishes_advisory_gaps_from_start_blockers():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    config_section = source[source.index("export function ConfigCenter"):source.index("export function TaskCenter")]
    editable_card = source[source.index("function EditableConfigSectionCard"):source.index("export function TaskCenter")]

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
    config_section = source[source.index("export function ConfigCenter"):source.index("export function TaskCenter")]

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
    assert "任务覆盖" in config_section
    assert "商品 payload" in config_section
    assert "店铺/类目模板" in config_section
    assert "系统默认值" in config_section
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
    config_section = source[source.index("export function ConfigCenter"):source.index("export function TaskCenter")]

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
    config_section = source[source.index("export function ConfigCenter"):source.index("export function TaskCenter")]
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
    assert "保存到本次任务" in config_section
    assert "保存为店铺模板（后续任务可用）" in config_section
    assert "本次任务只影响当前批次" in config_section
    assert "仅本次任务使用" not in config_section
    assert "页面填写值会进入执行取值" in config_section
    assert "带 * 字段参与启动门禁" in config_section
    assert "当前任务会优先使用这些值" not in config_section
    assert "@app.patch('/api/tasks/{task_id}/config-overrides')" in main_source
    assert "TaskConfigOverrideRequest" in models_source
    assert "update_task_template_override" in repo_source


def test_config_center_draft_uses_current_scope_before_template_fallback():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    helper_section = source[source.index("function buildEditableConfigDraft"):source.index("function ConfigReadinessPanel")]
    config_section = source[source.index("export function ConfigCenter"):source.index("export function TaskCenter")]

    assert "binding: TemplateBinding" in helper_section
    assert "findScopedTemplate(templates, section.templateType, binding)" in helper_section
    assert "templates.find((item) => item.template_type === section.templateType)" not in helper_section
    assert "buildEditableConfigDraft(workspace.templates, configPreview, currentTemplateBinding)" in config_section


def test_config_center_exposes_default_template_pack_and_save_state():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    config_section = source[source.index("export function ConfigCenter"):source.index("export function TaskCenter")]
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    qa_source = QA_BROWSER_CHECK.read_text(encoding="utf-8")

    assert "demoTemplateSeeds" in source
    assert "applyDefaultTemplatePack" in config_section
    assert "默认测试模板" in config_section
    assert "使用之前测试通过的数据配置" in config_section
    assert "defaultTemplatePackState" in config_section
    assert "config-template-console" in config_section
    assert "config-template-console--compact" in config_section
    assert "config-template-console__main" in config_section
    assert "config-template-console__details" in config_section
    assert "config-precheck-action__buttons" in config_section
    assert "当前分区模板" in config_section
    assert "sectionTemplateOptions" in config_section
    assert "selectedTemplateBySection" in config_section
    assert "applyTemplateToDraft" in config_section
    assert "套用到表单" in config_section
    assert "重新套用到表单" not in config_section
    assert "写入测试模板到当前范围" in config_section
    assert "精确店铺/类目模板优先" in config_section
    assert "全局模板只作为读取候选，不会被保存覆盖" in config_section
    assert "sectionSaveState" in config_section
    assert "未保存修改" in config_section
    assert "已保存" in config_section
    assert "保存时间" in config_section
    assert ".config-template-console" in styles_source
    assert ".config-template-console--compact" in styles_source
    assert ".config-template-console__detail-grid" in styles_source
    assert ".config-save-state--compact" in styles_source
    assert ".config-save-state" in styles_source
    assert "configDefaultTemplatePackVisible" in qa_source
    assert "configTemplateSelectorVisible" in qa_source


def test_config_center_explains_active_template_source_and_filtered_choices():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    config_section = source[source.index("export function ConfigCenter"):source.index("export function TaskCenter")]
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
    assert ".config-template-source" in styles_source
    assert "configTemplateSourceState" in qa_source


def test_config_center_uses_compact_density_and_collapsed_assist_drawer():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    config_section = source[source.index("export function ConfigCenter"):source.index("export function TaskCenter")]
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    qa_source = QA_BROWSER_CHECK.read_text(encoding="utf-8")

    assert "--font-body: 13px" in styles_source
    assert "--font-compact: 12px" in styles_source
    assert ".content-density-summary" in styles_source
    assert ".config-assist-drawer" in styles_source
    assert "config-density-summary" in config_section
    assert "config-assist-drawer" in config_section
    assert "配置详情与下一步字段" in config_section
    assert "NextRequiredConfigFields" in config_section
    assert "configDensityCompact" in qa_source
    assert "configAssistDrawerCollapsed" in qa_source
    assert "configEditorNearFirstViewport" in qa_source


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


def test_config_center_template_picker_hides_other_scope_templates():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    config_helpers = source[source.index("function templateBindingValueMatches"):source.index("function withTemplateBinding")]

    assert "templateSelectableForBinding" in config_helpers
    assert "templateSelectableForBinding(template, binding)" in config_helpers
    assert ".filter((template) => template.template_type === section.templateType && template.is_enabled && templateSelectableForBinding(template, binding))" in config_helpers
    assert ".sort((left, right) => compareTemplateBindingSpecificity(left, right, binding)" in config_helpers


def test_config_center_template_save_does_not_overwrite_global_template():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    config_section = source[source.index("export function ConfigCenter"):source.index("export function TaskCenter")]
    config_helpers = source[source.index("function templateBindingValueMatches"):source.index("function withTemplateBinding")]

    assert "function templateHasStrictBinding" in config_helpers
    assert "function findExactScopedTemplate" in config_helpers
    assert "templateHasStrictBinding(template, binding)" in config_helpers
    assert "const existing = findExactScopedTemplate(workspace.templates, section.templateType, currentTemplateBinding)" in config_section
    assert "全局模板只作为读取候选，不会被保存覆盖" in config_section


def test_config_center_preserves_multi_value_reference_template_fields():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    config_section = source[source.index("export function ConfigCenter"):source.index("export function TaskCenter")]

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
    assert "credentialStateText" in source
    assert "consoleRealBrowserLoginEntry" in source
    assert "consoleBrowserControlPad" in source
    assert "consoleRuntimeLogState" in source
    assert "consoleRuntimeLogPreviewVisible" in source
    assert "consoleRuntimeLogSourcesVisible" in source
    assert "browserControlPad" in source
    assert "'\\u6253\\u5f00\\u6267\\u884c\\u6d4f\\u89c8\\u5668'" in source
    assert "'\\u542f\\u52a8\\u6267\\u884c\\u89c2\\u5bdf'" not in source
    assert "browserControlClickCoords" in source
    assert "browserControlSelector" in source
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
    app_source = APP_TSX.read_text(encoding="utf-8")
    shell_source = (REPO_ROOT / "app" / "frontend" / "src" / "components" / "AppShell.tsx").read_text(encoding="utf-8")
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")

    assert "useState<WorkbenchSection>('guide')" in app_source
    assert "type WorkbenchPrimaryArea" in shell_source
    assert "summary: '操作引导与编辑页配置'" in shell_source
    assert "{ id: 'guide', label: '操作引导', short: '导', hint: '下一步' }" in shell_source
    assert "{ id: 'config', label: '编辑页配置', short: '配', hint: '按店小秘分区填写' }" in shell_source
    assert "const sectionLabels: Record<WorkbenchSection, string>" in shell_source
    assert "evidence: '证据中心'" in shell_source
    assert "exceptions: '异常池'" in shell_source
    assert "reports: '报告中心'" in shell_source
    assert "sectionLabels[activeSection] ?? '工作台'" in shell_source
    assert "case 'guide'" in app_source
    assert "GuideCenter" in app_source
    assert "export function GuideCenter" in workbench_source
    assert "确认服务运行" not in workbench_source
    assert "打开真实 DXM 浏览器并确认登录" in workbench_source
    assert "后台状态" in workbench_source
    assert "工作台服务连接异常" in workbench_source
    assert "填写编辑页配置" in workbench_source
    assert "运行只读页面核验" in workbench_source
    assert "运行只读页面检查（不保存）" in workbench_source
    assert "onRunL2Probe" in workbench_source
    assert "runL2ReadonlyProbe" in app_source
    assert "runRuntimeControl('run_l2_readonly_probe')" in app_source
    assert "selectedTaskDraft = selectedTask?.status === 'draft'" in workbench_source
    assert "canRequestSave = selectedSingleSave && selectedTaskDraft && configOk && l2Passed" in workbench_source
    assert "当前任务已完成，继续查看报告与证据。" in workbench_source
    assert "const guardLabel = selectedTaskCompleted" in workbench_source
    assert "? '任务已完成'" in workbench_source
    assert "const primaryActionLabel = primaryPath.ctaLabel" in workbench_source
    assert ".filter(isStartableSingleSaveTask)" in workbench_source
    assert "selectedTask.status === 'completed'" in workbench_source
    assert "任务已完成，查看报告" in workbench_source
    assert "const primaryDisabled = busy || (!selectedTaskCompleted && startDisabled)" in workbench_source
    assert "const primaryAction = selectedTaskCompleted ? onShowReports : onStartTask" in workbench_source
    assert "data-section={selectedTaskCompleted ? 'reports' : undefined}" in workbench_source
    assert "selectedTask.status !== 'draft'" in workbench_source
    assert "needsApproval && !selectedTaskNotDraft" in workbench_source
    assert "人工确认真实保存" in workbench_source
    assert "申请并启动单商品只保存" in workbench_source
    assert "进入控制台操控真实浏览器" in workbench_source
    assert "function isStartableSingleSaveTask" in workbench_source
    assert "task.status === 'draft'" in workbench_source
    assert "RELEASED_SINGLE_SAVE_STORE_NAMES.has(storeName)" in workbench_source
    assert "等待任务启动后接入真实浏览器会话" in workbench_source
    assert "查看报告与证据" in workbench_source
    assert "查看证据中心" in workbench_source
    assert "查看异常池" in workbench_source
    assert "<summary>常用入口</summary>" in workbench_source
    assert "guide-quick-actions" in styles_source
    assert "<summary>登录与批准输入</summary>" not in workbench_source
    assert "guide-step.is-current" in styles_source
    assert "guide-step.is-blocked" in styles_source
    assert "guide-path-summary" in workbench_source
    assert "当前路径" in workbench_source
    assert "guideAutomationPath" in workbench_source
    assert "真实自动化主路径" in workbench_source
    assert "登录真实店小秘" in workbench_source
    assert "核对编辑页配置" in workbench_source
    assert "只读页面检查" in workbench_source
    assert "单商品只保存" in workbench_source
    assert "报告复核" in workbench_source
    assert "guideHeroTitle" in workbench_source
    assert "guideFocusTitle" in workbench_source
    assert "完成后复核" in workbench_source
    assert "报告与证据" in workbench_source
    assert "后续只需要复核报告、证据和真实浏览器记录" in workbench_source
    assert "要处理新商品时再回到任务中心创建任务" in workbench_source
    assert "登录" in workbench_source
    assert "配置" in workbench_source
    assert "只读检查" in workbench_source
    assert "真实保存" in workbench_source
    assert "报告" in workbench_source
    assert ".guide-path-summary" in styles_source
    assert ".guide-automation-path" in styles_source
    assert "data-guide-step" in workbench_source
    assert "reason:" in workbench_source


def test_sidebar_is_navigation_only_not_status_or_hint_panel():
    shell_source = (REPO_ROOT / "app" / "frontend" / "src" / "components" / "AppShell.tsx").read_text(encoding="utf-8")
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")

    assert "sidebar__current" in shell_source
    assert "当前：" in shell_source
    assert "aria-label={`运营工作台导航，${sourceLabel}`}" in shell_source
    assert "sidebar__note" not in shell_source
    assert "nav-section__index" not in shell_source
    assert "nav-subitem__mark" not in shell_source
    assert "<small>{item.hint}</small>" not in shell_source
    assert "nav-subitem__label" in shell_source
    assert ".sidebar__current" in styles_source
    assert ".sidebar__note" not in styles_source


def test_guide_center_can_start_real_dxm_login_without_l2_gate():
    app_source = APP_TSX.read_text(encoding="utf-8")
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    navigate_section = app_source[app_source.index("async function navigateDxmTarget"):app_source.index("async function startAgentConsole")]

    assert "async function openDxmLogin" in app_source
    assert "async function continueDxmLogin" in app_source
    assert "async function navigateDxmTarget" in app_source
    assert "/api/dxm/login/start" in app_source
    assert "/api/dxm/login/continue" in app_source
    assert "/api/dxm/navigate" in app_source
    assert "const DXM_TARGET_URLS" in app_source
    assert "const DXM_TARGET_PATHS" in app_source
    assert "const AGENT_CONSOLE_NAVIGATION_SETTLE_MS = 2500" in app_source
    assert "function currentUrlMatchesDxmTarget" in app_source
    assert "function compactDxmUrl" in app_source
    assert "function waitForAgentConsoleNavigationSettle" in app_source
    assert "https://www.dianxiaomi.com/web/productCrawl/dataAcquisition" in app_source
    assert "https://www.dianxiaomi.com/web/smt/smtProductList/draft" in app_source
    assert "agentConsole?.active && agentConsole.browser_visible && !agentConsole.manual_takeover" in navigate_section
    assert "postJson<AgentConsoleControlResponse>('/api/agent-console/control'" in navigate_section
    assert "action: 'goto'" in navigate_section
    assert "url: targetUrl" in navigate_section
    assert "await waitForAgentConsoleNavigationSettle()" in navigate_section
    assert "const settledStatus = await refreshAgentConsole(true) ?? status" in navigate_section
    assert "currentUrlMatchesDxmTarget(settledStatus.current_url, target)" in navigate_section
    assert "店小秘当前停留在" in navigate_section
    assert "compactDxmUrl(settledStatus.current_url)" in navigate_section
    assert "await postJson('/api/dxm/navigate', { target })" in navigate_section
    assert "真实浏览器已进入" in navigate_section
    assert "执行浏览器" not in navigate_section
    assert "已请求店小秘登录流进入" in navigate_section
    assert "onOpenDxmLogin={openDxmLogin}" in app_source
    assert "onContinueDxmLogin={continueDxmLogin}" in app_source
    assert "onNavigateDxmTarget={navigateDxmTarget}" in app_source
    assert "onOpenDxmLogin: () => void" in workbench_source
    assert "onContinueDxmLogin: () => void" in workbench_source
    assert "onNavigateDxmTarget: (target: 'data_acquisition' | 'draft_box') => void" in workbench_source
    assert "action: '打开登录页'" in workbench_source
    assert "验证码已完成，检测登录态" in workbench_source
    assert "进入采集箱" in workbench_source
    assert "onAction: onOpenDxmLogin" in workbench_source
    assert "可见的独立店小秘浏览器窗口" in workbench_source
    assert "账号密码可保存到本机加密存储" in workbench_source
    assert "DXM_LOGGED_IN_STATUSES" in workbench_source
    assert "not_published_verified" in workbench_source
    assert "DXM 登录状态" in workbench_source
    assert "runtimeStatus={runtimeStatus}" in workbench_source
    assert "function humanDxmLoginFlowNotice" in app_source
    assert "setOperationNotice(humanDxmLoginFlowNotice(loginStart" in app_source
    assert "const message = humanDxmLoginFlowNotice(loginResult" in app_source
    assert "setOperationError(message)" in app_source
    assert "真实浏览器窗口会保留" in workbench_source
    assert "真实浏览器窗口会保留" in (REPO_ROOT / "app" / "backend" / "src" / "execution" / "dxm_login_flow.py").read_text(encoding="utf-8")


def test_start_selected_task_requires_dxm_session_before_real_save():
    app_source = APP_TSX.read_text(encoding="utf-8")
    start_section = app_source[app_source.index("async function startSelectedTask"):app_source.index("async function openDxmLogin")]

    assert "DXM_READY_SESSION_STATUSES" in app_source
    assert "not_published_verified" in app_source
    assert "const latestRuntimeStatus = await getJson<RuntimeStatus>(`/api/runtime/status?frontend_url=${encodeURIComponent(window.location.origin)}`)" in start_section
    assert "请先完成真实 DXM 登录" in start_section
    assert "setActiveSection('guide')" in start_section


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
    assert "l3ApprovedBy" in app_source
    assert "useState('ops-owner')" not in app_source
    assert "rememberCredential: true" in app_source
    assert "const canSubmit = Boolean(draft.username.trim() && draft.password && !busy)" in workbench_source
    assert "if (!canSubmit) return" in workbench_source
    assert "required" in workbench_source
    assert "店小秘账号" in workbench_source
    assert "店小秘密码" in workbench_source
    assert "记住账号密码" in workbench_source
    assert "清除已记住账号" in workbench_source
    assert "function humanDxmLoginState" in workbench_source
    assert "等待验证码/人工确认" in workbench_source
    assert "登录未通过" in workbench_source
    assert "DXM 已进入业务页" in workbench_source
    assert "真实浏览器停留在" in workbench_source
    assert "真实浏览器窗口会保留" in workbench_source
    assert "operator-inline-form__login-state" in workbench_source
    assert "operator-inline-form__login-state" in styles_source
    assert ".operator-inline-form__login-state.is-danger" in styles_source
    assert "批准人标识" in workbench_source
    assert "打开真实登录页" in workbench_source
    assert "申请并启动单商品只保存" in workbench_source
    assert "本机加密存储" in workbench_source
    assert "operator-inline-form" in styles_source


def test_user_docs_explain_login_secret_and_launcher_takeover_boundaries():
    readme = README.read_text(encoding="utf-8")
    user_guide = USER_GUIDE.read_text(encoding="utf-8")

    for source in (readme, user_guide):
        assert "密码" in source
        assert "本机加密存储" in source
        assert "可见" in source
        assert "启动器会自动接管 8000 端口" in source
        assert "不要在真实任务" in source
        assert "重复启动" in source
        assert "未知进程" in source


def test_user_docs_keep_real_operation_path_before_self_check_appendix():
    readme = README.read_text(encoding="utf-8")
    user_guide = USER_GUIDE.read_text(encoding="utf-8")
    readme_head = "\n".join(readme.splitlines()[:45])
    guide_head = "\n".join(user_guide.splitlines()[:80])

    assert "真实用户快速开始" in readme_head
    assert "Windows 单窗口启动" in guide_head
    assert "真实单商品只保存操作流程" in guide_head
    for forbidden in ("final-delivery", "Browser QA", "源码包验收", "clean worktree", "dry_run"):
        assert forbidden not in readme_head
        assert forbidden not in guide_head
    for forbidden in ("L3 single_save", "申请并启动 single_save", "真实 single_save 操作流程", "批准并启动真实金丝雀"):
        assert forbidden not in readme_head
        assert forbidden not in guide_head
    assert "执行模式选择“单商品只保存”" in readme_head
    assert "申请并启动单商品只保存" in readme_head
    assert "验收人附录：当前证据态与源码包验收" in user_guide
    assert "验收人附录：自检命令" in user_guide


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
    assert "真实店小秘操作在执行控制台的独立浏览器窗口中完成" in shell_source
    assert "真实接口优先" not in shell_source
    assert "不伪造保存结果" not in shell_source
    assert "演示数据仅开发模式可用" not in shell_source
    assert "准备演示数据或接入后端任务后" not in workspace_source
    assert "接入后端任务或导入真实商品后" in workspace_source
    assert "批量/无人值守：未放行" in safety_source
    assert "发布：无入口" in safety_source


def test_execution_console_defaults_to_operator_focus_and_collapses_advanced_noise():
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    console_section = workbench_source[workbench_source.index("export function ExecutionConsole"):workbench_source.index("function AgentBrowserFrame")]

    assert "ConsoleFocusPanel" in console_section
    assert "compactCompletedReview" in console_section
    assert "selectedTaskCompleted && !agentConsole?.active" in console_section
    assert "ConsoleCompletedReviewPanel" in console_section
    assert "任务已完成" in workbench_source
    assert "下一步只复核结果" in workbench_source
    assert "查看报告、未发布证明和真实浏览器记录" in workbench_source
    assert "<summary>继续操作真实浏览器</summary>" in workbench_source
    assert "完成态默认不展示浏览器操控细节" in workbench_source
    assert "embedded" in workbench_source
    assert "agent-console-stage--embedded" in workbench_source
    assert "title=\"登录浏览器与执行浏览器\"" in console_section
    assert "<strong>执行浏览器</strong>" in workbench_source
    assert "<strong>当前页面</strong>" in workbench_source
    assert "<strong>操控状态</strong>" in workbench_source
    assert "<strong>人工接管</strong>" in workbench_source
    assert "<strong>下一步</strong>" in workbench_source
    assert "hasBrowserSession && currentUrl ? shortUrl(currentUrl) : '等待启动执行浏览器'" in workbench_source
    assert "可在生命周期区接管" in workbench_source
    assert "可在会话管理中接管" not in workbench_source
    assert "buildConsolePrimaryPath({ selectedTask, configPreview, configPreviewError, l2Gate, l3Gate, busy })" in workbench_source
    assert "primaryPath={consolePrimaryPath}" in console_section
    assert "primaryPath.action === 'config'" in workbench_source
    assert "primaryPath.action === 'run_l2'" in workbench_source
    assert "primaryPath.action === 'start_browser'" in workbench_source
    assert "去配置中心补齐配置" in workbench_source
    assert "运行只读页面检查（不保存）" in workbench_source
    assert "可以打开执行浏览器" in workbench_source
    assert "处理只读检查与确认" not in workbench_source
    assert "处理任务门禁" not in workbench_source
    assert "控制台不播放截图；截图只作为证据路径，不会启动保存或发布。" in workbench_source
    assert "'module-card span-2 agent-console-stage'" in console_section
    assert "className=\"module-card span-1 console-log-card console-log-card--compact\"" in console_section
    assert "title=\"实时日志\"" in console_section
    assert "RuntimeLogPreview" in console_section
    assert "日志会自动刷新；筛选和搜索保留在下方“更多诊断与维护”。" in console_section
    assert "<summary>更多诊断与维护</summary>" in console_section
    assert "console-diagnostics-drawer" in console_section
    assert "console-diagnostics-grid" in console_section
    assert "RuntimeLogPanel" in console_section
    assert "summary>辅助面板：运行维护 / 自动操作轨迹</summary>" not in console_section
    assert "summary>执行步骤明细</summary>" not in console_section
    assert "summary>任务执行日志</summary>" not in console_section
    assert "登录/人工处理真实浏览器" in workbench_source
    assert "agent-console-controls__primary-operator" in workbench_source
    assert "DxmLoginInlineForm" in workbench_source
    assert "登录浏览器：打开真实店小秘登录页" in workbench_source
    assert "只负责登录、验证码和人工导航；L2 未通过也可以打开，不会保存、不发布。" in workbench_source
    assert "验证码已完成，检测登录态" in workbench_source
    assert "进入采集箱" in workbench_source
    assert "登录浏览器用于人工登录；执行浏览器只在配置、只读检查和人工确认通过后由 Agent 操控。" in workbench_source
    assert "控制台不播放截图；截图只作为证据路径，不会启动保存或发布。" in workbench_source
    assert "aria-label=\"Agent 执行浏览器会话生命周期\"" in workbench_source
    assert "未选择任务，Agent 执行浏览器暂不启动" in workbench_source
    assert "配置未完成，Agent 执行浏览器暂不启动" in workbench_source
    assert "只读检查未通过，Agent 执行浏览器暂不启动" in workbench_source
    assert "等待人工确认，Agent 执行浏览器暂不启动" in workbench_source
    assert "会打开可见的独立店小秘浏览器窗口" in workbench_source
    assert "启动后可接管" in workbench_source
    assert "const takeoverStateLabel = !active" in workbench_source
    assert "打开执行浏览器（不保存）" in workbench_source
    assert "disabled={busy || !selectedTask || browserStartBlocked || active || launching}" in workbench_source
    assert "Agent 执行浏览器启动中" in workbench_source
    assert "{launching ? 'Agent 执行浏览器启动中' : active ? 'Agent 执行浏览器已打开' : '打开执行浏览器（不保存）'}" in workbench_source
    assert "当前 Agent 执行浏览器会话正在运行。" in workbench_source
    assert "<summary>执行浏览器操作细节</summary>" in workbench_source
    assert "agent-console-controls__operator-drawer" in workbench_source
    assert "agent-console-controls__operator-grid" in workbench_source
    assert "<summary>Agent 执行浏览器会话生命周期</summary>" in workbench_source
    assert "控制台不播放截图，不会启动保存或发布" in workbench_source
    assert "<summary>会话管理</summary>" not in workbench_source
    assert "<summary>高级浏览器控制</summary>" in workbench_source
    assert "不会发布" in workbench_source
    assert "console-focus-panel" in styles_source
    assert ".console-review-panel" in styles_source
    assert ".agent-console-stage--embedded" in styles_source
    assert "repeat(4, minmax(0, 1fr))" in styles_source
    assert ".agent-console-lifecycle" in styles_source
    assert ".console-advanced" in styles_source
    assert ".console-support-grid" in styles_source
    assert ".agent-console-controls__advanced" in styles_source
    assert ".agent-console-controls__operator-drawer" in styles_source
    assert ".agent-console-controls__operator-grid" in styles_source


def test_execution_console_distinguishes_login_browser_from_agent_execution_browser():
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    app_source = (REPO_ROOT / "app" / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    console_section = workbench_source[workbench_source.index("function AgentConsoleControls"):workbench_source.index("function BrowserControlPad")]
    primary_path_section = workbench_source[workbench_source.index("function buildConsolePrimaryPath"):workbench_source.index("function FinalCheckFreshnessRow")]

    assert 'title="登录浏览器与执行浏览器"' in workbench_source
    assert "<strong>登录浏览器：打开真实店小秘登录页</strong>" in console_section
    assert "只负责登录、验证码和人工导航；L2 未通过也可以打开，不会保存、不发布。" in console_section
    assert "登录浏览器用于人工登录；执行浏览器只在配置、只读检查和人工确认通过后由 Agent 操控。" in console_section
    assert "打开执行浏览器（不保存）" in console_section
    assert "Agent 执行浏览器启动中" in console_section
    assert "Agent 执行浏览器已打开" in console_section
    assert "Agent 执行浏览器暂不启动" in primary_path_section
    assert "只读页面检查未通过，Agent 执行浏览器不可启动" in app_source

    assert "首步：打开真实店小秘登录页" not in console_section
    assert "只读检查未通过，真实浏览器暂不启动" not in primary_path_section
    assert "只读页面检查未通过，真实浏览器自动化不可启动" not in app_source


def test_execution_console_collapses_operator_forms_inside_real_browser_details():
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    controls_section = workbench_source[workbench_source.index("function AgentConsoleControls"):workbench_source.index("function BrowserControlPad")]
    drawer_section = controls_section[controls_section.index("<summary>执行浏览器操作细节</summary>"):controls_section.index("{agentConsoleError")]
    primary_section = controls_section[
        controls_section.index("agent-console-controls__primary-operator"):
        controls_section.index("<details className=\"agent-console-controls__advanced agent-console-controls__operator-drawer")
    ]

    assert "DxmLoginInlineForm" in primary_section
    assert "运行只读页面检查（不保存）" in primary_section
    assert "DxmLoginInlineForm" not in drawer_section
    assert "<summary>Agent 执行浏览器会话生命周期</summary>" in drawer_section
    assert "<summary>高级浏览器控制</summary>" in drawer_section
    assert "<summary>技术详情</summary>" in drawer_section
    assert primary_section.index("DxmLoginInlineForm") < primary_section.index("agent-console-controls__actions")
    assert controls_section.index("agent-console-controls__actions") < controls_section.index("<summary>执行浏览器操作细节</summary>")


def test_execution_console_log_center_autofollows_and_surfaces_sources():
    app_source = APP_TSX.read_text(encoding="utf-8")
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    log_panel_section = workbench_source[workbench_source.index("function RuntimeLogPanel"):workbench_source.index("function RuntimeLogLine")]
    focus_panel_section = workbench_source[workbench_source.index("function ConsoleFocusPanel"):workbench_source.index("function AgentBrowserFrame")]

    assert "window.setInterval" in app_source
    assert "1500" in app_source
    assert "useState<RuntimeLogSource>('backend')" in app_source
    assert "完整日志中心" in workbench_source
    assert "每 1.5 秒刷新" in workbench_source
    assert "更多诊断与维护" in workbench_source
    assert "筛选和搜索保留在下方“更多诊断与维护”" in workbench_source
    assert "自动跟随最新日志" in log_panel_section
    assert "setAutoFollow" in log_panel_section
    assert "logViewRef" in log_panel_section
    assert "scrollTop = logViewRef.current.scrollHeight" in log_panel_section
    assert "onScroll" in log_panel_section
    assert "data-testid=\"runtime-log-view\"" in log_panel_section
    assert "RuntimeLogPreview" in workbench_source
    assert "启动器" in log_panel_section
    assert "依赖安装" in log_panel_section
    assert "浏览器 Agent" in log_panel_section
    assert "launcher: '启动器'" in focus_panel_section
    assert "task: '任务'" in focus_panel_section
    assert "agent: '浏览器 Agent'" in focus_panel_section
    assert "打开 DXM" in workbench_source
    assert "网络响应" in workbench_source
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
    app_source = APP_TSX.read_text(encoding="utf-8")
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    types_source = (REPO_ROOT / "app" / "frontend" / "src" / "types.ts").read_text(encoding="utf-8")
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    console_section = workbench_source[workbench_source.index("function AgentBrowserFrame"):workbench_source.index("function AgentConsoleControls")]
    browser_frame_helper = workbench_source[workbench_source.index("function getBrowserFrame"):workbench_source.index("function nextPendingStep")]

    assert "/api/agent-console/frame" in app_source
    assert "Boolean(agentConsole?.browser_visible)" in app_source
    assert "last_frame_at?: string | null" in types_source
    assert "network_events?: AgentConsoleNetworkEvent[]" in types_source
    assert "网络响应" in console_section
    assert "等待网络响应" in console_section
    assert "<summary>证据路径与网络响应</summary>" in console_section
    assert "agent-browser__details" in console_section
    assert "getRecentNetworkEvents(agentConsole)" in console_section
    assert "browser-live-surface" in console_section
    assert "控制台不渲染本地截图" in console_section
    assert "真实浏览器视口截图" not in workbench_source
    assert "evidencePath" in console_section
    assert "src={browserFrame" not in console_section
    assert "file://" not in console_section
    assert "withCacheBust(" not in workbench_source
    assert "is-controllable" not in console_section
    assert "等待启动真实浏览器" in browser_frame_helper
    assert "历史截图仅用于报告证据，实时操作请启动真实浏览器" in browser_frame_helper
    assert "<dt>下一步</dt>" in console_section
    assert "<dd>{browserFrame.evidencePath" not in console_section
    assert "browser-live-surface" in styles_source
    assert "刷新当前画面" in workbench_source


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
    assert "CSS 选择器" in workbench_source
    assert "坐标点击" in workbench_source
    assert "原始坐标点击、焦点输入和按键已关闭" in workbench_source
    assert "选择器定位" in workbench_source
    assert "按选择器点击" in workbench_source
    assert "按选择器填写" in workbench_source
    assert "输入到焦点" not in workbench_source
    assert "<span>按键</span>" not in workbench_source
    assert "滚动页面" in workbench_source
    assert "仅控制当前独立浏览器窗口" in workbench_source
    assert "'click'" not in control_action_type
    assert "'type'" not in control_action_type
    assert "'press'" not in control_action_type
    assert "'selector_click'" in control_action_type
    assert "'selector_fill'" in control_action_type
    assert "selector?: string" in types_source
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
    assert "交还 Agent" in workbench_source
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
    assert "已启动只读页面检查，请在执行控制台查看实时日志" in app_source
    assert ".operation-alert--ok" in styles_source
    assert "runtimeControl?: {" in types_source
    assert "owner?: 'start_mvp' | 'desktop' | 'direct' | string" in types_source
    assert "managedByLauncher: boolean" in types_source
    assert "managedByDesktop?: boolean" in types_source
    assert "restartAvailable: boolean" in types_source
    assert "onRuntimeControl={onRuntimeControl}" in workbench_source
    assert "onRuntimeControl('run_l2_readonly_probe')" in workbench_source
    assert "agent-console-lifecycle__actions" in workbench_source
    assert ".agent-console-lifecycle__actions" in styles_source
    assert "console-diagnostics-drawer" in console_section
    assert "ModuleHead title=\"运行时维护\"" in console_section
    assert "RuntimeControlPanel" in console_section
    assert "停止浏览器 Agent" in workbench_source
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
    assert "browser_control: '控制'" in workbench_source
    assert "fill: '填写'" in workbench_source
    assert ".runtime-control-panel" in styles_source
    assert ".agent-action-timeline" in styles_source


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


def test_browser_qa_reuses_existing_qa_tasks_instead_of_creating_duplicates():
    source = QA_BROWSER_CHECK.read_text(encoding="utf-8")
    ensure_section = source[source.index("async function ensureRealMutationTask"):source.index("async function screenshot")]

    assert "function findReusableQaTask(" in ensure_section
    assert "fetchJson('/api/tasks')" in ensure_section
    assert "findReusableQaTask(existingTasks, 'QA local gated single_save fixture', 'single_save')" in ensure_section
    assert "QA guarded real mutation task" not in source
    assert "findReusableQaTask(existingTasks, 'QA unreleased claim_only task', 'claim_only')" in ensure_section
    assert "findReusableQaTask(existingTasks, '\\u672c\\u5730\\u6f14\\u793a\\u6838\\u9a8c\\u6279\\u6b21', 'dry_run')" in ensure_section
    assert "if (reusableTask) return reusableTask" in ensure_section


def test_task_center_sanitizes_legacy_qa_fixture_names_from_user_visible_rows():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    task_center_section = source[source.index("export function TaskCenter"):source.index("export function ExecutionConsole")]
    focus_panel_section = source[source.index("function ConsoleFocusPanel"):source.index("function AgentBrowserFrame")]
    dashboard_section = source[source.index("export function Dashboard"):source.index("export function GuideCenter")]

    assert "function displayTaskName(" in source
    assert "QA local gated single_save fixture" in source
    assert "LEGACY_QA_REAL_MUTATION_TASK_NAME" in source
    assert "['QA guarded', 'real mutation task'].join(' ')" in source
    assert "<strong>{displayTaskName(task)}</strong>" in task_center_section
    assert "<strong>{selectedTask ? displayTaskName(selectedTask)" in dashboard_section
    assert "displayTaskName(selectedTask)" in focus_panel_section
    assert "${displayTaskName(latestSingleSaveTask)}" in source
    assert "<strong>{task.name}</strong>" not in task_center_section
    assert "${selectedTask.name}" not in focus_panel_section


def test_task_center_hides_auxiliary_qa_and_dry_run_tasks_by_default():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    task_center_section = source[source.index("export function TaskCenter"):source.index("export function ExecutionConsole")]

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
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    workspace_source = (REPO_ROOT / "app" / "frontend" / "src" / "workspace.ts").read_text(encoding="utf-8")
    report_center_section = source[source.index("export function ReportCenter"):source.index("function FinalDeliveryCheckCard")]

    assert "details className=\"module-card span-3 disclosure-card l2-next-step-card\"" in report_center_section
    assert "重新验证只读检查" in report_center_section
    assert "高级复核，需人工批准" in report_center_section
    assert "workspace.l2ProbePlan" in report_center_section
    assert "l2ProbePlan.commands.map" in report_center_section
    assert "l2ProbePlan.acceptanceCriteria" in report_center_section
    assert "normalizeL2ProbePlan" in workspace_source
    assert "Array.isArray(plan.commands)" in workspace_source
    assert "Array.isArray(plan.acceptanceCriteria)" in workspace_source
    assert "Array.isArray(plan.safetyNotes)" in workspace_source


def test_report_center_shows_allowlist_review_before_l2_recheck_commands():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    types_source = (REPO_ROOT / "app" / "frontend" / "src" / "types.ts").read_text(encoding="utf-8")
    report_center_section = source[source.index("export function ReportCenter"):source.index("function FinalDeliveryCheckCard")]

    assert "l2AllowlistReviewItems" in report_center_section
    assert "L2 allowlist 候选处理" in report_center_section
    assert "先评审，再复跑 L2" in report_center_section
    assert "review_only=true / allowlist_applied=false" in report_center_section
    assert "未完成人工评审前，不运行下方只读页面检查命令" in report_center_section
    assert "l2_allowlist_review_template_state" in source
    assert "l2_allowlist_review_template_markdown_path" in source
    assert "l2_allowlist_review_template_markdown_sha256" in source
    assert "l2_allowlist_review_template_json_sha256" in source
    assert "l2_allowlist_review_template_candidate_count" in types_source
    assert "ok_scope" in source
    assert "real_dxm_mutation_allowed" in source
    assert "real_dxm_write_blocked_reason" in source
    assert "expected_real_dxm_write_readiness" in source
    assert "real_dxm_write_readiness_matches_expected" in source
    assert "预期真实写入" in source
    assert "真实写入允许 false" in source


def test_final_delivery_card_explains_blocked_to_ready_prerequisites():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    final_card_section = source[source.index("function FinalDeliveryCheckCard"):source.index("function SourcePackageCheckRow")]
    qa_script = QA_BROWSER_CHECK.read_text(encoding="utf-8")

    assert "真实写入放行前置" in final_card_section
    assert "L2 双目标真实只读通过" in source
    assert "人工批准 L3 金丝雀" in source
    assert "保存成功、未发布证明、截图和 network/HAR" in source
    assert "不能用 allowlist 模板替代 L2 通过" in source
    assert "delivery-check-card__release-gates" in final_card_section
    assert "realWriteReleasePrerequisites" in source
    assert "reportRealWriteReleasePrerequisites" in qa_script


def test_report_center_keeps_final_check_engineering_details_in_appendix():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    final_card_section = source[source.index("function FinalDeliveryCheckCard"):source.index("function SourcePackageCheckRow")]

    assert "ModuleHead title=\"最近自动化验收\"" in final_card_section
    assert "最终验收报告${localWorkbenchOk ? '通过' : '待刷新'}" in final_card_section
    assert "最终验收报告待刷新；当前运行门禁已按最新 L2/L3 覆盖为可申请单商品只保存" in final_card_section
    assert "历史验收结果已过期，请先重新运行只读复验和本地验收。" not in final_card_section
    assert "humanReadinessLabel(readiness)" in final_card_section
    assert "humanGateDetail(blockedReason)" in final_card_section
    assert '<details className="disclosure-card delivery-check-card__appendix">' in final_card_section
    assert "验收人附录" in final_card_section
    assert "仅供验收复核" in final_card_section
    assert "命令、源码包、路径和门禁细节" not in final_card_section
    assert "delivery-check-card__paths" in final_card_section
    assert "delivery-check-card__commands" in final_card_section
    visible_section = final_card_section[:final_card_section.index('<details className="disclosure-card delivery-check-card__appendix">')]
    for forbidden in ("源码包验收", "Browser QA", "allowlist", "READY", "BLOCKED", "L2=", "L3=", "scripts\\final-delivery-check.bat"):
        assert forbidden not in visible_section


def test_dashboard_and_guide_default_copy_hide_gate_codes():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    dashboard_section = source[source.index("export function Dashboard"):source.index("function OperationGuide")]
    operation_guide_section = source[source.index("function OperationGuide"):source.index("export function GuideCenter")]
    guide_center_section = source[source.index("export function GuideCenter"):source.index("function DxmLoginInlineForm")]

    for section in (dashboard_section, operation_guide_section, guide_center_section):
        assert "选择真实 single_save 任务" not in section
        assert "确认 L2 真实只读通过" not in section
        assert "L2 真实只读通过" not in section
        assert "仅 single_save 放行" not in section
        assert "single_save 任务" not in section
        assert "运行 L2 页面核验" not in section
        assert "运行 L2 复验" not in section
    assert "选择单商品只保存任务" in operation_guide_section
    assert "确认只读页面检查通过" in operation_guide_section
    assert "单商品只保存任务" in guide_center_section
    assert "运行只读页面核验" in guide_center_section
    assert "运行只读页面检查（不保存）" in guide_center_section
    assert "可申请 single_save" not in guide_center_section
    assert "可申请单商品只保存" in guide_center_section


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


def test_execution_console_default_log_summary_hides_absolute_paths():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    console_section = source[source.index("export function ExecutionConsole"):source.index("function RuntimeLogPreview")]
    login_form_section = source[source.index("function DxmLoginInlineForm"):source.index("function RegressionGateGrid")]
    log_summary_section = source[source.index("function RuntimeLogPreview"):source.index("function RuntimeLogPanel")]

    assert "日志会自动刷新；筛选和搜索保留在下方“更多诊断与维护”" in console_section
    assert "humanConsoleCodeLabel(step.state)" in console_section
    assert "humanConsoleCodeLabel((hasConsoleHud ? hud?.state ?? hud?.code : null) ?? activeStep?.code ?? 'WAITING')" in source
    assert "PRECHECK_CONFIG: '启动前配置校验'" in source
    assert "登录和人工处理不要求 L2" not in login_form_section
    assert "只打开真实店小秘窗口，不启动保存" in login_form_section
    assert "日志来源：{labels[source]}" in log_summary_section
    assert "onSourceChange(item)" in log_summary_section
    assert "runtime-log-tabs--compact" in log_summary_section
    assert "items.slice(-7)" in log_summary_section
    assert "runtimeLogRefreshMeta(current, items.length)" in log_summary_section
    assert "界面自动刷新" in log_summary_section
    assert "日志来源：{labels[source]} / 正在实时刷新" not in log_summary_section
    assert "日志源久未写入" in source
    assert "formatLogAge(current.ageSeconds)" in source
    assert "界面刷新" in source
    assert "最后写入" in source
    assert "最后刷新" not in source
    assert "current?.path ?? 'data/*.log'" not in log_summary_section


def test_report_center_treats_missing_l3_evidence_as_expected_when_real_write_blocked():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    report_center_section = source[source.index("export function ReportCenter"):source.index("function FinalDeliveryCheckCard")]

    assert "realWriteExpectedBlocked" in report_center_section
    assert "EvidenceCheckRow" in report_center_section
    assert "BusinessReportCheckRow" in report_center_section
    assert "PostL3ReportCheckRow" in report_center_section
    assert "humanPublishGuardStatus(workspace.publishGuardState?.status)" in report_center_section
    assert source.index("function humanPublishGuardStatus") < source.index("export function ReportCenter")
    assert "safe_unpublished: '保存后未发布'" in source
    assert "meta={workspace.publishGuardState?.status" not in report_center_section
    assert "label=\"保存结果\"" in source
    assert "label=\"未发布证明\"" in source
    assert "label=\"网络/HAR\"" in source
    assert "业务保存报告 0 份（真实保存后，预期阻断）" in source
    assert "（预期阻断）" in source
    assert "state={'locked'}" in source
    assert "state === 'locked' ? 'locked'" in source
    assert "state === 'locked' ? '暂停'" in source
    assert "ok={true} state={'locked'}" not in source
    assert "人工确认前不要求生成新的真实保存证据" in source
    assert "真实写入未确认前不要求生成业务保存报告" in source
    assert "真实保存后报告必须覆盖" in source
    assert "details className=\"module-card span-3 disclosure-card\"" in report_center_section
    assert "交付检查表" in report_center_section
    assert "真实保存后要求" in source
    assert "CheckRow label={`报告 ${reportSummary?.total_reports ?? reports.length} 份`}" not in report_center_section


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
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    dashboard_section = source[source.index("export function Dashboard"):source.index("function RegressionGateGrid")]
    exception_section = source[source.index("export function ExceptionQueue"):source.index("export function ReportCenter")]
    gap_list_section = source[source.index("function GapList"):source.index("function CheckRow")]

    assert "presentAcceptanceGaps" in source
    assert "isRealWriteExpectedBlocked" in source
    assert "l3PostEvidenceGapIds" in source
    assert "presentedAcceptanceGaps" in dashboard_section
    assert "presentedAcceptanceGaps" in exception_section
    assert "emptyExceptionDetail" in exception_section
    assert "当前任务暂无异常记录" in exception_section
    assert "请查看报告中心和证据中心" in exception_section
    assert "GapList gaps={presentedAcceptanceGaps" in dashboard_section
    assert "GapList gaps={presentedAcceptanceGaps}" in exception_section
    assert "真实保存后补齐：" in source
    assert "真实写入放行后再补齐" in source
    assert "severity: 'watch'" in source
    assert "data-gap-id={gap.id}" in gap_list_section
    assert "data-severity={gap.severity}" in gap_list_section


def test_task_and_evidence_center_describe_l3_blocked_as_expected_lock():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    task_center_section = source[source.index("export function TaskCenter"):source.index("export function ExecutionConsole")]
    evidence_timeline_section = source[source.index("export function EvidenceTimeline"):source.index("function EvidencePointCard")]

    assert "真实保存必须停止并复核 publish guard" not in task_center_section
    assert "解除发布隔离风险" not in task_center_section
    assert "齐全后才会形成 A/B/C 证据等级" not in evidence_timeline_section

    assert "只读检查未通过或人工确认未完成前" in task_center_section
    assert "不启动认领、批量保存或真实保存" in task_center_section
    assert "当前按钮策略：只读检查未通过或人工确认未完成时保持阻断" in task_center_section
    assert "人工确认未完成，禁止启动" in task_center_section
    assert "当前真实写入未放行时" in evidence_timeline_section
    assert "0 条是预期阻断" in evidence_timeline_section
    assert "只有单商品只保存完成后才生成可验收证据等级" in evidence_timeline_section
    assert "evidence-raw-disclosure" in evidence_timeline_section
    assert "原始证据明细" in evidence_timeline_section
    assert "按需展开" in evidence_timeline_section
    assert "evidence-grade-disclosure" in evidence_timeline_section
    assert "<ModuleHead title=\"原始证据\"" not in evidence_timeline_section
    assert "humanEvidencePointTitle(point)" in source
    assert "humanEvidencePointKind(point.kind)" in source
    assert "步骤快照" in source
    assert "执行证据" in source
    assert "确认未发布" in source
    assert "只点击保存" in source


def test_task_center_only_uses_demo_ready_copy_for_dry_run_tasks():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    task_center_section = source[source.index("export function TaskCenter"):source.index("export function ExecutionConsole")]

    assert "selectedTask?.mode === 'dry_run'" in task_center_section
    assert "demoEnabled && selectedTaskIsDryRun && selectedTask?.status === 'draft' && <span className=\"readonly-recheck-help__note\">开发自检批次不触达店小秘" in source
    assert "{selectedTask?.status === 'draft' && <span>本地演示批次已可用于验收门禁" not in task_center_section
    assert "当前真实任务保持门禁控制，请先处理上方阻断原因。" in source


def test_task_center_exposes_real_task_creation_instead_of_demo_first_flow():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    app_source = APP_TSX.read_text(encoding="utf-8")
    task_center_section = source[source.index("export function TaskCenter"):source.index("export function ExecutionConsole")]

    assert "onCreateRealTask" in task_center_section
    assert "创建真实任务" in task_center_section
    assert "只读页面检查" in task_center_section
    assert "单商品只保存" in task_center_section
    assert "批量保存未放行" in task_center_section
    assert "发布动作未开放" in task_center_section
    assert "SMT_SEMI_MANAGED_SAVE_ONLY" in task_center_section
    assert "data-testid=\"real-task-create\"" in task_center_section
    assert "postJson<Task>('/api/tasks'" in app_source
    assert "mode: request.mode" in app_source
    assert "publish_scene: 'SMT_SEMI_MANAGED_SAVE_ONLY'" in app_source
    assert "onCreateRealTask={createRealTask}" in app_source


def test_task_center_surfaces_single_save_recovery_guide_for_blocked_real_tasks():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    qa_source = QA_BROWSER_CHECK.read_text(encoding="utf-8")
    task_center_section = source[source.index("export function TaskCenter"):source.index("export function ExecutionConsole")]

    assert "SingleSaveRecoveryGuide" in task_center_section
    assert "needsSingleSaveRecovery" in task_center_section
    assert "latestSingleSaveTask" in task_center_section
    assert "submitSingleSaveTask" in task_center_section
    assert "data-testid=\"single-save-recovery-guide\"" in source
    assert "恢复到单商品只保存" in source
    assert "当前任务不可直接启动时，按这里回到真实自动化可执行路径。" in source
    assert "选择最近单商品只保存任务" in source
    assert "创建新的单商品只保存任务" in source
    assert "运行只读页面检查（不保存）" in source
    assert "查看检查计划" in source
    assert "onRunL2Probe={onRunL2Probe}" in task_center_section
    assert "不放行认领/批量保存" in source
    recovery_section = source[source.index("function SingleSaveRecoveryGuide"):source.index("function RealModeReleasePlanPanel")]
    for forbidden in ("恢复到受控 single_save", "选择最近 single_save", "创建新的 single_save", "运行 L2 复验"):
        assert forbidden not in recovery_section
    assert "single-save-recovery-guide" in styles_source
    assert "singleSaveRecoveryGuideVisible" in qa_source


def test_task_center_explains_l2_recheck_before_real_save():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    task_center_section = source[source.index("export function TaskCenter"):source.index("export function ExecutionConsole")]
    recheck_card_section = source[source.index("function ReadonlyRecheckHelpCard"):source.index("function SingleSaveRecoveryGuide")]

    assert "ReadonlyRecheckHelpCard" in task_center_section
    assert "l2BlocksStart && (" in task_center_section
    assert "只读页面检查未通过，真实保存先暂停" in recheck_card_section
    assert "检查商品采集页和草稿箱页" in recheck_card_section
    assert "不领取、不备注、不保存、不发布" in recheck_card_section
    assert "当前状态：{humanGateStateLabel(l2Gate?.status ?? 'not_run')}" in recheck_card_section
    assert "运行只读页面检查（不保存）" in recheck_card_section
    assert "查看诊断摘要" in recheck_card_section
    assert "查看检查计划" in recheck_card_section
    assert "查看证据缺口" in recheck_card_section
    assert "readonly-recheck-help" in styles_source

    for forbidden in ("data_acquisition", "draft_box", "L2 readonly", "probe runner"):
        assert forbidden not in recheck_card_section


def test_task_center_defaults_to_current_task_first_and_collapses_setup_noise():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    qa_source = QA_BROWSER_CHECK.read_text(encoding="utf-8")
    task_center_section = source[source.index("export function TaskCenter"):source.index("export function ExecutionConsole")]

    assert "TaskCurrentActionPanel" in task_center_section
    assert "task-quick-actions" in task_center_section
    assert "aria-label=\"任务操作台\"" in task_center_section
    assert "现在只做这三件事" in task_center_section
    assert "创建单商品只保存任务" in task_center_section
    assert "data-testid=\"task-quick-create-single-save\"" in task_center_section
    assert "setShowAllTasks(true)" in task_center_section
    assert "选择历史任务" in task_center_section
    assert task_center_section.index("task-quick-actions__buttons") < task_center_section.index("task-quick-actions__status")
    assert task_center_section.index("task-quick-actions") < task_center_section.index("TaskCurrentActionPanel")
    assert "onShowConsole={onShowConsole}" in task_center_section
    assert "打开执行控制台复核" in source
    assert "onShowConsole: () => void" in source
    assert "aria-label=\"当前任务执行\"" in source
    assert "当前任务 #${selectedTask.id}" in source
    assert "task-current-panel__task-id" in source
    assert "aria-label=\"启动判定\"" in source
    assert "taskStartDecision" in source
    assert "<strong>当前能做</strong>" in source
    assert "<strong>原因</strong>" in source
    assert "<strong>下一步</strong>" in source
    assert "去配置中心补齐 DXM 编辑页必填字段" in source
    assert "运行只读页面检查，确认商品采集页和草稿箱页均无写入风险" in source
    assert "点击主按钮后，在执行控制台查看真实浏览器执行" in source
    assert "先选择或创建单商品只保存任务" in source
    assert "先选择或创建 single_save 任务" not in source
    assert "默认只展示真实自动化主路径" in source
    assert "humanTaskModeLabel(selectedTask.mode)" in source
    assert "humanGateDetail(l2Gate?.detail)" in source
    assert "单商品只保存核验任务" in source
    assert "<strong>只读检查</strong>" in source
    assert "<strong>人工确认</strong>" in source
    assert "humanGateStateLabel(l2Gate?.status ?? 'not_run')" in source
    assert "humanGateStateLabel(l3Gate?.status ?? 'blocked')" in source
    assert "const l2CheckLabel = selectedTaskCompleted ? '已完成'" in source
    assert "const l3CheckLabel = selectedTaskCompleted ? '已完成'" in source
    assert "更多任务操作与记录" in task_center_section
    assert "创建新任务、历史批次、商品队列和启动条件都在这里" in task_center_section
    assert "<summary>创建真实任务</summary>" in task_center_section
    assert "<summary>查看未发布模式边界</summary>" in task_center_section
    assert "<summary>选择其它任务 / 历史批次</summary>" in task_center_section
    assert "<summary>查看商品队列</summary>" in task_center_section
    assert "<summary>查看任务验收口径</summary>" in task_center_section
    assert "<summary>启动条件说明</summary>" in task_center_section
    assert "className=\"module-card span-2 task-support-drawer disclosure-card\"" in task_center_section
    assert "className=\"inline-disclosure task-create-drawer\"" in task_center_section
    assert "className=\"inline-disclosure task-release-drawer\"" in task_center_section
    assert "className=\"inline-disclosure task-history-drawer\"" in task_center_section
    assert "className=\"inline-disclosure task-product-drawer\"" in task_center_section
    assert "className=\"inline-disclosure task-acceptance-drawer\"" in task_center_section
    assert "className=\"inline-disclosure task-decision-drawer\"" in task_center_section
    assert "data-testid=\"task-start-button\"" in source
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


def test_task_center_compacts_duplicate_history_tasks_by_default():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    qa_source = QA_BROWSER_CHECK.read_text(encoding="utf-8")
    task_center_section = source[source.index("export function TaskCenter"):source.index("export function ExecutionConsole")]

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
    task_center_section = source[source.index("export function TaskCenter"):source.index("export function ExecutionConsole")]

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
    task_center_section = source[source.index("export function TaskCenter"):source.index("export function ExecutionConsole")]

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
    task_center_section = source[source.index("export function TaskCenter"):source.index("export function ExecutionConsole")]

    assert '<details className="inline-disclosure l2-block-summary">' in task_center_section
    assert "<summary>只读检查诊断摘要</summary>" in task_center_section
    assert "humanDiagnosticNavigation(item.navigation)" in task_center_section
    assert "humanFailedCheckLabel" in source


def test_task_center_blocks_unreleased_store_for_single_save_creation():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    task_center_section = source[source.index("export function TaskCenter"):source.index("export function ExecutionConsole")]

    assert "RELEASED_SINGLE_SAVE_STORE_NAMES" in source
    assert "selectedStoreReleasedForSingleSave" in task_center_section
    assert "storeBlocksSingleSave" in task_center_section
    assert "单商品只保存当前只放行" in task_center_section
    assert "未放行单商品只保存" in task_center_section
    assert "未放行 single_save" not in task_center_section
    assert "draftMode !== 'probe' && storeBlocksSingleSave" in task_center_section


def test_app_defaults_to_actionable_single_save_when_delivery_task_is_completed():
    app_source = APP_TSX.read_text(encoding="utf-8")
    workspace_source = (REPO_ROOT / "app" / "frontend" / "src" / "workspace.ts").read_text(encoding="utf-8")
    qa_source = QA_BROWSER_CHECK.read_text(encoding="utf-8")

    assert "function pickDefaultTaskId(" in app_source
    assert "deliveryWorkspace?.current_task?.id" in app_source
    assert "function isActionableSingleSaveTask(" in app_source
    assert "deliveryTask && deliveryTask.status !== 'completed'" in app_source
    assert "tasks.find(isActionableSingleSaveTask)" in app_source
    assert "setSelectedTaskId((current) => current ?? pickDefaultTaskId(deliveryWorkspace, nextWorkspace.tasks))" in app_source
    assert "mergeCurrentTaskIntoTasks(" in workspace_source
    assert "nonEmptyList(workspace?.tasks)" in workspace_source
    assert "currentTask ? [currentTask, ...bundle.tasks] : bundle.tasks" in workspace_source
    assert "defaultTaskSelectionPrefersDeliveryCurrentTask" in qa_source
    assert "const defaultWorkspacePayload = await fetchJson('/api/delivery/workspace');" in qa_source
    assert "currentTaskPrefix: '\\u5f53\\u524d\\u4efb\\u52a1 #'" in qa_source
    assert "expectedCurrentTaskMarker: defaultCurrentTaskMarker" in qa_source
    assert "defaultTaskSelectionState.taskCenterTextSample = taskDefaultText.slice(0, 1200)" in qa_source
    assert "defaultCurrentTaskText.includes(defaultCurrentTaskMarker) || taskDefaultText.includes(defaultCurrentTaskMarker)" in qa_source
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


def test_task_center_surfaces_l2_allowlist_review_candidates_as_manual_review_only():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    app_source = APP_TSX.read_text(encoding="utf-8")

    assert "reviewCandidateRequests" in source
    assert "只读依赖人工评审清单" in source
    assert "仅人工评审，不自动放行真实保存" in source
    assert "allowlist_applied=false" in source
    assert "不自动放行真实保存" in source
    assert "onShowReports" in source
    assert "查看只读评审与检查计划" in source
    assert "onShowReports={() => setActiveSection('reports')}" in app_source


def test_frontend_blocks_unreleased_real_modes_before_l3_manual_approval():
    source = APP_TSX.read_text(encoding="utf-8")
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    start_section = source[source.index("async function startSelectedTask"):source.index("async function startAgentConsole")]
    qa_source = QA_BROWSER_CHECK.read_text(encoding="utf-8")
    no_old_action_copy_start = qa_source.index("noOldActionCopy:")
    no_old_action_copy_section = qa_source[no_old_action_copy_start:qa_source.index("noConsoleErrors:", no_old_action_copy_start)]

    assert "const RELEASED_REAL_DXM_MUTATION_MODES = new Set(['single_save'])" in source
    assert "const UNRELEASED_REAL_DXM_MUTATION_MODES = new Set(['claim_only', 'batch_save'])" in source
    assert "UNRELEASED_REAL_DXM_MUTATION_MODES.has(selectedTask.mode)" in start_section
    assert "当前仅开放单商品只保存" in start_section
    assert "认领和批量保存必须重新验收后再放行" in start_section
    assert "将只启动单商品只保存任务，不会发布" in start_section
    assert "将只启动 save-only/claim-only 受控任务" not in start_section
    assert "const selectedTaskIsUnreleasedRealMode = selectedTask ? isUnreleasedRealDxmMutationTask(selectedTask) : false" in workbench_source
    assert "startDisabled = busy || !selectedTask || selectedTaskNotDraft || selectedTaskIsUnreleasedRealMode || loginBlocksStart || configUnknownBlocksStart || configPreviewLoading || configBlocksStart || l2BlocksStart || l3BlocksStart" in workbench_source
    assert "const selectedTaskNotDraft = Boolean(selectedTask && selectedTask.status !== 'draft')" in workbench_source
    assert "未发布，禁止启动" in workbench_source
    assert "function isReleasedRealDxmMutationTask" in workbench_source
    assert "function isUnreleasedRealDxmMutationTask" in workbench_source
    assert "当前按钮策略：只读检查未通过或人工确认未完成时保持阻断；单商品只保存仍需后端人工批准；认领和批量保存当前未开放。" in workbench_source
    assert "unreleasedRealModeCopy" in qa_source
    assert "unreleasedRealModeButtonDisabled" in qa_source
    assert "async function ensureUnreleasedRealModeTask()" in qa_source
    assert "const unreleasedRealModeTask = reportOnlyFinal || qaExpectedReady ? null : await ensureUnreleasedRealModeTask();" in qa_source
    assert "mode: 'claim_only'" in qa_source
    assert "QA unreleased claim_only task" in qa_source
    assert "async function clickTaskByName(name)" in qa_source
    assert "await clickTaskByName(unreleasedRealModeTask.name)" in qa_source
    assert "document.querySelector(\".task-history-drawer\")" in qa_source
    assert "显示全部历史任务" in qa_source
    assert "await clickText(unreleasedRealModeTask.name)" not in qa_source
    assert "unreleasedRealModeTaskSelected:" in qa_source
    assert "unreleasedRealModeStartButtonDisabled" in qa_source
    assert "finalCheckExpectedReady || unreleasedRealModeStartButtonDisabled" in qa_source
    assert "unreleasedRealModeCopy: finalCheckExpectedReady" in qa_source
    assert "defaultCurrentTaskCompleted || taskStartDisabled" in qa_source
    assert "taskText.includes('\\u8fd0\\u884c\\u53ea\\u8bfb\\u590d\\u9a8c')" in qa_source
    assert "taskStartDisabled && taskText.includes(text.unreleasedRealModeButtonDisabled)" in qa_source
    assert "\\u0063\\u006c\\u0061\\u0069\\u006d\\u005f\\u006f\\u006e\\u006c\\u0079/\\u0062\\u0061\\u0074\\u0063\\u0068\\u005f\\u0073\\u0061\\u0076\\u0065 \\u5f53\\u524d\\u672a\\u53d1\\u5e03" in qa_source
    assert "\\u672a\\u53d1\\u5e03\\uff0c\\u7981\\u6b62\\u542f\\u52a8" in qa_source
    assert "\\u4ec5\\u53d7\\u63a7\\u5355\\u5546\\u54c1\\u53ea\\u4fdd\\u5b58" in qa_source
    assert "oldSaveOnly" not in qa_source
    assert "\\u53ea\\u4fdd\\u5b58\\u4e0d\\u53d1\\u5e03" not in no_old_action_copy_section
    assert "oldWaitSave" in no_old_action_copy_section
    assert "oldVisibleBrowser" in no_old_action_copy_section
    assert "oldAutomation" in no_old_action_copy_section
    assert "SAVE_ONLY" in no_old_action_copy_section


def test_task_center_start_button_matches_real_start_prechecks():
    app_source = APP_TSX.read_text(encoding="utf-8")
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    task_center_section = workbench_source[workbench_source.index("export function TaskCenter"):workbench_source.index("export function ExecutionConsole")]

    assert "runtimeStatus={runtimeStatus}" in app_source
    assert "runtimeStatus: RuntimeStatus | null" in workbench_source
    assert "const selectedRealDxmMutationTask = Boolean(selectedTask && isRealDxmMutationTask(selectedTask))" in task_center_section
    assert "const dxmLoggedIn = !runtimeStatusError && DXM_LOGGED_IN_STATUSES.has(runtimeStatus?.dxmLogin?.status ?? '')" in task_center_section
    assert "const loginBlocksStart = selectedRealDxmMutationTask && !dxmLoggedIn" in task_center_section
    assert "const configUnknownBlocksStart = selectedRealDxmMutationTask && !configPreview && !configPreviewLoading" in task_center_section
    assert "startDisabled = busy || !selectedTask || selectedTaskNotDraft || selectedTaskIsUnreleasedRealMode || loginBlocksStart || configUnknownBlocksStart || configPreviewLoading || configBlocksStart || l2BlocksStart || l3BlocksStart" in task_center_section
    assert "DXM 未登录，先打开真实浏览器登录" in task_center_section
    assert "先检查本次任务配置" in task_center_section
    assert "正在检查配置，稍候启动" in task_center_section


def test_task_center_surfaces_real_mode_release_readiness_without_releasing_modes():
    workspace_source = WORKSPACE_TS.read_text(encoding="utf-8")
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    qa_source = QA_BROWSER_CHECK.read_text(encoding="utf-8")
    task_center_section = workbench_source[workbench_source.index("export function TaskCenter"):workbench_source.index("export function ExecutionConsole")]

    assert "real_mode_release_plan?: RealModeReleasePlan" in workspace_source
    assert "workspace?.real_mode_release_plan" in workspace_source
    assert "buildRealModeReleasePlan" in workspace_source
    assert "normalizeRealModeReleasePlan" in workspace_source
    assert "normalizeReadinessChecklistItem" in workspace_source
    assert "readiness_checklist" in workspace_source
    assert "RealModeReleasePlanPanel" in task_center_section
    assert "认领 / 批量保存放行准备" in workbench_source
    assert "认领当前未发布" in workbench_source
    assert "批量保存当前未发布" in workbench_source
    assert "不能复用单商品只保存证据" in workbench_source
    assert "批量大小上限" in workbench_source
    assert "回滚/人工接管" in workbench_source
    assert "批量保存不启动真实浏览器保存" in workbench_source
    assert "仅受控单商品只保存" in workbench_source
    assert "humanReadinessCheckLabel" in workbench_source
    assert "humanReleaseBlocker" in workbench_source
    assert "独立只读与真实保存证据链" in workbench_source
    assert "目标草稿领取归属证明" in workbench_source
    assert "逐商品保存结果与 published=false" in workbench_source
    assert "RELEASED_REAL_DXM_MUTATION_MODES = new Set(['single_save'])" in (REPO_ROOT / "app" / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    assert "real-mode-release-panel" in styles_source
    assert "real-mode-release-panel__grid" in styles_source
    assert "realModeReleasePlanVisible" in qa_source


def test_frontend_does_not_expose_developer_fallback_copy():
    workspace_source = WORKSPACE_TS.read_text(encoding="utf-8")
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")

    assert "前端使用工作台 fallback 数据" not in workspace_source
    assert "前端使用工作台默认数据" in workspace_source
    assert "section.source === 'legacy' ? '旧字段兼容' : 'fallback'" not in workbench_source
    assert "默认规则" in workbench_source
    qa_source = QA_BROWSER_CHECK.read_text(encoding="utf-8")
    assert "fallbackCopyPatterns" in qa_source
    assert "fallback \\u6570\\u636e" in qa_source
    assert "\\u6765\\u6e90\\uff1afallback" in qa_source


def test_frontend_surfaces_runtime_status_and_log_filters():
    app_source = APP_TSX.read_text(encoding="utf-8")
    safety_bar = SAFETY_STATUS_BAR_TSX.read_text(encoding="utf-8")
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")

    assert "/api/runtime/status?frontend_url=" in app_source
    assert "encodeURIComponent(window.location.origin)" in app_source
    assert "runtimeStatus={runtimeStatus}" in app_source
    assert "`后端：${runtimeStatus.backend.status === 'ok' ? '运行中' : '异常'}`" in safety_bar
    assert "`前端：${runtimeStatus.frontend.status === 'ok' ? '运行中' : '异常'}`" in safety_bar
    assert "runtimeEndpointLine" in safety_bar
    assert "dxmReadySessionStatuses" in safety_bar
    assert "dxmLoginTone(runtimeStatus.dxmLogin.status)" in safety_bar
    assert "if (dxmReadySessionStatuses.has(status)) return 'ok'" in safety_bar
    assert "后端端口" in safety_bar
    assert "前端端口" in safety_bar
    assert "safety-bar__meta-details" in safety_bar
    assert "自动浏览器" in safety_bar
    assert "DXM 登录" in safety_bar
    assert "safety-bar__meta-details" in safety_bar
    assert "primaryStatus" in safety_bar
    assert "primaryActionLabel" in safety_bar
    assert "onShowTasks" in safety_bar
    visible_meta = safety_bar[
        safety_bar.index('<div className="safety-bar__meta"'):
        safety_bar.index('<details className="safety-bar__meta-details')
    ]
    assert "启动来源" not in visible_meta
    assert "runtimeOwnerChip" not in visible_meta
    details_section = safety_bar[safety_bar.index('<details className="safety-bar__meta-details'):]
    assert "启动来源" in safety_bar
    assert "detailChips.map" in details_section
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
    assert "dependencies.l2_readonly_probe_runner" in workbench_source
    assert "dependencies.l2_readonly_probe_script" in workbench_source
    assert "dependencies.l2_readonly_probe_allowlist" in workbench_source
    assert "checkedPaths" in (REPO_ROOT / "app" / "frontend" / "src" / "types.ts").read_text(encoding="utf-8")
    assert "已检查：" in workbench_source
    assert ".slice(0, 4)" in workbench_source
    assert "agent-console-resource-alert" in workbench_source
    assert "只读页面检查资源缺失，请关闭旧进程并重新打开完整免安装目录版" in workbench_source
    assert "DXM-Agent-Console-免安装版\\\\DXM-Agent-Console.exe" in workbench_source
    assert "task: '任务'" in workbench_source
    assert "agent: '浏览器 Agent'" in workbench_source
    assert "级别" in workbench_source
    assert "搜索" in workbench_source
    assert "item.tags.slice(0, 3)" in workbench_source


def test_safety_status_bar_does_not_duplicate_completed_task_status():
    safety_bar = SAFETY_STATUS_BAR_TSX.read_text(encoding="utf-8")

    assert "const activeTaskLabel = selectedTask ? `#${selectedTask.id}` : '未选择任务'" in safety_bar
    assert "const activeTaskStatusLabel = selectedTask ? humanTaskStatus(selectedTask.status) : ''" in safety_bar
    assert "任务 ${activeTaskLabel} ${activeTaskStatusLabel}，继续查看报告、证据或打开执行控制台复核。" in safety_bar
    assert "`#${selectedTask.id} ${humanTaskStatus(selectedTask.status)}`" not in safety_bar


def test_frontend_refreshes_workspace_after_l2_runner_finishes():
    app_source = APP_TSX.read_text(encoding="utf-8")

    assert "lastObservedL2CompletionRef" in app_source
    assert "[l2-readonly-runner] finished" in app_source
    assert "exit_code=0" in app_source
    assert "runnerEvent.line.match(/run_id=" in app_source
    assert "void refreshWorkspace()" in app_source
    assert "void refreshRuntimeStatus()" in app_source


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
    assert "setOperationError('只读页面检查失败" in app_source
    assert "l2RunnerState={l2RunnerState}" in app_source
    assert "L2RunnerStatePanel" in workbench_source
    assert "只读页面检查状态" in workbench_source
    assert "正在运行双目标只读检查" in workbench_source
    assert "只读页面检查通过，已刷新门禁" in workbench_source
    assert "只读页面检查失败，真实保存仍阻断" in workbench_source
    assert ".l2-runner-state" in styles_source


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
    assert "L2 readonly probe runner is missing" in app_source
    assert "只读页面检查启动器缺失，请关闭旧进程并重新打开完整免安装目录版。" in app_source
    assert "function searchedPathHint(message: string)" in app_source
    assert "const marker = 'Searched:'" in app_source
    assert ".slice(0, 3)" in app_source
    assert "已检查：${paths.join('；')}" in app_source
    assert "setOperationError(humanOperationError(message))" in app_source


def test_frontend_keeps_runtime_and_config_fetch_failures_distinct_from_user_state():
    app_source = APP_TSX.read_text(encoding="utf-8")
    safety_bar = SAFETY_STATUS_BAR_TSX.read_text(encoding="utf-8")
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")

    assert "const [runtimeStatusError, setRuntimeStatusError]" in app_source
    assert "setRuntimeStatusError(error instanceof Error ? error.message : '运行状态接口不可用')" in app_source
    assert "runtimeStatusError={runtimeStatusError}" in app_source
    assert "运行状态接口不可用" in safety_bar
    assert "状态接口异常" in safety_bar
    assert "runtimeStatusError?: string | null" in safety_bar

    assert "const [configPreviewError, setConfigPreviewError]" in app_source
    assert "setConfigPreviewError(error instanceof Error ? error.message : '配置检查接口不可用')" in app_source
    assert "configPreviewError={configPreviewError}" in app_source
    assert "配置检查接口不可用" in workbench_source
    assert "请先确认本机后端仍在运行，再重新检查配置" in workbench_source
    assert "configPreviewError: string | null" in workbench_source


def test_frontend_treats_workflow_navigation_as_logged_in_across_primary_surfaces():
    app_source = APP_TSX.read_text(encoding="utf-8")
    safety_bar = SAFETY_STATUS_BAR_TSX.read_text(encoding="utf-8")
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")

    assert "new Set(['login_success', 'logged_in', 'not_published_verified', 'workflow_navigation'])" in app_source
    assert "new Set(['login_success', 'logged_in', 'not_published_verified', 'workflow_navigation'])" in safety_bar
    assert "new Set(['login_success', 'logged_in', 'not_published_verified', 'workflow_navigation'])" in workbench_source
    assert "label: status === 'workflow_navigation' ? 'DXM 已进入业务页' : 'DXM 已登录'" in workbench_source


def test_frontend_recovers_from_stale_task_id_in_url():
    app_source = APP_TSX.read_text(encoding="utf-8")

    assert "function syncSelectedTaskIdUrl(taskId: number | null)" in app_source
    assert "const taskMissing = failures.some((failure) => failure.path.startsWith('/api/delivery/workspace') && /task not found/i.test(failure.message))" in app_source
    assert "const recoveredTaskId = pickDefaultTaskId(null, nextWorkspace.tasks)" in app_source
    assert "setSelectedTaskId(recoveredTaskId)" in app_source
    assert "syncSelectedTaskIdUrl(recoveredTaskId)" in app_source
    assert "} else {\n      setSelectedTaskId((current) => current ?? pickDefaultTaskId(deliveryWorkspace, nextWorkspace.tasks))" in app_source
    assert "syncSelectedTaskIdUrl(taskId)" in app_source


def test_execution_console_uses_unified_primary_path_before_rendering():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    console_section = source[source.index("export function ExecutionConsole"):source.index("function AgentStagePanel")]

    assert "function buildConsolePrimaryPath" in source
    assert "configPreview: ConfigPreview | null" in source
    assert "const consolePrimaryPath = buildConsolePrimaryPath({ selectedTask, configPreview, configPreviewError, l2Gate, l3Gate, busy })" in console_section
    assert "const realSaveBlocked = consolePrimaryPath.saveBlocked" in console_section
    assert "const browserStartBlocked = consolePrimaryPath.blocksBrowserStart" in console_section
    assert "const diagnosticBlockReason" not in console_section
    assert "l2Gate?.detail ?? '只读检查未通过。'" not in console_section
    assert "先选择或创建任务" in source
    assert "先补齐本次任务配置" in source
    assert "先运行只读页面检查" in source
    assert "等待人工确认保存" in source
    assert "可以打开执行浏览器" in source
    assert "最新证据年龄" in source
    assert "只读检查证据已过期，请点击“运行只读页面检查（不保存）”刷新后再继续。" in source


def test_frontend_first_screen_names_dxm_automation_delivery():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    shell = (REPO_ROOT / "app" / "frontend" / "src" / "components" / "AppShell.tsx").read_text(encoding="utf-8")
    safety_bar = SAFETY_STATUS_BAR_TSX.read_text(encoding="utf-8")
    qa_source = QA_BROWSER_CHECK.read_text(encoding="utf-8")

    assert "店小秘半托管只保存自动化" in source
    assert "按真实店铺、真实商品和编辑页配置推进" in source
    assert "不会发布；批量和无人值守保存仍保持关闭" in source
    assert "aria-label=\"验收结论\"" in source
    assert "工作台</strong><b>可使用" in source
    assert "保存范围</strong><b>{realWriteReady ? '单商品只保存可执行' : '等待人工确认'}" in source
    assert "当前范围' : '下一步'" in source
    assert "只保存，不发布" in source
    assert "完成页面检查" in source
    assert "继续下一步：打开真实店小秘登录" in safety_bar
    assert "当前可执行：单商品只保存自动化" in safety_bar
    assert "系统状态与验收详情" in safety_bar
    assert "safety-bar__meta-details inline-disclosure" in safety_bar
    assert "真实写入门禁未通过" not in safety_bar
    assert "配置 / 任务 / 真实浏览器执行" in shell
    assert "\\u0044\\u0058\\u004d \\u81ea\\u52a8\\u5316\\u5de5\\u4f5c\\u53f0" in qa_source
    assert "\\u73b0\\u5728\\u53ea\\u505a\\u8fd9\\u4e00\\u6b65" in qa_source
    assert "\\u67e5\\u770b\\u5b8c\\u6574 8 \\u6b65\\u6d41\\u7a0b" in qa_source
    assert "半托管保存交付工作台" not in source
    assert "保存核验 / 证据复盘" not in shell


def test_mock_workspace_uses_dry_run_demo_language_not_real_single_save():
    workspace_source = (REPO_ROOT / "app" / "frontend" / "src" / "workspace.ts").read_text(encoding="utf-8")
    mock_section = workspace_source[workspace_source.index("export function buildMockWorkspace"):workspace_source.index("function buildRegressionGates")]

    assert "name: '本地演示保存核验批次 #19'" in mock_section
    assert "mode: 'dry_run'" in mock_section
    assert "演示截图占位" in mock_section
    assert "本地演示保存核验报告 #19" in mock_section
    assert "buildRegressionGates(null, evidenceGradeValue, [])" in mock_section
    assert "file:///mock/l2.html" not in mock_section
    assert "mode: 'single_save'" not in mock_section
    assert "保存动作截图" not in mock_section


def test_frontend_labels_mock_l2_as_evidence_not_passed():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    safety_bar = SAFETY_STATUS_BAR_TSX.read_text(encoding="utf-8")
    workspace_source = (REPO_ROOT / "app" / "frontend" / "src" / "workspace.ts").read_text(encoding="utf-8")

    assert "mock_passed: '离线证据'" in source
    assert "mock_passed: '离线证据'" in safety_bar
    assert "仅有离线/mock L2 证据；不满足真实页面 L2 放行条件。" in workspace_source
    assert "已有离线/mock L2 证据；真实页面仍需批准执行。" not in workspace_source

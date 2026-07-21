from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
FRONTEND_SRC = REPO_ROOT / "app" / "frontend" / "src"
TYPES_TS = FRONTEND_SRC / "types.ts"
STYLES_CSS = FRONTEND_SRC / "styles.css"
TEMPLATE_CENTER_TSX = FRONTEND_SRC / "components" / "workbench" / "TemplateCenterPage.tsx"
BATCH_COMPOSER_TSX = FRONTEND_SRC / "components" / "workbench" / "BatchTemplateComposer.tsx"


REQUIRED_SECTIONS = (
    "category",
    "sku",
    "pricing",
    "logistics",
    "image",
    "compliance",
    "semi_managed",
    "dxm_reference",
)


def test_template_center_defaults_to_section_mode_and_exposes_batch_mode():
    source = TEMPLATE_CENTER_TSX.read_text(encoding="utf-8")

    assert "from './BatchTemplateComposer'" in source
    assert "useState<TemplateCenterMode>('sections')" in source
    assert ">分区模板</button>" in source
    assert ">整批模板</button>" in source
    assert "templateCenterMode === 'batch_bundle'" in source
    assert "<BatchTemplateComposer" in source
    assert "onEditSection={(section) =>" in source
    assert "setActiveSectionId(section)" in source
    assert "setTemplateCenterMode('sections')" in source


def test_batch_composer_uses_fixed_live_options_and_exact_create_request():
    source = BATCH_COMPOSER_TSX.read_text(encoding="utf-8")

    for section in REQUIRED_SECTIONS:
        assert f"'{section}'" in source
    assert "new URLSearchParams" in source
    assert "store_id: String(selectedStoreId)" in source
    assert "if (categoryName.trim()) params.set('category_name', categoryName.trim())" in source
    assert "getJson<EditBatchBundleOptions>(`/api/template-center/edit-batch-bundle-options?${params.toString()}`)" in source
    assert "postJson<Template>('/api/template-center/edit-batch-bundles'" in source
    for field in (
        "template_name: templateName.trim()",
        "version: version.trim()",
        "store_id: selectedStoreId",
        "category_name: categoryName.trim() || null",
        "section_templates: sectionTemplates",
    ):
        assert field in source
    assert "payload:" not in source
    assert "localStorage" not in source
    assert "mock" not in source.lower()


def test_batch_composer_only_selects_backend_ready_candidates_and_never_posts_when_blocked():
    source = BATCH_COMPOSER_TSX.read_text(encoding="utf-8")
    submit_start = source.index("async function handlePrimaryAction")
    submit = source[submit_start:source.index("\n  return (", submit_start)]

    assert "candidate.ready" in source
    assert ".filter((candidate) => candidate.ready)" in source
    assert "section.ready_count" in source
    assert "const firstIssue = issueSections[0]" in source
    assert "if (firstIssue)" in submit
    assert "onEditSection(firstIssue.section)" in submit
    assert submit.index("if (firstIssue)") < submit.index("postJson<Template>")
    assert "source_digest: candidate.source_digest" in submit


def test_batch_composer_refreshes_template_list_and_returns_to_batch_draft_after_success():
    source = BATCH_COMPOSER_TSX.read_text(encoding="utf-8")

    assert "await onBundleCreated()" in source
    assert "setCreatedBundle(created)" in source
    assert source.index("setCreatedBundle(created)") < source.index("await onBundleCreated()")
    assert "if (createdBundle)" in source
    assert "onShowDraftEdit()" in source
    assert "回到批次草稿" in source
    assert "模板列表已更新" in source
    assert "workspace 已刷新" not in source
    assert "message?.text || optionsError" in source


def test_batch_composer_keeps_digest_technical_details_out_of_the_ui():
    source = BATCH_COMPOSER_TSX.read_text(encoding="utf-8")

    assert "source_digest.slice" not in source
    assert "candidate.source_digest}" not in source
    assert "<code" not in source
    assert "<summary>调整来源模板（可选）</summary>" in source
    assert source.count('className="button button--primary"') == 1
    assert ">ready_count<" not in source
    assert "`缺少 ${missingField}`" not in source
    assert "humanMissingField(missingField)" in source


def test_batch_composer_allows_store_level_bundle_without_category():
    source = BATCH_COMPOSER_TSX.read_text(encoding="utf-8")
    form_ready = source[source.index("const formReady"):source.index("const canCompose")]
    disabled = source[source.index("const primaryDisabled"):source.index("function changeStore")]

    assert "categoryName.trim()" not in form_ready
    assert "categoryName.trim()" not in disabled
    assert "category_name: categoryName.trim() || null" in source
    assert "留空则生成店铺级模板" in source


def test_batch_composer_types_preserve_backend_readiness_contract():
    source = TYPES_TS.read_text(encoding="utf-8")

    for type_name in (
        "EditBatchBundleCandidate",
        "EditBatchBundleSectionOptions",
        "EditBatchBundleOptions",
        "EditBatchBundleCreateRequest",
    ):
        assert f"export type {type_name}" in source
    for field in (
        "ready_count: number",
        "default_candidate",
        "source_digest: string",
        "section_templates",
        "required_sections: EditBatchBundleSectionCode[]",
        "store: { id: number; name: string; platform: string }",
        "ready: boolean",
    ):
        assert field in source
    assert "can_compose" not in source
    assert "ready_count?:" not in source


def test_batch_composer_styles_keep_readable_text():
    source = STYLES_CSS.read_text(encoding="utf-8")
    start = source.index("/* Batch template composer")
    styles = source[start : source.index("/* End batch template composer", start)]

    assert "font-size: 10px" not in styles
    assert "font-size: 11px" not in styles
    assert ".batch-template-composer" in styles

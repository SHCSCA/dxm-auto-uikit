import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowClockwiseIcon,
  CheckCircleIcon,
  ClockCounterClockwiseIcon,
  FloppyDiskIcon,
  FunnelIcon,
  GitBranchIcon,
  MagnifyingGlassIcon,
  PencilSimpleIcon,
  PlusIcon,
  ShieldCheckIcon,
  SparkleIcon,
  SquaresFourIcon,
  WarningCircleIcon,
  XIcon,
} from "@phosphor-icons/react";
import { countTemplateRules, normalizeTemplateSafety, normalizeTemplateSections } from "../data/templateRuleCatalog.js";
import "./TemplateEditor.css";

function incrementPatchVersion(version) {
  const match = String(version ?? "").trim().match(/^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?/i);
  if (!match) return "v1.0.1";
  const [, major, minor = "0", patch = "0"] = match;
  return `v${Number(major)}.${Number(minor)}.${Number(patch) + 1}`;
}

function formatVersion(version) {
  const value = String(version || "—");
  return value.startsWith("v") ? value : `v${value}`;
}

function templateContentErrors(template) {
  const errors = [];
  if (!String(template?.name || "").trim()) errors.push("模板名称不能为空");
  if (!String(template?.scope || "").trim()) errors.push("适用范围不能为空");
  const sections = template?.sections || [];
  const rules = sections.flatMap((section) => section.rules || []);
  if (!sections.length || !rules.length) errors.push("模板至少需要一个包含规则的章节");
  rules.forEach((rule) => {
    if (!String(rule.label || "").trim()) errors.push("存在缺少字段名称的规则");
    if (!String(rule.value || "").trim()) errors.push(`${rule.label || "未命名规则"} 缺少规则值`);
    if (!String(rule.source || "").trim()) errors.push(`${rule.label || "未命名规则"} 缺少来源说明`);
  });
  const repeatedRuleIds = rules.map((rule) => rule.id).filter((id, index, ids) => id && ids.indexOf(id) !== index);
  if (repeatedRuleIds.length) errors.push("规则 ID 存在重复，不能生成稳定快照");
  return [...new Set(errors)];
}

function cloneTemplate(template) {
  return JSON.parse(JSON.stringify(template));
}

function currentTimestamp() {
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "short",
    timeStyle: "short",
    hour12: false,
  }).format(new Date());
}

function collectTemplateChanges(baseTemplate, nextTemplate) {
  if (!baseTemplate || !nextTemplate) return [];
  const changes = [];
  if (baseTemplate.version !== nextTemplate.version) {
    changes.push({ id: "version", section: "版本", label: "版本号", before: baseTemplate.version, after: nextTemplate.version });
  }
  if (baseTemplate.name !== nextTemplate.name) {
    changes.push({ id: "name", section: "模板信息", label: "模板名称", before: baseTemplate.name, after: nextTemplate.name });
  }
  if (baseTemplate.scope !== nextTemplate.scope) {
    changes.push({ id: "scope", section: "模板信息", label: "适用范围", before: baseTemplate.scope, after: nextTemplate.scope });
  }

  const baseSections = new Map((baseTemplate.sections ?? []).map((section) => [section.id, section]));
  (nextTemplate.sections ?? []).forEach((section) => {
    const baseSection = baseSections.get(section.id);
    const baseRules = new Map((baseSection?.rules ?? []).map((rule) => [rule.id, rule]));
    section.rules.forEach((rule) => {
      const previous = baseRules.get(rule.id);
      if (!previous) {
        changes.push({ id: `${section.id}-${rule.id}-added`, section: section.label, label: rule.label, before: "未配置", after: rule.value });
        return;
      }
      if (previous.value !== rule.value) {
        changes.push({ id: `${section.id}-${rule.id}`, section: section.label, label: rule.label, before: previous.value, after: rule.value });
      }
    });
  });
  return changes;
}

function normalizeCatalogSections(sections) {
  const canonicalSections = normalizeTemplateSections();
  const suppliedSections = normalizeTemplateSections(sections);
  const suppliedById = new Map(suppliedSections.map((section) => [section.id, section]));

  return canonicalSections.map((canonicalSection) => {
    const suppliedSection = suppliedById.get(canonicalSection.id);
    const suppliedRules = new Map(
      (suppliedSection?.rules || []).map((rule) => [rule.field || rule.source || rule.id, rule]),
    );

    const rules = canonicalSection.rules.map((canonicalRule) => {
      const suppliedRule = suppliedRules.get(canonicalRule.field || canonicalRule.source || canonicalRule.id);
      return suppliedRule
        ? {
            ...canonicalRule,
            value: suppliedRule.value ?? canonicalRule.value,
          }
        : canonicalRule;
    });

    return {
      ...canonicalSection,
      status: suppliedSection?.status ?? canonicalSection.status,
      fieldCount: rules.length,
      rules,
    };
  });
}

const fallbackTemplates = [
  {
    id: "tpl-hud-13",
    name: "速卖通半托管_只保存_执行模板",
    version: "v1.3",
    status: "warning",
    scope: "AliExpress 半托管 · 店小秘当前商品",
    updatedAt: "2026-07-20 09:52",
    owner: "运营小秘",
    summary: "9 组 60 个当前项目字段（24 个必填）；用于整批一次批准后的串行自动编辑，只保存。",
  },
  {
    id: "tpl-acrylic-21",
    name: "包装物流_只保存_类目模板",
    version: "v2.1",
    status: "ready",
    scope: "店小秘当前商品 · 包装物流字段",
    updatedAt: "2026-07-18 16:24",
    owner: "模板管理员",
    summary: "9 组 60 个当前项目字段（24 个必填）；商品范围来自店小秘现场，批次授权在编辑工作台完成。",
  },
  {
    id: "tpl-legacy-09",
    name: "店小秘引用_只保存_基础模板",
    version: "v0.9",
    status: "disabled",
    scope: "历史任务留档",
    updatedAt: "2026-06-24 11:08",
    owner: "系统迁移",
    summary: "9 组 60 个当前项目字段（24 个必填）；已停用，仅用于回看历史版本。",
  },
];

const statusMeta = {
  ready: { label: "已就绪", tone: "success" },
  warning: { label: "需校验", tone: "warning" },
  disabled: { label: "已停用", tone: "info" },
};

const prototypeReferenceCounts = {
  "template-hud-half-managed-v1.3": 1,
  "template-auto-tools-v2.1": 2,
  "template-car-electronics-v1.8": 0,
  "tpl-hud-13": 1,
  "tpl-acrylic-21": 2,
  "tpl-legacy-09": 0,
};

function getTemplateStatusMeta(template) {
  if (template?.lifecycle === "draft") {
    return template.draftValidated
      ? { label: "草稿 · 可启用", tone: "success" }
      : { label: "草稿 · 待校验", tone: "warning" };
  }
  return statusMeta[template?.status] ?? statusMeta.warning;
}

function normalizeTemplate(template, index) {
  const fallback = fallbackTemplates[index] ?? fallbackTemplates[0];
  const sections = normalizeCatalogSections(template?.sections);
  const fieldCount = countTemplateRules(sections);
  const requiredFieldCount = sections.reduce(
    (total, section) => total + section.rules.filter((rule) => rule.required).length,
    0,
  );
  const version = template?.version ?? template?.template_version ?? fallback.version;
  const lifecycle = template?.lifecycle ?? (template?.isDraft ? "draft" : "active");
  const templateId = template?.id ?? template?.template_id ?? fallback.id;
  return {
    ...(template || {}),
    ...normalizeTemplateSafety(template),
    id: templateId,
    name: template?.name ?? template?.template_name ?? fallback.name,
    version,
    status: template?.status ?? fallback.status,
    scope: template?.scope ?? template?.binding ?? fallback.scope,
    updatedAt: template?.updatedAt ?? template?.updated_at ?? fallback.updatedAt,
    owner: template?.owner ?? template?.updated_by ?? fallback.owner,
    summary: `${sections.length} 组 ${fieldCount} 个当前项目字段（${requiredFieldCount} 个必填）；模板不保存商品或店铺清单，批次授权在编辑工作台完成。`,
    lifecycle,
    isDraft: lifecycle === "draft",
    draftOf: template?.draftOf ?? template?.parentTemplateId ?? null,
    baseVersion: template?.baseVersion ?? null,
    draftValidated: Boolean(template?.draftValidated),
    validatedAt: template?.validatedAt ?? null,
    usageCount: Number.isFinite(Number(template?.usageCount ?? template?.referenceCount))
      ? Number(template?.usageCount ?? template?.referenceCount)
      : lifecycle === "draft"
        ? 0
        : prototypeReferenceCounts[templateId] ?? 0,
    rules: fieldCount,
    sections,
    history: Array.isArray(template?.history) && template.history.length
      ? template.history
      : [
          { version, time: template?.updatedAt ?? fallback.updatedAt, operator: template?.owner ?? fallback.owner, note: "当前任务可使用版本" },
          { version: "v1.2", time: "2026-07-16 14:10", operator: "运营小秘", note: "补充半托管尺寸和未发布校验" },
          { version: "v1.1", time: "2026-07-12 09:35", operator: "模板管理员", note: "完成店小秘引用模板绑定" },
        ],
  };
}

const ui = {
  headerRow: { display: "flex", alignItems: "center", justifyContent: "space-between", gap: 18 },
  headerCopy: { margin: "4px 0 0", color: "var(--muted)", fontSize: 13 },
  toolbar: { padding: 14, display: "grid", gridTemplateColumns: "minmax(260px, 1fr) 180px auto", gap: 10, alignItems: "center" },
  inputWrap: { minHeight: 42, padding: "0 12px", border: "1px solid var(--border)", borderRadius: 7, background: "#fff", display: "flex", alignItems: "center", gap: 9 },
  input: { width: "100%", padding: 0, border: 0, outline: 0, color: "var(--ink)", background: "transparent", fontSize: 13 },
  select: { minHeight: 42, padding: "0 11px", border: "1px solid var(--border)", borderRadius: 7, color: "#415168", background: "#fff", font: "inherit" },
  workGrid: { display: "grid", gridTemplateColumns: "310px minmax(0, 1fr)", gap: 16, alignItems: "start" },
  list: { minHeight: 610, padding: 10, display: "grid", alignContent: "start", gap: 7 },
  listButton: { width: "100%", padding: 12, border: "1px solid transparent", borderRadius: 8, background: "transparent", display: "grid", gap: 6, textAlign: "left", cursor: "pointer" },
  detail: { minHeight: 610, overflow: "hidden" },
  detailHeader: { padding: 20, borderBottom: "1px solid var(--border)", display: "flex", justifyContent: "space-between", gap: 20, alignItems: "flex-start" },
  detailBody: { display: "grid", gridTemplateColumns: "230px minmax(0, 1fr)" },
  sectionNav: { padding: 12, borderRight: "1px solid var(--border)", display: "grid", alignContent: "start", gap: 5 },
  sectionButton: { width: "100%", padding: "10px 11px", border: "1px solid transparent", borderRadius: 7, color: "#516075", background: "transparent", display: "grid", gap: 3, textAlign: "left", cursor: "pointer" },
  ruleArea: { minWidth: 0, padding: 20, display: "grid", alignContent: "start", gap: 14 },
  ruleRow: { padding: "12px 0", borderBottom: "1px solid #edf1f5", display: "grid", gridTemplateColumns: "145px minmax(0, 1fr) 110px", gap: 12, alignItems: "center", fontSize: 13 },
  meta: { color: "var(--muted)", fontSize: 12 },
  actions: { display: "flex", flexWrap: "wrap", gap: 8 },
  validation: { padding: 14, border: "1px solid #c5d9f5", borderRadius: 8, color: "#315271", background: "#f3f7fd", display: "grid", gridTemplateColumns: "26px minmax(0, 1fr)", gap: 10 },
  history: { padding: 14, borderTop: "1px solid var(--border)", background: "#f8fafc", display: "grid", gap: 8 },
  historyRow: { padding: "9px 10px", border: "1px solid #e1e7ef", borderRadius: 7, background: "#fff", display: "grid", gridTemplateColumns: "70px 140px minmax(0, 1fr)", gap: 10, fontSize: 12 },
  field: { display: "grid", gap: 6, color: "#4c5b70", fontSize: 12 },
  textField: { minHeight: 42, padding: "0 11px", border: "1px solid var(--border)", borderRadius: 7, color: "var(--ink)", background: "#fff", outline: 0 },
  textArea: { minHeight: 90, padding: 11, border: "1px solid var(--border)", borderRadius: 7, color: "var(--ink)", background: "#fff", resize: "vertical", outline: 0, font: "inherit" },
};

function SafetyStrip() {
  return (
    <section className="safety-banner" aria-label="模板安全边界" data-testid="templates-safety-boundary">
      <div className="safety-banner__message">
        <ShieldCheckIcon size={24} weight="fill" aria-hidden="true" />
        <strong>模板只定义当前项目字段与取值来源</strong>
        <span className="safety-banner__divider" aria-hidden="true" />
        <span>商品范围由店小秘现场提供，本系统不做本地商品或店铺选择；模板版本会随批次一起批准，随后严格逐件串行并自动继续。</span>
      </div>
      <div className="safety-banner__mode"><ShieldCheckIcon size={18} aria-hidden="true" />安全模式</div>
    </section>
  );
}

export function TemplatesPage({ templates = [], onUpdateTemplate, notify }) {
  const validationTimerRef = useRef(null);
  const validationTokenRef = useRef(0);
  const validationTemplateIdRef = useRef(null);
  const selectedTemplateIdRef = useRef(null);
  const previousFocusRef = useRef(null);
  const versionNameInputRef = useRef(null);
  const versionDialogRef = useRef(null);
  const editTriggerRef = useRef(null);
  const editorNameInputRef = useRef(null);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [selectedId, setSelectedId] = useState(null);
  const [activeSectionId, setActiveSectionId] = useState("category");
  const [showHistory, setShowHistory] = useState(true);
  const [validationState, setValidationState] = useState("idle");
  const [versionDialogOpen, setVersionDialogOpen] = useState(false);
  const [versionDraft, setVersionDraft] = useState({ name: "", version: "", note: "" });
  const [editor, setEditor] = useState(null);
  const [showComparison, setShowComparison] = useState(false);

  const normalizedTemplates = useMemo(() => {
    const source = templates.length ? templates : fallbackTemplates;
    return source.map(normalizeTemplate);
  }, [templates]);

  const filteredTemplates = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return normalizedTemplates.filter((template) => {
      const matchesStatus = statusFilter === "all" || template.status === statusFilter;
      const matchesQuery = !normalizedQuery || `${template.name} ${template.version} ${template.scope}`.toLowerCase().includes(normalizedQuery);
      return matchesStatus && matchesQuery;
    });
  }, [normalizedTemplates, query, statusFilter]);

  useEffect(() => {
    if (!filteredTemplates.length) {
      if (selectedId !== null) setSelectedId(null);
      return;
    }
    if (!filteredTemplates.some((template) => String(template.id) === String(selectedId))) {
      setSelectedId(filteredTemplates[0].id);
    }
  }, [filteredTemplates, selectedId]);

  const selectedTemplate = filteredTemplates.find((template) => String(template.id) === String(selectedId)) ?? filteredTemplates[0] ?? null;
  const displayedTemplate = editor?.draft ?? selectedTemplate;
  const activeSection = displayedTemplate?.sections.find((section) => section.id === activeSectionId) ?? displayedTemplate?.sections[0];
  const comparisonBase = useMemo(() => {
    if (editor?.base) return editor.base;
    if (!selectedTemplate?.draftOf) return selectedTemplate;
    return normalizedTemplates.find((template) => String(template.id) === String(selectedTemplate.draftOf)) ?? selectedTemplate;
  }, [editor?.base, normalizedTemplates, selectedTemplate]);
  const comparisonChanges = useMemo(
    () => collectTemplateChanges(comparisonBase, displayedTemplate),
    [comparisonBase, displayedTemplate],
  );
  selectedTemplateIdRef.current = selectedTemplate?.id ?? null;
  const visibleValidationState = validationState !== "idle" && String(validationTemplateIdRef.current) !== String(selectedTemplate?.id)
    ? "idle"
    : validationState;

  useEffect(() => {
    if (displayedTemplate && !displayedTemplate.sections.some((section) => section.id === activeSectionId)) {
      setActiveSectionId(displayedTemplate.sections[0]?.id ?? "basic");
    }
    validationTokenRef.current += 1;
    if (validationTimerRef.current !== null) {
      window.clearTimeout(validationTimerRef.current);
      validationTimerRef.current = null;
    }
    validationTemplateIdRef.current = null;
    setValidationState("idle");
  }, [selectedTemplate?.id, Boolean(editor)]);

  useEffect(() => {
    if (!editor) return undefined;
    const frame = window.requestAnimationFrame(() => editorNameInputRef.current?.focus());
    return () => window.cancelAnimationFrame(frame);
  }, [Boolean(editor)]);

  useEffect(() => () => {
    validationTokenRef.current += 1;
    if (validationTimerRef.current !== null) window.clearTimeout(validationTimerRef.current);
  }, []);

  useEffect(() => {
    if (versionDialogOpen) {
      versionNameInputRef.current?.focus();
      const closeOnEscape = (event) => {
        if (event.key === "Escape") {
          event.preventDefault();
          setVersionDialogOpen(false);
          return;
        }
        if (event.key === "Tab" && versionDialogRef.current) {
          const controls = [...versionDialogRef.current.querySelectorAll('button, input, textarea, select, [href], [tabindex]:not([tabindex="-1"])')].filter((node) => !node.disabled);
          if (!controls.length) return;
          const first = controls[0];
          const last = controls[controls.length - 1];
          if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last.focus();
          } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
          }
        }
      };
      document.addEventListener("keydown", closeOnEscape);
      return () => document.removeEventListener("keydown", closeOnEscape);
    }

    if (previousFocusRef.current instanceof HTMLElement) {
      previousFocusRef.current.focus();
      previousFocusRef.current = null;
    }
    return undefined;
  }, [versionDialogOpen]);

  const selectTemplateRow = (templateId) => {
    if (editor && String(templateId) !== String(selectedId)) {
      notify?.("请先保存草稿或放弃本次编辑，再切换模板", "warning");
      return;
    }
    setSelectedId(templateId);
    setShowComparison(false);
  };

  const startEditing = () => {
    if (!selectedTemplate) return;
    const isExistingDraft = selectedTemplate.lifecycle === "draft";
    const baseTemplate = isExistingDraft
      ? normalizedTemplates.find((template) => String(template.id) === String(selectedTemplate.draftOf)) ?? selectedTemplate
      : selectedTemplate;
    const editableDraft = cloneTemplate(selectedTemplate);
    if (!isExistingDraft) {
      editableDraft.id = `local-draft-${Date.now()}`;
      editableDraft.version = incrementPatchVersion(selectedTemplate.version);
      editableDraft.lifecycle = "draft";
      editableDraft.isDraft = true;
      editableDraft.draftOf = selectedTemplate.id;
      editableDraft.baseVersion = selectedTemplate.version;
      editableDraft.usageCount = 0;
      editableDraft.status = "warning";
      editableDraft.draftValidated = false;
      editableDraft.validatedAt = null;
      editableDraft.updatedAt = "尚未保存";
      editableDraft.summary = "正在编辑的新补丁草稿；保存并校验前不能绑定任务。";
    }
    editTriggerRef.current = document.activeElement;
    setEditor({
      base: cloneTemplate(baseTemplate),
      draft: editableDraft,
      persisted: isExistingDraft,
    });
    setShowComparison(false);
    notify?.(isExistingDraft ? "已打开草稿编辑器" : `已从 ${selectedTemplate.version} 建立 ${editableDraft.version} 编辑草稿`);
  };

  const updateDraftField = (field, value) => {
    setEditor((current) => current ? {
      ...current,
      draft: {
        ...current.draft,
        [field]: value,
        status: "warning",
        draftValidated: false,
        validatedAt: null,
      },
    } : current);
  };

  const updateDraftRule = (sectionId, ruleId, value) => {
    setEditor((current) => current ? {
      ...current,
      draft: {
        ...current.draft,
        status: "warning",
        draftValidated: false,
        validatedAt: null,
        sections: current.draft.sections.map((section) => section.id === sectionId ? {
          ...section,
          status: "warning",
          rules: section.rules.map((rule) => rule.id === ruleId ? { ...rule, value } : rule),
        } : section),
      },
    } : current);
  };

  const saveEditorDraft = () => {
    if (!editor) return;
    const name = editor.draft.name.trim();
    const scope = editor.draft.scope.trim();
    const validationErrors = templateContentErrors({ ...editor.draft, name, scope });
    if (validationErrors.length) {
      notify?.(`草稿未保存：${validationErrors[0]}`, "warning");
      editorNameInputRef.current?.focus();
      return;
    }
    const savedTemplate = {
      ...editor.draft,
      name,
      scope,
      lifecycle: "draft",
      isDraft: true,
      status: "warning",
      draftValidated: false,
      validatedAt: null,
      updatedAt: currentTimestamp(),
      owner: "当前操作者",
      summary: "编辑草稿已保存；完成模拟校验后才能在批量编辑计划中选择。",
      history: editor.persisted
        ? editor.draft.history
        : [
            {
              version: editor.draft.version,
              time: "刚刚",
              operator: "当前操作者",
              note: `从 ${editor.base.version} 创建编辑草稿`,
            },
            ...editor.draft.history,
          ],
    };
    onUpdateTemplate?.({
      type: "create-version",
      parentTemplateId: savedTemplate.draftOf,
      template: savedTemplate,
    });
    setSelectedId(savedTemplate.id);
    setEditor(null);
    setShowComparison(true);
    notify?.(`草稿 ${savedTemplate.version} 已保存；下一步需要模拟校验`);
    window.requestAnimationFrame(() => editTriggerRef.current?.focus?.());
  };

  const discardEditorChanges = () => {
    if (!editor) return;
    const wasPersisted = editor.persisted;
    setEditor(null);
    setShowComparison(false);
    notify?.(wasPersisted ? "未保存的修改已放弃，已恢复上次保存的草稿" : "未保存的编辑草稿已放弃", "info");
    window.requestAnimationFrame(() => editTriggerRef.current?.focus?.());
  };

  const enableValidatedDraft = () => {
    if (!selectedTemplate || selectedTemplate.lifecycle !== "draft" || !selectedTemplate.draftValidated) return;
    const enabledTemplate = {
      ...selectedTemplate,
      lifecycle: "active",
      isDraft: false,
      status: "ready",
      draftValidated: false,
      usageCount: 0,
      updatedAt: currentTimestamp(),
      owner: "当前操作者",
      summary: "新补丁版本已启用，可在批量编辑计划中明确选择，并随不可变批次一起完成一次批准。",
      history: [
        {
          version: selectedTemplate.version,
          time: "刚刚",
          operator: "当前操作者",
          note: "校验通过并启用为新补丁版本",
        },
        ...selectedTemplate.history,
      ],
    };
    onUpdateTemplate?.({ type: "create-version", parentTemplateId: selectedTemplate.draftOf, template: enabledTemplate });
    setShowComparison(false);
    notify?.(`${enabledTemplate.version} 已启用；原版本及历史任务引用保持不变`);
  };

  const runValidation = () => {
    if (!selectedTemplate) return;
    const validationErrors = templateContentErrors(selectedTemplate);
    if (validationErrors.length) {
      setValidationState("blocked");
      notify?.(`校验未通过：${validationErrors[0]}`, "warning");
      return;
    }
    validationTokenRef.current += 1;
    const validationToken = validationTokenRef.current;
    const validatingTemplateId = selectedTemplate.id;
    validationTemplateIdRef.current = validatingTemplateId;
    if (validationTimerRef.current !== null) window.clearTimeout(validationTimerRef.current);
    setValidationState("running");
    validationTimerRef.current = window.setTimeout(() => {
      if (validationTokenRef.current !== validationToken || String(selectedTemplateIdRef.current) !== String(validatingTemplateId)) return;
      validationTimerRef.current = null;
      const blocked = selectedTemplate.status === "disabled";
      setValidationState(blocked ? "blocked" : "complete");
      if (!blocked) {
        const isDraft = selectedTemplate.lifecycle === "draft";
        const validatedTemplate = {
          ...selectedTemplate,
          status: isDraft ? "warning" : "ready",
          draftValidated: isDraft,
          validatedAt: new Intl.DateTimeFormat("zh-CN").format(new Date()),
          updatedAt: "刚刚",
          summary: isDraft
            ? "编辑草稿校验通过，可由操作者启用为新补丁版本；尚未绑定任何任务。"
            : "本地模拟校验已完成，可在原型向导中绑定；未执行任何店小秘动作。",
          sections: selectedTemplate.sections.map((section) => ({ ...section, status: "ready" })),
        };
        onUpdateTemplate?.({ type: "validation-complete", templateId: selectedTemplate.id, template: validatedTemplate });
      }
      notify?.(
        blocked
          ? "该模板已停用，不能用于新任务"
          : selectedTemplate.lifecycle === "draft"
            ? "草稿校验通过；确认变更后可启用新补丁版本"
            : "本地模拟校验完成；该版本现在可在原型向导中选择",
      );
    }, 620);
  };

  const openVersionDialog = () => {
    if (!selectedTemplate) return;
    previousFocusRef.current = document.activeElement;
    setVersionDraft({
      name: selectedTemplate.name,
      version: incrementPatchVersion(selectedTemplate.version),
      note: "从当前已确认规则创建新版本",
    });
    setVersionDialogOpen(true);
  };

  const createVersion = (event) => {
    event.preventDefault();
    if (!selectedTemplate || !versionDraft.name.trim() || !versionDraft.version.trim()) return;
    const nextTemplate = {
      ...selectedTemplate,
      id: `local-version-${Date.now()}`,
      name: versionDraft.name.trim(),
      version: versionDraft.version.trim(),
      status: "warning",
      lifecycle: "draft",
      isDraft: true,
      draftOf: selectedTemplate.lifecycle === "draft" ? selectedTemplate.draftOf : selectedTemplate.id,
      baseVersion: selectedTemplate.version,
      draftValidated: false,
      validatedAt: null,
      usageCount: 0,
      updatedAt: new Intl.DateTimeFormat("zh-CN", { dateStyle: "short", timeStyle: "short", hour12: false }).format(new Date()),
      summary: "新版本草稿已创建，需完成内容编辑与模拟校验后再启用。",
      history: [
        { version: versionDraft.version.trim(), time: "刚刚", operator: "当前操作者", note: versionDraft.note.trim() || "创建新版本" },
        ...selectedTemplate.history,
      ],
    };
    setSelectedId(nextTemplate.id);
    setVersionDialogOpen(false);
    onUpdateTemplate?.({ type: "create-version", parentTemplateId: selectedTemplate.id, template: nextTemplate });
    notify?.(`已创建 ${nextTemplate.version} 草稿；请编辑规则、保存并校验后再启用`);
  };

  if (!normalizedTemplates.length) {
    return (
      <div className="secondary-view" data-testid="templates-page-empty">
        <SafetyStrip />
        <section className="card" style={{ padding: 28 }}><h1>模板中心</h1><p>当前没有可查看的模板。</p></section>
      </div>
    );
  }

  const selectedMeta = displayedTemplate ? getTemplateStatusMeta(displayedTemplate) : null;

  return (
    <div className="secondary-view" data-testid="templates-page">
      <SafetyStrip />

      <header className="templates-header" style={ui.headerRow}>
        <div>
          <div className="page-heading" style={{ height: "auto", minHeight: 64 }}>
            <h1>模板</h1>
            <span className="status-badge status-badge--info">{normalizedTemplates.length} 套</span>
          </div>
          <p style={ui.headerCopy}>核对当前项目的 9 个字段组、取值与来源，再为批量编辑创建明确版本；商品范围由店小秘现场提供，本系统不做本地商品或店铺选择。</p>
        </div>
        <div className="template-header-actions" style={ui.actions}>
          <button
            ref={editTriggerRef}
            type="button"
            className="secondary-button"
            onClick={startEditing}
            disabled={!selectedTemplate || Boolean(editor)}
            data-testid="edit-template-button"
          >
            <PencilSimpleIcon size={18} weight="bold" aria-hidden="true" />
            {selectedTemplate?.lifecycle === "draft" ? "继续编辑草稿" : "编辑模板"}
          </button>
          <button type="button" className="primary-button" onClick={openVersionDialog} disabled={!selectedTemplate || Boolean(editor)} data-testid="create-template-version-button" aria-label="为当前模板创建新版本草稿">
            <PlusIcon size={18} weight="bold" aria-hidden="true" />新建版本草稿
          </button>
        </div>
      </header>

      <section className="card" style={ui.toolbar} aria-label="模板筛选" data-testid="templates-filter-bar">
        <label style={ui.inputWrap}>
          <MagnifyingGlassIcon size={18} color="#758398" aria-hidden="true" />
          <span className="sr-only">搜索模板</span>
          <input
            style={ui.input}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索模板名称、版本或适用范围"
            data-testid="templates-search-input"
            aria-label="搜索模板名称、版本或适用范围"
          />
        </label>
        <label style={{ display: "grid" }}>
          <span className="sr-only">按模板状态筛选</span>
          <select style={ui.select} value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} data-testid="templates-status-filter" aria-label="按模板状态筛选">
            <option value="all">全部状态</option>
            <option value="ready">已就绪</option>
            <option value="warning">需校验</option>
            <option value="disabled">已停用</option>
          </select>
        </label>
        <span style={{ ...ui.meta, display: "inline-flex", alignItems: "center", gap: 6 }}><FunnelIcon size={16} aria-hidden="true" />显示 {filteredTemplates.length} 套</span>
      </section>

      <div className="templates-work-grid" style={ui.workGrid}>
        <section className="card" style={ui.list} aria-label="模板列表" data-testid="templates-list">
          {filteredTemplates.map((template) => {
            const selected = String(template.id) === String(selectedId);
            const meta = getTemplateStatusMeta(template);
            return (
              <button
                key={template.id}
                type="button"
                style={{ ...ui.listButton, borderColor: selected ? "#8ab6f2" : "transparent", background: selected ? "#f2f7ff" : "transparent", boxShadow: selected ? "0 0 0 3px rgba(9,105,237,.06)" : "none" }}
                onClick={() => selectTemplateRow(template.id)}
                aria-pressed={selected}
                data-testid={`template-row-${template.id}`}
              >
                <span style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                  <strong style={{ color: "var(--ink)", fontSize: 13, lineHeight: 1.4 }}>{template.name}</strong>
                  <span className={`status-badge status-badge--${meta.tone}`}>{meta.label}</span>
                </span>
                <span style={{ color: "#415168", fontSize: 12, fontWeight: 650 }}>{formatVersion(template.version)}{template.lifecycle === "draft" ? " · 编辑草稿" : " · 已启用版本"}</span>
                <small style={ui.meta}>{template.scope}</small>
              </button>
            );
          })}
          {!filteredTemplates.length && <div style={{ padding: 18, color: "var(--muted)", fontSize: 13 }} data-testid="templates-no-results">没有符合筛选条件的模板。</div>}
        </section>

        <section className="card" style={ui.detail} aria-label="当前模板详情" data-testid="template-detail-panel">
          {selectedTemplate ? (
            <>
          <header className="template-detail-header" style={ui.detailHeader}>
            {editor ? (
              <div className="template-editor-heading" data-testid="template-editor-heading">
                <span className="template-editor-kicker">编辑草稿 · {formatVersion(displayedTemplate.version)}</span>
                <label className="template-editor-field">
                  <span>模板名称</span>
                  <input
                    ref={editorNameInputRef}
                    value={displayedTemplate.name}
                    onChange={(event) => updateDraftField("name", event.target.value)}
                    required
                    data-testid="template-editor-name"
                  />
                </label>
                <label className="template-editor-field">
                  <span>适用范围</span>
                  <input
                    value={displayedTemplate.scope}
                    onChange={(event) => updateDraftField("scope", event.target.value)}
                    required
                    data-testid="template-editor-scope"
                  />
                </label>
                <small>当前修改只存在于 {formatVersion(displayedTemplate.version)} 草稿，不会改变 {formatVersion(editor.base.version)} 或已运行任务。</small>
              </div>
            ) : (
              <div style={{ minWidth: 0 }}>
                <span style={{ color: "var(--blue)", fontSize: 12, fontWeight: 700 }}>{displayedTemplate.lifecycle === "draft" ? "编辑草稿" : "已启用版本"} · {formatVersion(displayedTemplate.version)}</span>
                <h2 style={{ margin: "5px 0 7px", color: "var(--ink)", fontSize: 20 }}>{displayedTemplate.name}</h2>
                <p style={{ margin: 0, color: "var(--muted)", fontSize: 13, lineHeight: 1.6 }}>{displayedTemplate.summary}</p>
                <p style={{ ...ui.meta, margin: "8px 0 0" }}>{displayedTemplate.scope} · {displayedTemplate.owner} 更新于 {displayedTemplate.updatedAt}</p>
              </div>
            )}
            <span className={`status-badge status-badge--${selectedMeta.tone}`}>{selectedMeta.label}</span>
          </header>

          <div className={`template-reference-warning ${displayedTemplate.usageCount === 0 ? "template-reference-warning--empty" : ""}`} role="note" data-testid="template-reference-warning">
            <WarningCircleIcon size={20} weight="fill" aria-hidden="true" />
            <div>
              <strong>{editor ? `本地原型记录：基础版本 ${formatVersion(editor.base.version)} 被 ${editor.base.usageCount} 个任务引用` : `本地原型记录：当前版本被 ${displayedTemplate.usageCount} 个任务引用`}</strong>
              <span>{editor ? "引用关系不会迁移；只有保存、校验并启用后的新任务才能选择此补丁版本。" : displayedTemplate.lifecycle === "draft" ? "草稿尚未被任务引用；校验通过并启用后才会出现在任务选择器中。" : "已启用版本不可原地修改。编辑会创建新的补丁草稿，历史任务继续引用原版本。"}</span>
            </div>
          </div>

          <div className="template-detail-body" style={ui.detailBody}>
            <nav className="template-section-nav" style={ui.sectionNav} aria-label="模板分区规则" data-testid="template-section-navigation">
              {displayedTemplate.sections.map((section) => {
                const selected = activeSection?.id === section.id;
                return (
                  <button
                    key={section.id}
                    type="button"
                    style={{ ...ui.sectionButton, color: selected ? "#075ccf" : "#516075", borderColor: selected ? "#bad3f5" : "transparent", background: selected ? "#edf5ff" : "transparent" }}
                    onClick={() => setActiveSectionId(section.id)}
                    aria-pressed={selected}
                    data-testid={`template-section-${section.id}`}
                  >
                    <strong style={{ fontSize: 12.5 }}>{section.label}</strong>
                    <small style={{ color: selected ? "#4f75a7" : "#8a96a8", fontSize: 10.5 }}>{section.fieldCount} 个字段规则</small>
                  </button>
                );
              })}
            </nav>

            <div className="template-rule-area" style={ui.ruleArea}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 16, alignItems: "flex-start" }}>
                <div>
                  <h3 style={{ margin: 0, fontSize: 17 }}>{activeSection?.label}</h3>
                  <p style={{ margin: "5px 0 0", color: "var(--muted)", fontSize: 12.5 }}>{activeSection?.description}</p>
                </div>
                <span className={`status-badge status-badge--${activeSection?.status === "ready" ? "success" : "warning"}`}>{activeSection?.status === "ready" ? "规则已就绪" : "需要人工确认"}</span>
              </div>

              <div aria-label={`${activeSection?.label ?? "当前分区"}规则`} data-testid="template-section-rules">
                {activeSection?.rules.map((rule) => (
                  <div key={rule.id} className="template-rule-row" style={ui.ruleRow}>
                    <strong style={{ color: "#405067", display: "flex", alignItems: "center", gap: 7, minWidth: 0 }}>
                      <span>{rule.label}</span>
                      {rule.required && (
                        <span
                          style={{ padding: "2px 5px", borderRadius: 4, color: "#8a4b08", background: "#fff2dd", fontSize: 10, lineHeight: 1.2, whiteSpace: "nowrap" }}
                          data-testid={`template-required-${rule.id}`}
                        >
                          必填
                        </span>
                      )}
                    </strong>
                    {editor ? (
                      <label className="template-rule-editor-field">
                        <span className="sr-only">{rule.label}取值</span>
                        <input
                          value={rule.value}
                          onChange={(event) => updateDraftRule(activeSection.id, rule.id, event.target.value)}
                          required={rule.required}
                          aria-label={`${rule.label}取值`}
                          data-testid={`template-rule-value-${rule.id}`}
                        />
                      </label>
                    ) : (
                      <span style={{ color: "var(--ink)", minWidth: 0 }}>{rule.value}</span>
                    )}
                    <span style={{ ...ui.meta, overflowWrap: "anywhere" }} title="当前项目字段路径">
                      字段：{rule.source}
                    </span>
                  </div>
                ))}
              </div>

              <div style={ui.actions}>
                {editor ? (
                  <>
                    <button type="button" className="primary-button" onClick={saveEditorDraft} data-testid="save-template-draft-button">
                      <FloppyDiskIcon size={18} weight="bold" aria-hidden="true" />保存草稿
                    </button>
                    <button type="button" className="secondary-button" onClick={discardEditorChanges} data-testid="discard-template-changes-button">
                      <XIcon size={18} aria-hidden="true" />放弃修改
                    </button>
                  </>
                ) : (
                  <>
                    <button type="button" className="secondary-button" onClick={startEditing} data-testid="detail-edit-template-button">
                      <PencilSimpleIcon size={18} aria-hidden="true" />{selectedTemplate.lifecycle === "draft" ? "继续编辑草稿" : "编辑模板"}
                    </button>
                    <button type="button" className="primary-button" onClick={runValidation} disabled={visibleValidationState === "running" || selectedTemplate.status === "disabled"} data-testid="simulate-template-validation-button">
                      {visibleValidationState === "running" ? <ArrowClockwiseIcon size={18} className="spin" aria-hidden="true" /> : <SparkleIcon size={18} weight="fill" aria-hidden="true" />}
                      {visibleValidationState === "running" ? "正在模拟校验" : selectedTemplate.lifecycle === "draft" ? "校验草稿" : "重新校验"}
                    </button>
                    {selectedTemplate.lifecycle === "draft" && (
                      <button type="button" className="primary-button template-enable-button" onClick={enableValidatedDraft} disabled={!selectedTemplate.draftValidated} data-testid="enable-template-version-button">
                      <CheckCircleIcon size={18} weight="fill" aria-hidden="true" />启用 {formatVersion(selectedTemplate.version)}
                      </button>
                    )}
                  </>
                )}
                <button type="button" className="secondary-button" onClick={() => setShowComparison((value) => !value)} aria-expanded={showComparison} data-testid="toggle-template-comparison">
                  <SquaresFourIcon size={18} aria-hidden="true" />对比变更 ({comparisonChanges.length})
                </button>
                <button type="button" className="secondary-button" onClick={() => setShowHistory((value) => !value)} aria-expanded={showHistory} data-testid="toggle-template-version-history">
                  <ClockCounterClockwiseIcon size={18} aria-hidden="true" />版本历史
                </button>
              </div>

              {showComparison && (
                <section className="template-comparison" aria-label="模板变更对比" data-testid="template-change-comparison">
                  <header>
                    <div><strong>变更对比</strong><span>{formatVersion(comparisonBase?.version)} → {formatVersion(displayedTemplate.version)}</span></div>
                    <span>{comparisonChanges.length} 项变更</span>
                  </header>
                  {comparisonChanges.length ? (
                    <div className="template-comparison-list">
                      {comparisonChanges.map((change) => (
                        <div className="template-comparison-row" key={change.id}>
                          <div><small>{change.section}</small><strong>{change.label}</strong></div>
                          <span className="template-comparison-before">{change.before || "空"}</span>
                          <span aria-hidden="true">→</span>
                          <span className="template-comparison-after">{change.after || "空"}</span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p>当前草稿与基础版本没有内容差异。</p>
                  )}
                </section>
              )}

              {visibleValidationState !== "idle" && (
                <div style={{ ...ui.validation, borderColor: visibleValidationState === "blocked" ? "#f1c48a" : "#c5d9f5", background: visibleValidationState === "blocked" ? "#fff8eb" : "#f3f7fd" }} role="status" data-testid="template-validation-result">
                  {visibleValidationState === "running" ? <ArrowClockwiseIcon size={22} color="var(--blue)" aria-hidden="true" /> : visibleValidationState === "blocked" ? <WarningCircleIcon size={22} color="var(--warning)" weight="fill" aria-hidden="true" /> : <CheckCircleIcon size={22} color="var(--success)" weight="fill" aria-hidden="true" />}
                  <div>
                    <strong style={{ display: "block", color: "#1f3d63", fontSize: 13 }}>{visibleValidationState === "running" ? "正在检查规则和字段来源" : visibleValidationState === "blocked" ? "模板已停用，模拟校验阻断" : "模拟校验完成"}</strong>
                    <span style={{ display: "block", marginTop: 4, color: "#65768c", fontSize: 12, lineHeight: 1.55 }}>
                      {visibleValidationState === "running" ? `仅在本地检查 ${displayedTemplate.sections.length} 组 ${displayedTemplate.rules} 个当前项目字段，不打开店小秘、不执行任何保存动作。` : visibleValidationState === "blocked" ? "请创建新版本并重新校验；停用版本不能绑定新任务。" : selectedTemplate.lifecycle === "draft" ? "字段与来源检查通过；草稿仍未启用，需由用户点击启用新补丁版本。" : "字段可映射；商品范围从店小秘现场读取并冻结，模板随整批一次批准后用于严格单件串行自动编辑。"}
                    </span>
                  </div>
                </div>
              )}
            </div>
          </div>

          {showHistory && (
            <section style={ui.history} aria-label="模板版本历史" data-testid="template-version-history">
              <strong style={{ fontSize: 13 }}>版本历史</strong>
              {displayedTemplate.history.map((item, index) => (
                <div key={`${item.version}-${index}`} className="template-history-row" style={ui.historyRow}>
                  <strong>{formatVersion(item.version)}</strong>
                  <span style={ui.meta}>{item.time}</span>
                  <span>{item.note} · {item.operator}</span>
                </div>
              ))}
            </section>
          )}
            </>
          ) : (
            <div className="empty-state" style={{ minHeight: 610 }} data-testid="template-detail-empty">
              <FunnelIcon size={38} weight="duotone" aria-hidden="true" />
              <strong>当前筛选没有可展示的模板</strong>
              <p>调整搜索词或状态筛选后，再查看模板详情。</p>
            </div>
          )}
        </section>
      </div>

      {versionDialogOpen && (
        <div className="drawer-layer" role="presentation" data-testid="create-template-version-dialog-layer">
          <button className="drawer-backdrop" type="button" aria-label="关闭创建模板版本" onClick={() => setVersionDialogOpen(false)} />
          <aside ref={versionDialogRef} className="evidence-drawer" role="dialog" aria-modal="true" aria-labelledby="create-version-title" data-testid="create-template-version-dialog">
            <header className="drawer-header">
              <div><span>模板版本</span><h2 id="create-version-title">创建新版本</h2></div>
              <button type="button" className="icon-button" onClick={() => setVersionDialogOpen(false)} aria-label="关闭"><XIcon size={18} /></button>
            </header>
            <div className="drawer-boundary">
              <ShieldCheckIcon size={22} weight="fill" aria-hidden="true" />
              <div><strong>新版本不会立即进入真实任务</strong><span>必须重新完成模拟校验和人工选择；安全边界不能由模板改变。</span></div>
            </div>
            <form onSubmit={createVersion} style={{ minHeight: 0, overflow: "auto", padding: 20, display: "grid", alignContent: "start", gap: 15 }} data-testid="create-template-version-form">
              <label style={ui.field}>模板名称<input ref={versionNameInputRef} style={ui.textField} value={versionDraft.name} onChange={(event) => setVersionDraft((current) => ({ ...current, name: event.target.value }))} required data-testid="new-template-version-name" /></label>
              <label style={ui.field}>版本号<input style={ui.textField} value={versionDraft.version} onChange={(event) => setVersionDraft((current) => ({ ...current, version: event.target.value }))} required data-testid="new-template-version-number" /></label>
              <label style={ui.field}>变更说明<textarea style={ui.textArea} value={versionDraft.note} onChange={(event) => setVersionDraft((current) => ({ ...current, note: event.target.value }))} data-testid="new-template-version-note" /></label>
            </form>
            <footer className="drawer-footer">
              <button type="button" className="secondary-button" onClick={() => setVersionDialogOpen(false)} data-testid="cancel-create-template-version">取消</button>
              <button type="button" className="primary-button" onClick={createVersion} data-testid="submit-create-template-version"><GitBranchIcon size={18} />创建版本</button>
            </footer>
          </aside>
        </div>
      )}
    </div>
  );
}

export default TemplatesPage;

import { useEffect, useRef } from "react";
import {
  CheckCircleIcon,
  InfoIcon,
  ShieldCheckIcon,
  WarningCircleIcon,
  XIcon,
} from "@phosphor-icons/react";

export function SafetyBanner({ compact = false }) {
  return (
    <section className={`safety-banner${compact ? " safety-banner--compact" : ""}`} aria-label="安全边界">
      <div className="safety-banner__message">
        <ShieldCheckIcon size={24} weight="fill" aria-hidden="true" />
        <strong>只保存，不发布</strong>
        <span className="safety-banner__divider" aria-hidden="true" />
        <span>商品范围来自店小秘现场；未来批量编辑整批一次批准、严格单件串行并自动继续，当前生产仍由 single_save 子任务编排。</span>
      </div>
      <div className="safety-banner__mode">
        <ShieldCheckIcon size={18} aria-hidden="true" />
        安全模式
      </div>
    </section>
  );
}

export function PageHeader({ eyebrow, title, description, badge, actions, children }) {
  return (
    <header className="page-header">
      <div className="page-header__copy">
        {eyebrow && <span className="page-eyebrow">{eyebrow}</span>}
        <div className="page-header__title-row">
          <h1>{title}</h1>
          {badge}
        </div>
        {description && <p>{description}</p>}
        {children}
      </div>
      {actions && <div className="page-header__actions">{actions}</div>}
    </header>
  );
}

export function StatusBadge({ tone = "neutral", children }) {
  return <span className={`status-badge status-badge--${tone}`}>{children}</span>;
}

export function MetricCard({ icon: Icon, label, value, detail, tone = "neutral" }) {
  return (
    <article className={`metric-card metric-card--${tone}`}>
      {Icon && <div className="metric-card__icon"><Icon size={21} weight="duotone" aria-hidden="true" /></div>}
      <div>
        <span>{label}</span>
        <strong>{value}</strong>
        {detail && <small>{detail}</small>}
      </div>
    </article>
  );
}

export function EmptyState({ icon: Icon = InfoIcon, title, detail, action }) {
  return (
    <div className="empty-state">
      <div className="empty-state__icon"><Icon size={28} weight="duotone" aria-hidden="true" /></div>
      <strong>{title}</strong>
      <p>{detail}</p>
      {action}
    </div>
  );
}

export function InlineNotice({ tone = "info", title, children }) {
  const Icon = tone === "success" ? CheckCircleIcon : tone === "warning" || tone === "danger" ? WarningCircleIcon : InfoIcon;
  return (
    <div className={`inline-notice inline-notice--${tone}`} role={tone === "danger" ? "alert" : undefined}>
      <Icon size={20} weight="fill" aria-hidden="true" />
      <div><strong>{title}</strong>{children && <span>{children}</span>}</div>
    </div>
  );
}

export function Drawer({ open, title, eyebrow, onClose, children, footer, width = "wide", testId }) {
  const closeRef = useRef(null);
  const panelRef = useRef(null);
  const triggerRef = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    triggerRef.current = document.activeElement;
    closeRef.current?.focus();
    const onKeyDown = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab" || !panelRef.current) return;
      const controls = [...panelRef.current.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')].filter((node) => !node.disabled);
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
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      window.requestAnimationFrame(() => triggerRef.current?.focus?.());
    };
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="drawer-layer" data-testid={testId}>
      <button className="drawer-backdrop" type="button" aria-label="关闭抽屉" onClick={onClose} />
      <aside ref={panelRef} className={`app-drawer app-drawer--${width}`} role="dialog" aria-modal="true" aria-label={title}>
        <header className="drawer-header">
          <div>{eyebrow && <span>{eyebrow}</span>}<h2>{title}</h2></div>
          <button ref={closeRef} className="icon-button" type="button" onClick={onClose} aria-label="关闭">
            <XIcon size={21} />
          </button>
        </header>
        <div className="app-drawer__body">{children}</div>
        {footer && <footer className="drawer-footer">{footer}</footer>}
      </aside>
    </div>
  );
}

export function Toast({ message, tone = "success" }) {
  if (!message) return null;
  const Icon = tone === "warning" || tone === "danger" ? WarningCircleIcon : CheckCircleIcon;
  return <div className={`toast toast--${tone}`} role="status"><Icon size={19} weight="fill" />{message}</div>;
}

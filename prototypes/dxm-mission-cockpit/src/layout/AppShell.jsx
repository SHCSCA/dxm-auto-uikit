import { useEffect, useRef, useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import {
  BrowserIcon,
  CaretRightIcon,
  ClipboardTextIcon,
  FileTextIcon,
  GearIcon,
  PencilSimpleLineIcon,
  ShieldCheckIcon,
  SquaresFourIcon,
  UserCircleIcon,
  UserIcon,
  WarningCircleIcon,
} from "@phosphor-icons/react";

const navigation = [
  { id: "edit", label: "编辑工作台", to: "/tasks/current", matches: ["/tasks", "/edit", "/batches"], icon: PencilSimpleLineIcon },
  { id: "template", label: "模板中心", to: "/templates", matches: ["/templates"], icon: SquaresFourIcon },
  { id: "browser", label: "浏览器现场", to: "/browser", matches: ["/browser"], icon: BrowserIcon },
  { id: "records", label: "批次记录", to: "/records", matches: ["/records"], icon: FileTextIcon },
  { id: "settings", label: "系统设置", to: "/settings", matches: ["/settings"], icon: GearIcon },
];

export function AppShell({ children, notify, runtimeIdentity }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef(null);
  const profileButtonRef = useRef(null);
  const menuRefocusTarget = useRef("first");
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => {
    const onPointerDown = (event) => {
      if (menuRef.current && !menuRef.current.contains(event.target)) setMenuOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, []);

  useEffect(() => {
    window.scrollTo({ top: 0, left: 0, behavior: "instant" });
  }, [location.pathname, location.search]);

  useEffect(() => {
    if (!menuOpen) return undefined;
    const menuItems = [...(menuRef.current?.querySelectorAll('[role="menuitem"]') || [])];
    const target = menuRefocusTarget.current === "last" ? menuItems[menuItems.length - 1] : menuItems[0];
    window.requestAnimationFrame(() => target?.focus());

    const onKeyDown = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setMenuOpen(false);
        window.requestAnimationFrame(() => profileButtonRef.current?.focus());
        return;
      }
      if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
      const items = [...(menuRef.current?.querySelectorAll('[role="menuitem"]') || [])];
      if (!items.length) return;
      const currentIndex = Math.max(0, items.indexOf(document.activeElement));
      const nextIndex = event.key === "Home"
        ? 0
        : event.key === "End"
          ? items.length - 1
          : (currentIndex + (event.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
      event.preventDefault();
      items[nextIndex].focus();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [menuOpen]);

  const openMenu = (target = "first") => {
    menuRefocusTarget.current = target;
    setMenuOpen(true);
  };

  return (
    <div className="app-shell">
      <aside className="sidebar" aria-label="主导航">
        <div className="brand">
          <img src="/assets/dxm-mark.png" alt="DXM" className="brand__mark" />
          <div><strong>DXM</strong><span>店小秘批量编辑 Agent</span></div>
        </div>

        <nav className="sidebar__nav">
          {navigation.map((item) => {
            const Icon = item.icon;
            const selected = item.matches.some((match) => location.pathname.startsWith(match));
            return (
              <NavLink
                key={item.id}
                className={`nav-item${selected ? " is-active" : ""}`}
                to={item.to}
                aria-current={selected ? "page" : undefined}
                aria-label={item.label}
                title={item.label}
              >
                <Icon size={22} weight={selected ? "fill" : "regular"} aria-hidden="true" />
                <span>{item.label}</span>
              </NavLink>
            );
          })}
        </nav>

        <div className="sidebar__context" aria-label="当前运行上下文">
          <div className="sidebar__context-head"><ShieldCheckIcon size={17} weight="fill" /><span>批量目标原型</span></div>
          <strong>一次批准，连续编辑</strong>
          <small>范围来自店小秘现场 · 只保存，不发布</small>
        </div>

        <div className="profile" ref={menuRef}>
          <button
            ref={profileButtonRef}
            type="button"
            className="profile__button"
            onClick={() => menuOpen ? setMenuOpen(false) : openMenu("first")}
            onKeyDown={(event) => {
              if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                event.preventDefault();
                openMenu(event.key === "ArrowUp" ? "last" : "first");
              }
            }}
            aria-expanded={menuOpen}
            aria-haspopup="menu"
            aria-controls="profile-menu"
            aria-label={`${runtimeIdentity?.operator || "运营小秘"}身份菜单`}
          >
            <UserCircleIcon size={37} weight="fill" aria-hidden="true" />
            <span>{runtimeIdentity?.operator || "运营小秘"}</span>
            <CaretRightIcon size={18} aria-hidden="true" />
          </button>
          {menuOpen && (
            <div className="profile-menu" role="menu" id="profile-menu" aria-label="运营身份菜单">
              <div className="profile-menu__header"><strong>{runtimeIdentity?.operator || "运营小秘"}</strong><span>本地原型身份 · 非真实连接</span></div>
              <button type="button" role="menuitem" onClick={() => { navigate("/tasks/current"); setMenuOpen(false); }}>
                <ClipboardTextIcon size={18} />查看批次工作台
              </button>
              <button type="button" role="menuitem" onClick={() => { navigate("/settings?tab=runtime"); notify?.("已打开当前运行身份"); setMenuOpen(false); }}>
                <UserIcon size={18} />查看运行身份
              </button>
            </div>
          )}
        </div>
      </aside>

      <main className="main-stage" key={location.pathname}>
        <div className="prototype-global-truth" role="status" aria-label="原型与生产状态">
          <WarningCircleIcon size={17} weight="fill" aria-hidden="true" />
          <strong>批量编辑目标原型</strong>
          <span>未来批次会一次批准并顺序编排；当前生产仍只放行受控 single_save，原型不执行真实写入。</span>
          <em>只保存 · 不发布</em>
        </div>
        {children}
      </main>
    </div>
  );
}

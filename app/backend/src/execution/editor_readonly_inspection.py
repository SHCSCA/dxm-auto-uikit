"""Read-only editor observations; never an execution capability or save receipt."""

import runpy
import time
from pathlib import Path
from urllib.parse import urlsplit


def make_editor_readonly_guard(probe_file: Path, allowlist_file: Path, read_apis):
    probe = runpy.run_path(str(probe_file))
    entries, errors, resolved = probe["load_allowlist"](allowlist_file)
    if errors:
        raise ValueError("Editor inspection read allowlist is invalid")
    for method, url in sorted(read_apis):
        parts = urlsplit(url)
        if (
            method not in {"GET", "POST"}
            or parts.scheme != "https"
            or parts.netloc != "www.dianxiaomi.com"
            or not parts.path.startswith("/api/")
            or parts.query or parts.fragment
            or any(word.lower() in url.lower() for word in probe["FORBIDDEN_URL_KEYWORDS"])
        ):
            raise ValueError("Editor inspection read allowlist contains an unsafe endpoint")
        for resource_type in ("xhr", "fetch"):
            reasons = [f"active_or_unknown_resource_type:{resource_type}"]
            if method == "POST":
                reasons.extend(["non_read_method:POST", "write_method:POST"])
            entries.append({
                "id": f"editor-existing-read:{method}:{parts.path}:{resource_type}",
                "decision": "approve", "method": method,
                "host": parts.netloc, "path": parts.path,
                "resource_type": resource_type, "readonly_post": method == "POST",
                "allowed_reasons": reasons, "allow_forbidden_keywords": [],
                "rationale": "Existing DXM_E2_PLAN_READ_ALLOWLIST; editor observation only",
            })
    return probe["ReadOnlyProbeGuard"](
        strict_active_requests=True, allowlist_entries=entries,
        allowlist_file=resolved, allowlist_errors=errors,
    )


EDITOR_READONLY_READY_SCRIPT = r"""expectedTitle => {
  const expected = String(expectedTitle || '').trim();
  if (!expected) return false;
  return [...document.querySelectorAll('input:not([type=password]),textarea,[contenteditable=true]')].some(el => {
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden'
      && String(el.value || el.innerText || '').trim() === expected;
  });
}"""


EDITOR_READONLY_HYDRATED_SCRIPT = r"""expectedSourceUrl => {
  if (typeof expectedSourceUrl !== 'string' || !expectedSourceUrl.trim()) return false;
  const fields = [...document.querySelectorAll('input[name="sourceUrl"]')].filter(el => {
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
  });
  return fields.length === 1 && fields[0].value === expectedSourceUrl;
}"""


# Exact structural identities observed in the 2026-09-08 editor inspection.
# Only the entry may be clicked; these are not generation/translation commands.
EDITOR_DIALOG_REVEAL_BINDINGS = {
    "translation": (".product-add-wrapper .header .btn-box button.translation-btn", "一键翻译"),
    "video": (".product-add-wrapper .video-operate", "图片生成视频"),
}

# Observed in the private 2026-09-08 translation surface; not a modal.
EDITOR_TRANSLATION_SURFACE_BINDING = '.ant-popover:visible .translate-panel:visible'
EDITOR_VIDEO_SURFACE_BINDING = '.ant-modal-wrap[role="dialog"]:visible:has(.img-translate-video)'

# The current public editor renders language rows and video choices as li
# elements, not inputs. This is observation only, never a capability receipt.
EDITOR_CONTENT_ACTION_SURFACE_SCRIPT = r"""action => {
  const visible = el => {
    if (!el) return false;
    const rect = el.getBoundingClientRect(), style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
  };
  const text = el => el ? String(el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim() : null;
  const describe = el => ({tag:el.tagName.toLowerCase(), text:text(el),
    visible:visible(el), disabled:!!el.disabled || el.getAttribute('aria-disabled') === 'true'});
  const roots = action === 'translation'
    ? [...document.querySelectorAll('.ant-popover .translate-panel')].filter(visible)
    : action === 'video'
      ? [...document.querySelectorAll('.ant-modal-wrap[role="dialog"]')]
          .filter(el => visible(el) && el.querySelector('.img-translate-video')) : [];
  const result = {schema:'dxm.editor_content_surface.v1', action, surface_match_count:roots.length,
    write_attempted:false, execution_allowed:false};
  if (roots.length !== 1) return result;
  const root = roots[0];
  const read = selector => ({selector, matches:[...root.querySelectorAll(selector)].filter(visible).map(describe)});
  if (action === 'translation') {
    const typeSelector = '.panel-translate-type .ant-radio-button-wrapper';
    result.types = {selector:typeSelector, matches:[...root.querySelectorAll(typeSelector)].filter(visible).map(el => {
      const inputs = [...el.querySelectorAll('input[type="radio"]')];
      return {...describe(el), selected:el.classList.contains('ant-radio-button-wrapper-checked'),
        input_match_count:inputs.length, value:inputs.length === 1 ? inputs[0].value : null,
        checked:inputs.length === 1 ? inputs[0].checked : null,
        disabled:!!el.disabled || el.getAttribute('aria-disabled') === 'true'
          || el.classList.contains('ant-radio-button-wrapper-disabled') || inputs.some(input => input.disabled)};
    })};
    const languageSelector = '.panel-language-list > .panel-language-item';
    result.languages = {selector:languageSelector, matches:[...root.querySelectorAll(languageSelector)].filter(visible).map(el => ({
      ...describe(el), titles:[...el.querySelectorAll('.panel-language-title')].map(text),
      descriptions:[...el.querySelectorAll('.panel-language-desc')].map(text)
    }))};
    result.content = read('.panel-content-main > span:not(.panel-content-edit)');
    result.edit_content = read('.panel-content-main > .panel-content-edit');
  } else {
    result.generate = read('.ant-modal-header .title-right button.btn-orange');
    result.quota = read('.ant-modal-header .title-right > .gray-c');
    result.quota_notice = read('.img-translate-video .title-tips .flex-1');
    const imageSelector = '.img-translate-video .content-imgs > li';
    result.images = {selector:imageSelector, matches:[...root.querySelectorAll(imageSelector)].filter(visible).map(el => ({
      ...describe(el), images:[...el.querySelectorAll('img')].map(img => ({
        src:img.getAttribute('src'), current_src:img.currentSrc || null,
        complete:img.complete, natural_width:img.naturalWidth, natural_height:img.naturalHeight
      }))
    }))};
    for (const [key, selector, label] of [
      ['transitions','.img-translate-video .page-content_right-top .content-list > li','.w-full.text-center'],
      ['music','.img-translate-video .page-content_right-bottom .content-list > li','.m-left5']
    ]) {
      result[key] = {selector, matches:[...root.querySelectorAll(selector)].filter(visible).map(el => ({
        ...describe(el), selected:el.classList.contains('activeName'), labels:[...el.querySelectorAll(label)].map(text)
      }))};
    }
  }
  return result;
}"""


EDITOR_READONLY_FORM_SCRIPT = r"""root => [...root.querySelectorAll(
  'input:not([type=password]),textarea,select,[contenteditable=true]'
)].filter(el => !el.closest('[role="dialog"],.ant-modal')).map(el => ({
  tag: el.tagName.toLowerCase(), id: el.id, name: el.getAttribute('name'),
  type: el.getAttribute('type'), disabled: !!el.disabled, readOnly: !!el.readOnly,
  value: 'value' in el ? el.value : el.innerHTML,
  checked: 'checked' in el ? el.checked : null,
  selected: el.tagName === 'SELECT' ? [...el.selectedOptions].map(option => option.value) : null,
  files: el.type === 'file' ? [...el.files].map(file => ({
    name: file.name, size: file.size, type: file.type, lastModified: file.lastModified
  })) : null
}))"""


def wait_editor_form_stable(page, main_form):
    """Observe two unchanged seconds, bounded to fifteen; never change the form."""
    started = stable_since = time.monotonic()
    snapshot = main_form.evaluate(EDITOR_READONLY_FORM_SCRIPT)
    changes = 0
    while time.monotonic() - started < 15:
        page.wait_for_timeout(250)
        current = main_form.evaluate(EDITOR_READONLY_FORM_SCRIPT)
        if current != snapshot:
            snapshot = current
            stable_since = time.monotonic()
            changes += 1
        elif snapshot and time.monotonic() - stable_since >= 2:
            return {'ok': True, 'snapshot': snapshot, 'changes': changes}
    return {'ok': False, 'snapshot': None, 'changes': changes}


# Broad observation only, not locator bindings or authorization for popup actions.
EDITOR_READONLY_OVERLAYS_SCRIPT = r"""() => {
  const visible = el => {
    const rect = el.getBoundingClientRect(), style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
  };
  const describe = el => ({tag:el.tagName.toLowerCase(), id:el.id,
    role:el.getAttribute('role'), className:el.getAttribute('class'),
    text:(el.innerText || el.textContent || '').slice(0, 3000),
    attributes:Object.fromEntries(['name','type','aria-label','aria-controls','aria-describedby','data-value','data-testid']
      .map(key => [key,el.getAttribute(key)]).filter(([,value]) => value !== null)),
    value:'value' in el ? el.value : null, checked:'checked' in el ? el.checked : null,
    disabled:!!el.disabled});
  return [...document.querySelectorAll('[role=dialog],[role=tooltip],.ant-popover,.ant-modal')]
    .filter(visible).filter((el, _i, all) => !all.some(other => other !== el && other.contains(el)))
    .slice(0, 10).map(el => ({...describe(el),
      nodes:[...el.querySelectorAll('input:not([type=password]),select,button,[role],[tabindex],label,a,span,div')]
        .filter(visible).slice(0, 250).map(describe)}));
}"""


EDITOR_READONLY_DOM_SCRIPT = r"""() => {
  const visible = el => {
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
  };
  const text = el => String(el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
  // Observed attributes only: no generated selectors, arbitrary data-* or framework state.
  const bindingAttributes = el => Object.fromEntries([
    'id', 'name', 'role', 'for', 'aria-labelledby', 'aria-controls',
    'data-testid', 'data-field', 'data-ui-binding', 'data-attribute-id', 'data-attr-name-id'
  ].map(name => [name, el.getAttribute(name)]).filter(([, value]) => value !== null));
  const ancestors = el => {
    const result = [];
    for (let parent = el.parentElement; parent && result.length < 6; parent = parent.parentElement) {
      result.push({tag: parent.tagName.toLowerCase(), className: parent.getAttribute('class'),
        attributes: bindingAttributes(parent)});
    }
    return result;
  };
  const controls = [...document.querySelectorAll('input:not([type=password]),textarea,select,button,[role=button],[role=dialog],[contenteditable=true]')]
    .filter(visible).slice(0, 1500).map(el => ({
      tag: el.tagName.toLowerCase(), id: el.id, name: el.getAttribute('name'),
      role: el.getAttribute('role'), type: el.getAttribute('type'),
      testid: el.getAttribute('data-testid'), className: el.className,
      label: el.getAttribute('aria-label'), placeholder: el.getAttribute('placeholder'),
      text: text(el).slice(0, 1500), value: 'value' in el ? el.value : null,
      disabled: !!el.disabled, readOnly: !!el.readOnly,
      checked: 'checked' in el ? el.checked : null,
      bindingAttributes: bindingAttributes(el), ancestors: ancestors(el),
      labels: [...(el.labels || [])].filter(visible).slice(0, 8).map(label => ({
        text: text(label).slice(0, 300), attributes: bindingAttributes(label)
      })),
      parentText: el.parentElement ? text(el.parentElement).slice(0, 600) : '',
      formItemText: el.closest('.ant-form-item') ? text(el.closest('.ant-form-item')).slice(0, 1500) : '',
      options: el.tagName === 'SELECT' ? [...el.options].map(o => ({value:o.value, text:o.text, disabled:o.disabled})) : null
    }));
  return {url: location.href, title: document.title, readyState: document.readyState,
    bodyText: document.body.innerText.slice(0, 120000), controls};
}"""

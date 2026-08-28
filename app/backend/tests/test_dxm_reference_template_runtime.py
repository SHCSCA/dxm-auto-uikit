from __future__ import annotations

from playwright.sync_api import sync_playwright

from src.execution.dxm_login_flow import DxmLoginFlow


REFERENCE_TEMPLATE_HTML = """
<!doctype html>
<html>
  <body>
    <section id="attribute-section">
      <div>属性信息</div>
      <div>产品属性模板</div>
      <div class="ant-select" style="width: 260px; height: 36px;">
        <div class="ant-select-selector" style="width: 260px; height: 36px;">
          <span class="ant-select-selection-item">请选择引用模板</span>
          <input id="attribute-template-select" aria-expanded="true" />
        </div>
      </div>
    </section>
    <div class="ant-select-dropdown" style="position: absolute; left: 8px; top: 110px; width: 260px;">
      <div class="ant-select-item-option" role="option" style="height: 32px;">普货属性模板</div>
    </div>
    <script>
      document.querySelector('[role="option"]').addEventListener('click', () => {
        document.querySelector('.ant-select-selection-item').textContent = '普货属性模板'
      })
    </script>
  </body>
</html>
"""


def _flow(tmp_path) -> DxmLoginFlow:
    return DxmLoginFlow(object(), state_file=tmp_path / "runtime-state.json")


def test_attribute_reference_template_selects_exact_visible_option(
    tmp_path,
) -> None:
    flow = _flow(tmp_path)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1000, "height": 700})
        page.set_content(REFERENCE_TEMPLATE_HTML)

        results = flow._apply_dxm_reference_templates_on_page(
            page,
            {
                "dxm_reference_templates_resolved": {
                    "attribute_info": {
                        "names": ["普货属性模板"],
                        "required": True,
                    }
                }
            },
        )

        assert results["attribute_info"]["ok"] is True
        assert results["attribute_info"]["expected_value"] == "普货属性模板"
        assert results["attribute_info"]["value_after"] == "普货属性模板"
        assert results["attribute_info"]["exact_readback"] is True
        assert page.locator(".ant-select-selection-item").inner_text() == "普货属性模板"
        browser.close()

def test_duplicate_exact_reference_options_fail_closed_without_click(
    tmp_path,
) -> None:
    flow = _flow(tmp_path)
    html = REFERENCE_TEMPLATE_HTML.replace(
        '<div class="ant-select-item-option" role="option" style="height: 32px;">普货属性模板</div>',
        (
            '<div class="ant-select-item-option" role="option" style="height: 32px;">普货属性模板</div>'
            '<div class="ant-select-item-option" role="option" style="height: 32px;">普货属性模板</div>'
        ),
    ).replace(
        "document.querySelector('[role=\"option\"]')",
        "document.querySelectorAll('[role=\"option\"]')[0]",
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1000, "height": 700})
        page.set_content(html)
        clicks = {"count": 0}
        page.expose_function(
            "recordReferenceClick",
            lambda: clicks.__setitem__("count", clicks["count"] + 1),
        )
        page.evaluate(
            """() => document.querySelectorAll('[role="option"]').forEach(
              option => option.addEventListener('click', () => window.recordReferenceClick())
            )"""
        )
        anchor = page.locator(".ant-select").bounding_box()
        assert anchor is not None

        result = flow._click_ant_option_near_rect(
            page,
            ["普货属性模板"],
            anchor,
            required=True,
        )

        assert result["ok"] is False
        assert result["reason"] == "未找到匹配选项"
        assert clicks["count"] == 0
        browser.close()

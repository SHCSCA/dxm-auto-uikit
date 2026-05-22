# V1 Dang Kang / 速卖通半托管 Save-Only 模板规范

**Status**: Draft  
**Last Updated**: 2026-05-22  
**Scope**: Dang Kang 店铺、AliExpress / 速卖通半托管、V1 `single_save` / `batch_save`、只保存不发布。

## 1. 目标

把已经跑通的 V1 字段配置收敛为可复用模板，后续任务只覆盖商品差异字段，避免每次重新配置类目、图片、价格、库存、物流、合规和半托管字段。

本规范不授权发布、不操作真实店小秘、不写真实任务 DB。示例文件只用于模板录入或测试夹具参考；任何真实账号、真实网络写入、发布相关动作都必须走独立人工确认闸门。

## 2. 当前合并逻辑

V1 执行默认值由 `V1TaskRunner._execution_defaults` 生成：

1. 读取启用模板，按仓库返回顺序反向合并。
2. 仅合并 canonical `template_type`：`category`、`sku`、`pricing`、`logistics`、`image`、`compliance`、`semi_managed`。
3. 模板可用 `payload.binding` / `payload.applies_to` / `payload.match` 绑定 `store_name`、`category_name`、`platform`。
4. 之后合并任务 payload；`template_overrides` 对指定模板域做覆盖。
5. 最后合并商品 payload，商品级字段优先级最高。

结论：示例模板必须使用 canonical `template_type`，字段建议按域分组，商品差异只放商品 payload 或任务 `template_overrides`。店小秘页面里的可复用参考模板统一写入 `dxm_reference_templates` 分区映射，不再把示例写成散落的 `*_priorities` 字段；旧字段仍由执行器兼容解析，用于迁移期和回归测试。

## 3. 推荐模板字段

| Domain | Required / Recommended fields | 推荐值 / 策略 |
|---|---|---|
| `category` | `template_category_id` 或 `category_match` / `category_keyword`；`dxm_reference_templates.attribute_info` | Dang Kang 速卖通立牌类目需人工确认后固化；属性信息模板名写入 `names`。 |
| `sku` | `sku_code` 或 SKU 规则字段 | V1 可沿用店小秘 / 商品导入 SKU；不要伪造条码。 |
| `pricing` | `declared_value`、`stock`、`retail_price` | `declared_value=1`、普通库存 `200`；实际价格优先商品级覆盖。 |
| `logistics` | `weight`、`length`、`width`、`height`、`delivery_days`、`logistics_attribute`、`is_original_box`；`dxm_reference_templates.freight` / `dxm_reference_templates.service` | 默认 `0.03kg`、`10 x 10 x 2cm`、发货 `7` 天、`普货`、`否`。运费/服务模板名需人工确认。 |
| `image` | `eu_outer_package_filename`、`marketing_images_strategy`；可选 `dxm_reference_templates.description` | 欧盟外包装标签图必须明确文件名；营销图策略推荐 `generate`，如已人工生成可用 `already_generated` 并在任务中覆盖。 |
| `compliance` | `dxm_reference_templates.eu_responsible`、`dxm_reference_templates.manufacturer`、`dxm_reference_templates.compliance`，以及 `customs_product_name_priorities`、已知材质/资质字段 | 不自动伪造资质；缺真实配置则进入人工确认。 |
| `semi_managed` | `product_price` 或 `supply_price`、`jit_stock`、`is_original_box`、`length`、`width`、`height`、`goods_code_strategy`、`barcode_strategy`；可选 `dxm_reference_templates.semi_managed` | JIT 库存 `100`；是否原箱 `否`；尺寸默认 `10 x 10 x 2cm`；V1 允许货品编码和货品条码按策略留空。 |

### `dxm_reference_templates` 分区映射

每个模板 payload 可以在顶层或对应 domain 内声明：

```json
{
  "dxm_reference_templates": {
    "freight": {
      "names": ["CONFIRM_FREIGHT_TEMPLATE"],
      "required": true
    },
    "description": {
      "names": [],
      "required": false
    }
  }
}
```

当前分区名：`attribute_info`、`description`、`freight`、`service`、`eu_responsible`、`manufacturer`、`compliance`、`semi_managed`。`required=true` 且 `names` 为空时，配置校验必须失败并阻止进入 `save_only`；`required=false` 表示该参考模板可缺省。

## 4. 校验规则

`ConfigValidationService` 对 `single_save` / `batch_save` 做启动前校验：

- 必须存在启用模板：`category`、`sku`、`pricing`、`logistics`、`image`、`semi_managed`。
- `compliance` 必须存在模板，或任务 / 商品 payload 中提供 `compliance` 域。
- 必须能从图片模板、任务或商品中找到 `image.eu_outer_package_filename` 等价字段。
- 必须明确 `image.marketing_images_strategy`。
- 必须明确 `logistics.weight` 和 `logistics.length/width/height`。
- 必须明确 `semi_managed.product_price` 或 `semi_managed.supply_price`。
- 必须明确 `semi_managed.jit_stock`、`semi_managed.is_original_box`、`semi_managed.length/width/height`。
- 必须明确 `semi_managed.goods_code_strategy` 和 `semi_managed.barcode_strategy`，以表达“可留空”是配置决策，不是漏填。
- 若配置了 `dxm_reference_templates.<section>.required=true`，则必须提供非空 `names`；缺失时启动前失败，不进入 `save_only`。
- 执行报告必须包含 `dxm_reference_templates_resolved` 和 `dxm_reference_template_results`：前者记录配置解析出的参考模板分区、候选名称和 required 状态，后者记录页面实际应用结果和失败原因，便于回归审计。

## 5. 网络 / 发布安全边界

- 本模板规范不改变现有安全边界：不操作真实店小秘、不发起真实网络写入、不发布商品。
- V1 只允许 `single_save` / `batch_save` 的 save-only 路径；`publish`、`continue_publish`、`save_and_publish` 必须被拒绝。
- 保存前后仍需保留发布隔离证据：目标动作只能是“保存”，报告中的 `published` 必须为 `false`。

## 6. 人工确认项

上线跑真实任务前必须确认：

- Dang Kang 当前速卖通类目 ID / 类目路径是否仍匹配目标商品。
- `eu_outer_package_filename` 对应图片是否已在速卖通图片银行可选，且为正确外包装/标签实拍图。
- 运费模板、服务模板名称是否与店小秘页面完全一致。
- 欧盟负责人、制造商、海关品名候选是否仍有效。
- `supply_price` / `product_price` 是否适用于当前商品利润策略；示例值不可直接用于真实商品。
- 货品编码和货品条码留空是否仍被当前半托管页面接受。

参考 JSON：`docs/product/v1-dang-kang-smt-semi-managed-save-only-template.json`。

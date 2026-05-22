# V1 Dang Kang / 速卖通半托管 Save-Only 模板规范

**Status**: Draft  
**Last Updated**: 2026-05-22  
**Scope**: Dang Kang 店铺、AliExpress / 速卖通半托管、V1 `single_save` / `batch_save`、只保存不发布。

## 1. 目标

把已经跑通的 V1 字段配置收敛为可复用模板，后续任务只覆盖商品差异字段，避免每次重新配置类目、图片、价格、库存、物流、合规和半托管字段。

本规范不授权发布、不操作真实店小秘、不写真实任务 DB。示例文件只用于模板录入或测试夹具参考。

## 2. 当前合并逻辑

V1 执行默认值由 `V1TaskRunner._execution_defaults` 生成：

1. 读取启用模板，按仓库返回顺序反向合并。
2. 仅合并 canonical `template_type`：`category`、`sku`、`pricing`、`logistics`、`image`、`compliance`、`semi_managed`。
3. 模板可用 `payload.binding` / `payload.applies_to` / `payload.match` 绑定 `store_name`、`category_name`、`platform`。
4. 之后合并任务 payload；`template_overrides` 对指定模板域做覆盖。
5. 最后合并商品 payload，商品级字段优先级最高。

结论：示例模板必须使用 canonical `template_type`，字段建议按域分组，商品差异只放商品 payload 或任务 `template_overrides`。

## 3. 推荐模板字段

| Domain | Required / Recommended fields | 推荐值 / 策略 |
|---|---|---|
| `category` | `template_category_id` 或 `category_match` / `category_keyword`；`attribute_template_priorities` | Dang Kang 速卖通立牌类目需人工确认后固化。 |
| `sku` | `sku_code` 或 SKU 规则字段 | V1 可沿用店小秘 / 商品导入 SKU；不要伪造条码。 |
| `pricing` | `declared_value`、`stock`、`retail_price` | `declared_value=1`、普通库存 `200`；实际价格优先商品级覆盖。 |
| `logistics` | `weight`、`length`、`width`、`height`、`delivery_days`、`freight_template_priorities`、`service_template_priorities`、`logistics_attribute`、`is_original_box` | 默认 `0.03kg`、`10 x 10 x 2cm`、发货 `7` 天、`普货`、`否`。运费/服务模板名需人工确认。 |
| `image` | `eu_outer_package_filename`、`marketing_images_strategy` | 欧盟外包装标签图必须明确文件名；营销图策略推荐 `generate`，如已人工生成可用 `already_generated` 并在任务中覆盖。 |
| `compliance` | `eu_responsible_priorities`、`manufacturer_priorities`、`customs_product_name_priorities`，以及已知材质/资质字段 | 不自动伪造资质；缺真实配置则进入人工确认。 |
| `semi_managed` | `product_price` 或 `supply_price`、`jit_stock`、`is_original_box`、`length`、`width`、`height`、`goods_code_strategy`、`barcode_strategy` | JIT 库存 `100`；是否原箱 `否`；尺寸默认 `10 x 10 x 2cm`；V1 允许货品编码和货品条码按策略留空。 |

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

## 5. 人工确认项

上线跑真实任务前必须确认：

- Dang Kang 当前速卖通类目 ID / 类目路径是否仍匹配目标商品。
- `eu_outer_package_filename` 对应图片是否已在速卖通图片银行可选，且为正确外包装/标签实拍图。
- 运费模板、服务模板名称是否与店小秘页面完全一致。
- 欧盟负责人、制造商、海关品名候选是否仍有效。
- `supply_price` / `product_price` 是否适用于当前商品利润策略；示例值不可直接用于真实商品。
- 货品编码和货品条码留空是否仍被当前半托管页面接受。

参考 JSON：`docs/product/v1-dang-kang-smt-semi-managed-save-only-template.json`。

# L0 策略 B · 迁移计划（E2 关闭硬门槛）

> **G0 裁定（2026-08-03 · 用户）**：**策略 B**  
> E2 正式 `E2_ACCEPTED` **依赖**完整后端 L0 绿，或每个失败簇有**可审计迁移关闭证明**（不得靠放宽 fail-closed / 三铁证 / 发布与认领叙事换绿）。  
> **状态**：进行中；在 L0 达标前 E2 仅可为 `E2_DEV_SLICE`，不得宣称 `E2_ACCEPTED` / `MVP_READY` / `PROD_READY`。

---

## 1. 目标与禁止

### 目标

1. 在 **G1 固定 SHA** 上可复现地跑完整 `pytest`。  
2. 将失败降为 **0**，或形成「可接受剩余失败表」且**每一簇**有关闭证明 + 负责人签字（默认目标仍是 **0 failed**）。  
3. 历史 `claim_only` / `single_save` 能力可保留为安全回归，**不得**恢复为 MVP 产品主路径前置。

### 禁止（迁移红线）

- 为旧测补不安全默认值绕过身份/读回/三铁证  
- 接受缺 `save_result` / `fresh_probe` 的“成功”  
- 重开已关闭的独立 `/manual-approval` 令牌入口（须保持 `BATCH_APPROVAL_REQUIRES_ATOMIC_START`）  
- 放宽 PublishGuard / 发布指令拒绝  
- 读取并提交 Cookie、`data/sessions`、未脱敏 raw  

---

## 2. 失败簇索引（按优先级）

| 簇 ID | 代表范围 | 现状（约） | 关闭策略 |
|-------|----------|------------|----------|
| **L0-C01** | `test_edit_batch_bundle_composer` + 前端 composer 合同 | **已绿**（店铺级 + digest） | 保持；回归纳入 G2 扩展集 |
| **L0-C02** | acquisition claim 工作流 | 部分已迁 `source_url` 必填 | 整文件 0 fail；不恢复 claim 为主路径 |
| **L0-C03** | action-result 合同 | 部分已补 `save_result`/`fresh_probe` | 整文件 0 fail；不放宽证据 |
| **L0-C04** | Agent Console | 预览改 probe | 整文件 0 fail |
| **L0-C05** | LoginFlow / 公开响应最小披露 | 部分已迁 | 不扩大 API 泄露；测改读持久化证据 |
| **L0-C06** | `test_batch_edit_api` 独立批准 | **~22 failed**（正确 409） | **迁到 E3 原子 approve-and-start 合同** 或登记「生产正确、测过时」关闭表；**禁止**重开旧端点 |
| **L0-C07** | v1 runner / single_save / claim_only 状态机 | 大批历史失败 | 测迁移到现行公开入口 + 强制身份字段；不改弱生产私有 API |
| **L0-C08** | 其余 login_flow 私有 `_save_only_on_page` 直调 | TypeError 等 | 测改走公开 save 路径或构造完整强制参数 |
| **L0-C09** | 其它未分类 | 以完整 L0 摘要为准 | 逐项入表 |

数字以 **G1 SHA 上当次完整 L0 报告** 为准；本文件簇表随迁移更新。

---

## 3. 里程碑

| 里程碑 | 内容 | 出口 |
|--------|------|------|
| **M0** | G0=B 书面化 + G1 commit | `E2-CLOSE-CANDIDATE` SHA |
| **M1** | G2 在 SHA 上专项+前端 build 绿 | 记录命令与条数 |
| **M2** | 完整 L0 基线报告（该 SHA） | failed 列表归档 `docs/product/l0-baseline-*.md` 或 PROGRESS |
| **M3** | 关闭 L0-C06 策略（迁 E3 合同或签字剩余表） | 簇关闭证明 |
| **M4** | 关闭 C02–C05、C07–C08 至 failed=0 或签字表 | 同左 |
| **M5** | 完整 L0 0 failed（或签字可接受表） | 满足 G3 |
| **M6** | G4 真实零写 + G5 残留 | 才可申请 `E2_ACCEPTED` |

---

## 4. 单簇关闭证明模板

```text
簇 ID:
文件/用例:
基线失败数 → 关闭后:
改动类型: [仅测迁移 | 生产修复 | 合同澄清]
生产安全是否放宽: 否（必须）
复跑命令:
exit code / passed/failed:
仍禁止事项确认:
```

---

## 5. 变更记录

| 日期 | 说明 |
|------|------|
| 2026-08-03 | 用户裁定 G0=策略 B；初版迁移计划 |

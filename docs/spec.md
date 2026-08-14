# 产品规则

先读 `HANDOFF.md` 与本文件。实现细节以代码与测试为准。

## 章标题

章标题由系统按 `order_index` + `title` 生成「第N章 标题」（阿拉伯数字，如 `第1章 醒木`），不是「第一章」。

- 写手 / 修订不得把「第N章 标题」或「第一章 xxx」写入场景正文（字数与 Judge 保持干净）。
- 审稿页、CLI/API、generic / 起点 / 番茄 / EPUB 导出共用 `novel_agent.production.heading.chapter_heading`。
- `order_index < 1` 时回退为去空白后的 `title`。

## 两段式 SCENE 标记

两段式 SCENE 标记用真实 scene_id；解析容忍占位词与重复块。

- 格式说明在已知场景卡时写入真实 id，示例必须是 `<<<SCENE:v1c001_s1>>>` 或本批第一个 id，禁止把「场景id」/ `scene_id` 写进标记。
- `parse_two_part` 先剥 `<think>` / `<thinking>`；把占位词 `场景id` / `scene_id` / `场景ID` 按顺序填入尚未占用的期望槽；同一真实 id 重复时保留最后一块非空正文。真正未知的多余 id 仍失败。

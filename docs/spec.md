# 产品规则

先读 `HANDOFF.md` 与本文件。实现细节以代码与测试为准。

## 章标题

章标题由系统按 `order_index` + `title` 生成「第N章 标题」（阿拉伯数字，如 `第1章 醒木`），不是「第一章」。

- 写手 / 修订不得把「第N章 标题」或「第一章 xxx」写入场景正文（字数与 Judge 保持干净）。
- 审稿页、CLI/API、generic / 起点 / 番茄 / EPUB 导出共用 `novel_agent.production.heading.chapter_heading`。
- `order_index < 1` 时回退为去空白后的 `title`。

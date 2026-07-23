# 对标成熟题库·功能缺口路线图(2026-07-24)

> 面向日本大学院入试(院試)双语题库。栈:Flask + SQLite(WAL)+ Jinja2 + 原生 JS + MathJax v4,单 VPS。
> 对标:力扣/LeetCode、AtCoder、洛谷、過去問道場、Brilliant、Anki、Quizlet、Math StackExchange、予備校在线。

## 已实现(不再列入缺口)
字体排版(自托管中日字体+MathJax v4)· 双轨题解 · 渐进提示 · **采点四段** · 知识点标签+多维筛选+facet ·
题单(官方+自建)· 学习闭环(做题状态/掌握/SM-2 复习/做题日历/进度面板)· 院試定位筛选 ·
**相关题推荐** · **全文检索强化(双轨+标签名)** · **手写作答采点判题(可插拔 LLM 引擎)** · 账号/反馈/查看日志。

---

## P0 必做(留存与"真实产品"的关键细节)

1. **个人笔记(per-question notes)** — 每题一块可保存的私人笔记。对标力扣/Anki。
   实现:新表 `question_notes(user_id,question_id 唯一,content,updated_at)`;GET/PUT `/api/questions/<id>/note`;
   详情页文本域自动保存。**S,加 1 表。** → 本轮实现。

2. **收藏/书签(bookmarks)** — 一键收藏 + "我的收藏"筛选/视图。对标全平台。
   实现:新表 `question_bookmarks(user_id,question_id,created_at)`;toggle 端点;列表/详情星标;
   列表 `bookmarked=1` 筛选(仿 masteryStatus)。**S,加 1 表。** → 本轮实现。

3. **题解纠错上报(report issue on solution)** — 用户标记题解/采点错误,形成质量闭环。对标 StackExchange/洛谷。
   实现:**复用既有 Feedback 表**(加可选 question_id 关联),详情页"报告问题"入口;admin 反馈页显示题号。**S。**

4. **前后题导航(prev/next)** — 详情页在当前筛选/题单内跳上一题/下一题。对标力扣题目间导航。
   实现:进入详情带 `?ctx=list&...` 或 `?list=<id>`;端点 `/api/questions/<id>/neighbors?...` 回前后题 id。**M。**

## P1 高价值

5. **知识点树浏览页 `/tags`** — 按 category 分组罗列全部知识点(带题数),点击进筛选后的题库。对标力扣题库标签页。
   实现:复用 `tag_facets`;新页 + 路由。**S–M,纯读。**

6. **每日一题(daily)** — 首页/导航"今日一题",按日期确定性轮播(hash(date)%N)。对标多平台。
   实现:端点按当日选一题;首页卡片。**S。**(注意:workflow/脚本禁 Date.now,但 Web 请求内可用服务器日期。)

7. **个人统计仪表盘增强 `/overview`** — 掌握度按知识点雷达、近30天做题曲线、正确率、连续打卡 streak。
   对标力扣个人主页/Anki 统计。实现:聚合 question_progress/error_book/view_logs;既有 /overview 扩展。**M。**

8. **Anki / CSV 导出** — 把错题或题单导出为 Anki(apkg 较重,先 CSV/TSV)供离线复习。对标 Anki 生态。
   实现:端点流式生成 CSV;GeneratedFile 登记(基础设施已在)。**M。**

9. **离线练习册 PDF 导出** — 题目/题单导出可打印 PDF(无 xelatex 时走 HTML 打印样式 `@media print`)。
   实现:打印专用模板 + 按钮;或既有 PDF 基础设施。**M。**(环境无 xelatex,优先 HTML 打印。)

## P2 锦上添花

10. **QAPage 结构化数据 + sitemap.xml + meta** — 公开题面页注入 schema.org QAPage JSON-LD,提升搜索收录/排名。**S,增长向但不可视。**
11. **键盘快捷键** — 详情页 j/k 切题、f 收藏、n 笔记;列表 / 聚焦搜索。对标力扣/Gmail。**S。**
12. **难度投票 + 社区难度** — 用户投票,显示"官方 vs 社区"难度分布。**M,加 1 表。**
13. **无障碍(a11y)** — 复习/评分交互补 ARIA、focus 管理、MathJax 语义标注。**S–M。**
14. **通知/复习提醒** — 到期错题邮件/站内提醒(需 SMTP)。**M,依赖外部。**
15. **社区题解 / 多题解** — 用户提交替代解法,点赞。**L,内容治理成本高。**

## 若今晚只再做 3 件(除判题外)
**① 个人笔记 ② 收藏书签 ③ 题解纠错上报** —— 三者都是 S、加表少/复用现表、纯自包含、直接可视、
补齐"真实用户日常学习动作"(记、藏、纠),留存杠杆最高,风险最低。→ 本轮优先落地 ①②(③ 视余力)。

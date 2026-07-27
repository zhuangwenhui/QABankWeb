# scripts/ 用途索引

19 个脚本,3346 行。**没有一个是"跑完就该删"的一次性脚本** —— 每次有新内容入库,
盘查类会重新报问题,修复类就是那些问题的解药。删掉修复类等于留下探测器、扔掉解药。

写这份索引是因为:光看文件名分不出"哪个还该跑、哪个跑完了、哪个必须配着哪个跑"。

## 怎么用:盘查 → 修复 → 复查

内容质量的工作流是三步,`audit_X` 与 `fix_X` **成对**使用:

```
audit_language.py   报告问题  →  fix_language.py --apply       机械修正  →  再跑 audit 复查
audit_latex.py      报告问题  →  fix_math_text.py --apply      包 \text{}  →  再跑 audit 复查
audit_images.py     报告问题  →  recrop_images.py --apply      重裁图片  →  再跑 audit 复查
```

**所有 `fix_*` / `repair_*` 默认只试算,必须显式加 `--apply` 才写库。** 先不加参数跑一遍看它打算改什么。

> ⚠️ **别对本地库跑盘查。** `instance/question_bank.db` 是过期开发库,只有 37 道旧种子题,
> 会报一堆假命中。线上 358 道在 VPS `/srv/question-bank/instance/question_bank.db`:
> ```bash
> cd /srv/question-bank && .venv/bin/python3 scripts/audit_language.py instance/question_bank.db
> ```

## 盘查类(只读,不改任何东西)

| 脚本 | 行 | 查什么 |
|---|---|---|
| `audit_language.py` | 543 | 中日双轨各按各自标准做机器可判定的全量语言检查(跨语言字符用 GB2312/Shift_JIS 判定,不引第三方库) |
| `audit_render.py` | 268 | 全站渲染巡检:带网络延迟遍历每个显示题目内容的页面与交互,`--scheme light\|dark` 还查对比度 |
| `audit_solution_completeness.py` | 212 | 题解是否覆盖题目全部小问,以及有无被截断的迹象 |
| `audit_answer_coverage.py` | 141 | 小问覆盖:题面问了几问,题解就得答几问 |
| `audit_images.py` | 121 | 题面图 PDF 跨页截断检测 |
| `audit_latex.py` | 108 | LaTeX 可渲染性:找出 MathJax 认不出的环境/宏(白名单在 `KNOWN_ENVS`) |

> `audit_latex.py` 是全仓唯一没被任何测试或文档提及的脚本,但**别按"零引用即删"处理** ——
> 它是上线前唯一能发现"MathJax 认不出的环境 → 页面上一个红色报错框"的检查。

## 修复类(与上面配对,默认试算,`--apply` 才写库)

| 脚本 | 行 | 修什么 | 配对 |
|---|---|---|---|
| `fix_language.py` | 261 | 语言的机械修正:日文轨结构小标题整套是中文、句読点体例混用等 | `audit_language.py` |
| `fix_math_text.py` | 216 | 数学模式里裸露的中日文包进 `\text{}`(否则按变量排版,字形与间距都不对) | `audit_latex.py` |
| `recrop_images.py` | 134 | 被 PDF 跨页切断的题面图裁到留白边界 | `audit_images.py` |
| `repair_ordered_lists.py` | 98 | 被误改成全角的 markdown 有序列表符号改回来 | — |

> `repair_ordered_lists.py` 修的是 `fix_language.py` 早期版本的越界(把「1. 」这样的**列表项目符号**
> 也当成句点转成了「1。 」)。源头已在 2026-07-27 打好补丁,所以它在干净数据上跑就是报 0 命中 ——
> 保留它相当于一个免费的回归检查:哪天 `fix_language` 又越界了,它会立刻报出来。

## 落库/导入类(幂等,吃外部 JSON,新内容入库时用)

| 脚本 | 行 | 干什么 |
|---|---|---|
| `apply_language_patches.py` | 168 | 把逐题语言评审的 (old, new) 替换补丁落库,落库前做机械校验(old 必须恰好出现一次) |
| `apply_knowledge_tags.py` | 85 | 把 `tagmap.json` 的知识点分类幂等写入 `tags` / `question_tags`(`--prune` 可清理旧关联) |
| `sync_solution_columns.py` | 83 | 把本地整理好的题解同步进**在跑的**生产库,只动五列(生产库同时装着用户数据,不能整库覆盖) |
| `apply_generated_content.py` | 56 | 把渐进提示与采点四段幂等写入 `Question.hints` / `solution_structured` |

## 构建类

| 脚本 | 行 | 干什么 | 谁在用 |
|---|---|---|---|
| `build_fonts.py` | 293 | 字体子集化流水线:语料收集 → 合并兜底 → 子集 woff2 → @font-face/CSS → 覆盖校验 | `tests/test_build_fonts.py` 导入 |
| `gen_official_lists.py` | 143 | 官方题单自动生成(纯元数据,无需 LLM) | **`tests/test_lists.py:231` 导入,删了 pytest 就挂** |
| `gen_charsets.py` | 48 | 由编码枚举生成兜底字表(GB2312 6763 字 / JIS X0208 6590 字) | `tests/test_build_fonts.py:17` 调用 |
| `refresh_fonts.sh` | 45 | 新题发布后刷新自托管字体子集(SSH 只读导语料 → 重建) | CI 对 `scripts/*.sh` 跑 shellcheck |

> 依赖注意:`build_fonts.py` 需要 `fontools[woff]`,它是**手写在 `requirements-dev.txt` 的 pip-compile 页脚之后**的。
> 重跑 `pip-compile` 会静默丢掉它,随即打断 `ci.yml:17` 与 `tests/test_build_fonts.py:110`。
> 要动依赖,先改 `requirements-dev.in`。

## 端到端护栏

| 脚本 | 行 | 干什么 |
|---|---|---|
| `e2e_math_render.py` | 323 | 强制注入网络延迟、把题解 API 压到开场排版之后,确认数学真的排版成了、没残留 LaTeX 源码。**CI 单独一个 job**(`ci.yml:58`,需 Chrome) |

> 它只开**一个**详情页。`static/js/` 那 4603 行的其余部分没有任何运行时测试覆盖。

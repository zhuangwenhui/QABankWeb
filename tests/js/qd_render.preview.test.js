/**
 * 列表预览截断的**行为**测试。
 *
 * 为什么必须是行为测试:2026-07-28 线上 33 道题在题目管理页露出 LaTeX 源码,成因是
 * renderPreviewInto 按字符数硬切、切点落进了 $$…$$ 内部。这是纯逻辑错误 ——
 * pytest 那边只能做源码文本断言(函数名在不在、正则一不一致),挡不住"函数自己算错"。
 *
 * 跑法:node --test tests/js/
 */
const test = require('node:test');
const assert = require('node:assert');
const { loadBrowserScript } = require('./load');

const QD = loadBrowserScript('qd_render.js', 'QDRender');
const { clipOutsideMath, mathSpans } = QD;

/**
 * 独立的配对检查(不复用 mathSpans,否则是自己验自己):
 * 挖掉代码段与字面 \$ 之后,$$ 必须成双,剩下的单 $ 也必须成双。
 */
function delimitersBalanced(text) {
  const s = text
    .replace(/```[\s\S]*?```|`[^`\n]*`/g, ' ')
    .replace(/\\\$/g, '');
  const display = (s.match(/\$\$/g) || []).length;
  if (display % 2 !== 0) return false;
  const singles = (s.replace(/\$\$/g, '').match(/\$/g) || []).length;
  return singles % 2 === 0;
}

const LIMIT = 240;
const pad = (n, ch) => ch.repeat(n);

test('切点落在 display 公式内部时不得把它剖开', () => {
  // 公式起点很靠前(< limit*0.5),按规则应整块带上
  const text = '前言。\n$$' + pad(400, 'x') + '$$\n后面还有很多字' + pad(300, 'y');
  const out = clipOutsideMath(text, LIMIT);
  assert.ok(delimitersBalanced(out), '截断结果里定界符不成对:' + out.slice(-60));
  assert.ok(out.includes('$$' + pad(400, 'x') + '$$'), '整块公式应被完整带上');
});

test('公式前正文已经够长时,切在公式之前而不是带上整块', () => {
  const head = pad(200, 'あ');            // 200 > limit*0.5
  const text = head + '\n$$' + pad(400, 'x') + '$$ 尾巴';
  const out = clipOutsideMath(text, LIMIT);
  assert.ok(delimitersBalanced(out));
  assert.ok(!out.includes('$$'), '应切在公式之前,不该带进半截或整块公式');
  assert.ok(out.length >= LIMIT * 0.5, '也不该把预览切得太短');
});

test('公式过长(超出预算四倍)时宁可切在它前面', () => {
  const text = '短前言。\n$$' + pad(LIMIT * 5, 'x') + '$$ 尾巴';
  const out = clipOutsideMath(text, LIMIT);
  assert.ok(delimitersBalanced(out));
  assert.ok(!out.includes('$$'), '超长公式不应整块带上,否则截断省渲染量的初衷就没了');
});

test('切点落在行内公式内部时同样不得剖开', () => {
  const text = pad(230, 'a') + '$' + pad(60, 'b') + '$' + pad(200, 'c');
  const out = clipOutsideMath(text, LIMIT);
  assert.ok(delimitersBalanced(out), '行内公式被剖开了:' + out.slice(-40));
});

test('退到段落边界时不得退进公式里', () => {
  // 让 limit 落在公式后面的正文里,而其前最近的换行在公式内部
  const text = '引子。\n$$abc\n' + pad(150, 'd') + '\ndef$$\n' + pad(200, 'z');
  const out = clipOutsideMath(text, LIMIT);
  assert.ok(delimitersBalanced(out), '退到了公式内部的换行:' + JSON.stringify(out.slice(-50)));
});

// 注:下面比的是 spans.length 而不是 deepStrictEqual([], spans) —— 脚本跑在 vm 沙箱里,
// 它造出来的数组来自另一个 realm,原型不同,deepStrictEqual 会以"结构相同但引用不等"失败。
test('转义的 \\$ 是字面美元号,不能当定界符', () => {
  const text = '价格 \\$100 起。' + pad(400, 'w');
  const out = clipOutsideMath(text, LIMIT);
  assert.ok(delimitersBalanced(out));
  assert.strictEqual(mathSpans(text).length, 0, '\\$ 不该被认成公式');
});

test('代码段里的 $ 不是公式', () => {
  const text = '示例:`printf("$%d", x)` 说明。' + pad(400, 'q');
  assert.strictEqual(mathSpans(text).length, 0, '代码段里的 $ 被当成了公式定界符');
  assert.ok(delimitersBalanced(clipOutsideMath(text, LIMIT)));
});

test('切点落在代码段内部时也不得剖开', () => {
  // 切开代码段会留下半截反引号,里面的 $ 一旦失去代码段保护还可能被当成公式定界符
  const text = pad(220, 'あ') + '\n`' + pad(200, 'z') + ' $ ' + pad(200, 'z') + '`\n尾巴';
  const out = clipOutsideMath(text, LIMIT);
  const ticks = (out.match(/`/g) || []).length;
  assert.strictEqual(ticks % 2, 0, '留下了半截反引号:' + JSON.stringify(out.slice(-40)));
  assert.ok(delimitersBalanced(out));
});

test('display 内部的 $ 不应再被认成行内公式', () => {
  const text = '$$a $b$ c$$' + pad(400, 'k');
  const spans = mathSpans(text);
  assert.strictEqual(spans.length, 1, '应只识别出一个 display 区间,实际:' + JSON.stringify(spans));
  assert.strictEqual(text.slice(spans[0][0], spans[0][1]), '$$a $b$ c$$');
});

test('#348 的真实题面:截断后必须配对', () => {
  // 线上原文(节选到足够触发截断),\\ 在 JS 字面量里要写成 \\\\
  const text = [
    '第2問',
    '',
    '実数値関数 $u(t,x)$ に関する次の偏微分方程式の初期値・境界値問題を考える。',
    '$$\\begin{cases} \\dfrac{\\partial u}{\\partial t} = u - u^3 + ' +
      '\\dfrac{\\partial^2 u}{\\partial x^2} & (0<x<L,\\ t>0),\\\\[2mm] ' +
      '\\dfrac{\\partial u}{\\partial x}(t,0) = \\dfrac{\\partial u}{\\partial x}(t,L) = 0 ' +
      '& (t>0),\\\\[2mm] u(0,x)=f(x) & (0\\leq x\\leq L). \\end{cases} \\quad (\\mathrm{A})$$',
    'ただし、$L$ は正の実数とし、以下の設問に答えよ。',
  ].join('\n');
  assert.ok(delimitersBalanced(text), '样本本身应该是配对的,否则测的就不是截断');
  const out = clipOutsideMath(text, LIMIT);
  assert.ok(delimitersBalanced(out),
    '这正是线上露源码的那道题,截断后仍不配对:' + JSON.stringify(out.slice(-80)));
  // 修复前这里会切在 (t,L) 附近、把 cases 环境劈开;修复后要么整块在、要么整块不在
  const hasOpen = out.includes('\\begin{cases}');
  const hasClose = out.includes('\\end{cases}');
  assert.strictEqual(hasOpen, hasClose, 'cases 环境被截成了半截');
});

test('穷举组合下:输入配对 ⇒ 截断后仍配对', () => {
  // 固定序列而不是真随机:测试必须可复现,失败时能原样重跑。
  // 片段之间垫一个空格 —— 直接相邻会造出 `$x^2$` + `$$` = `$$$` 这种本身就有歧义的串,
  // 那属于坏输入,不是截断的锅。下面也会显式跳过输入本就不配对的组合。
  const pieces = ['正文', '$x^2$', '$$\\int_0^1 f(x)\\,dx$$', '\n', '`code $ here`',
                  '\\$50', '$$\\begin{cases} a & b \\end{cases}$$', 'あいうえお'];
  let checked = 0;
  let skipped = 0;
  for (let i = 0; i < pieces.length; i++) {
    for (let j = 0; j < pieces.length; j++) {
      for (let k = 0; k < pieces.length; k++) {
        // 重复段之间也要垫分隔符:直接 repeat 会让上一段结尾的 $ 贴上下一段开头的 $$,
        // 拼出 `$$$` 这种本身就有歧义的串 —— 那是坏输入,不是截断的锅。
        const chunk = [pieces[i], pieces[j], pieces[k]].join(' ');
        const text = new Array(12).fill(chunk).join('\n');
        if (text.length <= LIMIT) continue;
        if (!delimitersBalanced(text)) { skipped++; continue; }
        const out = clipOutsideMath(text, LIMIT);
        assert.ok(delimitersBalanced(out),
          `组合 (${i},${j},${k}) 截断后不配对:` + JSON.stringify(out.slice(-60)));
        checked++;
      }
    }
  }
  assert.ok(checked > 300, `实际只验了 ${checked} 组(跳过 ${skipped} 组坏输入),覆盖不足`);
});

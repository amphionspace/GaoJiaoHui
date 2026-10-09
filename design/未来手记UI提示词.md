# 未来手记 · Tab1「未来手记旅程」UI 提示词与构建规格

生成方式：内置 image_gen 工具。首图（01）新生成，02–04、05、08 基于首图编辑；06–07 基于 05 手记预览图编辑。所有图片均为非透明背景。
用途：为前端 `components/BoothJourney.vue`（8 屏状态机）提供视觉目标；每屏的「构建要点」即该屏的交互规格（状态名与代码一致）。

统一设计语言（每屏 prompt 开头均包含，原文沿用）：

> warm off-white paper background, deep charcoal Chinese typography, restrained dark teal accents for status and primary controls, delicate pencil illustrations inspired by a handwritten visitor journal. Generous negative space, strong editorial hierarchy, highly legible simplified Chinese sans serif; hand-drawn lines only for decorative accents. Large reachable touch buttons anchored in the lower quarter. Thin consistent top header reading “高交会 · 未来手记”, small outlined telephone handset mark. Bottom minimal 3-stage journey “讲述 — 修改 — 打印” with current stage marked in teal.

三段旅程状态对照（底部指示条，随屏推进）：

| 屏 | 状态名 | 讲述 | 修改 | 打印 |
|---|---|---|---|---|
| 01 | idle | 激活 | — | — |
| 02/03 | listening / pause | 激活 | — | — |
| 04 | summarizing | 完成 | 即将 | — |
| 05 | journal | ✓ | 激活 | — |
| 06 | editing | ✓ | 激活 | — |
| 07 | confirm | ✓ | ✓ | 激活 |
| 08 | printing→done | ✓ | ✓ | ✓ |

## 01-获得问题.png

**构建要点（idle）**：初始屏。三张问题卡为**竖排**（大序号 + 问题 + 一行小字提示），点任意卡 = 从该问开始连讲；主按钮「开始讲述（从第一问）」；静音切安抚屏的秒数默认 3s（页头可调，视觉上可收进设置角标）。文案逐字：听筒已接通 / 今天在高交会，有什么让你觉得"未来已经来了"？/ 想到什么，就从哪里说起 · 讲完一问，自动进入下一问 / 1 最惊喜的产品（小字：哪一件展品让你觉得未来已来）· 2 一个新想法（小字：技术照顾日常的新点子）· 3 今天的小故事（小字：今天遇到的有意思瞬间）/ 直接对着听筒说就好 · 说「我说完了」进入下一问 / 开始讲述（从第一问）。

```text
Use case: ui-mockup.
Asset type: high fidelity portrait touchscreen interface for a physical telephone booth at 高交会. One SINGLE full-bleed portrait 9:16 image, ideally 1080×1920, never a collage or multiple screens. The image itself is the entire screen: no phone bezel, no device mockup, no room, no people, no perspective.
Design a coherent, refined exhibition kiosk UI, warm off-white paper background, deep charcoal Chinese typography, restrained dark teal accents for status and primary controls, delicate pencil illustrations inspired by a handwritten visitor journal. Generous negative space, strong editorial hierarchy, highly legible simplified Chinese sans serif; hand-drawn lines only for decorative accents. Large reachable touch buttons anchored in the lower quarter. Thin consistent top header reading “高交会 · 未来手记”, small outlined telephone handset mark. Bottom minimal 3-stage journey “讲述 — 修改 — 打印” with current stage marked in teal. No countdown, microphone icon suggesting a smartphone, marketing claims, extra logos, or unrelated copy. Keep all specified Chinese text exact. Render as a polished finished touchscreen UI, not a wireframe.
Screen 01 of a coherent journey: handset has just been lifted; invite the visitor with one easy question.
Near upper middle a small outlined handset with a gentle speech ripple; small label “听筒已接通”.
Main headline very large and split into readable lines:
“今天在高交会，
有什么让你觉得
‘未来已经来了’？”
Below headline small supporting text “想到什么，就从哪里说起”.
Three spacious rounded prompt cards stacked vertically, each with a delicate pencil doodle and the exact label:
“最惊喜的产品”
“一个新想法”
“今天的小故事”
These are optional prompts; tapping any card also starts the session.
Bottom voice indicator with modest teal waveform and text “直接对着听筒说就好”.
In the lower quarter one large outlined teal primary button “开始讲述”, tapping it opens the listening screen.
The first journey stage “讲述” is active. Lots of breathing room. No numbered screen label inside UI.
```


## 02-自由讲述.png

**构建要点（listening）**：由 01 任意入口进入；屏幕顶部常驻**三问竖排清单**（三行：已讲完的行打勾 ✓ 且文字划线变淡、当前问行高亮并带「正在听」小标签、未开始的行弱化）；WS 实时转写全量覆盖上屏「实时记录」卡；「我说完了」按钮或语音说出结束语（转写尾部检测"我说完了"）即结束**本问**（非最后一问 -> 自动进 03b；最后一问 -> 进 04）；静音仅切 03，不结束；小字随问题数变化（非最后一问："说「我说完了」，或点击按钮进入下一问"；最后一问："…生成手记"）。文案逐字：正在聆听 · 第 1/3 问 / 我在听 / 想到什么，就慢慢说 / 实时记录 / 可以停顿，想好了再继续 / 我说完了 / 说「我说完了」，或点击按钮进入下一问。

```text
Use case: ui-mockup.
Asset type: high fidelity portrait touchscreen interface for a physical telephone booth at 高交会. One SINGLE full-bleed portrait 9:16 image, ideally 1080×1920, never a collage or multiple screens. The image itself is the entire screen: no phone bezel, no device mockup, no room, no people, no perspective.
Design a coherent, refined exhibition kiosk UI, warm off-white paper background, deep charcoal Chinese typography, restrained dark teal accents for status and primary controls, delicate pencil illustrations inspired by a handwritten visitor journal. Generous negative space, strong editorial hierarchy, highly legible simplified Chinese sans serif; hand-drawn lines only for decorative accents. Large reachable touch buttons anchored in the lower quarter. Thin consistent top header reading “高交会 · 未来手记”, small outlined telephone handset mark. Bottom minimal 3-stage journey “讲述 — 修改 — 打印” with current stage marked in teal. No countdown, microphone icon suggesting a smartphone, marketing claims, extra logos, or unrelated copy. Keep all specified Chinese text exact. Render as a polished finished touchscreen UI, not a wireframe. The sample content is fictional for this demonstration; small “体验示例” label in header for screens containing sample visitor content.
Input image: the reference is screen 01; use it as an EDIT TARGET and preserve its portrait dimensions, paper background, exact header visual, restrained charcoal/teal colors, pencil drawing language, generous safe margins and bottom three-stage journey placement. Change the center content to screen 02: actively listening to the visitor. Active stage remains “讲述”. Remove all prompt cards and the question, remove incidental handwritten promotional slogans.
Small status “正在聆听”; enormous main heading “我在听”; supporting sentence “想到什么，就慢慢说”.
Underneath an elegant large teal live waveform, mid-speech amplitude.
A spacious paper-like live transcript card with small label “实时记录” and clear exact sample text:
“今天看到一个机器人帮人拿东西，
动作比我想象中稳。
技术真的开始照顾日常的小事了。”
Add small “体验示例” in header.
A pencil doodle of a friendly utilitarian robot arm delicately picking up a plain cup on the lower edge of the card; avoid implying a real visitor identity.
Below card “可以停顿，想好了再继续”.
Near bottom one large outlined button “我说完了”.
Immediately below that button helper “说「我说完了」，或点击按钮结束”.
No countdown, no stop triggered by silence, no print control on this screen. Render precise Chinese typography and preserve the reference's exceptionally polished visual character.
```

## 03-暂时停顿.png

**构建要点（pause）**：listening 中静音达阈值（默认 3s）自动切入；同一条 WS 会话不断流；检测到声音立即回 02；「刚刚说到」卡展示转写最后一句。文案逐字：暂时停顿 · 仍在聆听 / 慢慢想，我还在 / 想好了，接着说就好 / 刚刚说到 / 不会因为安静而自动结束 / 我说完了 / 讲完后，再告诉我。

```text
Use case: ui-mockup.
Asset type: high fidelity portrait touchscreen interface for a physical telephone booth at 高交会. One SINGLE full-bleed portrait 9:16 image, ideally 1080×1920, never a collage or multiple screens. The image itself is the entire screen: no phone bezel, no device mockup, no room, no people, no perspective.
Design a coherent, refined exhibition kiosk UI, warm off-white paper background, deep charcoal Chinese typography, restrained dark teal accents for status and primary controls, delicate pencil illustrations inspired by a handwritten visitor journal. Generous negative space, strong editorial hierarchy, highly legible simplified Chinese sans serif; hand-drawn lines only for decorative accents. Large reachable touch buttons anchored in the lower quarter. Thin consistent top header reading “高交会 · 未来手记”, small outlined telephone handset mark. Bottom minimal 3-stage journey “讲述 — 修改 — 打印” with current stage marked in teal. No countdown, microphone icon suggesting a smartphone, marketing claims, extra logos, or unrelated copy. Keep all specified Chinese text exact. Render as a polished finished touchscreen UI, not a wireframe. The sample content is fictional for this demonstration; small “体验示例” label in header for screens containing sample visitor content.
Input image is an EDIT TARGET and visual master for the same series. Preserve portrait dimensions, exact header and bottom journey location, paper background and pencil visual design, charcoal and teal. Remove question and cards and stray promotional slogans. Active stage “讲述”.
Screen 03 shows a thinking pause, EXPLICITLY different from completing.
Small quiet status pill “暂时停顿 · 仍在聆听”.
Large two-line reassuring headline “慢慢想，
我还在”.
Smaller helper “想好了，接着说就好”.
Waveform now becomes a serene nearly flat line with three softly spaced teal dots, not a completion check.
Small “体验示例” at header.
Large airy transcript card labeled “刚刚说到”, text “技术真的开始照顾日常的小事了。”
Around the card only a tiny thoughtful pencil lightbulb and cup doodle, huge breathing room.
A very clear small reassurance “不会因为安静而自动结束”.
Near bottom the same outlined large button “我说完了” with helper “讲完后，再告诉我”.
No timer, no countdown, no spinner, no automatic advancing, no print button.
```

## 03b-下一问过渡.png

**构建要点（nextq）**：一问讲完（说「我说完了」）自动切入；顶部绿色小徽章「✓ 第 1/3 问 · 已讲完」；主标题「这一问，聊完了」；预告下一问（「接下来，我们聊聊」+ 大字「一个新想法」+ 小字提示）；「3 秒后自动开始」倒计时小字 + 主按钮「现在就开始」可跳过；到点自动开始下一问聆听（回 02）。文案逐字：✓ 第 1/3 问 · 已讲完 / 这一问，聊完了 / 接下来，我们聊聊 / 一个新想法 / 技术照顾日常的新点子 / 3 秒后自动开始 / 现在就开始。

```text
Use case: ui-mockup.
Asset type: high fidelity portrait touchscreen interface for a physical telephone booth at 高交会. One SINGLE full-bleed portrait 9:16 image, ideally 1080×1920, never a collage or multiple screens. The image itself is the entire screen: no phone bezel, no device mockup, no room, no people, no perspective.
Design a coherent, refined exhibition kiosk UI, warm off-white paper background, deep charcoal Chinese typography, restrained dark teal accents, delicate pencil journal illustration accents. Generous negative space, editorial hierarchy, legible simplified Chinese sans serif. Thin consistent top header “高交会 · 未来手记”, small outlined telephone handset mark. Bottom minimal 3-stage journey “讲述 — 修改 — 打印” with “讲述” still the active stage in teal.
This screen celebrates finishing one of three conversation questions, then transitions to the next.
Small outlined green pill badge “✓ 第 1/3 问 · 已讲完”.
Large two-line headline “这一问，聊完了”.
Smaller helper “接下来，我们聊聊”.
Below it the next question in larger teal weight “一个新想法”, tiny gray hint “技术照顾日常的新点子”.
A soft countdown line in teal “3 秒后自动开始” with three small teal progress dots.
Near bottom one large outlined button “现在就开始”.
No waveform, no transcript card, no print elements. Keep all specified Chinese text exact. Render as a polished finished touchscreen UI, not a wireframe.
```

## 04-完成讲述.png

**构建要点（summarizing）**：**第三问**讲完（结束语/按钮）触发；合并三问全文规则式整理（发现 = 每问各取一句，≤3 条），约 1.4s 后自动进 05（无返回）；演示文案逐字：讲述已完成 / 三问都聊完了，这段讲述，记下了 / “我说完了” / 正在整理你的手记 / 把你的发现和原话，认真留下 / 生成后，你可以继续修改。

```text
Use case: ui-mockup.
Asset type: high fidelity portrait touchscreen interface for a physical telephone booth at 高交会. One SINGLE full-bleed portrait 9:16 image, ideally 1080×1920, never a collage or multiple screens. The image itself is the entire screen: no phone bezel, no device mockup, no room, no people, no perspective.
Design a coherent, refined exhibition kiosk UI, warm off-white paper background, deep charcoal Chinese typography, restrained dark teal accents for status and primary controls, delicate pencil illustrations inspired by a handwritten visitor journal. Generous negative space, strong editorial hierarchy, highly legible simplified Chinese sans serif; hand-drawn lines only for decorative accents. Large reachable touch buttons anchored in the lower quarter. Thin consistent top header reading “高交会 · 未来手记”, small outlined telephone handset mark. Bottom minimal 3-stage journey “讲述 — 修改 — 打印” with current stage marked in teal. No countdown, microphone icon suggesting a smartphone, marketing claims, extra logos, or unrelated copy. Keep all specified Chinese text exact. Render as a polished finished touchscreen UI, not a wireframe.
Input image is an EDIT TARGET and visual master for the same series. Preserve portrait dimensions, exact header and bottom journey location, paper background and pencil visual design, charcoal and teal. Remove question and cards and stray promotional slogans.
Screen 04 is a soft moment of reflection and transitions into creating.
Upper small outlined teal pill badge “讲述已完成”.
Large two-line charcoal heading “这段讲述，
记下了”.
Small bubble shows “我说完了”.
Below shows a delicate pencil illustration of a friendly utilitarian robot arm writing a tiny paper journal by hand.
Status line “正在整理你的手记”.
Three evenly spaced small loading dots.
Supporting sentence “把你的发现和原话，认真留下”.
Smaller footer line “生成后，你可以继续修改”.
Footer “讲述 — 修改 — 打印”, active “讲述”.
No buttons on this screen; auto transitions forward after about 1.4 seconds. Warm, unhurried, inviting.
```

## 05-生成手记.png

**构建要点（journal）**：04 自动进入；手记卡字段=刊头/标题/发现×2（01/02 编号）/留下一句原话/关键词 chips；双路径主按钮「我想改一改」+ 次级「内容没问题」（直达 07）；示例标题与关键词与 02 示例转写对应。文案逐字：手记已生成 / 你的未来手记 / 我的高交会手记 / 未来，开始照顾日常 / 我的发现 / 留下一句原话 / 机器人、日常、未来 / 直接说，你想怎么改 / 比如：标题改得轻松一点 / 我想改一改 / 内容没问题。

```text
Use case: ui-mockup.
Asset type: high fidelity portrait touchscreen interface for a physical telephone booth at 高交会. One SINGLE full-bleed portrait 9:16 image, ideally 1080×1920, never a collage or multiple screens. The image itself is the entire screen: no phone bezel, no device mockup, no room, no people, no perspective.
Design a coherent, refined exhibition kiosk UI, warm off-white paper background, deep charcoal Chinese typography, restrained dark teal accents for status and primary controls, delicate pencil illustrations inspired by a handwritten visitor journal. Generous negative space, strong editorial hierarchy, highly legible simplified Chinese sans serif; hand-drawn lines only for decorative accents. Large reachable touch buttons anchored in the lower quarter. Thin consistent top header reading “高交会 · 未来手记”, small outlined telephone handset mark. Bottom minimal 3-stage journey “讲述 — 修改 — 打印” with current stage marked in teal. No countdown, microphone icon suggesting a smartphone, marketing claims, extra logos, or unrelated copy. Keep all specified Chinese text exact. Render as a polished finished touchscreen UI, not a wireframe. The sample content is fictional for this demonstration; small “体验示例” label in header for screens containing sample visitor content.
Input image is an EDIT TARGET and visual master for the same series. Preserve portrait dimensions, exact header and bottom journey location, paper background and pencil visual design, charcoal and teal. Active stage now “修改”.
Screen 05 presents the completed handwritten journal card.
Small outlined teal pill badge “手记已生成”.
Below it slightly bigger charcoal heading “你的未来手记”.
Small “体验示例” at header.
Large centered paper journal card with subtle soft shadow and faint grain, masthead “我的高交会手记” in tiny letters, elegant bold title “未来，开始照顾日常”, two findings numbered:
“01  今天看到一个机器人帮人拿东西，动作比我想象中稳。
02  技术真的开始照顾日常的小事了。”
Label “留下一句原话” and italic charcoal quote “原来未来可以这么日常”.
At bottom of card a row of three small keyword chips “机器人”“日常”“未来”.
No print button on this screen yet.
Under the card hint “直接说，你想怎么改”.
A dashed pill “比如：标题改得轻松一点”.
Below it a large outlined primary button “我想改一改” and a secondary quiet text-level button “内容没问题”.
Footer “讲述 — 修改 — 打印”, “修改” active.
No QR code, no watermark, no watermark-like marks, no visible scanning elements, no extra stationery props.
```

## 06-语音修改.png

**构建要点（editing）**：05 点「我想改一改」进入（07「返回修改」也回此屏）；新一轮短聆听，停顿 2s 自动应用指令；变更高亮=标题行「标题已修改」标签 + 新增句块「新增」标签；顶部状态显示本次已应用数（示例"已更新 2 处"）；「修改完成，去确认」主按钮、「重新说修改」次级；可循环多轮修改；另有文本输入兜底（无麦克风演示用，设计稿可不放）。文案逐字：已更新 2 处 / 按你说的，改好了 / 你想怎么改：标题改得轻松一点，加一句我想明年再来。/ 我的发现 / 留下一句原话 / 机器人、日常、未来 / 还想调整，可以继续说 / 修改完成，去确认 / 重新说修改。

```text
Use case: ui-mockup.
Asset type: high fidelity portrait touchscreen interface for a physical telephone booth at 高交会. One SINGLE full-bleed portrait 9:16 image, ideally 1080×1920, never a collage or multiple screens. The image itself is the entire screen: no phone bezel, no device mockup, no room, no people, no perspective.
Design a coherent, refined exhibition kiosk UI, warm off-white paper background, deep charcoal Chinese typography, restrained dark teal accents for status and primary controls, delicate pencil illustrations inspired by a handwritten visitor journal. Generous negative space, strong editorial hierarchy, highly legible simplified Chinese sans serif; hand-drawn lines only for decorative accents. Large reachable touch buttons anchored in the lower quarter. Thin consistent top header reading “高交会 · 未来手记”, small outlined telephone handset mark. Bottom minimal 3-stage journey “讲述 — 修改 — 打印” with current stage marked in teal. No countdown, microphone icon suggesting a smartphone, marketing claims, extra logos, or unrelated copy. Keep all specified Chinese text exact. Render as a polished finished touchscreen UI, not a wireframe. The sample content is fictional for this demonstration; small “体验示例” label in header for screens containing sample visitor content.
Use the reference as an EDIT TARGET; keep this artwork consistent with the screen 05 visual: same header, same margins, same warm off-white background, same charcoal and restrained dark teal language, same pencil journal aesthetic. Small “体验示例” at header. Active stage “修改”.
Screen 06 shows the journal card IMMEDIATELY AFTER a spoken edit request was applied.
Small outlined teal pill badge “已更新 2 处”.
Slightly bigger charcoal heading “按你说的，改好了”.
Below heading a small rounded voice-command bubble with subtle teal tint, prefix “你想怎么改：” and command text “标题改得轻松一点，加一句我想明年再来。”.
The same paper journal card as screen 05, masthead “我的高交会手记”, title now updated to the relaxed “嘿，日常有点酷” with a small teal corner tag “标题已修改”.
Two findings unchanged:
“01  今天看到一个机器人帮人拿东西，动作比我想象中稳。
02  技术真的开始照顾日常的小事了。”
After the findings a newly added line rendered as if freshly handwritten, subtle teal highlight behind it:
“我想明年再来。”
with a small teal corner tag “新增”.
Italic quote “原来未来可以这么日常” under label “留下一句原话”.
Keyword chips “机器人”“日常”“未来”.
Hint “还想调整，可以继续说”.
Near bottom one large outlined primary button “修改完成，去确认”; below it a secondary quiet text-level button “重新说修改”.
No print button yet. No keyboard input field.
```

## 07-确认打印.png

**构建要点（confirm）**：06「修改完成，去确认」或 05「内容没问题」进入；终版手记卡**无任何编辑标记**（干净版）；实心深青全宽主按钮「确认并打印」+ 次级「返回修改」回 06；打印动作仅由本屏按钮触发。文案逐字：手记已就绪 / 最后看一眼 / 确认后，才会打印 / 嘿，日常有点酷 / 我的发现 / 留下一句原话 / 我想明年再来。/ 机器人、日常、未来 / 确认并打印 / 返回修改。

```text
Use case: ui-mockup.
Asset type: high fidelity portrait touchscreen interface for a physical telephone booth at 高交会. One SINGLE full-bleed portrait 9:16 image, ideally 1080×1920, never a collage or multiple screens. The image itself is the entire screen: no phone bezel, no device mockup, no room, no people, no perspective.
Design a coherent, refined exhibition kiosk UI, warm off-white paper background, deep charcoal Chinese typography, restrained dark teal accents for status and primary controls, delicate pencil illustrations inspired by a handwritten visitor journal. Generous negative space, strong editorial hierarchy, highly legible simplified Chinese sans serif; hand-drawn lines only for decorative accents. Large reachable touch buttons anchored in the lower quarter. Thin consistent top header reading “高交会 · 未来手记”, small outlined telephone handset mark. Bottom minimal 3-stage journey “讲述 — 修改 — 打印” with current stage marked in teal. No countdown, microphone icon suggesting a smartphone, marketing claims, extra logos, or unrelated copy. Keep all specified Chinese text exact. Render as a polished finished touchscreen UI, not a wireframe. The sample content is fictional for this demonstration; small “体验示例” label in header for screens containing sample visitor content.
Use the reference as an EDIT TARGET; keep this artwork consistent with the screen 05 visual: same header, same margins, same warm off-white background, same charcoal and restrained dark teal language, same pencil journal aesthetic. Small “体验示例” at header.
Screen 07 is the FINAL PRE-PRINT check.
Small outlined teal pill badge “手记已就绪”.
Slightly bigger charcoal heading “最后看一眼”.
Small supporting sentence “确认后，才会打印”.
The same paper journal card, CLEAN VERSION WITHOUT ANY EDIT MARKERS OR HIGHLIGHT TAGS: masthead “我的高交会手记”, bold title “嘿，日常有点酷”, findings:
“01  今天看到一个机器人帮人拿东西，动作比我想象中稳。
02  技术真的开始照顾日常的小事了。”
italic quote “原来未来可以这么日常” under label “留下一句原话”, handwritten line “我想明年再来。”, keyword chips “机器人”“日常”“未来”.
Below the card ONE full-width SOLID dark teal primary button “确认并打印” (the only solid filled button in the whole journey).
Under it a secondary quiet text-level button “返回修改”.
Footer “讲述 — 修改 — 打印”, “打印” active.
The print never starts by voice alone; only tapping this solid button prints. No extra marks.
```

## 08-取走手记.png

**构建要点（printing→done）**：07 按钮触发；printing 约 1.2s 模拟打印（提示"正在打印，请稍候"）后自动转 done；done 屏无退回、无确认（**三问已在讲述阶段连讲完毕、手记只打印这一份，打印即旅程终点**），显示「三个问题都聊完了，谢谢你」。真实亭子挂机即重置回 01，演示版额外提供小字「重新开始」链接（设计稿可不画）。文案逐字：打印完成 / 把今天的未来，带回家 / 正在打印，请稍候 / 请从下方取走手记 / 取走后，请挂好听筒 / 三个问题都聊完了，谢谢你。

```text
Use case: ui-mockup.
Asset type: high fidelity portrait touchscreen interface for a physical telephone booth at 高交会. One SINGLE full-bleed portrait 9:16 image, ideally 1080×1920, never a collage or multiple screens. The image itself is the entire screen: no phone bezel, no device mockup, no room, no people, no perspective.
Design a coherent, refined exhibition kiosk UI, warm off-white paper background, deep charcoal Chinese typography, restrained dark teal accents for status and primary controls, delicate pencil illustrations inspired by a handwritten visitor journal. Generous negative space, strong editorial hierarchy, highly legible simplified Chinese sans serif; hand-drawn lines only for decorative accents. Large reachable touch buttons anchored in the lower quarter. Thin consistent top header reading “高交会 · 未来手记”, small outlined telephone handset mark. Bottom minimal 3-stage journey “讲述 — 修改 — 打印” with current stage marked in teal. No countdown, microphone icon suggesting a smartphone, marketing claims, extra logos, or unrelated copy. Keep all specified Chinese text exact. Render as a polished finished touchscreen UI, not a wireframe. The sample content is fictional for this demonstration; small “体验示例” label in header for screens containing sample visitor content.
Use the reference as an EDIT TARGET; keep this artwork consistent with the screen 05 visual: same header, same margins, same warm off-white background, same charcoal and restrained dark teal language, same pencil journal aesthetic. Small “体验示例” at header.
Screen 08 is the gentle take-away finale.
Small outlined teal pill badge “打印完成”.
Large two-line charcoal heading “把今天的未来，
带回家”.
Under the heading a subtle printer slot illustration, warm off-white paper card emerging from it, with small “体验示例” at header. The card shows in small neat handwriting:
masthead “我的高交会手记”, title “嘿，日常有点酷”, four lines:
“未来，也会搭把手。
原来未来可以这么日常。
我想明年再来。”
“机器人  日常  未来”
A small downward teal arrow and the line “请从下方取走手记”.
Below a small outlined handset icon and the farewell “取走后，请挂好听筒”.
No confirmation buttons, no back button, no countdown, no unrelated props. Footer “讲述 — 修改 — 打印”, now all three stages completed.
Calm and warm, ending with breathing room.
```

---

## 与当前实现（BoothJourney.vue）的差异备忘

设计稿以上述 8 屏为准；以下为**演示版实现**的补充细节，真实亭子 UI 可裁剪：

| 项 | 实现行为 | 设计稿处理 |
|---|---|---|
| 三问连讲（讲完即切） | 一问说\"我说完了\"即存本问全文，自动进过渡屏（✓ 第 X/3 问 · 已讲完 + 下一问预告 + 3 秒倒计时），到点自动开始下一问聆听；可点\"现在就开始\"跳过 | 新增 03b 过渡屏；02 顶部画三问竖排清单（已讲完 ✓ 划线 / 当前问高亮\"正在听\"）；01 三问卡片改竖排（序号 + 问题 + 小字提示） |
| 一份手记 | 第三问讲完合并三问全文生成一份手记：发现 = 每问各取一句（≤3 条），原话/关键词/标题取全文；修改→打印只走一次，打印即终点（不再有 08 倒计时跳问） | 05 手记\"我的发现\"支持 3 条；08 结束文案\"三个问题都聊完了，谢谢你\" |
| 06 文本兜底输入框 | 无麦克风时输入指令（如"加一句明年再来"）直接应用 | 不画；仅浏览器演示用 |
| 08「重新开始」按钮 | done 屏提供小字按钮一键回 01 | 不画；真实亭子=挂机自动重置 |
| 01 停顿秒数调节 | 页头小数字输入（默认 3s） | 不画；收进运维设置 |
| 02 实时转写 | 真实 WS 全量文本覆盖上屏 | 图中用"体验示例"固定文本示意 |
| 05→07 直达 | 「内容没问题」跳过修改直达确认 | 已含在 05（次级文字按钮） |
| 手记生成方式 | 本地规则式（无 LLM），标题/发现/原话/关键词由 journal.js 产出 | 图中示例即规则产出结果 |

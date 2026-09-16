# Trace 分析在 Codex 与 Pi 中的实现流程

## 1. 目标

这套流程用于分析 Chrome Trace Event、Ascend/CANN profiler trace、PyPTO serving
泳道，以及两组 GroupNorm profiler 结果。核心原则是：

- JSON 是精确测量来源，用于计算时长、比例、计数、分位数和重叠时间。
- Chrome Tracing 截图用于复核泳道顺序、空洞、同步点和横向重叠关系。
- 不从图片像素估算精确时长或事件数量。
- 输入 trace 保持只读；摘要、聚焦 trace 和截图写入独立输出目录。

## 2. 共用分析链路

```text
原始 trace（只读）
        |
        v
计算 SHA-256 + 解析 JSON 事件
        |
        +--> 通用统计：进程、事件、inclusive duration、median/max
        +--> A3/CANN：step、compute、communication、free、collective
        +--> PyPTO：多 device decode-step 的起止偏斜
        +--> GroupNorm：官方结果、硬件 kernel、launch、sync、gap 分开统计
        |
        v
生成 structured summary + focused trace
        |
        v
从结构化数据提出待验证假设
        |
        v
Chrome 加载 focused trace 并截图
        |
        v
模型读取 PNG，检查泳道几何关系
        |
        v
结构化结论与视觉观察交叉核对
        |
        v
final summary（含证据、限制和 visual_confirmation）
```

推荐的分析顺序不是单纯的“先 JSON、后看图”，而是一个校验环：

1. JSON 初筛并定位慢 step、长 kernel 或异常 device。
2. 截取该范围，避免让整张超宽泳道图稀释关键信息。
3. 通过截图确认事件是否真的相邻、重叠、串行或存在空洞。
4. 回到 JSON 对截图中发现的位置做精确计算。

## 3. 共用脚本

当前原型位于：

```text
~/.pi/agent/skills/trace-analysis/
├── SKILL.md
├── package.json
└── scripts/
    ├── trace_summary.py
    ├── compare_groupnorm.py
    └── capture_chrome_trace.mjs
```

依赖为 Python 3.9+、Node.js、Google Chrome/Chromium 和 `playwright-core`。

### 3.1 通用、A3 和 PyPTO trace

```bash
TRACE_SKILL_DIR="$HOME/.pi/agent/skills/trace-analysis"

python3 "$TRACE_SKILL_DIR/scripts/trace_summary.py" input/trace.json \
  --output output/summary-raw.json \
  --subset output/focus.json

node "$TRACE_SKILL_DIR/scripts/capture_chrome_trace.mjs" \
  output/focus.json output/chrome-tracing.png
```

`trace_summary.py` 接受根数组或 `{ "traceEvents": [...] }`。检测到
`ProfilerStep#N` 时，会找出最慢 step，并保留与计算、通信、等待和同步有关的事件，
形成 `focus.json`。检测到 PyPTO 的 `device`、`decode_step` 和对应事件签名时，会增加
多 device 起止偏斜统计。

### 3.2 GroupNorm 对比

```bash
python3 "$TRACE_SKILL_DIR/scripts/compare_groupnorm.py" INPUT_ROOT \
  --left group_norm \
  --right group_norm_goal_plus \
  --summary output/groupnorm-summary.json \
  --trace output/groupnorm-aligned.json

node "$TRACE_SKILL_DIR/scripts/capture_chrome_trace.mjs" \
  output/groupnorm-aligned.json output/groupnorm-chrome-tracing.png
```

对比脚本按 case 读取官方 evaluator 报告、`trace_view.json` 和
`kernel_details.csv`，以硬件 `AI_VECTOR_CORE` kernel 的中位数作为主要对比依据。
生成的 aligned trace 是便于横向观察的合成视图，不是原始硬件 capture，报告中必须标注。

### 3.3 Chrome 截图实现

`capture_chrome_trace.mjs` 执行以下动作：

1. 创建一次性 Chrome profile，并以 1600 x 1000 headless viewport 启动 Chrome。
2. 启用 Chrome internal debugging pages。
3. 打开 `chrome://tracing/`，通过文件选择器加载 trace。
4. 等待泳道完成渲染，必要时点击指定坐标，再保存 PNG。
5. 关闭 Chrome 并删除一次性 profile。

它只负责渲染和截图，不负责解释图片。

## 4. Codex 实现

Codex 版本是工具编排模式：Codex 先运行上述 Python/Node 脚本，再调用 Codex 的
`view_image` 读取本地 PNG，最后把视觉观察与结构化摘要合并。

```text
Codex
  |-- shell/Python --> summary-raw.json + focus.json
  |-- Chrome script --> chrome-tracing.png
  |-- view_image ----> 视觉观察
  `-- 综合判断 ------> summary.json 或文字报告
```

Codex 的视觉检查提示应限制为：

```text
检查截图中的泳道顺序、事件先后、明显空洞、同步位置和横向重叠关系。
不要从像素估算精确时长、比例或事件数量；这些值必须引用 JSON 摘要。
指出截图是否支持结构化假设，以及是否存在矛盾或无法辨认的区域。
```

如果截图与 JSON 冲突，不能直接覆盖结构化结果。应先检查 focused trace 的筛选范围、
时间单位、嵌套事件和 inclusive duration 是否被误当成独占墙钟时间。

## 5. Pi 实现

Pi 版本把相同规则包装成 `trace-performance-analysis` skill。Pi 加载 skill 后，可以在
一次模型会话内自主执行解析、截图、图片读取和最终报告生成：

```text
Pi 主会话
  |-- 读取 SKILL.md
  |-- 调用 trace_summary.py
  |-- 读取 summary-raw.json 并提出假设
  |-- 调用 capture_chrome_trace.mjs
  |-- Pi read(chrome-tracing.png)
  `-- 写入 final summary
```

调用示例：

```bash
PI_CODING_AGENT_DIR=/path/to/pi-agent \
pi --offline \
  --provider PROVIDER \
  --model IMAGE_CAPABLE_MODEL \
  --thinking high \
  --skill "$HOME/.pi/agent/skills/trace-analysis/SKILL.md" \
  --print "分析 input/trace.json。先生成结构化摘要和聚焦 trace，再生成 Chrome \
Tracing 截图并使用 read 读取 PNG；最后把精确 JSON 证据和视觉确认分别写入 \
output/summary.json。不要修改输入文件。"
```

Pi 当前模型必须声明并实际支持 image input。模型不支持图片时，skill 要求跳过图片解释，
只返回结构化分析，不能声称完成了视觉确认。

## 6. Codex 与 Pi 的关系

| 项目 | Codex | Pi |
| --- | --- | --- |
| 分析算法 | 共用 Python 脚本 | 共用 Python 脚本 |
| Chrome 渲染 | 共用 Node/Playwright 脚本 | 共用 Node/Playwright 脚本 |
| 图片读取 | Codex `view_image` | Pi `read` |
| 流程约束 | 当前对话中的编排指令 | `SKILL.md` |
| 精确数值来源 | JSON | JSON |
| 视觉证据作用 | 复核几何关系 | 复核几何关系 |
| 模型无图片能力 | 报告无法视觉确认 | 跳过图片并明确降级 |

两者的分析语义是一致的，差别主要在宿主工具接口和流程的装载方式。脚本没有绑定
Codex runtime，因此可以继续由 Pi、Codex 或其他能够执行命令并读取图片的 harness 使用。

## 7. 已完成的 Pi + GPT 合成 trace 验证

验证环境：`jenkins@8.92.9.77`，工作目录：

```text
/data/l00939996/pi-trace-pi-smoke/
```

使用 `bench-openai/gpt-5.6-luna`、`thinking=high`，实际完成了：

```text
input/synthetic-trace.json
  -> output/gpt-summary-raw.json
  -> output/gpt-focus.json
  -> output/gpt-chrome-tracing.png
  -> Pi read(PNG)
  -> output/gpt-summary.json
```

结构化结论为：`ProfilerStep#2` 从 10 ms 增至 20 ms，其中 70% 的增量来自未重叠
通信；allReduce 从 1 ms 增至 8 ms，计算和通信重叠为 0。

截图复核实际确认了：

- `Computing -> Communication(Not Overlapped) -> Free` 的泳道顺序。
- 慢 allReduce 与未重叠通信区间横向对齐。
- allReduce 与 Computing 没有横向重叠。

这次截图没有发现 JSON 之外的新问题，因为合成 trace 很小且事件关系是刻意构造的；
它的作用是证明 Pi 的图片读取链路确实执行，并完成结构化结果的跨模态交叉复核；
这不是一个独立评测器。

输入 SHA-256 在执行前后均为：

```text
031092b59495d008d85d07d13d6225cc37c5a9096f1a41a80bfabb2bb95301b6
```

## 8. 输出与验收契约

建议每次分析至少保留：

```text
output/
├── summary-raw.json       # 脚本产生的精确结构化统计
├── focus.json             # 用于视觉复核的聚焦 trace
├── chrome-tracing.png     # Chrome 实际渲染结果
└── summary.json            # 模型综合后的最终报告
```

最终报告至少说明：

- 原始 trace 路径、哈希、范围和时间单位。
- 比较基准以及精确时长、比例、计数的 JSON 证据。
- `visual_confirmation.status`：`confirmed`、`contradicted`、`inconclusive` 或
  `not_run`。
- 截图观察与结构化结论分开记录。
- inclusive totals、单样本、合成视图或缺少重复实验等不确定性。

验收时检查：

1. 输入哈希未改变。
2. 摘要和 PNG 均存在，PNG 能识别为有效图片。
3. 模型调用记录能证明实际读取了 PNG，不能只凭最终文字自报。
4. 报告中的精确数字能回溯到 JSON 字段，而不是图片估算。
5. 截图与结构化结论冲突时，状态不是 `confirmed`。

## 9. 安全边界

- API key 只通过环境变量注入目标子进程，不写入 prompt、配置产物或命令行参数。
- 不在日志中打印环境变量，也不把包含凭据的进程环境复制到输出目录。
- 分析真实 trace 前先确认其中是否包含路径、用户输入或业务数据；对外发送时只发送获准的
  trace 或脱敏后的 focused trace。
- Chrome profile 必须是一次性的；分析完成后删除，输入和正式产物不随 profile 清理。

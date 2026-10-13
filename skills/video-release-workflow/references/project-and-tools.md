# 项目与工具

## 唯一项目与断点

项目放用户工作区，使用固定 work_id；再开会话先读它，不凭日期或相似标题新建另一条。建议结构：

```text
video-project/
  VIDEO_PROJECT.json
  PROGRESS.md
  script/                  原稿、确认稿、拍摄大纲
  edit/                    转写、语义清单、切点、字幕、音效计划
  assets/                  本条原帧、授权素材、封面图层
  render/                  版本化成片、可编辑工程
  release/                 本条发布包
```

没有素材的目录不必提前创建。原素材可只读引用外部路径；源时间→输出时间映射、实际媒体哈希和当前版本指针必须可追溯。原始路径等个人信息只留私有项目，不作为公共示例。

`VIDEO_PROJECT.json` 保存当前阶段、当前文件、用户确认与平台状态；`PROGRESS.md` 简写确认事项、完成的验证、缺口、下一步。修改前重读；不覆盖并行工作的内容。

当前阶段可为 draft / awaiting_filming / editing / awaiting_style_confirmation / package_ready / upload_prepared / submitted / published / blocked。某个平台审核中与另一平台已发布可以并存，不能用单一全局 published 掩盖差异。

## 随包脚本

脚本只要求 Python 3 标准库；媒体功能另外需要本机 FFmpeg、FFprobe。先实际探测版本和功能，不自动安装软件。可以用工具发现的绝对可执行路径，不把作者机器路径写进项目模板。

设 `$skillDir` 为实际 Skill 安装目录，`$projectDir` 为本条新项目目录。这两个名字不覆盖系统环境变量。

```powershell
python "$skillDir/scripts/bundle.py" init --project "$projectDir" --name "本条主题"
python "$skillDir/scripts/media.py" probe "原片路径.mp4"
python "$skillDir/scripts/media.py" frame "原片路径.mp4" --at 2.5 --output "原帧.png"
python "$skillDir/scripts/media.py" cut "原片路径.mp4" --plan "edit-plan.json" --output "精剪_v1.mp4"
python "$skillDir/scripts/media.py" captions "精剪_v1.mp4" --cues "captions.json" --output "字幕_v1.mp4" --font-name "本机已确认字体"
python "$skillDir/scripts/media.py" mix "字幕_v1.mp4" --plan "sfx-plan.json" --output "混音_v1.mp4"
python "$skillDir/scripts/bundle.py" pack --spec "release-spec.json" --output "release-v1"
python "$skillDir/scripts/bundle.py" check "release-v1"
```

每个命令有 `--help`。媒体命令可用 `--ffmpeg`、`--ffprobe` 指定工具；参数位于子命令之前。生成文件拒绝覆盖旧版本。脚本执行结束还须看真实文件/媒体，不把退出码当人工验收。

`bundle.py pack` 会复制已选成片和封面并核对哈希，写相对路径清单与标题话题，不执行网页上传、最终发布、用户确认或预测。大文件占用应提前评估；已存在的包用现有清单继续，不重复打包。

## 能力与降级

| 能力 | 必要条件 | 不具备时 |
| --- | --- | --- |
| 写稿、计划、标题话题 | 当前 Codex 与真实输入 | 补会改变内容的最小材料 |
| 媒体探测、裁切、字幕、混音、基础封面 | Python 3、FFmpeg/FFprobe；字幕/封面需可用字体及相关滤镜 | 交决策清单，标明未渲染；不声称成片完成 |
| 转写与对齐 | 用户字幕/转写，或已可用且获准的 ASR | 听/看可访问原片；无法核准关键字时询问；不能拿拍前稿充当逐字转写 |
| 复杂动效、画中画、图解 | 可编辑渲染环境，如已可用 Remotion/Node | 先样式静帧；需安装时说明依赖与成本后取得授权 |
| 精确人像分割 | 可用分割工具或用户蒙版 | 保留完整原帧做构图，不用失真抠像冒充完成 |
| 网页上传与提交 | 可用浏览器控制/连接器、本人登录与作品授权 | 交完整本地发布包和手动清单；上传状态保持未开始 |
| 指标与复盘/自动化 | 用户实绩或授权数据工具；自动化需真实产品接口 | 缺失数据记未知；没有调度工具不宣称自动唤醒 |

浏览器接口随 Codex 安装变化，优先发现当前工具并读其 Skill/说明，不附旧版本私有桥接代码。若有对应视频/内容 Skill，实际读取后按适用范围调用；本包不强制购买课程、配置 CTS、ASR 云服务或 API Key。

发布后复盘不混用账号、平台或作品；如有正式发布前预测，保留不可变原版，记录执行偏差。计划 T+3/T+7 只是观察约定，非官方推流规律或已启用后台任务。

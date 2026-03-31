# 项目：冒险岛 v079 经典版 完整单机复刻

## 技术栈
- **引擎**: Godot 4.x（C#）| **渲染**: Godot 2D | **类型**: 纯单机
- **平台**: Windows（主力）> Web（HTML5）> 移动端（后期）
- 跨平台：输入抽象化、UI自适应、路径兼容、Web异步加载、WebGL兼容

## 资源来源与使用原则

### ⚠ 资源自包含原则（最高优先级）
**本项目必须完全自包含，禁止依赖项目外部的任何文件路径。**
- WZ 文件位于项目内 `Resources/WZ/`（~4.3GB，gitignore）
- 提取资源缓存到 `Resources/Extracted/`（Sprites/Animations/Audio/Data）
- 服务端参考数据在 `Resources/ServerRef/`
- 代码中禁止硬编码外部路径，所有路径用 `res://Resources/` 相对路径
- 项目克隆 + WZ 文件即可运行

### ⚠ 视觉资源严格要求
**所有视觉资源必须从原版 WZ 文件精确提取并正确对应。**
- 资源ID映射必须严格正确（怪物ID→Mob.wz对应img）
- 动画帧序列、帧延迟、原点偏移必须从 WZ 精确读取
- **严禁 Image.CreateEmpty()、StyleBoxFlat、ColorRect 等占位图代替真实 WZ 资源**

### WZ 资源加载 API（已实现，直接使用）
```csharp
// 纹理
var texture = WzTextureLoader.Instance.LoadTexture("UI.wz/UIWindow.img/Item/backgrnd");
// 动画
var frames = WzAnimationLoader.Instance.LoadAnimation("Mob.wz/100100.img/move");
// 音频
var bgm = WzSoundLoader.Instance.LoadSound("Sound.wz/BgmGL.img/Ellinia");
// 属性数据
var prop = WzManager.Instance.GetProperty("String.wz/Map.img/victoria/100000000");
var name = WzPropertyHelper.GetString(prop, "mapName", "");
```
如不确定 WZ 路径，用 `WzManager.Instance.GetWzDirectory("xxx.wz")` 浏览目录。

### 参考实现
`D:\workspace\MapleStory-Client` (HeavenClient) 是一个完整的 C++ MapleStory 客户端实现，可参考其渲染逻辑和 WZ 路径规则。详细参考信息已提取到 knowledge 文件中。

### 服务端数据（仅作功能逻辑参考）
`Resources/ServerRef/` 下的服务端脚本（NPC/任务/传送门/活动）仅供参考，应根据 Godot+C# 架构重新设计实现。

## 项目目标
1:1 复刻冒险岛 v079 版本的完整单机游戏体验。Big Bang 前经典版本，含5大职业（战士/法师/弓箭手/飞侠/海盗）完整4次转职、骑士团、战神等职业线。

### ⚠ 版本限制（严格遵守）
**本项目严格限定为 v079 版本，禁止引入任何 v079 之后版本的功能、系统或资源。**
- 所有功能和数据必须在 v079 WZ 文件中存在。如果 WZ 文件中找不到对应资源，说明该功能不属于 v079，不应该实现
- **禁止实现的高版本功能示例**：潜能系统（Potential）、星之力强化（Star Force）、超级技能（Hyper Skills）、第五次转职、联盟系统、内在能力（Inner Ability）、精灵吊坠、怪物生命值显示百分比、Boss匹配系统
- v079 存在的系统：5大职业4转、骑士团（1-3转）、战神（1-3转）、基础卷轴强化（10%/30%/60%/100%）、混沌卷轴、白卷轴
- 判断标准：如果 `D:\workspace\MapleStory-Client` (HeavenClient, v83) 没有实现某功能，v079 大概率也没有
- 资源路径必须在 Resources/WZ/ 的 v079 WZ 文件中真实存在，不允许猜测或编造 WZ 路径

---

## ⚠ 实现原则：循序渐进，始终可运行

**最重要的原则：每完成一个任务后，项目必须仍然可以编译、运行、不崩溃。**

**占位图清除优先级**：代码中 `Image.CreateEmpty()`、`StyleBoxFlat`、`ColorRect` 等占位实现必须尽快替换为真实 WZ 资源。发现占位图代码时，应优先生成替换任务。

### 实现阶段划分

**第一阶段 — 核心骨架（最高优先级）**
1. WZ 资源管线 2. 核心引擎骨架 3. 地图系统 4. 角色系统 5. UI/HUD 基础

**第二阶段 — 战斗循环（高优先级）**
6. 怪物系统 7. 战斗系统 8. 物品系统 9. 装备系统 10. 技能系统 11. 职业系统

**第三阶段 — 内容扩展（中优先级）**
12. 经济系统 13. 音效系统 14. 特效系统 15. 内容填充 16. 职业扩展 17. 游戏设置

**第四阶段 — 暂不实现（低优先级）**
NPC系统、任务系统、宠物、骑宠、Boss战、迷你游戏、交通系统

---

详细功能规格见 `.autoforge/knowledge/L2_features/` 目录下各系统知识文件。

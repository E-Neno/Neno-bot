# Phase 1 — 多房间 + 房间切换 · Codex 详规

> 在 Phase 0 的能跑骨架 `app/static/world-engine.html` 上增量。**只改这一个文件**
> （需要时可从 worldViewAdapter.js import 现成导出，不改 worldViewAdapter）。
> 目标：现在引擎只渲染写死的 living_room；让它支持**全部 9 个房间 + 切换**。

## 背景
- Phaser 引擎已跑通（5 层 depth 分带、renderRoom 状态纯函数、物理演示件）。
- `this.roomKey` 现在写死 `"living_room"`，`preload` 只加载 living 背景。
- 设计决定：**单房间显示**（不是横向 strip）——显示她当前所在房间，换房间时淡入淡出切换。
  不同房间是不同背景图，无法无缝平移，所以用「切换」而非「平移」。

## 要做的

### 1) 预加载全部 9 个房间背景（preload）
房间 key → 图片路径（**注意 living_room 的图名是 room-living 不是 room-living_room**）：
```
bedroom            -> /static/img/world/room-bedroom-v1.png
kitchen            -> /static/img/world/room-kitchen-v1.png
living_room        -> /static/img/world/room-living-v1.png
balcony            -> /static/img/world/room-balcony-v1.png
entryway           -> /static/img/world/scene-entryway-v1.svg
building_entrance  -> /static/img/world/scene-building-entrance-v1.svg
cafe               -> /static/img/world/scene-cafe-v1.svg
convenience_store  -> /static/img/world/scene-convenience-store-v1.svg
park               -> /static/img/world/scene-park-v1.svg
```
把这个 map 写成常量 `ROOM_BG`（key → path），preload 里 `for (const [k,p] of Object.entries(ROOM_BG)) this.load.image("bg-"+k, p);`
（SVG 用 this.load.image 也能加载；若某张加载失败不要让整个场景崩——可监听 this.load.on('loaderror', ...) 打日志即可。）

### 2) setRoom(roomKey)（带淡入淡出）
新增方法。逻辑：
- 若 roomKey === this.roomKey 直接 return。
- 用相机淡出 → 换背景纹理 + 清掉旧房间的精灵 → 渲染新房间 → 淡入：
```
setRoom(roomKey) {
  if (roomKey === this.roomKey || !this.textures.exists("bg-" + roomKey)) return;
  const cam = this.cameras.main;
  cam.fadeOut(180, 14, 12, 18);
  cam.once("camerafadeoutcomplete", () => {
    this.roomKey = roomKey;
    this.bg.setTexture("bg-" + roomKey);
    this.bg.setScale(Math.max(W / this.bg.width, H / this.bg.height));
    this.clearRoomSprites();
    if (window.__world) this.renderRoom(window.__world);
    cam.fadeIn(180, 14, 12, 18);
  });
}
clearRoomSprites() {
  for (const k of Object.keys(this.sprites)) { this.sprites[k].destroy(); }
  for (const k of Object.keys(this.phys)) { if (this.phys[k].sprite) this.phys[k].sprite.destroy(); }
  this.sprites = {}; this.phys = {}; this.prevState = {};
}
```
- 注意：`this.bg` 现在是 create 里的局部 const，要改成 `this.bg = this.add.image(...)` 存成实例属性，setRoom 才能换它的纹理。

### 3) 自动跟随她 + 手动切换
- create 里存一个 `this.followHer = true`。
- 渲染 tick 里：`if (this.followHer && window.__world && window.__world.location !== this.roomKey) this.setRoom(window.__world.location);`
- HTML 加一行**房间按钮**（9 个）：点了 `setRoom(key)` + `this.followHer = false`；再加一个「跟随她」按钮恢复 `followHer = true` 并 setRoom 到 world.location。
  - 房间中文名从 worldViewAdapter import `ROOM_NAME`、顺序 import `ROOM_ORDER`。
  - 按钮放在现有 `.bar` 下面新开一个 `.rooms` 行。事件绑定在 module script 里，通过 `game.scene.getScene("world")` 拿 scene 调 setRoom。

### 4) 物理演示件只在 living_room
- makeDemoPendulum 现在 create 里无条件建。改成：只在 `this.roomKey === "living_room"` 时显示/存在；
  切到别的房间时隐藏或销毁，切回来再有。最简单：演示件挂个引用，setRoom 时 `this.demoPendulum.setVisible(roomKey==="living_room")`（物理体可继续存在，仅隐藏精灵）。

## 红线
- **只改 `app/static/world-engine.html`**（可 import worldViewAdapter 的现成导出，不改它）。
- 不碰任何后端 / 主控制台 JS（consciousness.js/layout.js）/ .env。
- 不破坏 Phase 0 的 DEPTHS 分带、renderRoom 的状态纯函数契约、ensurePhysics 占位。
- 美术继续 emoji 占位，不引入新图。

## 验收（codex 能做的 + 我来补）
- codex 自查：`node --check`（HTML 内 module 抽出来过不了 node，可跳过；改为人工核对 Phaser API 按本详规）。
  确认 ROOM_BG 9 个路径、setRoom/clearRoomSprites/followHer/房间按钮都加了、this.bg 改成实例属性。
- **浏览器渲染由用户肉眼验**（codex 和 AI 都跑不了浏览器）——codex 把代码写对即可，别试图自己开浏览器。
- 不 commit。报：改了哪些块 + 关键 Phaser 调用清单，供我审。

## 注意（Phaser 易错点，照抄别自创）
- 换背景纹理用 `this.bg.setTexture(key)` 后**必须重算 setScale**（不同图尺寸不同）。
- 相机淡入淡出用 `cam.fadeOut/fadeIn(duration, r,g,b)` + `camerafadeoutcomplete` 事件，别用别的写法。
- 切房间**必须先 clearRoomSprites**，否则上个房间的精灵会串台。
- import 路径用绝对 `/static/js/worldViewAdapter.js`。

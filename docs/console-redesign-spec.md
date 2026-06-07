# Console Dark Theme Redesign Spec

## 目标
将 Neno 控制台从 "milk 暖米色" 重构为 Linear/Vercel 风格暗色主题。

## 设计系统

### 色彩（Linear Dark）
```
--bg-deepest:    #09090B    /* 页面最底层 */
--bg-surface:    #111113    /* 卡片/侧边栏 */
--bg-elevated:   #1A1A1E    /* 输入框/hover/弹出层 */
--border:        #27272A    /* 默认边框 */
--border-hover:  #3F3F46    /* hover/active 边框 */
--text-primary:  #EDEDEF    /* 主文字 */
--text-secondary:#A1A1AA    /* 次要文字 */
--text-muted:    #71717A    /* 最弱文字/placeholder */
--accent:        #3B82F6    /* 强调色(蓝) */
--accent-hover:  #2563EB    /* 强调色hover */

/* 状态色 */
--ok:    #22C55E
--warn:  #EAB308
--error: #EF4444
--info:  #3B82F6
```

### 原则
1. **纯色，零渐变** — 所有 background: linear-gradient(...) 改为纯色
2. **零重阴影** — 去掉所有 box-shadow > 2px，或直接去掉
3. **小圆角** — 卡片 8px，按钮/输入框 6px，不要 18px/24px
4. **1px 边框分隔** — 用 border 而不是 shadow 来分层
5. **克制的 hover** — 背景微微变亮，不要 transform/translate

### 按钮系统
```
/* 默认 */
background: #27272A; color: #EDEDEF; border: 1px solid #3F3F46;
/* Hover */
background: #3F3F46;
/* Primary */
background: #3B82F6; color: white; border: none;
/* Primary Hover */
background: #2563EB;
/* Danger */
background: rgba(239,68,68,0.15); color: #EF4444; border: 1px solid rgba(239,68,68,0.3);
/* Ghost/Secondary */
background: transparent; color: #A1A1AA; border: 1px solid #27272A;
```

### 输入框
```
background: #1A1A1E; border: 1px solid #27272A; color: #EDEDEF; border-radius: 6px;
/* Focus */
border-color: #3B82F6; box-shadow: 0 0 0 2px rgba(59,130,246,0.15);
```

### 侧边栏
- 背景: #111113
- 右边框: 1px solid #27272A
- 导航按钮: 透明背景，hover 时 #1A1A1E
- Active 按钮: #1A1A1E 背景 + 左边 3px #3B82F6 竖条

### 卡片
```
background: #111113; border: 1px solid #27272A; border-radius: 8px;
```

### 聊天气泡
- User: #3B82F6 (纯色，无渐变)
- Bot: #27272A

### Tag/Badge
保持语义色但降低饱和度，半透明背景：
```
.ok    { background: rgba(34,197,94,0.12);  color: #22C55E; }
.warn  { background: rgba(234,179,8,0.12);  color: #EAB308; }
.error { background: rgba(239,68,68,0.12);  color: #EF4444; }
.info  { background: rgba(59,130,246,0.12); color: #3B82F6; }
```

### 滚动条（暗色）
```css
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #3F3F46; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #52525B; }
```

## 禁区（AI 味太重，不要出现）
- ❌ 所有 linear-gradient
- ❌ box-shadow 超过 0 2px 4px
- ❌ border-radius 超过 12px
- ❌ backdrop-filter: blur()
- ❌ transition 超过 200ms
- ❌ transform: translateY() 做 hover 效果
- ❌ 纯黑 #000000 或纯白 #FFFFFF
- ❌ 紫色/霓虹/发光效果
- ❌ Inter 字体（用系统字体栈）

## 不动的部分
- HTML 结构完全不变
- JS 逻辑完全不变
- 只改 <style> 标签内的 CSS
- 布局（grid、flex）不变
- 面板切换逻辑不变

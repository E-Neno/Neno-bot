---
name: codegraph-query
description: 轻量级代码图谱查询（不启动MCP，省228MB内存）
trigger: 当需要查找函数定义、调用关系、类结构、文件依赖、代码搜索时使用
---

# CodeGraphContext 轻量查询

## 为什么用这个而不是MCP

服务器只有1.6GB内存。MCP server（cgc mcp start）启动后永久占用228MB，会导致服务器OOM。
本方案通过命令行按需查询，用完即释放，仅临时占用~60MB。

## 使用方式

通过 Bash/terminal 工具调用：

```bash
/home/admin/emotion-bot/scripts/cgc-query.sh <命令> [参数]
```

## 可用命令

### search — 搜索任何名称
```bash
/home/admin/emotion-bot/scripts/cgc-query.sh search "session"
```

### functions — 搜索函数
```bash
/home/admin/emotion-bot/scripts/cgc-query.sh functions "run_chat"
/home/admin/emotion-bot/scripts/cgc-query.sh functions  # 列出所有
```

### classes — 搜索类
```bash
/home/admin/emotion-bot/scripts/cgc-query.sh classes "Session"
```

### callers — 谁调用了这个函数
```bash
/home/admin/emotion-bot/scripts/cgc-query.sh callers "run_chat_turn"
```

### calls — 这个函数调用了谁
```bash
/home/admin/emotion-bot/scripts/cgc-query.sh calls "run_chat_turn"
```

### files — 列出/搜索文件
```bash
/home/admin/emotion-bot/scripts/cgc-query.sh files "context_builder"
```

### cypher — 自定义Cypher查询
```bash
/home/admin/emotion-bot/scripts/cgc-query.sh cypher "MATCH (f:Function)-[:CALLS]->(c) WHERE f.name = \"run_chat_turn\" RETURN c.name LIMIT 20"
```

## 节点类型与属性

| 节点类型 | 关键属性 |
|---------|---------|
| Function | name, class_context, args, decorators, http_method, http_path, lang |
| Class | name |
| File | path, name, relative_path, package_name |
| Variable | name |
| Directory | name |

## 关系类型

| 关系 | 含义 |
|------|------|
| CALLS | 函数调用函数 |
| CONTAINS | 文件/目录包含函数/类 |
| IMPORTS | 文件导入模块 |
| DEFINES | 文件定义函数/类 |

## 典型工作流

1. **理解代码结构**：先 search 找到目标，再 callers/calls 看调用链
2. **修改前影响分析**：callers 看谁依赖这个函数，评估改动影响面
3. **调试**：search 定位函数，calls 追踪执行路径

## 注意事项

- **绝对不要启动 MCP server**（cgc mcp start），会吃228MB内存导致OOM
- 每次查询约2-5秒，返回JSON结果，查询完内存自动释放
- Cypher语法类似Neo4j但不完全兼容（不支持 CALL db.labels()）

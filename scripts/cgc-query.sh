#!/bin/bash
# CodeGraphContext 轻量查询脚本（不启动MCP server）
# 用法: cgc-query.sh <命令> [参数]

export CGC_RUNTIME_DB_TYPE=kuzudb
export CGC_RUNTIME_DB_PATH=/home/admin/emotion-bot/.codegraphcontext/codegraph.kuzu
CGC=/home/admin/emotion-bot/venv/bin/cgc

cd /tmp

case "${1:-help}" in
    stats)
        $CGC stats /home/admin/emotion-bot 2>&1 | grep -v "^No config\|^Using\|^Resolving\|^Services\|^Welcome\|^CGC\|^  global\|^  per-repo\|^  named\|^Switch\|^Or:"
        ;;
    search)
        $CGC query "MATCH (n) WHERE n.name CONTAINS \"${2}\" RETURN label(n) as type, n.name as name LIMIT 20" 2>&1 | grep -v "^No config\|^Using\|^Resolving\|^Services"
        ;;
    functions|funcs)
        if [ -n "$2" ]; then
            $CGC query "MATCH (f:Function) WHERE f.name CONTAINS \"$2\" RETURN f.name as name, f.class_context as class, f.args as args LIMIT 20" 2>&1 | grep -v "^No config\|^Using\|^Resolving\|^Services"
        else
            $CGC query "MATCH (f:Function) RETURN f.name as name, f.class_context as class LIMIT 30" 2>&1 | grep -v "^No config\|^Using\|^Resolving\|^Services"
        fi
        ;;
    classes)
        $CGC query "MATCH (c:Class) WHERE c.name CONTAINS \"${2}\" RETURN c.name as name LIMIT 20" 2>&1 | grep -v "^No config\|^Using\|^Resolving\|^Services"
        ;;
    callers)
        $CGC query "MATCH (caller)-[:CALLS]->(f:Function) WHERE f.name = \"${2}\" RETURN caller.name as caller LIMIT 20" 2>&1 | grep -v "^No config\|^Using\|^Resolving\|^Services"
        ;;
    calls)
        $CGC query "MATCH (f:Function)-[:CALLS]->(callee) WHERE f.name = \"${2}\" RETURN callee.name as callee LIMIT 20" 2>&1 | grep -v "^No config\|^Using\|^Resolving\|^Services"
        ;;
    files)
        if [ -n "$2" ]; then
            $CGC query "MATCH (f:File) WHERE f.path CONTAINS \"$2\" RETURN f.path as path, f.package_name as pkg LIMIT 20" 2>&1 | grep -v "^No config\|^Using\|^Resolving\|^Services"
        else
            $CGC query "MATCH (f:File) RETURN f.path as path LIMIT 30" 2>&1 | grep -v "^No config\|^Using\|^Resolving\|^Services"
        fi
        ;;
    cypher)
        shift
        $CGC query "$*" 2>&1 | grep -v "^No config\|^Using\|^Resolving\|^Services"
        ;;
    help|*)
        echo "用法: cgc-query.sh <命令> [参数]"
        echo ""
        echo "命令:"
        echo "  stats                - 索引统计"
        echo "  search <name>        - 搜索任何名称"
        echo "  functions [name]     - 搜索函数"
        echo "  classes <name>       - 搜索类"
        echo "  callers <func>       - 谁调用了这个函数"
        echo "  calls <func>         - 这个函数调用了谁"
        echo "  files [path]         - 列出文件"
        echo "  cypher <query>       - 自定义Cypher查询"
        ;;
esac

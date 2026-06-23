package com.neno.app.ui

enum class AsyncListState {
    Loading,
    Empty,
    Content,
}

fun asyncListState(items: List<*>?): AsyncListState = when {
    items == null -> AsyncListState.Loading
    items.isEmpty() -> AsyncListState.Empty
    else -> AsyncListState.Content
}

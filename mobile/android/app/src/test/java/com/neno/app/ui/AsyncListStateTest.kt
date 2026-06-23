package com.neno.app.ui

import org.junit.Assert.assertEquals
import org.junit.Test

class AsyncListStateTest {
    @Test
    fun nullListIsLoadingNotContent() {
        assertEquals(AsyncListState.Loading, asyncListState(null))
    }

    @Test
    fun emptyListIsEmptyAfterLoad() {
        assertEquals(AsyncListState.Empty, asyncListState(emptyList<Any>()))
    }

    @Test
    fun populatedListIsContent() {
        assertEquals(AsyncListState.Content, asyncListState(listOf("Neno")))
    }
}

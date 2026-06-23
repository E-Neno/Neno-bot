package com.neno.app.data

class NenoRepository(
    private val api: NenoApi,
    private val settingsStore: SettingsStore,
) {
    suspend fun checkStatus(): MobileStatus = api.status()

    suspend fun loadConversations(): List<MobileConversation> =
        runCatching { api.conversations() }.getOrElse { defaultConversations() }

    suspend fun loadNenoMessages(): List<MobileMessage> =
        runCatching { api.messages("neno") }.getOrElse { emptyList() }

    suspend fun sendToNeno(text: String): Result<MobileSendMessageResponse> {
        val normalized = text.trim()
        if (normalized.isBlank()) {
            return Result.failure(IllegalArgumentException("消息不能为空"))
        }
        return runCatching { api.sendMessage("neno", normalized) }
    }

    fun saveSettings(baseUrl: String, token: String) {
        settingsStore.save(baseUrl, token)
    }

    fun currentBaseUrl(): String = settingsStore.baseUrl

    fun currentToken(): String = settingsStore.token

    companion object {
        fun defaultConversations(): List<MobileConversation> = listOf(
            MobileConversation(
                id = "neno",
                title = "Neno",
                subtitle = "置顶联系人",
                lastMessage = "慢慢来，明早再说。",
                pinned = true,
                kind = "primary",
            ),
            MobileConversation(
                id = "writing",
                title = "写作助手",
                subtitle = "状态整理好了。",
                lastMessage = "状态整理好了。",
                kind = "utility",
            ),
            MobileConversation(
                id = "code",
                title = "代码助手",
                subtitle = "今天的改动先收住。",
                lastMessage = "今天的改动先收住。",
                kind = "utility",
            ),
            MobileConversation(
                id = "quiet",
                title = "安静记录",
                subtitle = "我会在这里等你。",
                lastMessage = "我会在这里等你。",
                kind = "utility",
            ),
        )
    }
}

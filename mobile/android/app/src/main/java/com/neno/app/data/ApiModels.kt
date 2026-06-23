package com.neno.app.data

data class MobileFeatureFlags(
    val attachments: Boolean = false,
    val notifications: Boolean = false,
    val quickReply: Boolean = false,
)

data class MobileStatus(
    val success: Boolean,
    val serverTime: String,
    val api: String,
    val sessionIdLabel: String,
    val features: MobileFeatureFlags = MobileFeatureFlags(),
)

data class MobileConversation(
    val id: String,
    val title: String,
    val subtitle: String,
    val lastMessage: String = "",
    val lastMessageAt: String? = null,
    val unreadCount: Int = 0,
    val pinned: Boolean = false,
    val kind: String,
)

data class MobileMessage(
    val id: Long,
    val role: String,
    val text: String,
    val createdAt: String? = null,
    val pending: Boolean = false,
)

data class MobileSendMessageResponse(
    val success: Boolean,
    val conversationId: String,
    val userMessage: MobileMessage,
    val assistantMessage: MobileMessage? = null,
)

from enum import Enum

class Colors:
    PRIMARY = 0x5865F2
    SUCCESS = 0x57F287
    WARNING = 0xFEE75C
    DANGER = 0xED4245
    INFO = 0x5865F2
    RAILWAY = 0x0B0D0E  # Railway brand color

class Emojis:
    SUCCESS = "✅"
    ERROR = "❌"
    WARNING = "⚠️"
    INFO = "ℹ️"
    LOADING = "⏳"
    THREAD = "🧵"
    CALENDAR = "📅"
    TICKET = "🎫"
    REMINDER = "⏰"
    WORKFLOW = "⚙️"
    RAILWAY = "🚄"

class TicketStatus(Enum):
    OPEN = "open"
    CLOSED = "closed"
    IN_PROGRESS = "in_progress"

class TicketPriority(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

class ReminderType(Enum):
    PERSONAL = "personal"
    CHANNEL = "channel"
    ROLE = "role"

class WorkflowStatus(Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    PAUSED = "paused"

class WorkflowTrigger(Enum):
    MESSAGE = "message"
    MEMBER_JOIN = "member_join"
    THREAD_CREATE = "thread_create"
    CHANNEL_CREATE = "channel_create"

class WorkflowAction(Enum):
    SEND_MESSAGE = "send_message"
    ADD_ROLE = "add_role"
    CREATE_CHANNEL = "create_channel"
    SEND_DM = "send_dm"

class RailwayConfig:
    """Railway-specific configuration constants"""
    MAX_BUILD_TIME = 600  # 10 minutes
    DEFAULT_MEMORY = "512MB"
    DEFAULT_CPU = "1vCPU"
    SUPPORTED_REGIONS = ["us-west1", "us-east1", "eu-west1"]

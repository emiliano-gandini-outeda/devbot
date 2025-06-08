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
    IN_PROGRESS = "in_progress"
    CLOSED = "closed"

class WorkflowStatus(Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    PAUSED = "paused"

class ReminderType(Enum):
    PERSONAL = "personal"
    CHANNEL = "channel"
    ROLE = "role"

class RailwayConfig:
    """Railway-specific configuration constants"""
    MAX_BUILD_TIME = 600  # 10 minutes
    DEFAULT_MEMORY = "512MB"
    DEFAULT_CPU = "1vCPU"
    SUPPORTED_REGIONS = ["us-west1", "us-east1", "eu-west1"]

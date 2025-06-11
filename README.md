# devBot - Community Manager Bot 🤖

A comprehensive Discord bot designed to streamline community management with powerful automation, integrations, and administrative tools. Built for open source communities, development teams, and Discord servers that need professional-grade management capabilities.

## ✨ Features

### 🛡️ Advanced Administration
- **Role-based Admin System**: Flexible permission management with custom admin roles
- **Server Configuration**: Easy setup commands for all bot features
- **Comprehensive Logging**: Track all server activities with detailed audit logs
- **Bot Status Monitoring**: Real-time health checks and performance metrics

### 🎫 Professional Ticket System
- **Smart Ticket Creation**: Organized support ticket system with categories
- **Assignment Management**: Assign tickets to specific team members
- **Status Tracking**: Monitor ticket progress with automated updates
- **Transcript Generation**: Automatic ticket transcripts for record keeping
- **Privacy Controls**: Restricted access to ticket assignees and admins only

### ⏰ Smart Reminders & Scheduling
- **Flexible Time Parsing**: Natural language time input (1h, 30m, 2d, etc.)
- **Personal & Channel Reminders**: DM notifications with channel fallbacks
- **Meeting Scheduler**: Integrated meeting planning with voice channel support
- **Automated Announcements**: Server-wide meeting notifications

### 🗨️ Advanced Conversation Management
- **Thread Organization**: Create and manage discussion threads
- **Message Search**: Powerful search across server history
- **Archive System**: Thread archiving with complete transcripts
- **Pin Management**: Easy message pinning and organization

### 🔔 Intelligent Notifications
- **Keyword Monitoring**: Get notified when specific terms are mentioned
- **Custom Preferences**: Personalized notification settings
- **Smart Filtering**: Avoid notification spam with intelligent filtering
- **Multi-channel Support**: Monitor keywords across multiple channels

### 🤖 AI-Powered Features
- **Message Summarization**: Automatically summarize long conversations
- **Multi-language Translation**: Real-time text translation
- **AI Assistant**: Get help with questions and tasks
- **Tone Analysis**: Understand message sentiment and context

### 🔗 Powerful Integrations

#### GitHub Integration
- **Repository Tracking**: Monitor commits, issues, and pull requests
- **Smart Notifications**: Customizable ping preferences per repository
- **Detailed Repository Info**: View comprehensive repo statistics
- **Team Collaboration**: Keep your team updated on code changes

#### Google Calendar Integration *(Coming Soon)*
- **Event Viewing**: Display upcoming calendar events
- **Meeting Creation**: Schedule meetings directly from Discord
- **Calendar Sync**: Stay synchronized with your team's schedule

#### Notion Integration *(Coming Soon)*
- **Database Management**: Connect and manage Notion databases
- **Note Creation**: Create Notion pages from Discord
- **Workspace Search**: Search across your Notion workspace
- **Message Sync**: Sync Discord conversations to Notion

#### Trello Integration *(Coming Soon)*
- **Board Management**: View and manage Trello boards
- **Card Creation**: Create Trello cards from Discord messages
- **Update Notifications**: Get notified about card changes
- **Team Coordination**: Streamline project management

### 🔒 Privacy & Data Management
- **GDPR Compliant**: Full data export and deletion capabilities
- **Transparent Policies**: Clear privacy policy and terms of service
- **User Control**: Users have complete control over their data
- **Secure Storage**: All data encrypted and securely stored

## 📋 Commands Overview

### 🔧 Setup Commands (Admin Only)
- `/ticket-system-setup` - Configure ticket system
- `/server-logs-setup` - Set up logging channel
- `/setup-tracking` - Configure GitHub tracking
- `/setup-meetings` - Set up meeting system
- `/setup-reminders` - Configure reminder system
- `/setup-threads` - Set up thread logging

### 👥 User Management
- `/help` - Interactive help system
- `/user-permissions [user]` - Check user permissions
- `/role-info <role>` - Display role information

### 🎫 Ticket System
- `/ticket create <title> <description>` - Create support ticket
- `/ticket list [status] [user]` - List tickets with filters
- `/ticket assign <ticket_id> <user>` - Assign ticket to user
- `/ticket private` - Make ticket private
- `/ticket public` - Make ticket public
- `/ticket join` - Join a ticket conversation

### ⏰ Reminders & Meetings
- `/remind <time> <message>` - Set personal reminder
- `/list-reminders` - View your active reminders
- `/delete-reminder <number>` - Remove reminder
- `/create-meeting` - Schedule a meeting

### 🗨️ Conversations
- `/create-thread <message_id> <name>` - Create discussion thread
- `/search-messages <query>` - Search server messages
- `/archive-thread` - Archive thread with transcript

### 🔔 Notifications
- `/add-keyword <keyword>` - Monitor keyword mentions
- `/list-keywords` - View monitored keywords
- `/remove-keyword <keyword>` - Stop monitoring keyword

### 🤖 AI Features
- `/summarize [count]` - Summarize recent messages
- `/translate <text> <language>` - Translate text
- `/ask-ai <question>` - Ask AI assistant
- `/analyze-tone <text>` - Analyze message tone

### 🔗 Integrations
- `/google-connect` - Connect Google account
- `/calendar-events` - View upcoming events
- `/track-repo <repository>` - Track GitHub repository
- `/list-repos` - Manage tracked repositories

### 🔒 Privacy & Data
- `/privacy-export-data` - Export your data (GDPR)
- `/delete-data [type]` - Delete specific or all data
- `/get-data <user>` - Get user data (Admin only)
- `/privacy-policy` - View privacy policy
- `/terms-of-service` - View terms of service

## 🏗️ Architecture

\`\`\`
├── main.py                 # Bot entry point and initialization
├── config/
│   ├── settings.py        # Configuration management
│   └── constants.py       # Application constants
├── utils/
│   ├── db.py             # Database connection and queries
│   ├── admin.py          # Admin permission management
│   ├── helpers.py        # Utility functions and embed builder
│   ├── logging_manager.py # Server logging system
│   ├── ticket_manager.py  # Ticket system logic
│   └── workflow_manager.py # Automation workflows
├── cogs/
│   ├── admin.py          # Administrative commands
│   ├── setup.py          # Server setup commands
│   ├── help.py           # Interactive help system
│   ├── tickets.py        # Ticket management
│   ├── reminders.py      # Reminder system
│   ├── meetings.py       # Meeting scheduler
│   ├── conversations.py  # Thread and message management
│   ├── notifications.py  # Keyword notifications
│   ├── intelligence.py   # AI-powered features
│   ├── privacy.py        # Data management and GDPR
│   ├── integrations_*.py # External service integrations
│   └── logging.py        # Server activity logging
\`\`\`

## 🗄️ Database Schema

The bot uses PostgreSQL with a comprehensive schema including:

- **users** - User profiles and integration tokens
- **admin_roles** - Server-specific admin role configuration
- **tickets** - Support ticket system with full lifecycle tracking
- **reminders** - User reminders with flexible scheduling
- **meetings** - Meeting scheduler with participant tracking
- **workflows** - Custom automation workflows
- **keywords** - Keyword monitoring and notifications
- **github_tracked_repos** - Repository tracking with user preferences
- **user_data** - Flexible data storage for various features

## 🤝 Contributing

We welcome contributions from the community! Here's how you can help:

### Getting Started
1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Add tests for new functionality
5. Ensure all tests pass
6. Commit your changes (`git commit -m 'Add amazing feature'`)
7. Push to the branch (`git push origin feature/amazing-feature`)
8. Open a Pull Request

### Development Guidelines
- Follow PEP 8 style guidelines
- Add docstrings to all functions and classes
- Include unit tests for new features
- Update documentation as needed
- Test thoroughly before submitting

### Areas for Contribution
- 🐛 Bug fixes and improvements
- ✨ New features and integrations
- 📚 Documentation improvements
- 🧪 Test coverage expansion
- 🎨 UI/UX enhancements
- 🌐 Internationalization support

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- Built with [discord.py](https://discordpy.readthedocs.io/)
- Database powered by PostgreSQL
- AI features powered by various ML APIs
- Integration APIs: GitHub, Google Calendar, Notion, Trello
- Community feedback and contributions

---

**devBot - Powered by EGOS** 🚀

*Making Discord community management effortless and professional.*

# Discord Slack-like Bot - Railway Edition 🚄

A comprehensive Discord bot that replicates Slack's collaborative features including automation, integrations, support tickets, and AI-powered assistance. Optimized for deployment on Railway.

## Features

### 🗨️ Conversations
- Create and manage threads
- Archive and rename threads
- Search and export messages
- Channel synchronization

### 🔗 Integrations
- **Google Workspace**: Calendar events, OAuth authentication
- **Notion**: Database access, page creation
- **Trello**: Board management, task creation

### ⚙️ Automation
- Custom workflow creation
- Trigger-based automation
- Workflow management and control

### 🎫 Support System  
- Ticket creation and management
- Assignment and status tracking
- Priority levels and organization

### 👥 Role Management
- Role assignment and removal
- Permission analysis
- Access control automation

### 🔒 Privacy & Data
- Data export requests
- Account deletion
- Privacy policy compliance

### ⏰ Reminders & Organization
- Personal and channel reminders
- Recurring reminders
- Time-based notifications

### 🔔 Smart Notifications
- Keyword alerts
- Thread muting
- Intelligent notification filtering

### 🤖 AI Features
- Conversation summarization
- Message translation
- Tone analysis
- AI-powered Q&A

## Quick Start

### Local Development

1. Clone the repository
2. Install dependencies:
   \`\`\`bash
   pip install -r requirements.txt
   \`\`\`

3. Copy `.env.example` to `.env` and fill in your credentials:
   \`\`\`bash
   cp .env.example .env
   \`\`\`

4. Run the bot:
   \`\`\`bash
   python main.py
   \`\`\`

### Railway Deployment 🚄

#### Method 1: Deploy from GitHub

1. **Fork this repository** to your GitHub account

2. **Connect to Railway**:
   - Visit [railway.app](https://railway.app)
   - Sign up/Login with GitHub
   - Click "New Project" → "Deploy from GitHub repo"
   - Select your forked repository

3. **Add PostgreSQL Database**:
   - In your Railway project dashboard
   - Click "New" → "Database" → "Add PostgreSQL"
   - Railway will automatically set the `DATABASE_URL` environment variable

4. **Set Environment Variables**:
   - Go to your service → "Variables" tab
   - Add the required variables from `.env.example`:
   \`\`\`
   DISCORD_TOKEN=your_discord_bot_token
   BOT_PREFIX=!
   # Add other optional variables as needed
   \`\`\`

5. **Deploy**:
   - Railway automatically deploys on every push to main branch
   - Check the "Deployments" tab for build status

#### Method 2: Deploy with Railway CLI

1. **Install Railway CLI**:
   \`\`\`bash
   npm install -g @railway/cli
   \`\`\`

2. **Login and Initialize**:
   \`\`\`bash
   railway login
   railway init
   \`\`\`

3. **Add PostgreSQL**:
   \`\`\`bash
   railway add postgresql
   \`\`\`

4. **Set Environment Variables**:
   \`\`\`bash
   railway variables set DISCORD_TOKEN=your_token_here
   railway variables set BOT_PREFIX=!
   # Add other variables as needed
   \`\`\`

5. **Deploy**:
   \`\`\`bash
   railway up
   \`\`\`

#### Method 3: One-Click Deploy

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/template/your-template-id)

## Configuration

### Required Environment Variables
- `DISCORD_TOKEN`: Your Discord bot token

### Railway-Specific Variables (Auto-set)
- `DATABASE_URL`: PostgreSQL connection string (auto-provided by Railway)
- `RAILWAY_ENVIRONMENT`: Current environment (production/staging)
- `PORT`: Port number (auto-provided by Railway)

### Optional Environment Variables
- `GOOGLE_CLIENT_ID` & `GOOGLE_CLIENT_SECRET`: For Google integrations
- `NOTION_TOKEN`: For Notion workspace integration
- `TRELLO_API_KEY` & `TRELLO_TOKEN`: For Trello project management
- `OPENAI_API_KEY`: For AI-powered features
- `REDIS_URL`: For Redis caching (Railway add-on)

## Railway Features Used

### 🗄️ **PostgreSQL Database**
- Managed PostgreSQL instance
- Automatic backups and scaling
- Connection pooling and monitoring

### 🚀 **Auto-Deployment**
- GitHub integration for CI/CD
- Automatic builds on push
- Preview deployments for pull requests

### 📊 **Monitoring & Observability**
- Application metrics and logging
- Performance monitoring
- Error tracking and alerts

### 🔧 **Environment Management**
- Separate staging and production environments
- Environment-specific configuration
- Secret management

## Commands

### Conversations
- `/create-thread` - Create a new thread
- `/archive-thread` - Archive current thread
- `/rename-thread` - Rename current thread
- `/search-messages` - Search for messages

### Integrations
- `/google-connect` - Connect Google account
- `/calendar-events` - View calendar events
- `/notion-databases` - List Notion databases
- `/trello-boards` - List Trello boards

### Automation
- `/create-workflow` - Create automation workflow
- `/list-workflows` - List server workflows
- `/toggle-workflow` - Enable/disable workflow

### Support
- `/create-ticket` - Create support ticket
- `/list-tickets` - List tickets
- `/assign-ticket` - Assign ticket to user

### Reminders
- `/remind` - Set personal reminder
- `/remind-channel` - Set channel reminder
- `/list-reminders` - List your reminders

### Notifications
- `/add-keyword` - Add keyword alert
- `/list-keywords` - List monitored keywords
- `/mute-thread` - Mute thread notifications

### AI Features
- `/summarize` - Summarize conversation
- `/translate` - Translate text
- `/ask-ai` - Ask AI assistant
- `/analyze-tone` - Analyze message tone

## Architecture

The bot is built with a modular architecture optimized for Railway:

- **main.py**: Core bot initialization and Railway-specific setup
- **cogs/**: Feature modules (conversations, integrations, etc.)
- **utils/**: Utility functions and API wrappers
- **config/**: Configuration and Railway-specific constants
- **railway.toml**: Railway deployment configuration

## Database Schema

The bot uses Railway's managed PostgreSQL with tables for:
- Users and authentication tokens
- Support tickets and assignments
- Reminders and schedules
- Workflows and automation
- User data and privacy

## Performance & Scaling

### Railway Optimizations
- **Automatic scaling** based on CPU and memory usage
- **Connection pooling** for database efficiency
- **CDN integration** for static assets
- **Load balancing** for high availability

### Bot Optimizations
- **Async/await patterns** for non-blocking operations
- **Connection reuse** for external APIs
- **Efficient database queries** with proper indexing
- **Memory-efficient data structures**

## Monitoring & Maintenance

### Railway Dashboard
- Real-time metrics and logs
- Performance analytics
- Error tracking and alerts
- Database monitoring

### Logging
- Structured logging with timestamps
- Error tracking and stack traces
- Performance metrics
- User activity monitoring

## Troubleshooting

### Common Issues

1. **Bot not responding**:
   - Check Railway logs in dashboard
   - Verify `DISCORD_TOKEN` is set correctly
   - Ensure bot has proper permissions in Discord

2. **Database connection errors**:
   - Verify PostgreSQL service is running
   - Check `DATABASE_URL` environment variable
   - Review connection limits

3. **Commands not syncing**:
   - Check bot permissions in Discord
   - Restart the Railway service
   - Verify slash command registration

### Railway-Specific

1. **Deployment failures**:
   - Check build logs in Railway dashboard
   - Verify `railway.toml` configuration
   - Ensure all dependencies are in `requirements.txt`

2. **Environment variables**:
   - Use Railway dashboard to manage variables
   - Restart service after variable changes
   - Check variable scope (service vs. project)

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test locally and on Railway
5. Submit a pull request

## Support

For support and questions:
- Create an issue on GitHub
- Join our Discord server
- Contact the maintainers
- Check Railway documentation

## License

This project is licensed under the MIT License - see the LICENSE file for details.

---

Built with ❤️ using Discord.py and deployed on Railway 🚄

**Railway Benefits:**
- ⚡ Lightning-fast deployments
- 📈 Auto-scaling infrastructure  
- 🔒 Enterprise-grade security
- 💰 Cost-effective pricing
- 🛠️ Developer-friendly tools

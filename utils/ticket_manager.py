async def create_ticket_channel(self, guild: discord.Guild, ticket_id: str, user: discord.Member, title: str) -> Optional[discord.TextChannel]:
    """Create a ticket channel - PUBLIC AND READ-ONLY BY DEFAULT"""
    try:
        print(f"🎫 Creating ticket channel for {ticket_id}")
        
        # Get ticket config
        config = await self.get_ticket_config(str(guild.id))
        if not config:
            print(f"❌ No ticket config found for guild {guild.id}")
            return None
        
        category_id = config.get('category_id')
        if not category_id:
            print(f"❌ No category_id in ticket config for guild {guild.id}")
            return None
        
        category = guild.get_channel(int(category_id))
        if not category:
            print(f"❌ Category channel {category_id} not found in guild {guild.id}")
            return None
        
        # Create channel name
        channel_name = f"ticket-{ticket_id.lower()}"
        
        print(f"🔧 Setting up PUBLIC READ-ONLY permissions for {channel_name}")
        
        # CRITICAL: Set permissions - PUBLIC AND READ-ONLY BY DEFAULT
        overwrites = {
            # @everyone can READ but NOT WRITE (PUBLIC READ-ONLY)
            guild.default_role: discord.PermissionOverwrite(
                read_messages=True,      # ✅ Can see the ticket
                send_messages=False,     # ❌ Cannot write messages
                add_reactions=False,     # ❌ Cannot add reactions
                attach_files=False       # ❌ Cannot attach files
            ),
            # Ticket creator can READ and WRITE
            user: discord.PermissionOverwrite(
                read_messages=True,      # ✅ Can see the ticket
                send_messages=True,      # ✅ Can write messages
                add_reactions=True,      # ✅ Can add reactions
                attach_files=True        # ✅ Can attach files
            ),
            # Bot can manage everything
            guild.me: discord.PermissionOverwrite(
                read_messages=True,
                send_messages=True,
                manage_channels=True,
                manage_messages=True,
                add_reactions=True,
                attach_files=True
            )
        }
        
        # Add admin roles with WRITE permissions
        if hasattr(self.bot, 'admin_manager') and self.bot.admin_manager:
            admin_role_ids = self.bot.admin_manager.get_admin_roles(str(guild.id))
            for role_id in admin_role_ids:
                role = guild.get_role(int(role_id))
                if role:
                    overwrites[role] = discord.PermissionOverwrite(
                        read_messages=True,
                        send_messages=True,
                        add_reactions=True,
                        attach_files=True
                    )
                    print(f"✅ Added admin role {role.name} with write permissions")
        
        print(f"📝 Creating channel with overwrites: {len(overwrites)} permission sets")
        
        # Create the channel
        channel = await guild.create_text_channel(
            name=channel_name,
            category=category,
            topic=f"Support ticket: {ticket_id} | Created by {user.display_name} | 🌐 Public & Read-Only",
            overwrites=overwrites
        )
        
        print(f"✅ Created PUBLIC READ-ONLY ticket channel: {channel.name}")
        return channel
        
    except Exception as e:
        print(f"❌ Error creating ticket channel: {e}")
        return None

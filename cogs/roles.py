@app_commands.command(name="see-user", description="View basic information about a user")
@app_commands.describe(user="User to view information about")
async def see_user(self, interaction: discord.Interaction, user: discord.Member = None):
    if not user:
        user = interaction.user
    
    embed = discord.Embed(
        title=f"👤 User Information: {user.display_name}",
        color=user.color if user.color != discord.Color.default() else 0x5865F2
    )
    
    # Basic information
    embed.add_field(name="Username", value=user.name, inline=True)
    embed.add_field(name="User ID", value=user.id, inline=True)
    embed.add_field(name="Bot", value="Yes" if user.bot else "No", inline=True)
    
    # Dates
    joined_at = user.joined_at.strftime("%Y-%m-%d %H:%M UTC") if user.joined_at else "Unknown"
    created_at = user.created_at.strftime("%Y-%m-%d %H:%M UTC")
    
    embed.add_field(name="Joined Server", value=joined_at, inline=True)
    embed.add_field(name="Account Created", value=created_at, inline=True)
    
    # Calculate account age
    account_age = datetime.utcnow() - user.created_at
    years = account_age.days // 365
    months = (account_age.days % 365) // 30
    days = (account_age.days % 365) % 30
    
    age_str = []
    if years > 0:
        age_str.append(f"{years} year{'s' if years != 1 else ''}")
    if months > 0:
        age_str.append(f"{months} month{'s' if months != 1 else ''}")
    if days > 0 or not age_str:
        age_str.append(f"{days} day{'s' if days != 1 else ''}")
    
    embed.add_field(name="Account Age", value=", ".join(age_str), inline=True)
    
    # Roles (up to 10)
    roles = [role.mention for role in user.roles[1:]]  # Skip @everyone
    if roles:
        embed.add_field(
            name=f"Roles ({len(roles)})",
            value=", ".join(roles[:10]) + ("..." if len(roles) > 10 else ""),
            inline=False
        )
    
    # Set thumbnail to user's avatar
    embed.set_thumbnail(url=user.display_avatar.url)
    
    await interaction.response.send_message(embed=embed)

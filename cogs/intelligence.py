import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
import json
from utils.helpers import EmbedBuilder
from config.settings import Settings

class Intelligence(commands.Cog):
    """AI-powered features for productivity and analysis"""
    
    def __init__(self, bot):
        self.bot = bot
    
    @app_commands.command(name="summarize", description="Summarize recent messages in this channel")
    @app_commands.describe(
        count="Number of messages to summarize (max 50)",
        user="Only summarize messages from this user"
    )
    async def summarize(self, interaction: discord.Interaction, count: int = 20, user: discord.Member = None):
        if count > 50:
            count = 50
        
        await interaction.response.defer()
        
        try:
            messages = []
            async for message in interaction.channel.history(limit=count):
                if user and message.author != user:
                    continue
                if not message.author.bot and message.content:
                    messages.append(f"{message.author.display_name}: {message.content}")
            
            if not messages:
                embed = EmbedBuilder.info("No Messages", "No messages found to summarize")
                await interaction.followup.send(embed=embed)
                return
            
            # Reverse to get chronological order
            messages.reverse()
            conversation = "\n".join(messages)
            
            # Mock AI summary (replace with actual AI service)
            summary = await self.generate_summary(conversation)
            
            embed = discord.Embed(
                title="📋 Conversation Summary",
                description=summary,
                color=0x5865F2
            )
            embed.add_field(name="Messages Analyzed", value=str(len(messages)), inline=True)
            embed.add_field(name="Channel", value=interaction.channel.mention, inline=True)
            embed.add_field(name="Platform", value="Railway 🚄", inline=True)
            
            if user:
                embed.add_field(name="User Filter", value=user.mention, inline=True)
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to generate summary: {str(e)}")
            await interaction.followup.send(embed=embed)
    
    @app_commands.command(name="translate", description="Translate text to another language")
    @app_commands.describe(
        text="Text to translate",
        target_language="Target language (e.g., 'spanish', 'french', 'german')"
    )
    async def translate(self, interaction: discord.Interaction, text: str, target_language: str):
        await interaction.response.defer()
        
        try:
            # Mock translation (replace with actual translation service)
            translated = await self.translate_text(text, target_language)
            
            embed = discord.Embed(
                title="🌐 Translation",
                color=0x5865F2
            )
            embed.add_field(name="Original", value=text[:1000], inline=False)
            embed.add_field(name=f"Translated ({target_language.title()})", value=translated[:1000], inline=False)
            embed.set_footer(text="Powered by Railway 🚄")
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to translate text: {str(e)}")
            await interaction.followup.send(embed=embed)
    
    @app_commands.command(name="ask-ai", description="Ask a question to the AI assistant")
    @app_commands.describe(question="Your question for the AI")
    async def ask_ai(self, interaction: discord.Interaction, question: str):
        await interaction.response.defer()
        
        try:
            # Mock AI response (replace with actual AI service)
            answer = await self.get_ai_response(question)
            
            embed = discord.Embed(
                title="🤖 AI Assistant",
                color=0x5865F2
            )
            embed.add_field(name="Question", value=question, inline=False)
            embed.add_field(name="Answer", value=answer, inline=False)
            embed.set_footer(text="AI responses may not always be accurate • Railway 🚄")
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to get AI response: {str(e)}")
            await interaction.followup.send(embed=embed)
    
    @app_commands.command(name="analyze-tone", description="Analyze the tone of recent messages")
    @app_commands.describe(count="Number of messages to analyze (max 20)")
    async def analyze_tone(self, interaction: discord.Interaction, count: int = 10):
        if count > 20:
            count = 20
        
        await interaction.response.defer()
        
        try:
            messages = []
            async for message in interaction.channel.history(limit=count):
                if not message.author.bot and message.content:
                    messages.append(message.content)
            
            if not messages:
                embed = EmbedBuilder.info("No Messages", "No messages found to analyze")
                await interaction.followup.send(embed=embed)
                return
            
            # Mock tone analysis (replace with actual sentiment analysis)
            tone_analysis = await self.analyze_message_tone(messages)
            
            embed = discord.Embed(
                title="📊 Tone Analysis",
                description=f"Analysis of the last {len(messages)} messages",
                color=0x5865F2
            )
            
            for tone, percentage in tone_analysis.items():
                embed.add_field(name=tone.title(), value=f"{percentage}%", inline=True)
            
            embed.set_footer(text="Powered by Railway 🚄")
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to analyze tone: {str(e)}")
            await interaction.followup.send(embed=embed)
    
    async def generate_summary(self, conversation: str) -> str:
        """Generate a summary of the conversation (mock implementation)"""
        # This is a mock implementation. In a real bot, you'd use OpenAI API or similar
        if not Settings.OPENAI_API_KEY:
            return "Summary generation requires OpenAI API configuration. Key topics discussed in the conversation include general discussion and information sharing. Deployed on Railway for scalable AI processing."
        
        # Mock summary for demonstration
        return f"The conversation involved multiple participants discussing various topics. Key themes included collaboration, planning, and information sharing. The discussion was generally positive and productive, with {len(conversation.split('\\n'))} total messages analyzed. Processing completed on Railway infrastructure."
    
    async def translate_text(self, text: str, target_language: str) -> str:
        """Translate text to target language (mock implementation)"""
        # Mock translation for demonstration
        translations = {
            "spanish": f"[Traducción al español de: {text}]",
            "french": f"[Traduction française de: {text}]",
            "german": f"[Deutsche Übersetzung von: {text}]",
            "italian": f"[Traduzione italiana di: {text}]",
            "portuguese": f"[Tradução portuguesa de: {text}]"
        }
        
        return translations.get(target_language.lower(), f"[{target_language.title()} translation of: {text}]")
    
    async def get_ai_response(self, question: str) -> str:
        """Get AI response to question (mock implementation)"""
        # This is a mock implementation. In a real bot, you'd use OpenAI API or similar
        if not Settings.OPENAI_API_KEY:
            return "AI responses require OpenAI API configuration. I'm a mock response for demonstration purposes, running on Railway's scalable infrastructure."
        
        # Mock responses for common questions
        mock_responses = {
            "hello": "Hello! I'm an AI assistant integrated into this Discord bot, running on Railway's cloud platform. How can I help you today?",
            "weather": "I don't have access to real-time weather data, but you can check your local weather service for current conditions.",
            "time": "I don't have access to real-time data, but you can check your system clock for the current time.",
            "help": "I can help with various tasks including answering questions, providing explanations, and assisting with general information. This bot is powered by Railway!",
            "railway": "Railway is an amazing deployment platform that makes it easy to deploy and scale applications like this Discord bot!"
        }
        
        question_lower = question.lower()
        for key, response in mock_responses.items():
            if key in question_lower:
                return response
        
        return f"I understand you're asking about: '{question}'. This is a mock AI response for demonstration. In a production environment, this would be powered by a real AI service like OpenAI's GPT, running efficiently on Railway's infrastructure."
    
    async def analyze_message_tone(self, messages: list) -> dict:
        """Analyze the tone of messages (mock implementation)"""
        # Mock sentiment analysis
        import random
        
        # Generate mock percentages that add up to 100
        positive = random.randint(30, 60)
        negative = random.randint(5, 20)
        neutral = 100 - positive - negative
        
        return {
            "positive": positive,
            "neutral": neutral,
            "negative": negative
        }

async def setup(bot):
    cog = Intelligence(bot)
    await bot.add_cog(cog)
    
    # Sync commands to all guilds
    for guild in bot.guilds:
        try:
            # Copy global commands to guild
            bot.tree.copy_global_to(guild=guild)
            
            # Add cog commands to guild
            for command in cog.get_app_commands():
                if command not in bot.tree.get_commands(guild=guild):
                    bot.tree.add_command(command, guild=guild)
            
            # Sync to guild
            await bot.tree.sync(guild=guild)
            print(f"✅ Synced Intelligence commands to {guild.name}")
        except Exception as e:
            print(f"❌ Failed to sync Intelligence commands to {guild.name}: {e}")
    
    print(f"🤖 Successfully loaded Intelligence cog with {len(cog.get_app_commands())} commands")

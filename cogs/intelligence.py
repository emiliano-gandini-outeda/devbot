import discord
from discord.ext import commands
from discord import app_commands
from utils.helpers import EmbedBuilder
import random
from datetime import datetime

class Intelligence(commands.Cog):
    """AI-powered features"""
    
    def __init__(self, bot):
        self.bot = bot
    
    @app_commands.command(name="summarize", description="Summarize recent messages")
    @app_commands.describe(
        count="Number of messages to summarize (default: 20, max: 50)",
        user="Only summarize messages from this user"
    )
    async def summarize(self, interaction: discord.Interaction, count: int = 20, user: discord.Member = None):
        await interaction.response.defer()
        
        try:
            # Validate count
            if count > 50:
                count = 50
            elif count < 1:
                count = 20
            
            # Get messages
            messages = []
            async for message in interaction.channel.history(limit=count):
                if not message.author.bot and (user is None or message.author == user):
                    messages.append(message.content)
            
            if not messages:
                embed = EmbedBuilder.info("No Messages", "No messages found to summarize")
                await interaction.followup.send(embed=embed)
                return
            
            # Mock AI summarization (in a real implementation, this would use OpenAI or another AI service)
            summary = self._mock_summarize(messages)
            
            embed = discord.Embed(
                title="📝 Message Summary",
                description=summary,
                color=0x5865F2
            )
            
            embed.add_field(
                name="Details",
                value=f"Summarized {len(messages)} messages{f' from {user.mention}' if user else ''}",
                inline=False
            )
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to summarize messages: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="translate", description="Translate text to another language")
    @app_commands.describe(
        text="Text to translate",
        target_language="Language to translate to"
    )
    async def translate(self, interaction: discord.Interaction, text: str, target_language: str):
        await interaction.response.defer()
        
        try:
            # Mock translation (in a real implementation, this would use a translation API)
            translated_text = self._mock_translate(text, target_language)
            
            embed = discord.Embed(
                title=f"🌐 Translation to {target_language.title()}",
                color=0x5865F2
            )
            
            embed.add_field(name="Original Text", value=text, inline=False)
            embed.add_field(name="Translated Text", value=translated_text, inline=False)
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to translate text: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="ask-ai", description="Ask the AI assistant a question")
    @app_commands.describe(question="Question to ask the AI")
    async def ask_ai(self, interaction: discord.Interaction, question: str):
        await interaction.response.defer()
        
        try:
            # Mock AI response (in a real implementation, this would use OpenAI or another AI service)
            answer = self._mock_ai_answer(question)
            
            embed = discord.Embed(
                title="🤖 AI Assistant",
                color=0x5865F2
            )
            
            embed.add_field(name="Question", value=question, inline=False)
            embed.add_field(name="Answer", value=answer, inline=False)
            
            embed.set_footer(text="Powered by Railway AI")
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to get AI response: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="analyze-tone", description="Analyze the tone of recent messages")
    @app_commands.describe(count="Number of messages to analyze (default: 20, max: 50)")
    async def analyze_tone(self, interaction: discord.Interaction, count: int = 20):
        await interaction.response.defer()
        
        try:
            # Validate count
            if count > 50:
                count = 50
            elif count < 1:
                count = 20
            
            # Get messages
            messages = []
            async for message in interaction.channel.history(limit=count):
                if not message.author.bot:
                    messages.append(message.content)
            
            if not messages:
                embed = EmbedBuilder.info("No Messages", "No messages found to analyze")
                await interaction.followup.send(embed=embed)
                return
            
            # Mock tone analysis (in a real implementation, this would use an AI service)
            analysis = self._mock_tone_analysis(messages)
            
            embed = discord.Embed(
                title="🎭 Tone Analysis",
                description=f"Analysis of {len(messages)} recent messages",
                color=0x5865F2
            )
            
            embed.add_field(name="Positive", value=f"{analysis['positive']}%", inline=True)
            embed.add_field(name="Neutral", value=f"{analysis['neutral']}%", inline=True)
            embed.add_field(name="Negative", value=f"{analysis['negative']}%", inline=True)
            
            embed.add_field(
                name="Summary",
                value=analysis['summary'],
                inline=False
            )
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            embed = EmbedBuilder.error("Error", f"Failed to analyze tone: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    def _mock_summarize(self, messages):
        """Mock implementation of message summarization"""
        if not messages:
            return "No messages to summarize."
        
        total_words = sum(len(msg.split()) for msg in messages)
        
        summaries = [
            f"The conversation contains {len(messages)} messages with approximately {total_words} words. The discussion appears to be focused on various topics including project updates, questions, and general conversation.",
            f"In this conversation with {len(messages)} messages, users are discussing several topics. The main themes include technical questions, planning, and some casual conversation.",
            f"This conversation of {len(messages)} messages includes discussion about upcoming events, technical issues, and some problem-solving. Users are actively engaged in the topics.",
            f"The {len(messages)} messages in this conversation cover topics like project management, technical support, and general updates. There are questions being asked and answered throughout."
        ]
        
        return random.choice(summaries)
    
    def _mock_translate(self, text, target_language):
        """Mock implementation of text translation"""
        translations = {
            "spanish": f"{text} (translated to Spanish)",
            "french": f"{text} (translated to French)",
            "german": f"{text} (translated to German)",
            "japanese": f"{text} (translated to Japanese)",
            "chinese": f"{text} (translated to Chinese)",
            "russian": f"{text} (translated to Russian)",
            "italian": f"{text} (translated to Italian)"
        }
        
        target_language = target_language.lower()
        return translations.get(target_language, f"{text} (translated to {target_language.title()})")
    
    def _mock_ai_answer(self, question):
        """Mock implementation of AI question answering"""
        question = question.lower()
        
        if "who are you" in question:
            return "I am Railway Bot, an AI assistant designed to help with various tasks in your Discord server."
        
        if "what can you do" in question:
            return "I can help with various tasks like summarizing conversations, translating text, answering questions, and analyzing message tone. Use the /help command to see all available commands."
        
        if "how does" in question or "what is" in question:
            return f"Based on my knowledge, {question} involves several factors. While I don't have complete information, I can provide a general explanation. Please note that for more accurate information, you might want to consult specialized resources."
        
        if "when" in question:
            return f"Regarding {question}, the timing depends on various factors. I don't have real-time data, but I can suggest checking the official documentation or announcements for the most accurate information."
        
        # Generic responses
        generic_responses = [
            "That's an interesting question. While I don't have complete information, I can provide a general perspective based on my knowledge.",
            "I understand you're asking about this topic. While my knowledge is limited, I can offer some insights that might be helpful.",
            "This is a good question. I don't have all the details, but I can share what I know about this subject.",
            "I appreciate your curiosity. My information might not be comprehensive, but I can provide some thoughts on this topic."
        ]
        
        return random.choice(generic_responses)
    
    def _mock_tone_analysis(self, messages):
        """Mock implementation of tone analysis"""
        # Generate random percentages that add up to 100
        positive = random.randint(20, 60)
        remaining = 100 - positive
        neutral = random.randint(10, remaining - 10)
        negative = 100 - positive - neutral
        
        # Generate summary based on percentages
        if positive > 50:
            summary = "The conversation has a predominantly positive tone. Users are engaging constructively and the atmosphere appears collaborative."
        elif negative > 40:
            summary = "The conversation has a significant negative tone. There may be disagreements or frustrations being expressed."
        else:
            summary = "The conversation has a balanced tone with a mix of positive, neutral, and negative elements."
        
        return {
            "positive": positive,
            "neutral": neutral,
            "negative": negative,
            "summary": summary
        }

async def setup(bot):
    await bot.add_cog(Intelligence(bot))

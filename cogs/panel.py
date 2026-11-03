import time
import discord
from discord.ext import commands
from discord import app_commands
import db
import sqlite3
import os

OWNER_ID = 1456353767606849628
LOG_CHANNEL_ID = 1566537524803928184

def is_owner():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("❌ Owner only.", ephemeral=True)
            return False
        return True
    return app_commands.check(predicate)

# ==========================================
# PANEL VIEW (Keyless Dynamic)
# ==========================================
class PanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Get Script", style=discord.ButtonStyle.primary, emoji="📜", custom_id="panel:getscript", row=0)
    async def get_script(self, interaction: discord.Interaction, button: discord.ui.Button):
        row = await db.get_user_key(interaction.user.id)
        
        is_paid = False
        script_key = "FREE_USER"

        if row:
            if row["blacklisted"]:
                return await interaction.response.send_message("❌ You are blacklisted.", ephemeral=True)
            if row["auth_expire"] and int(time.time()) >= row["auth_expire"]:
                return await interaction.response.send_message("❌ Your subscription has expired.", ephemeral=True)
            
            is_paid = True
            script_key = row["key"]

        # Figure out which loader exists
        has_paid = os.path.exists("paid_loader.lua")
        has_free = os.path.exists("free_loader.lua")

        if is_paid and not has_paid:
            return await interaction.response.send_message("❌ The paid script has not been uploaded yet.", ephemeral=True)
        if not is_paid and not has_free:
            return await interaction.response.send_message("❌ The free script has not been uploaded yet.", ephemeral=True)

        loader_endpoint = "paid_loader" if is_paid else "free_loader"

        loadstring_payload = (
            f'script_key = "{script_key}"\n'
            f'local req = (syn and syn.request) or (http and http.request) or http_request or request\n'
            f'local res = req({{Url = "https://afg-discord-bots.onrender.com/{loader_endpoint}", Method = "GET", Headers = {{["X-Keyhub-Secret"] = "keyhub_9f3a8c7e2b1d4056_do_not_share"}}}})\n'
            f'loadstring(res.Body)()'
        )
        
        try:
            await interaction.user.send(f"**Your script:**\n```lua\n{loadstring_payload}\n```")
            await interaction.response.send_message("✅ Sent to your DMs.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ I can't DM you. Enable DMs.", ephemeral=True)

    @discord.ui.button(label="Get Role", style=discord.ButtonStyle.secondary, emoji="👤", custom_id="panel:getrole", row=0)
    async def get_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        role_id_str = await db.get_setting("buyer_role_id")
        if not role_id_str: 
            return await interaction.response.send_message("❌ Role not configured.", ephemeral=True)
        
        role = interaction.guild.get_role(int(role_id_str))
        if not role: 
            return await interaction.response.send_message("❌ Role not found.", ephemeral=True)

        row = await db.get_user_key(interaction.user.id)
        if not row or row["blacklisted"]:
            return await interaction.response.send_message("❌ You need to purchase access first!", ephemeral=True)

        try:
            await interaction.user.add_roles(role)
            await interaction.response.send_message(f"✅ Role {role.mention} assigned.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ I don't have permission to give that role.", ephemeral=True)

    @discord.ui.button(label="Reset HWID", style=discord.ButtonStyle.secondary, emoji="⚙️", custom_id="panel:resethwid", row=1)
    async def reset_hwid(self, interaction: discord.Interaction, button: discord.ui.Button):
        ok = await db.reset_hwid(interaction.user.id)
        if ok: 
            await interaction.response.send_message("✅ HWID reset.", ephemeral=True)
        else: 
            await interaction.response.send_message("❌ No subscription found to reset.", ephemeral=True)

    @discord.ui.button(label="Get Stats", style=discord.ButtonStyle.secondary, emoji="📊", custom_id="panel:getstats", row=1)
    async def get_stats(self, interaction: discord.Interaction, button: discord.ui.Button):
        row = await db.get_user_key(interaction.user.id)
        if not row: 
            return await interaction.response.send_message("❌ No subscription found. You are on the Free tier.", ephemeral=True)
        
        hwid_status = f"`{row['hwid'][:10]}...`" if row["hwid"] else "Not bound"
        expires = f"<t:{row['auth_expire']}:R>" if row["auth_expire"] else "Never"
        is_paused = await db.get_setting("system_paused", "0")
        status = "Paused" if is_paused == "1" else ("Blacklisted" if row["blacklisted"] else "Active")

        embed = discord.Embed(title="📊 Account Stats", color=discord.Color.blue())
        embed.add_field(name="Key", value=f"||`{row['key']}`||", inline=False)
        embed.add_field(name="Status", value=status)
        embed.add_field(name="Expires", value=expires)
        embed.add_field(name="HWID", value=hwid_status)
        await interaction.response.send_message(embed=embed, ephemeral=True)

# ==========================================
# COMMANDS
# ==========================================
class Panel(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_app_command_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.CheckFailure): return
        msg = f"Error: `{error}`"
        if interaction.response.is_done(): 
            await interaction.followup.send(msg, ephemeral=True)
        else: 
            await interaction.response.send_message(msg, ephemeral=True)

    @app_commands.command(name="setup_role", description="Pick the role the panel will give out")
    @is_owner()
    async def setup_role(self, interaction: discord.Interaction, role: discord.Role):
        await db.set_setting("buyer_role_id", str(role.id))
        embed = discord.Embed(title="✅ Role Configured", description=f"Role set to {role.mention}.", color=discord.Color.green())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="setpanel", description="Sends the control panel (upload one or both)")
    @is_owner()
    @app_commands.describe(paid_loader="(.lua) Optional: The paid script", free_loader="(.lua) Optional: The free script")
    async def setpanel(self, interaction: discord.Interaction, paid_loader: discord.Attachment = None, free_loader: discord.Attachment = None):
        if not paid_loader and not free_loader:
            return await interaction.response.send_message("❌ You must upload at least one .lua file.", ephemeral=True)

        if paid_loader:
            if not paid_loader.filename.endswith(".lua"): 
                return await interaction.response.send_message("❌ Paid file must be .lua", ephemeral=True)
            with open("paid_loader.lua", "wb") as f: 
                f.write(await paid_loader.read())
                
        if free_loader:
            if not free_loader.filename.endswith(".lua"): 
                return await interaction.response.send_message("❌ Free file must be .lua", ephemeral=True)
            with open("free_loader.lua", "wb") as f: 
                f.write(await free_loader.read())

        embed = discord.Embed(
            title="Afg Control Panel", 
            description=(
                "This control panel is for the project: **Afg Joiner**\n"
                "Click below to get the script or get your role"
            ), 
            color=discord.Color.from_rgb(240, 160, 0)
        )
        embed.set_footer(text=f"Sent by {interaction.user.display_name}")
        
        await interaction.response.send_message(embed=embed, view=PanelView())
        await interaction.followup.send(f"✅ Panel posted.", ephemeral=True)

    @app_commands.command(name="say", description="Make the bot say a message in the channel")
    @is_owner()
    async def say(self, interaction: discord.Interaction, text: str):
        await interaction.response.send_message("✅ Message sent.", ephemeral=True)
        await interaction.channel.send(text)

    @app_commands.command(name="pause", description="Pause all keys, kick active users, and freeze timers")
    @is_owner()
    async def pause(self, interaction: discord.Interaction):
        is_paused = await db.get_setting("system_paused", "0")
        if is_paused == "1":
            return await interaction.response.send_message("❌ System is already paused.", ephemeral=True)
            
        await db.set_setting("system_paused", "1")
        await db.set_setting("pause_time", str(int(time.time())))
        
        embed = discord.Embed(title="⏸️ SYSTEM PAUSED", description="All keys frozen.", color=discord.Color.red())
        await interaction.response.send_message(embed=embed)
        
        log_channel = self.bot.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            await log_channel.send("⚠️ **Logs are down.** All active users kicked, timers paused.")
        else:
            await interaction.channel.send("⚠️ **Logs are down.** All active users kicked, timers paused.")

    @app_commands.command(name="unpause", description="Unpause keys and compensate users")
    @is_owner()
    async def unpause(self, interaction: discord.Interaction):
        is_paused = await db.get_setting("system_paused", "0")
        if is_paused == "0":
            return await interaction.response.send_message("❌ System is already running.", ephemeral=True)
            
        pause_time_str = await db.get_setting("pause_time", str(int(time.time())))
        down_duration = int(time.time()) - int(pause_time_str)
        await db.set_setting("system_paused", "0")
        
        conn = sqlite3.connect(db.DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE keys SET auth_expire = auth_expire + ? WHERE auth_expire IS NOT NULL AND blacklisted = 0", (down_duration,))
        conn.commit()
        conn.close()
        
        m, s = divmod(down_duration, 60)
        h, m = divmod(m, 60)
        duration_str = f"{h}h {m}m {s}s"
        
        embed = discord.Embed(title="▶️ SYSTEM RESUMED", description=f"Compensated `{duration_str}`.", color=discord.Color.green())
        await interaction.response.send_message(embed=embed)
        
        log_channel = self.bot.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            await log_channel.send(f"✅ **Logs are online.** Timers resumed, added `{duration_str}`.")
        else:
            await interaction.channel.send(f"✅ **Logs are online.** Timers resumed, added `{duration_str}`.")

    @app_commands.command(name="whitelist", description="Gives a user access to the paid tier")
    @is_owner()
    async def whitelist(self, interaction: discord.Interaction, member: discord.Member, days: int = 0):
        await interaction.response.defer(ephemeral=True)
        key_days = days if days > 0 else None
        
        existing = await db.get_user_key(member.id)
        if existing:
            return await interaction.followup.send(f"❌ {member.mention} is already whitelisted.", ephemeral=True)
            
        await db.create_key(member.id, key_days)
        
        try:
            await member.send(f"🔑 You've been whitelisted for **Afg Joiner**!\nClick **Get Script** in the server to start playing.")
            await interaction.followup.send(f"✅ Whitelisted {member.mention}.", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send(f"✅ Whitelisted {member.mention}. (DM failed).", ephemeral=True)

    @app_commands.command(name="unwhitelist", description="Removes a user's access")
    @is_owner()
    async def unwhitelist(self, interaction: discord.Interaction, member: discord.Member):
        n = await db.delete_user_keys(member.id)
        if n > 0: await interaction.response.send_message(f"✅ Unwhitelisted {member.mention}.", ephemeral=True)
        else: await interaction.response.send_message("❌ User not found.", ephemeral=True)

    @app_commands.command(name="blacklist", description="Blacklists the user")
    @is_owner()
    async def blacklist(self, interaction: discord.Interaction, member: discord.Member):
        n = await db.blacklist_user(member.id)
        if n > 0: await interaction.response.send_message(f"✅ Blacklisted {member.mention}.", ephemeral=True)
        else: await interaction.response.send_message("❌ User not found.", ephemeral=True)

    @app_commands.command(name="compensate", description="Adds days to everyone")
    @is_owner()
    async def compensate(self, interaction: discord.Interaction, days: int):
        await interaction.response.defer(ephemeral=True)
        conn = sqlite3.connect(db.DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE keys SET auth_expire = auth_expire + ? WHERE auth_expire IS NOT NULL AND blacklisted = 0", (days * 86400,))
        conn.commit()
        n = c.rowcount
        conn.close()
        await interaction.followup.send(f"✅ Compensated {n} users by {days} days.", ephemeral=True)

    @app_commands.command(name="force-resethwid", description="Resets the HWID of a user")
    @is_owner()
    async def force_resethwid(self, interaction: discord.Interaction, member: discord.Member):
        ok = await db.reset_hwid(member.id)
        if ok: await interaction.response.send_message(f"✅ HWID forcefully reset for {member.mention}.", ephemeral=True)
        else: await interaction.response.send_message("❌ User not found.", ephemeral=True)

    @app_commands.command(name="stats", description="Shows panel statistics")
    @is_owner()
    async def stats(self, interaction: discord.Interaction):
        total, active, blacklisted = await db.get_all_stats()
        is_paused = await db.get_setting("system_paused", "0")
        embed = discord.Embed(title="📊 Project Stats", color=discord.Color.green())
        embed.add_field(name="Total Users", value=str(total))
        embed.add_field(name="Active Paid", value=str(active))
        embed.add_field(name="Blacklisted", value=str(blacklisted))
        embed.add_field(name="System Status", value="⏸️ Paused" if is_paused == "1" else "▶️ Running")
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    bot.add_view(PanelView())
    await bot.add_cog(Panel(bot))

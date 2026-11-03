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
# REDEEM MODAL (Paid Users Only)
# ==========================================
class RedeemModal(discord.ui.Modal, title="Redeem a key"):
    key_input = discord.ui.TextInput(
        label="Enter script key below:", 
        placeholder="XXXX-XXXX-XXXX-XXXX", 
        required=True, 
        max_length=50
    )

    async def on_submit(self, interaction: discord.Interaction):
        key = self.key_input.value.strip().upper()
        row = await db.get_key(key)
        
        if not row:
            await interaction.response.send_message("❌ Invalid key.", ephemeral=True)
            return
        if row["blacklisted"]:
            await interaction.response.send_message("❌ This key is blacklisted.", ephemeral=True)
            return
        if row["discord_id"] != interaction.user.id:
            await interaction.response.send_message("❌ This key belongs to someone else.", ephemeral=True)
            return

        role_id_str = await db.get_setting("buyer_role_id")
        if role_id_str:
            role = interaction.guild.get_role(int(role_id_str))
            if role:
                try:
                    await interaction.user.add_roles(role)
                except discord.Forbidden:
                    pass

        await interaction.response.send_message("✅ Key redeemed successfully! You can now click **Get Paid Script**.", ephemeral=True)

# ==========================================
# FREE PANEL (No Redeem Button)
# ==========================================
class FreePanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Get Script", style=discord.ButtonStyle.primary, emoji="📜", custom_id="panel:free_getscript", row=0)
    async def get_free(self, interaction: discord.Interaction, button: discord.ui.Button):
        free_paused = await db.get_setting("free_paused", "0")
        if free_paused == "1":
            return await interaction.response.send_message("⏸️ The **Free Script** is currently paused by the owner.", ephemeral=True)

        if not os.path.exists("free_loader.lua"):
            return await interaction.response.send_message("❌ The free script has not been uploaded yet.", ephemeral=True)

        loadstring_payload = (
            f'script_key = "FREE_USER"\n'
            f'local req = (syn and syn.request) or (http and http.request) or http_request or request\n'
            f'local res = req({{Url = "https://afg-discord-bots.onrender.com/free_loader", Method = "GET", Headers = {{["X-Keyhub-Secret"] = "keyhub_9f3a8c7e2b1d4056_do_not_share"}}}})\n'
            f'loadstring(res.Body)()'
        )
        
        try:
            await interaction.user.send(f"**Your Free Script:**\n```lua\n{loadstring_payload}\n```")
            await interaction.response.send_message("✅ Free script sent to your DMs.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ I can't DM you. Enable DMs.", ephemeral=True)

    @discord.ui.button(label="Get Role", style=discord.ButtonStyle.secondary, emoji="👤", custom_id="panel:free_getrole", row=0)
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

    @discord.ui.button(label="Reset HWID", style=discord.ButtonStyle.secondary, emoji="⚙️", custom_id="panel:free_resethwid", row=1)
    async def reset_hwid(self, interaction: discord.Interaction, button: discord.ui.Button):
        ok = await db.reset_hwid(interaction.user.id)
        if ok: await interaction.response.send_message("✅ HWID reset.", ephemeral=True)
        else: await interaction.response.send_message("❌ No paid key found to reset.", ephemeral=True)

    @discord.ui.button(label="Get Stats", style=discord.ButtonStyle.secondary, emoji="📊", custom_id="panel:free_getstats", row=1)
    async def get_stats(self, interaction: discord.Interaction, button: discord.ui.Button):
        row = await db.get_user_key(interaction.user.id)
        if not row: 
            return await interaction.response.send_message("❌ No key found. You are on the Free tier.", ephemeral=True)
        
        hwid_status = f"`{row['hwid'][:10]}...`" if row["hwid"] else "Not bound"
        expires = f"<t:{row['auth_expire']}:R>" if row["auth_expire"] else "Never"
        is_paused = await db.get_setting("paid_paused", "0")
        status = "Paused" if is_paused == "1" else ("Blacklisted" if row["blacklisted"] else "Active")

        embed = discord.Embed(title="📊 Account Stats", color=discord.Color.blue())
        embed.add_field(name="Key", value=f"||`{row['key']}`||", inline=False)
        embed.add_field(name="Status", value=status)
        embed.add_field(name="Expires", value=expires)
        embed.add_field(name="HWID", value=hwid_status)
        await interaction.response.send_message(embed=embed, ephemeral=True)

# ==========================================
# PAID PANEL (Includes Redeem Button)
# ==========================================
class PaidPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Redeem Key", style=discord.ButtonStyle.success, emoji="🔑", custom_id="panel:paid_redeem", row=0)
    async def redeem(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RedeemModal())

    @discord.ui.button(label="Get Script", style=discord.ButtonStyle.primary, emoji="📜", custom_id="panel:paid_getscript", row=0)
    async def get_paid(self, interaction: discord.Interaction, button: discord.ui.Button):
        paid_paused = await db.get_setting("paid_paused", "0")
        if paid_paused == "1":
            return await interaction.response.send_message("⏸️ The **Paid Script** is currently paused by the owner.", ephemeral=True)

        row = await db.get_user_key(interaction.user.id)
        
        if not row: 
            return await interaction.response.send_message("❌ You don't have a paid key. Click **Redeem Key** first.", ephemeral=True)
        if row["blacklisted"]: 
            return await interaction.response.send_message("❌ You are blacklisted.", ephemeral=True)
        if row["auth_expire"] and int(time.time()) >= row["auth_expire"]: 
            return await interaction.response.send_message("❌ Your key has expired.", ephemeral=True)

        if not os.path.exists("paid_loader.lua"):
            return await interaction.response.send_message("❌ The paid script has not been uploaded yet.", ephemeral=True)

        loadstring_payload = (
            f'script_key = "{row["key"]}"\n'
            f'local req = (syn and syn.request) or (http and http.request) or http_request or request\n'
            f'local res = req({{Url = "https://afg-discord-bots.onrender.com/paid_loader", Method = "GET", Headers = {{["X-Keyhub-Secret"] = "keyhub_9f3a8c7e2b1d4056_do_not_share"}}}})\n'
            f'loadstring(res.Body)()'
        )
        
        try:
            await interaction.user.send(f"**Your Paid Script:**\n```lua\n{loadstring_payload}\n```")
            await interaction.response.send_message("✅ Paid script sent to your DMs.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ I can't DM you. Enable DMs.", ephemeral=True)

    @discord.ui.button(label="Get Role", style=discord.ButtonStyle.secondary, emoji="👤", custom_id="panel:paid_getrole", row=0)
    async def get_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        role_id_str = await db.get_setting("buyer_role_id")
        if not role_id_str: 
            return await interaction.response.send_message("❌ Role not configured.", ephemeral=True)
        
        role = interaction.guild.get_role(int(role_id_str))
        if not role: 
            return await interaction.response.send_message("❌ Role not found.", ephemeral=True)

        row = await db.get_user_key(interaction.user.id)
        if not row or row["blacklisted"]:
            return await interaction.response.send_message("❌ You need a paid key first!", ephemeral=True)

        try:
            await interaction.user.add_roles(role)
            await interaction.response.send_message(f"✅ Role {role.mention} assigned.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ I don't have permission to give that role.", ephemeral=True)

    @discord.ui.button(label="Reset HWID", style=discord.ButtonStyle.secondary, emoji="⚙️", custom_id="panel:paid_resethwid", row=1)
    async def reset_hwid(self, interaction: discord.Interaction, button: discord.ui.Button):
        ok = await db.reset_hwid(interaction.user.id)
        if ok: await interaction.response.send_message("✅ HWID reset.", ephemeral=True)
        else: await interaction.response.send_message("❌ No paid key found to reset.", ephemeral=True)

    @discord.ui.button(label="Get Stats", style=discord.ButtonStyle.secondary, emoji="📊", custom_id="panel:paid_getstats", row=1)
    async def get_stats(self, interaction: discord.Interaction, button: discord.ui.Button):
        row = await db.get_user_key(interaction.user.id)
        if not row: 
            return await interaction.response.send_message("❌ No key found.", ephemeral=True)
        
        hwid_status = f"`{row['hwid'][:10]}...`" if row["hwid"] else "Not bound"
        expires = f"<t:{row['auth_expire']}:R>" if row["auth_expire"] else "Never"
        is_paused = await db.get_setting("paid_paused", "0")
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

        # Post Free Panel
        if free_loader:
            embed_free = discord.Embed(
                title="Afg Control Panel", 
                description=(
                    "This control panel is for the project: **Afg Joiner**\n"
                    "Click below to get the script or get your role"
                ), 
                color=discord.Color.from_rgb(240, 160, 0)
            )
            embed_free.set_footer(text=f"Sent by {interaction.user.display_name}")
            await interaction.channel.send(embed=embed_free, view=FreePanelView())

        # Post Paid Panel
        if paid_loader:
            embed_paid = discord.Embed(
                title="Afg Control Panel", 
                description=(
                    "This control panel is for the project: **Afg Joiner**\n"
                    "If you're a buyer, click on the buttons below to redeem your key, get the script or get your role"
                ), 
                color=discord.Color.from_rgb(240, 160, 0)
            )
            embed_paid.set_footer(text=f"Sent by {interaction.user.display_name}")
            await interaction.channel.send(embed=embed_paid, view=PaidPanelView())

        await interaction.response.send_message("✅ Panels posted.", ephemeral=True)

    @app_commands.command(name="say", description="Make the bot say a message in the channel")
    @is_owner()
    async def say(self, interaction: discord.Interaction, text: str):
        await interaction.response.send_message("✅ Message sent.", ephemeral=True)
        await interaction.channel.send(text)

    # --- PAUSE / UNPAUSE PAID ---
    @app_commands.command(name="pause_paid", description="Pause the Paid script only")
    @is_owner()
    async def pause_paid(self, interaction: discord.Interaction):
        await db.set_setting("paid_paused", "1")
        await db.set_setting("paid_pause_time", str(int(time.time())))
        
        embed = discord.Embed(title="⏸️ PAID SCRIPT PAUSED", description="Free script remains active.", color=discord.Color.red())
        await interaction.response.send_message(embed=embed)
        
        log_channel = self.bot.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            await log_channel.send("⚠️ **Paid logs are down.** Timers paused.")

    @app_commands.command(name="unpause_paid", description="Unpause the Paid script and compensate time")
    @is_owner()
    async def unpause_paid(self, interaction: discord.Interaction):
        pause_time_str = await db.get_setting("paid_pause_time", str(int(time.time())))
        down_duration = int(time.time()) - int(pause_time_str)
        await db.set_setting("paid_paused", "0")
        
        conn = sqlite3.connect(db.DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE keys SET auth_expire = auth_expire + ? WHERE auth_expire IS NOT NULL AND blacklisted = 0", (down_duration,))
        conn.commit()
        conn.close()
        
        embed = discord.Embed(title="▶️ PAID SCRIPT RESUMED", description=f"Added `{down_duration}` seconds to paid users.", color=discord.Color.green())
        await interaction.response.send_message(embed=embed)
        
        log_channel = self.bot.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            await log_channel.send("✅ **Paid logs are online.**")

    # --- PAUSE / UNPAUSE FREE ---
    @app_commands.command(name="pause_free", description="Pause the Free script only")
    @is_owner()
    async def pause_free(self, interaction: discord.Interaction):
        await db.set_setting("free_paused", "1")
        
        embed = discord.Embed(title="⏸️ FREE SCRIPT PAUSED", description="Paid script remains active.", color=discord.Color.red())
        await interaction.response.send_message(embed=embed)
        
        log_channel = self.bot.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            await log_channel.send("⚠️ **Free logs are down.**")

    @app_commands.command(name="unpause_free", description="Unpause the Free script")
    @is_owner()
    async def unpause_free(self, interaction: discord.Interaction):
        await db.set_setting("free_paused", "0")
        
        embed = discord.Embed(title="▶️ FREE SCRIPT RESUMED", description="Free script is active again.", color=discord.Color.green())
        await interaction.response.send_message(embed=embed)
        
        log_channel = self.bot.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            await log_channel.send("✅ **Free logs are online.**")

    # --- PAUSE / UNPAUSE ALL ---
    @app_commands.command(name="pause_all", description="Pause both Paid and Free scripts")
    @is_owner()
    async def pause_all(self, interaction: discord.Interaction):
        await db.set_setting("system_paused", "1")
        await db.set_setting("paid_paused", "1")
        await db.set_setting("free_paused", "1")
        await db.set_setting("system_pause_time", str(int(time.time())))
        
        embed = discord.Embed(title="⏸️ ALL SCRIPTS PAUSED", description="Everything is offline.", color=discord.Color.red())
        await interaction.response.send_message(embed=embed)
        
        log_channel = self.bot.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            await log_channel.send("⚠️ **ALL logs are down.** Everything paused.")

    @app_commands.command(name="unpause_all", description="Unpause everything and compensate")
    @is_owner()
    async def unpause_all(self, interaction: discord.Interaction):
        pause_time_str = await db.get_setting("system_pause_time", str(int(time.time())))
        down_duration = int(time.time()) - int(pause_time_str)
        
        await db.set_setting("system_paused", "0")
        await db.set_setting("paid_paused", "0")
        await db.set_setting("free_paused", "0")
        
        conn = sqlite3.connect(db.DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE keys SET auth_expire = auth_expire + ? WHERE auth_expire IS NOT NULL AND blacklisted = 0", (down_duration,))
        conn.commit()
        conn.close()
        
        embed = discord.Embed(title="▶️ ALL SCRIPTS RESUMED", description=f"Added `{down_duration}` seconds to all paid users.", color=discord.Color.green())
        await interaction.response.send_message(embed=embed)
        
        log_channel = self.bot.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            await log_channel.send("✅ **ALL logs are online.** Everything resumed.")

    # --- WHITELIST ---
    @app_commands.command(name="whitelist", description="Gives a user a Paid Key")
    @is_owner()
    async def whitelist(self, interaction: discord.Interaction, member: discord.Member, days: int = 0):
        await interaction.response.defer(ephemeral=True)
        key_days = days if days > 0 else None
        
        existing = await db.get_user_key(member.id)
        if existing:
            return await interaction.followup.send(f"❌ {member.mention} already has a key.", ephemeral=True)
            
        key = await db.create_key(member.id, key_days)
        
        try:
            await member.send(f"🔑 You've been whitelisted.\n**Key:** `{key}`\nClick **Redeem Key** in the server.")
            await interaction.followup.send(f"✅ Gave {member.mention} a key: `{key}` (DM sent).", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send(f"✅ Gave {member.mention} a key: `{key}` (DM failed).", ephemeral=True)

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
        paid_paused = await db.get_setting("paid_paused", "0")
        free_paused = await db.get_setting("free_paused", "0")
        
        embed = discord.Embed(title="📊 Project Stats", color=discord.Color.green())
        embed.add_field(name="Total Paid Users", value=str(total))
        embed.add_field(name="Active", value=str(active))
        embed.add_field(name="Blacklisted", value=str(blacklisted))
        embed.add_field(name="Paid Status", value="⏸️ Paused" if paid_paused == "1" else "▶️ Running")
        embed.add_field(name="Free Status", value="⏸️ Paused" if free_paused == "1" else "▶️ Running")
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    bot.add_view(PanelView())
    bot.add_view(FreePanelView())
    bot.add_view(PaidPanelView())
    await bot.add_cog(Panel(bot))

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

class PaidPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Redeem Key", style=discord.ButtonStyle.success, emoji="🔑", custom_id="panel:paid_redeem", row=0)
    async def redeem(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RedeemModal())

    @discord.ui.button(label="Get Script", style=discord.ButtonStyle.primary, emoji="📜", custom_id="panel:paid_getscript", row=0)
    async def get_paid(self, interaction: discord.Interaction, button: discord.ui.Button):
        is_paused = await db.get_setting("system_paused", "0")
        if is_paused == "1":
            return await interaction.response.send_message("⏸️ The **Script** is currently paused by the owner.", ephemeral=True)

        row = await db.get_user_key(interaction.user.id)
        
        if not row: 
            return await interaction.response.send_message("❌ You don't have a key. Click **Redeem Key** first.", ephemeral=True)
        if row["blacklisted"]: 
            return await interaction.response.send_message("❌ You are blacklisted.", ephemeral=True)
        if row["auth_expire"] and int(time.time()) >= row["auth_expire"]: 
            return await interaction.response.send_message("❌ Your key has expired.", ephemeral=True)

        if not os.path.exists("paid_loader.lua"):
            return await interaction.response.send_message("❌ The script has not been uploaded yet.", ephemeral=True)

        # THIS IS THE EXACT 2 LINES YOU WANTED
        script_text = f'script_key = "{row["key"]}"\nloadstring(game:HttpGet("https://afg-bot.onrender.com/paid_loader?secret=keyhub_9f3a8c7e2b1d4056_do_not_share"))()'
        
        try:
            await interaction.user.send(f"```lua\n{script_text}\n```")
            await interaction.response.send_message("✅ Script sent to your DMs.", ephemeral=True)
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
            return await interaction.response.send_message("❌ You need a key first!", ephemeral=True)

        try:
            await interaction.user.add_roles(role)
            await interaction.response.send_message(f"✅ Role {role.mention} assigned.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ I don't have permission to give that role.", ephemeral=True)

    @discord.ui.button(label="Reset HWID", style=discord.ButtonStyle.secondary, emoji="⚙️", custom_id="panel:paid_resethwid", row=1)
    async def reset_hwid(self, interaction: discord.Interaction, button: discord.ui.Button):
        ok = await db.reset_hwid(interaction.user.id)
        if ok: await interaction.response.send_message("✅ HWID reset.", ephemeral=True)
        else: await interaction.response.send_message("❌ No key found to reset.", ephemeral=True)

    @discord.ui.button(label="Get Stats", style=discord.ButtonStyle.secondary, emoji="📊", custom_id="panel:paid_getstats", row=1)
    async def get_stats(self, interaction: discord.Interaction, button: discord.ui.Button):
        row = await db.get_user_key(interaction.user.id)
        if not row: 
            return await interaction.response.send_message("❌ No key found.", ephemeral=True)
        
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

    @app_commands.command(name="setpanel", description="Sends the control panel")
    @is_owner()
    @app_commands.describe(paid_loader="The script (.lua)")
    async def setpanel(self, interaction: discord.Interaction, paid_loader: discord.Attachment):
        if not paid_loader.filename.endswith(".lua"): 
            return await interaction.response.send_message("❌ File must be .lua", ephemeral=True)
            
        with open("paid_loader.lua", "wb") as f: 
            f.write(await paid_loader.read())

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

        await interaction.response.send_message("✅ Panel posted.", ephemeral=True)

    @app_commands.command(name="say", description="Make the bot say a message in the channel")
    @is_owner()
    async def say(self, interaction: discord.Interaction, text: str):
        await interaction.response.send_message("✅ Message sent.", ephemeral=True)
        await interaction.channel.send(text)

    @app_commands.command(name="pause", description="Pause all keys and kick active users")
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
        if log_channel: await log_channel.send("⚠️ **Logs are down.** Active users kicked, timers paused.")

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
        if log_channel: await log_channel.send(f"✅ **Logs are online.** Timers resumed, added `{duration_str}`.")

    @app_commands.command(name="whitelist", description="Gives a user a Paid Key")
    @is_owner()
    async def whitelist(self, interaction: discord.Interaction, member: discord.Member, days: int = 0):
        await interaction.response.defer(ephemeral=True)
        key_days = days if days > 0 else None
        
        existing = await db.get_user_key(member.id)
        if existing: return await interaction.followup.send(f"❌ {member.mention} already has a key.", ephemeral=True)
            
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
        is_paused = await db.get_setting("system_paused", "0")
        embed = discord.Embed(title="📊 Project Stats", color=discord.Color.green())
        embed.add_field(name="Total Users", value=str(total))
        embed.add_field(name="Active", value=str(active))
        embed.add_field(name="Blacklisted", value=str(blacklisted))
        embed.add_field(name="System Status", value="⏸️ Paused" if is_paused == "1" else "▶️ Running")
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    bot.add_view(PaidPanelView())
    await bot.add_cog(Panel(bot))

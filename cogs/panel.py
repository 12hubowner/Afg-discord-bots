import time
import discord
from discord.ext import commands
from discord import app_commands
import db
import sqlite3

OWNER_ID = 1456353767606849628

def is_owner():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("❌ Owner only.", ephemeral=True)
            return False
        return True
    return app_commands.check(predicate)

# ==========================================
# MODALS
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

        # Auto assign buyer role if configured
        role_id_str = await db.get_setting("buyer_role_id")
        if role_id_str:
            role = interaction.guild.get_role(int(role_id_str))
            if role:
                try:
                    await interaction.user.add_roles(role)
                except discord.Forbidden:
                    pass

        await interaction.response.send_message("✅ Key redeemed successfully! Click **Get Script**.", ephemeral=True)

# ==========================================
# PANEL VIEW
# ==========================================
class PanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Redeem Key", style=discord.ButtonStyle.success, emoji="🔑", custom_id="panel:redeem", row=0)
    async def redeem(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RedeemModal())

    @discord.ui.button(label="Get Script", style=discord.ButtonStyle.primary, emoji="📜", custom_id="panel:getscript", row=0)
    async def get_script(self, interaction: discord.Interaction, button: discord.ui.Button):
        row = await db.get_user_key(interaction.user.id)
        if not row: 
            return await interaction.response.send_message("❌ You don't have a key.", ephemeral=True)
        if row["blacklisted"]: 
            return await interaction.response.send_message("❌ You are blacklisted.", ephemeral=True)
        if row["auth_expire"] and int(time.time()) >= row["auth_expire"]: 
            return await interaction.response.send_message("❌ Your key has expired.", ephemeral=True)

        loadstring_payload = (
            f'script_key = "{row["key"]}"\n'
            f'local req = (syn and syn.request) or (http and http.request) or http_request or request\n'
            f'local res = req({{Url = "https://afg-discord-bots.onrender.com/loader", Method = "GET", Headers = {{["X-Keyhub-Secret"] = "keyhub_9f3a8c7e2b1d4056_do_not_share"}}}})\n'
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
            return await interaction.response.send_message("❌ Role not found in server.", ephemeral=True)

        row = await db.get_user_key(interaction.user.id)
        if not row or row["blacklisted"]:
            return await interaction.response.send_message("❌ Not whitelisted!", ephemeral=True)

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
            await interaction.response.send_message("❌ No key found to reset.", ephemeral=True)

    @discord.ui.button(label="Get Stats", style=discord.ButtonStyle.secondary, emoji="📊", custom_id="panel:getstats", row=1)
    async def get_stats(self, interaction: discord.Interaction, button: discord.ui.Button):
        row = await db.get_user_key(interaction.user.id)
        if not row: 
            return await interaction.response.send_message("❌ No key found.", ephemeral=True)
        
        hwid_status = f"`{row['hwid'][:10]}...`" if row["hwid"] else "Not bound"
        expires = f"<t:{row['auth_expire']}:R>" if row["auth_expire"] else "Never"
        status = "Paused" if await db.get_setting("system_paused", "0") == "1" else ("Blacklisted" if row["blacklisted"] else "Active")

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
        if isinstance(error, app_commands.CheckFailure): 
            return
        msg = f"Error: `{error}`"
        if interaction.response.is_done(): 
            await interaction.followup.send(msg, ephemeral=True)
        else: 
            await interaction.response.send_message(msg, ephemeral=True)

    # --- PANEL SETUP ---
    @app_commands.command(name="setpanel", description="Sends the control panel message in this channel")
    @is_owner()
    async def setpanel(self, interaction: discord.Interaction, loader_script: discord.Attachment, manager_role: discord.Role):
        if not loader_script.filename.endswith(".lua"): 
            return await interaction.response.send_message("❌ Must be .lua", ephemeral=True)
        
        raw = await loader_script.read()
        with open("loader.lua", "wb") as f: 
            f.write(raw)

        await db.set_setting("buyer_role_id", str(manager_role.id))

        embed = discord.Embed(
            title="GreenDuels Control Panel", 
            description="This control panel is for the project: **GreenDuels**\nIf you're a buyer, click on the buttons below to redeem your key, get the script or get your role", 
            color=discord.Color.from_rgb(240, 160, 0)
        )
        embed.set_footer(text=f"Sent by {interaction.user.display_name}")
        
        await interaction.response.send_message(embed=embed, view=PanelView())
        await interaction.followup.send(f"✅ Panel posted.", ephemeral=True)

    # --- SAY COMMAND ---
    @app_commands.command(name="say", description="Make the bot say a message in the channel")
    @is_owner()
    async def say(self, interaction: discord.Interaction, text: str):
        await interaction.response.send_message("✅ Message sent.", ephemeral=True)
        await interaction.channel.send(text)

    # --- PAUSE / RESUME TIMERS ---
    @app_commands.command(name="togglepanel", description="Pause or resume all keys (kicks users and freezes timers)")
    @is_owner()
    async def togglepanel(self, interaction: discord.Interaction):
        is_paused = await db.get_setting("system_paused", "0")
        
        if is_paused == "0":
            await db.set_setting("system_paused", "1")
            await db.set_setting("pause_time", str(int(time.time())))
            
            embed = discord.Embed(
                title="⏸️ SYSTEM PAUSED", 
                description="All keys have been frozen. Active users will be kicked.", 
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed)
            await interaction.channel.send("⚠️ **Logs are down.** All active users kicked, timers paused.")
        else:
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
            
            embed = discord.Embed(
                title="▶️ SYSTEM RESUMED", 
                description=f"Keys are active. All users received `{duration_str}` added to their timer.", 
                color=discord.Color.green()
            )
            await interaction.response.send_message(embed=embed)
            await interaction.channel.send(f"✅ **Logs are online.** Timers resumed, added `{duration_str}`.")

    # --- WHITELIST ---
    @app_commands.command(name="whitelist", description="Whitelists a user")
    @is_owner()
    async def whitelist(self, interaction: discord.Interaction, member: discord.Member, days: int = 0):
        await interaction.response.defer(ephemeral=True)
        key_days = days if days > 0 else None
        key = await db.create_key(member.id, key_days)
        try:
            await member.send(f"🔑 You've been whitelisted.\n**Key:** `{key}`\nClick **Redeem Key** in the server.")
            await interaction.followup.send(f"✅ Whitelisted {member.mention}. Key: `{key}` (DM sent).", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send(f"✅ Whitelisted {member.mention}. Key: `{key}` (DM failed).", ephemeral=True)

    # --- UNWHITELIST ---
    @app_commands.command(name="unwhitelist", description="Unwhitelists the user")
    @is_owner()
    async def unwhitelist(self, interaction: discord.Interaction, member: discord.Member):
        n = await db.delete_user_keys(member.id)
        if n > 0: 
            await interaction.response.send_message(f"✅ Unwhitelisted {member.mention}.", ephemeral=True)
        else: 
            await interaction.response.send_message("❌ No key found.", ephemeral=True)

    # --- BLACKLIST ---
    @app_commands.command(name="blacklist", description="Blacklists the user")
    @is_owner()
    async def blacklist(self, interaction: discord.Interaction, member: discord.Member):
        n = await db.blacklist_user(member.id)
        if n > 0: 
            await interaction.response.send_message(f"✅ Blacklisted {member.mention}.", ephemeral=True)
        else: 
            await interaction.response.send_message("❌ No key found.", ephemeral=True)

    # --- MASS GENERATE ---
    @app_commands.command(name="mass-generate", description="Generates multiple keys")
    @is_owner()
    async def mass_generate(self, interaction: discord.Interaction, amount: int, days: int = 0):
        await interaction.response.defer(ephemeral=True)
        keys = [await db.create_key(OWNER_ID, days if days > 0 else None, "Mass Gen") for _ in range(amount)]
        text = "\n".join([f"`{k}`" for k in keys[:20]])
        await interaction.followup.send(f"**Generated {amount} keys:**\n{text}", ephemeral=True)

    # --- COMPENSATE ---
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

    # --- FORCE RESET HWID ---
    @app_commands.command(name="force-resethwid", description="Resets the HWID of a user")
    @is_owner()
    async def force_resethwid(self, interaction: discord.Interaction, member: discord.Member):
        ok = await db.reset_hwid(member.id)
        if ok: 
            await interaction.response.send_message(f"✅ HWID forcefully reset for {member.mention}.", ephemeral=True)
        else: 
            await interaction.response.send_message("❌ No key found.", ephemeral=True)

    # --- STATS ---
    @app_commands.command(name="stats", description="Shows panel statistics")
    @is_owner()
    async def stats(self, interaction: discord.Interaction):
        total, active, blacklisted = await db.get_all_stats()
        is_paused = await db.get_setting("system_paused", "0")
        embed = discord.Embed(title="📊 Project Stats", color=discord.Color.green())
        embed.add_field(name="Total Keys", value=str(total))
        embed.add_field(name="Active", value=str(active))
        embed.add_field(name="Blacklisted", value=str(blacklisted))
        embed.add_field(name="System Status", value="⏸️ Paused" if is_paused == "1" else "▶️ Running")
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    bot.add_view(PanelView())
    await bot.add_cog(Panel(bot))

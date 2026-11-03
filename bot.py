import os
import json
import base64
import io
import time
import re
import urllib.request
from datetime import datetime
import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, db

# ---------- PATHS ----------
HOME = os.path.expanduser("~")
ENV_PATH = os.path.join(HOME, ".env")
KEY_PATH = os.path.join(HOME, "serviceAccountKey.json")
SEEN_PATH = os.path.join(HOME, "seen_keys.json")
REPORTS_PATH = os.path.join(HOME, "reports.json")

load_dotenv(ENV_PATH)
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

if not os.path.exists(KEY_PATH):
    raise SystemExit(f"\n❌ Missing Firebase key: {KEY_PATH}\n")
cred = credentials.Certificate(KEY_PATH)
firebase_admin.initialize_app(cred, {
    "databaseURL": "https://shop-e4da3-default-rtdb.firebaseio.com"
})

# ---------- ROLES ----------
BLACKLIST_ROLE_NAME = "Blacklisted"
RESELLER_ROLE_NAME  = "Reseller"
VERIFIED_ROLE_NAME  = "Verified Seller"

# ---------- SEEN KEYS ----------
def load_seen():
    try:
        with open(SEEN_PATH, "r") as f:
            d = json.load(f)
        return set(d.get("products", [])), set(d.get("messages", []))
    except FileNotFoundError:
        return set(), set()

def save_seen(p, m):
    with open(SEEN_PATH, "w") as f:
        json.dump({"products": list(p), "messages": list(m)}, f)

seen_products, seen_messages = load_seen()

# ---------- REPORTS ----------
def load_reports():
    try:
        with open(REPORTS_PATH, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_reports(r):
    with open(REPORTS_PATH, "w") as f:
        json.dump(r, f, indent=2)

# ---------- CHANNELS ----------
CHANNELS = {
    "Men":      "👔-men",
    "Women":    "👗-women",
    "Kids":     "🧒-kids",
    "Offers":   "💰-offers",
    "Asks":     "💬-messages",
    "Resell":   "🏪-resell",
    "ModLog":   "🛡️-mod-log",
    "SellPanel":"🛒-sell-here",
}

REPORT_THRESHOLD = 3

# ---------- DISCORD ----------
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.tree.sync()
        print("🔄 Slash commands synced")

bot = MyBot()

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    for guild in bot.guilds:
        await ensure_channels(guild)
        await ensure_blacklist_role(guild)
        await ensure_reseller_role(guild)
        await ensure_verified_role(guild)
        await ensure_sell_panel(guild)
    watch_products.start()
    watch_messages.start()

async def ensure_channels(guild):
    existing = {c.name for c in guild.text_channels}
    for name in CHANNELS.values():
        if name not in existing:
            try:
                await guild.create_text_channel(name)
                print(f"📁 Created: #{name}")
            except Exception as e:
                print(f"❌ Could not create #{name}: {e}")

async def ensure_blacklist_role(guild):
    role = discord.utils.get(guild.roles, name=BLACKLIST_ROLE_NAME)
    if role: return role
    try:
        role = await guild.create_role(name=BLACKLIST_ROLE_NAME, colour=discord.Colour.dark_red(), reason="Afg Marketplace")
        for ch in guild.text_channels:
            if ch.name in CHANNELS.values():
                try: await ch.set_permissions(role, send_messages=False)
                except Exception: pass
        print(f"🛡️ Created role: {BLACKLIST_ROLE_NAME}")
        return role
    except Exception as e:
        print(f"❌ Could not create role: {e}")
        return None

async def ensure_reseller_role(guild):
    role = discord.utils.get(guild.roles, name=RESELLER_ROLE_NAME)
    if role: return role
    try:
        role = await guild.create_role(name=RESELLER_ROLE_NAME, colour=discord.Colour.green(), reason="Afg Marketplace")
        print(f"🟢 Created role: {RESELLER_ROLE_NAME}")
        return role
    except Exception as e:
        print(f"❌ Could not create role: {e}")
        return None

async def ensure_verified_role(guild):
    role = discord.utils.get(guild.roles, name=VERIFIED_ROLE_NAME)
    if role: return role
    try:
        role = await guild.create_role(name=VERIFIED_ROLE_NAME, colour=discord.Colour.blue(), reason="Afg Marketplace")
        print(f"🔵 Created role: {VERIFIED_ROLE_NAME}")
        return role
    except Exception as e:
        print(f"❌ Could not create role: {e}")
        return None

async def ensure_sell_panel(guild):
    sell_ch = get_channel(guild, CHANNELS["SellPanel"])
    if not sell_ch: return
    async for msg in sell_ch.history(limit=20):
        if msg.author == bot.user and msg.embeds:
            if msg.embeds[0].title and "Sell an Item" in msg.embeds[0].title:
                return

    embed = discord.Embed(
        title="🛒 Sell an Item",
        description=(
            "Click the **Post Item** button below to list your own item.\n\n"
            "**What happens next:**\n"
            "• A private thread opens — only you and admins can see it\n"
            "• Fill out the form, then upload **1 picture** to the thread\n"
            "• Your listing goes live in **#🏪-resell**\n\n"
            "⚠️ **Rules:**\n"
            "• You need the **Reseller** role to sell\n"
            "• No scams or fake listings — 3 reports = auto-blacklist\n"
            "• Use `/sold` to mark your item as sold when it's gone\n"
        ),
        color=0x4FBF8B
    )
    embed.set_footer(text="Afg Marketplace · Sell an Item")
    view = SellPanelView()
    await sell_ch.send(embed=embed, view=view)
    print(f"🛒 Sell panel posted in #{CHANNELS['SellPanel']}")

def get_channel(guild, name):
    for ch in guild.text_channels:
        if ch.name == name: return ch
    return None

def image_from_data_url(data_url):
    if not data_url or not isinstance(data_url, str): return None
    if not data_url.startswith("data:image"): return None
    try:
        _, b64 = data_url.split(",", 1)
        return discord.File(io.BytesIO(base64.b64decode(b64)), filename="item.jpg")
    except Exception as e:
        print(f"⚠️ image decode failed: {e}")
        return None

def download_image_as_data_url(image_url, referer=None):
    if not image_url: return None
    if image_url.startswith("//"): image_url = "https:" + image_url
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0"}
        if referer: headers["Referer"] = referer
        req = urllib.request.Request(image_url, headers=headers)
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read()
            if 1000 < len(raw) < 8 * 1024 * 1024:
                b64 = base64.b64encode(raw).decode()
                mime = r.headers.get("Content-Type", "image/jpeg").split(";")[0]
                if not mime.startswith("image"): mime = "image/jpeg"
                return f"data:{mime};base64,{b64}"
    except Exception as e:
        print(f"⚠️ image download failed: {e}")
    return None

def detect_category(text):
    t = text.lower()
    if any(w in t for w in ["kid", "baby", "toddler", "child", "boy", "girl"]): return "Kids"
    if any(w in t for w in ["men", "male"]): return "Men"
    return "Women"

def apply_price_rule(price):
    if price > 0: return round(price + 5, 2), True
    return price, False

async def is_blacklisted(member: discord.Member) -> bool:
    return any(r.name == BLACKLIST_ROLE_NAME for r in member.roles)

async def has_reseller_or_admin(member: discord.Member) -> bool:
    if member.guild_permissions.administrator: return True
    return any(r.name == RESELLER_ROLE_NAME for r in member.roles)

async def is_verified(member: discord.Member) -> bool:
    return any(r.name == VERIFIED_ROLE_NAME for r in member.roles)

# ============================================================
#   SELL PANEL + PRIVATE THREAD SYSTEM
# ============================================================

class SellPanelView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)

    @discord.ui.button(label="Post Item", emoji="🛒", style=discord.ButtonStyle.success, custom_id="sell_panel_post")
    async def post_item(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await is_blacklisted(interaction.user):
            await interaction.response.send_message("⛔ You are blacklisted.", ephemeral=True); return
        if not await has_reseller_or_admin(interaction.user):
            await interaction.response.send_message(f"⛔ You need the **{RESELLER_ROLE_NAME}** role.", ephemeral=True); return

        thread_name = f"sell-{interaction.user.name.lower()}"
        existing = discord.utils.get(interaction.channel.threads, name=thread_name)
        if existing and not existing.archived:
            await interaction.response.send_message(f"⚠️ You already have an open listing thread: {existing.mention}", ephemeral=True); return

        try:
            thread = await interaction.channel.create_thread(
                name=thread_name, type=discord.ChannelType.private_thread,
                invitable=False, reason=f"New listing by {interaction.user}"
            )
        except Exception as e:
            await interaction.response.send_message(f"❌ Could not create thread: `{e}`", ephemeral=True); return

        await thread.add_user(interaction.user)
        embed = discord.Embed(
            title="📝 Post your item",
            description=(f"Hey {interaction.user.mention}, this is your private listing thread.\n\n"
                         "**Click the button below** to open the listing form.\n"
                         "**After you submit**, upload **1 picture** to this thread."),
            color=0x4FBF8B
        )
        embed.set_footer(text="Afg Marketplace · Private listing")
        await thread.send(embed=embed, view=ItemFormView(interaction.user.id))
        await interaction.response.send_message(f"✅ Private thread created: {thread.mention}", ephemeral=True)


class ItemFormView(discord.ui.View):
    def __init__(self, owner_id: int):
        super().__init__(timeout=None)
        self.owner_id = owner_id

    @discord.ui.button(label="Open Form", emoji="📝", style=discord.ButtonStyle.primary, custom_id="item_form_open")
    async def open_form(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner_id:
            if not await has_reseller_or_admin(interaction.user):
                await interaction.response.send_message("❌ This form belongs to another user.", ephemeral=True); return
        await interaction.response.send_modal(ItemFormModal())


class ItemFormModal(discord.ui.Modal, title="Post an Item"):
    def __init__(self):
        super().__init__()
        self.item_title = discord.ui.TextInput(label="Title", placeholder="Brand, model, color, and size", max_length=120, required=True)
        self.item_desc = discord.ui.TextInput(label="Description (Optional)", style=discord.TextStyle.paragraph, max_length=500, required=False)
        self.item_price = discord.ui.TextInput(label="Price (USD)", placeholder="e.g. 24.99", max_length=10, required=True)
        self.item_category = discord.ui.TextInput(label="Category (Men / Women / Kids)", placeholder="Men", max_length=20, required=True)
        self.item_cond_loc = discord.ui.TextInput(label="Condition & Location", placeholder="Used | New York", max_length=60, required=True)
        self.add_item(self.item_title); self.add_item(self.item_desc); self.add_item(self.item_price)
        self.add_item(self.item_category); self.add_item(self.item_cond_loc)

    async def on_submit(self, interaction: discord.Interaction):
        if await is_blacklisted(interaction.user):
            await interaction.response.send_message("⛔ You are blacklisted.", ephemeral=True); return
        try:
            price = float(self.item_price.value)
            if price <= 0: raise ValueError
        except ValueError:
            await interaction.response.send_message("❌ Price must be a number > 0.", ephemeral=True); return

        cat_input = self.item_category.value.strip().lower()
        if "men" in cat_input: cat = "Men"
        elif "kid" in cat_input or "child" in cat_input: cat = "Kids"
        else: cat = "Women"

        cond_loc_parts = self.item_cond_loc.value.split("|")
        cond_input = cond_loc_parts[0].strip().lower()
        location = cond_loc_parts[1].strip() if len(cond_loc_parts) > 1 else "—"

        if "new" in cond_input: condition = "New"
        elif "refurb" in cond_input: condition = "Refurbished"
        elif "broken" in cond_input or "damaged" in cond_input: condition = "Broken"
        else: condition = "Used"

        price, _ = apply_price_rule(price)
        product_id = int(time.time() * 1000)
        product = {
            "id": product_id, "name": self.item_title.value.strip(), "price": float(price), "cat": cat,
            "condition": condition, "desc": self.item_desc.value.strip() or f"Listed by {interaction.user.display_name}",
            "print": "AFG", "images": [], "sizes": [], "location": location,
            "postedAt": datetime.utcnow().isoformat() + "Z", "sourceUrl": "",
            "seller": interaction.user.display_name, "sellerId": interaction.user.id,
            "verified": await is_verified(interaction.user), "status": "active"
        }
        new_ref = db.reference("products").push(product)
        firebase_key = new_ref.key

        await interaction.response.send_message(
            "✅ Item submitted!\n\n**Please attach your picture right here in this thread** — the bot will update your public listing.",
            ephemeral=False
        )

        resell_ch = get_channel(interaction.guild, CHANNELS["Resell"])
        if resell_ch:
            embed = build_resell_embed(product, interaction.user)
            view = ResellView(str(product_id), interaction.user.id, product["name"], price, firebase_key)
            sent_msg = await resell_ch.send(embed=embed, view=view)
            db.reference(f"products/{firebase_key}").update({
                "resell_msg_id": sent_msg.id, "resell_ch_id": resell_ch.id
            })

        mod_log = get_channel(interaction.guild, CHANNELS["ModLog"])
        if mod_log:
            log_embed = discord.Embed(title="📥 New Listing", color=0x4FBF8B)
            log_embed.add_field(name="Seller", value=f"{interaction.user.mention} ({interaction.user.id})", inline=False)
            log_embed.add_field(name="Item", value=product["name"], inline=True)
            log_embed.add_field(name="Price", value=f"${price:.2f}", inline=True)
            log_embed.timestamp = datetime.utcnow()
            await mod_log.send(embed=log_embed)


def build_resell_embed(product: dict, seller: discord.Member) -> discord.Embed:
    sold = product.get("status") == "sold"
    color = 0x808080 if sold else 0xD4A24C
    title = "🔴 SOLD · 🏪 New Listing" if sold else "🏪 New Listing"
    embed = discord.Embed(
        title=title,
        description=f"**{product['name']}**\n\n_{product.get('desc', '')}_",
        color=color
    )
    embed.add_field(name="Price", value=f"${float(product['price']):.2f}", inline=True)
    embed.add_field(name="Category", value=product.get('cat', '—'), inline=True)
    embed.add_field(name="Condition", value=product.get('condition', '—'), inline=True)
    embed.add_field(name="Location", value=product.get('location', '—'), inline=True)
    embed.add_field(name="Seller", value=f"{seller.mention}" + (" ✅ Verified" if product.get("verified") else ""), inline=False)
    if sold:
        embed.set_footer(text="This item is sold")
    else:
        embed.set_footer(text="Report scams with the 🚩 button · Seller use /sold to mark sold")
    return embed


# ============================================================
#   PHOTO UPLOAD LISTENER
# ============================================================

@bot.event
async def on_message(message):
    if message.author.bot: return
    await bot.process_commands(message)
    if not isinstance(message.channel, discord.Thread): return
    if not message.channel.name.startswith("sell-"): return

    if message.attachments:
        for att in message.attachments:
            if not att.content_type or not att.content_type.startswith("image"): continue
            raw = await att.read()
            if len(raw) > 8 * 1024 * 1024:
                await message.reply("❌ Image too large (max 8 MB)."); continue

            b64 = base64.b64encode(raw).decode()
            data_url = f"data:{att.content_type or 'image/jpeg'};base64,{b64}"

            data = db.reference("products").order_by_child("sellerId").equal_to(message.author.id).get() or {}
            if not data:
                await message.reply("❌ Could not find your listing."); return

            last_key = list(data.keys())[-1]
            product = data[last_key]
            images = product.get("images") or []
            if len(images) >= 1:
                await message.reply("⚠️ You have already uploaded a picture for this listing."); return
            images.append(data_url)
            db.reference(f"products/{last_key}").update({"images": images})

            ch_id = product.get("resell_ch_id")
            msg_id = product.get("resell_msg_id")
            if ch_id and msg_id:
                try:
                    resell_ch = await bot.fetch_channel(ch_id)
                    sent_msg = await resell_ch.fetch_message(msg_id)
                    seller = message.author
                    embed = build_resell_embed({**product, "images": images}, seller)
                    file = image_from_data_url(data_url)
                    if file:
                        embed.set_image(url="attachment://item.jpg")
                        await sent_msg.edit(embed=embed, attachments=[file])
                    else:
                        await sent_msg.edit(embed=embed)
                except Exception as e:
                    print(f"⚠️ Could not update resell message: {e}")
            await message.reply("📸 Photo added to your public listing!")


# ============================================================
#   RESELL VIEW
# ============================================================

class ResellView(discord.ui.View):
    def __init__(self, product_id: str, owner_id: int, product_name: str, price: float, firebase_key: str):
        super().__init__(timeout=None)
        self.product_id = product_id
        self.owner_id = owner_id
        self.product_name = product_name
        self.price = price
        self.firebase_key = firebase_key

    @discord.ui.button(label="Report", emoji="🚩", style=discord.ButtonStyle.danger, custom_id="resell_report")
    async def report_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id == self.owner_id:
            await interaction.response.send_message("❌ You can't report your own listing.", ephemeral=True); return
        if await is_blacklisted(interaction.user):
            await interaction.response.send_message("❌ Blacklisted users can't report.", ephemeral=True); return

        reports = load_reports()
        pid = self.product_id
        if pid not in reports:
            reports[pid] = {"reported": [], "owner_id": self.owner_id, "product_name": self.product_name, "price": self.price}
        if str(interaction.user.id) in reports[pid]["reported"]:
            await interaction.response.send_message("✅ You already reported this.", ephemeral=True); return

        reports[pid]["reported"].append(str(interaction.user.id))
        save_reports(reports)
        count = len(reports[pid]["reported"])
        await interaction.response.send_message(f"🚩 Report received. **{count}/{REPORT_THRESHOLD}** reports.", ephemeral=True)
        if count >= REPORT_THRESHOLD:
            await trigger_blacklist(interaction.guild, interaction.channel, reports[pid], interaction.client)


async def trigger_blacklist(guild, channel, report_data, bot_client):
    owner_id = report_data["owner_id"]
    member = guild.get_member(owner_id)
    if not member: return
    role = discord.utils.get(guild.roles, name=BLACKLIST_ROLE_NAME)
    if not role or role in member.roles: return
    try:
        await member.add_roles(role, reason=f"Auto-blacklisted: {REPORT_THRESHOLD} reports")
        await channel.send(f"⛔ **{member.mention}** has been blacklisted after **{REPORT_THRESHOLD}** reports.")
        mod_log = get_channel(guild, CHANNELS["ModLog"])
        if mod_log:
            embed = discord.Embed(title="🛡️ Auto-Blacklist", color=0xE06A5A)
            embed.add_field(name="User", value=f"{member} ({member.id})", inline=False)
            embed.timestamp = datetime.utcnow()
            await mod_log.send(embed=embed)
    except Exception as e:
        print(f"❌ Blacklist failed: {e}")

# ============================================================
#   ITEM VIEW + MESSAGE
# ============================================================

class ItemView(discord.ui.View):
    def __init__(self, product: dict):
        super().__init__(timeout=None)
        self.product = product

    @discord.ui.button(label="Message", emoji="💬", style=discord.ButtonStyle.primary, custom_id="item_message")
    async def message_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(MessageModal(self.product))

    @discord.ui.button(label="Item", emoji="🛍️", style=discord.ButtonStyle.secondary, custom_id="item_details")
    async def item_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        p = self.product
        embed = discord.Embed(title=f"🛍️ {p.get('name', 'Item')}", description=p.get("desc", "—"), color=0xB026FF)
        try: price = float(p.get("price", 0))
        except (ValueError, TypeError): price = 0
        embed.add_field(name="Price", value=f"${price:.2f}", inline=True)
        embed.add_field(name="Category", value=p.get("cat", "—"), inline=True)
        embed.add_field(name="Condition", value=p.get("condition", "—"), inline=True)
        images = p.get("images") or []
        file = None
        if images and isinstance(images, list):
            file = image_from_data_url(images[0])
            if file: embed.set_image(url="attachment://item.jpg")
        if file: await interaction.response.send_message(embed=embed, file=file, ephemeral=True)
        else: await interaction.response.send_message(embed=embed, ephemeral=True)


class MessageModal(discord.ui.Modal, title="Send a message"):
    def __init__(self, product: dict):
        super().__init__()
        self.product = product
        self.message_input = discord.ui.TextInput(
            label=f"Your message about {product.get('name', 'this item')}",
            style=discord.TextStyle.paragraph, placeholder="Hi, I'd like to know more...",
            max_length=500, required=True
        )
        self.add_item(self.message_input)

    async def on_submit(self, interaction: discord.Interaction):
        user = interaction.user
        now_iso = datetime.utcnow().isoformat() + "Z"
        p = self.product
        item = {
            "id": "DISCORD-" + str(int(time.time())), "type": "ask", "date": now_iso,
            "userEmail": f"{user.name}@discord.dm", "userName": user.display_name or user.name,
            "product": {
                "id": p.get("id"), "name": p.get("name", "Item"), "price": float(p.get("price", 0)),
                "cat": p.get("cat", "Men"), "condition": p.get("condition", "New"),
                "images": (p.get("images") or [])[:1], "size": ""
            },
            "message": self.message_input.value, "offer": None, "status": "open",
            "chat": [{"from": "customer", "type": "text", "message": self.message_input.value, "time": now_iso}],
            "unreadByAdmin": True
        }
        try:
            db.reference("messages").push(item)
            await interaction.response.send_message(f"✅ Message sent about **{p.get('name')}**!", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Error: `{e}`", ephemeral=True)

# ============================================================
#   LOOPS
# ============================================================

async def post_product(product: dict):
    cat = (product.get("cat") or "Men").strip()
    channel_name = CHANNELS.get(cat)
    if not channel_name: return 0
    embed = discord.Embed(title="🆕 New Item!", description=f"**{product.get('name', 'Unnamed')}**", color=0xB026FF)
    try: price = float(product.get("price", 0))
    except (ValueError, TypeError): price = 0
    embed.add_field(name="Price", value=f"${price:.2f}", inline=True)
    embed.add_field(name="Category", value=cat, inline=True)
    embed.add_field(name="Condition", value=product.get("condition", "—"), inline=True)
    if product.get("desc"):
        embed.add_field(name="Description", value=str(product["desc"])[:200], inline=False)
    images = product.get("images") or []
    has_image = images and isinstance(images, list)
    if has_image: embed.set_image(url="attachment://item.jpg")
    embed.set_footer(text="Afg Marketplace · Click Message to chat")
    view = ItemView(product)
    posted = 0
    for guild in bot.guilds:
        ch = get_channel(guild, channel_name)
        if ch:
            try:
                if has_image:
                    f = image_from_data_url(images[0])
                    if f: await ch.send(embed=embed, file=f, view=view)
                    else: await ch.send(embed=embed, view=view)
                else: await ch.send(embed=embed, view=view)
                posted += 1
            except Exception as e: print(f"⚠️ send failed: {e}")
    return posted

@tasks.loop(seconds=10)
async def watch_products():
    try:
        data = db.reference("products").get() or {}
        for key, product in data.items():
            if key in seen_products: continue
            if product.get("seller"):
                seen_products.add(key); continue
            if "id" not in product: product["id"] = key
            n = await post_product(product)
            if n: print(f"📤 Posted: {product.get('name')} ({n} guilds)")
            seen_products.add(key)
        save_seen(seen_products, seen_messages)
    except Exception as e: print(f"⚠️ products loop: {e}")

@tasks.loop(seconds=10)
async def watch_messages():
    try:
        data = db.reference("messages").get() or {}
        for key, msg in data.items():
            if key in seen_messages: continue
            is_offer = msg.get("type") == "offer"
            channel_name = CHANNELS["Offers"] if is_offer else CHANNELS["Asks"]
            user = msg.get("userName", "Someone")
            item = (msg.get("product") or {}).get("name", "an item")
            size = (msg.get("product") or {}).get("size") or "—"
            if is_offer:
                try: offer = float(msg.get("offer", 0))
                except (ValueError, TypeError): offer = 0
                embed = discord.Embed(title="💰 New Offer", description=f"**{user}** offered **${offer:.2f}** for **{item}**", color=0xD4A24C)
            else:
                embed = discord.Embed(title="💬 New Message", description=f"**{user}** messaged about **{item}**", color=0x00D4FF)
            embed.add_field(name="Item", value=item, inline=True)
            embed.add_field(name="Size", value=size, inline=True)
            if msg.get("message"): embed.add_field(name="Their message", value=str(msg["message"])[:200], inline=False)
            images = (msg.get("product") or {}).get("images") or []
            has_image = images and isinstance(images, list)
            if has_image: embed.set_image(url="attachment://item.jpg")
            embed.set_footer(text="Afg Marketplace")
            for guild in bot.guilds:
                ch = get_channel(guild, channel_name)
                if ch:
                    try:
                        if has_image:
                            f = image_from_data_url(images[0])
                            if f: await ch.send(embed=embed, file=f)
                            else: await ch.send(embed=embed)
                        else: await ch.send(embed=embed)
                    except Exception as e: print(f"⚠️ send failed: {e}")
            seen_messages.add(key)
        save_seen(seen_products, seen_messages)
    except Exception as e: print(f"⚠️ messages loop: {e}")

# ============================================================
#   COMMANDS
# ============================================================

@bot.tree.command(name="ping", description="Check the bot's latency")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(f"🏓 Pong! **{round(bot.latency * 1000)}ms**")


@bot.tree.command(name="sold", description="Mark one of your listings as sold")
@app_commands.describe(message_id="Right-click your listing → Copy Message ID")
async def sold(interaction: discord.Interaction, message_id: str):
    await interaction.response.defer(thinking=True)
    data = db.reference("products").order_by_child("sellerId").equal_to(interaction.user.id).get() or {}
    if not data:
        await interaction.followup.send("❌ You have no listings.")
        return
    found_key = None
    for k, p in data.items():
        if str(p.get("resell_msg_id")) == message_id:
            found_key = k
            break
    if not found_key:
        await interaction.followup.send("❌ Could not find a listing with that message ID under your account.")
        return
    product = data[found_key]
    db.reference(f"products/{found_key}").update({"status": "sold"})
    try:
        resell_ch = await bot.fetch_channel(product["resell_ch_id"])
        sent_msg = await resell_ch.fetch_message(product["resell_msg_id"])
        seller = interaction.user
        embed = build_resell_embed({**product, "status": "sold"}, seller)
        file = None
        if product.get("images"):
            file = image_from_data_url(product["images"][0])
            if file: embed.set_image(url="attachment://item.jpg")
        if file: await sent_msg.edit(embed=embed, attachments=[file])
        else: await sent_msg.edit(embed=embed)
    except Exception as e:
        print(f"⚠️ Could not update sold message: {e}")
    await interaction.followup.send("✅ Marked as sold!")


@bot.tree.command(name="search", description="Search all listings by keyword")
@app_commands.describe(query="Title or description keyword")
async def search(interaction: discord.Interaction, query: str):
    await interaction.response.defer(thinking=True)
    q = query.strip().lower()
    data = db.reference("products").get() or {}
    matches = []
    for key, p in data.items():
        if p.get("status") == "sold":
            continue
        text = (str(p.get("name", "")) + " " + str(p.get("desc", ""))).lower()
        if q in text:
            matches.append(p)
    if not matches:
        await interaction.followup.send(f"❌ No items matching **{query}**.")
        return
    matches = matches[:5]
    embed = discord.Embed(title=f"🔍 Results for \"{query}\"", color=0xB026FF)
    for p in matches:
        try: price = float(p.get("price", 0))
        except (ValueError, TypeError): price = 0
        seller_line = "✅ Verified" if p.get("verified") else ""
        embed.add_field(
            name=f"{p.get('name', 'Item')} · ${price:.2f}",
            value=f"{p.get('cat', '—')} · {p.get('condition', '—')} · {p.get('location', '—')} {seller_line}",
            inline=False
        )
    embed.set_footer(text=f"Found {len(matches)} result(s)")
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="verify", description="Give a user the Verified Seller badge (admin only)")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(member="User to verify")
async def verify_cmd(interaction: discord.Interaction, member: discord.Member):
    role = discord.utils.get(interaction.guild.roles, name=VERIFIED_ROLE_NAME)
    if not role:
        await interaction.response.send_message("❌ Verified Seller role missing.", ephemeral=True)
        return
    if role in member.roles:
        await interaction.response.send_message(f"ℹ️ {member.mention} is already verified.")
        return
    await member.add_roles(role)
    await interaction.response.send_message(f"✅ {member.mention} is now a **Verified Seller**.")


@bot.tree.command(name="unverify", description="Remove the Verified Seller badge (admin only)")
@app_commands.default_permissions(administrator=True)
async def unverify_cmd(interaction: discord.Interaction, member: discord.Member):
    role = discord.utils.get(interaction.guild.roles, name=VERIFIED_ROLE_NAME)
    if not role or role not in member.roles:
        await interaction.response.send_message(f"ℹ️ {member.mention} is not verified.")
        return
    await member.remove_roles(role)
    await interaction.response.send_message(f"✅ Removed verification from {member.mention}.")


@bot.tree.command(name="sell_panel", description="Post the sell panel in #🛒-sell-here (admin only)")
@app_commands.default_permissions(administrator=True)
async def sell_panel(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    ch = get_channel(interaction.guild, CHANNELS["SellPanel"])
    if not ch:
        await ensure_channels(interaction.guild)
        ch = get_channel(interaction.guild, CHANNELS["SellPanel"])
    if not ch:
        await interaction.followup.send("❌ Could not find #🛒-sell-here."); return
    embed = discord.Embed(
        title="🛒 Sell an Item",
        description="Click **Post Item** to start your listing thread.\nYou need the **Reseller** role to sell.",
        color=0x4FBF8B
    )
    view = SellPanelView()
    await ch.send(embed=embed, view=view)
    await interaction.followup.send(f"✅ Sell panel posted in {ch.mention}")


@bot.tree.command(name="blacklist", description="Manually blacklist a user (admin only)")
@app_commands.default_permissions(administrator=True)
async def blacklist_cmd(interaction: discord.Interaction, member: discord.Member, reason: str = "Manual"):
    await interaction.response.defer(thinking=True)
    role = discord.utils.get(interaction.guild.roles, name=BLACKLIST_ROLE_NAME)
    if not role: role = await ensure_blacklist_role(interaction.guild)
    if role in member.roles:
        await interaction.followup.send(f"ℹ️ {member.mention} is already blacklisted."); return
    await member.add_roles(role, reason=reason)
    await interaction.followup.send(f"⛔ Blacklisted {member.mention}")


@bot.tree.command(name="unblacklist", description="Remove a user from Blacklisted (admin only)")
@app_commands.default_permissions(administrator=True)
async def unblacklist_cmd(interaction: discord.Interaction, member: discord.Member):
    await interaction.response.defer(thinking=True)
    role = discord.utils.get(interaction.guild.roles, name=BLACKLIST_ROLE_NAME)
    if not role or role not in member.roles:
        await interaction.followup.send(f"ℹ️ {member.mention} is not blacklisted."); return
    await member.remove_roles(role)
    await interaction.followup.send(f"✅ Unblacklisted {member.mention}")


@bot.tree.command(name="blacklisted", description="List all blacklisted users")
async def blacklisted_cmd(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    role = discord.utils.get(interaction.guild.roles, name=BLACKLIST_ROLE_NAME)
    if not role or not role.members:
        await interaction.followup.send("No blacklisted users."); return
    members = "\n".join(f"• {m} ({m.id})" for m in role.members)
    await interaction.followup.send(f"⛔ **Blacklisted:**\n{members}")


@bot.tree.command(name="add", description="Import a product from a URL (admin only)")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(url="Product URL", cat="Optional category")
@app_commands.choices(cat=[app_commands.Choice(name="Men", value="Men"), app_commands.Choice(name="Women", value="Women"), app_commands.Choice(name="Kids", value="Kids")])
async def add_product(interaction: discord.Interaction, url: str, cat: app_commands.Choice[str] = None):
    await interaction.response.defer(thinking=True)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            html = r.read().decode("utf-8", errors="ignore")

        def og(prop):
            for pat in [rf'<meta[^>]+property=["\']og:{prop}["\'][^>]+content=["\']([^"\']+)', rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:{prop}["\']']:
                m = re.search(pat, html, re.IGNORECASE)
                if m: return m.group(1).strip()
            return None

        title = re.sub(r'\s*[|\-–]\s*(SHEIN|Temu|Amazon).*$', '', og("title") or "Untitled", flags=re.IGNORECASE).strip()[:120]
        desc = (og("description") or "")[:300]
        image = og("image") or og("image:secure_url")
        price = 0.0
        for pat in [r'"price"\s*:\s*"?([\d.]+)', r'product:price:amount["\'][^>]+content=["\']([\d.]+)']:
            m = re.search(pat, html)
            if m:
                try:
                    price = float(m.group(1))
                    if price > 0: break
                except ValueError: continue

        sizes = set()
        for m in re.finditer(r'"sizeName"\s*:\s*"([^"]+)"', html):
            sizes.add(m.group(1).strip().upper())
        sorted_sizes = [s for s in ["XS","S","M","L","XL","2XL","XXL","3XL"] if s in sizes]

        original_price = price
        price, added = apply_price_rule(price)
        final_cat = cat.value if cat else detect_category(title + " " + desc + " " + url)
        data_url = download_image_as_data_url(image, referer=url) if image else None

        product = {
            "id": int(time.time() * 1000), "name": title, "price": float(price), "cat": final_cat,
            "condition": "New", "desc": desc or f"From {url}", "print": "AFG",
            "images": [data_url] if data_url else [], "sizes": sorted_sizes,
            "postedAt": datetime.utcnow().isoformat() + "Z", "sourceUrl": url
        }
        db.reference("products").push(product)

        preview = discord.Embed(title="✅ Added", description=f"**{title}**", color=0xB026FF)
        price_line = f"${price:.2f}"
        if added: price_line += f" (was ${original_price:.2f})"
        preview.add_field(name="Price", value=price_line, inline=True)
        preview.add_field(name="Category", value=final_cat, inline=True)
        preview.add_field(name="Image", value="✅" if data_url else "❌", inline=True)
        if data_url:
            f = image_from_data_url(data_url)
            if f:
                preview.set_image(url="attachment://item.jpg")
                await interaction.followup.send(embed=preview, file=f, ephemeral=True); return
        await interaction.followup.send(embed=preview, ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ Error: `{e}`", ephemeral=True)


@bot.tree.command(name="setup", description="Create missing channels + roles + sell panel (admin only)")
@app_commands.default_permissions(administrator=True)
async def setup(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    await ensure_channels(interaction.guild)
    await ensure_blacklist_role(interaction.guild)
    await ensure_reseller_role(interaction.guild)
    await ensure_verified_role(interaction.guild)
    await ensure_sell_panel(interaction.guild)
    await interaction.followup.send("✅ Channels + roles + sell panel ready.")


@bot.tree.command(name="channels", description="List channels")
async def channels_cmd(interaction: discord.Interaction):
    names = "\n".join(f"• #{n}" for n in CHANNELS.values())
    await interaction.response.send_message(f"📁 Channels:\n{names}")


# ---------- RUN ----------
if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise SystemExit("\n❌ DISCORD_TOKEN missing in ~/.env\n")
    bot.run(DISCORD_TOKEN)

import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import io

import os
TOKEN = os.environ["BOT_TOKEN"]
GUILD_ID = 1501252057116573868

# ─── Role IDs ──────────────────────────────────────────────────────────────────
ROLE = {
    "middleman":      1501252057179361514,
    "senior_mid":     1501252057179361515,
    "mid_manager":    1501252057179361516,
    "moderator":      1501252057217368189,
    "head_mod":       1501252057217368191,
    "lead_coord":     1501252057217368193,
    "admin":          1501252057259180153,
    "head_admin":     1501252057259180154,
    "co_founder":     1501252057259180156,
    "ops_manager":    1501252057259180157,
    "chief_exec":     1501252057259180160,
    "director":       1501252057305452624,
    "president":      1501252057305452626,
    "head_staff":     1501252057305452628,
}

# Ordered lowest → highest
HIERARCHY = [
    ROLE["middleman"],   ROLE["senior_mid"],  ROLE["mid_manager"],
    ROLE["moderator"],   ROLE["head_mod"],    ROLE["lead_coord"],
    ROLE["admin"],       ROLE["head_admin"],  ROLE["co_founder"],
    ROLE["ops_manager"], ROLE["chief_exec"],  ROLE["director"],
    ROLE["president"],   ROLE["head_staff"],
]

# Each role can promote/demote up to and including the listed ceiling
PROMOTE_CEILING = {
    ROLE["co_founder"]:   ROLE["senior_mid"],
    ROLE["ops_manager"]:  ROLE["co_founder"],
    ROLE["chief_exec"]:   ROLE["ops_manager"],
    ROLE["director"]:     ROLE["chief_exec"],
    ROLE["president"]:    ROLE["director"],
    ROLE["head_staff"]:   ROLE["president"],
}

# ─── Channel IDs ───────────────────────────────────────────────────────────────
CH = {
    "app_channel":    1501252058638975001,
    "app_ticket_cat": 1501252059096420514,
    "mm_channel":     1501252059587150029,
    "mm_ticket_cat":  1501252061029863457,
    "transcript_ch":  1501252063802163335,
    "ban_log":        1501252063802163337,
    "role_log":       1501252063802163336,
}

FOOTER      = "Powered by Brxxks Middleman Service"
FOOTER_HELP = "Powered by Brxxks Helper Bot"

# Role groups
ALL_STAFF   = list(ROLE.values())
TICKET_STAFF = ALL_STAFF
BAN_ROLES   = [ROLE["moderator"], ROLE["head_mod"], ROLE["lead_coord"], ROLE["admin"],
               ROLE["head_admin"], ROLE["co_founder"], ROLE["ops_manager"],
               ROLE["chief_exec"], ROLE["director"], ROLE["president"], ROLE["head_staff"],
               1501252057217368192]
ADMIN_ROLES = [ROLE["admin"], ROLE["head_admin"], ROLE["co_founder"], ROLE["ops_manager"],
               ROLE["chief_exec"], ROLE["director"], ROLE["president"], ROLE["head_staff"]]
MM_PING     = [ROLE["middleman"]]

# Active trade views stored in memory: {message_id: TradeView}
active_trades: dict = {}

# ─── Helpers ───────────────────────────────────────────────────────────────────

def has_role(member: discord.Member, role_ids: list) -> bool:
    return any(r.id in role_ids for r in member.roles)

def top_role_id(member: discord.Member):
    for rid in reversed(HIERARCHY):
        if any(r.id == rid for r in member.roles):
            return rid
    return None

def can_manage_role(executor: discord.Member, target_role_id: int) -> bool:
    top = top_role_id(executor)
    if top not in PROMOTE_CEILING:
        return False
    ceiling     = PROMOTE_CEILING[top]
    ceiling_idx = HIERARCHY.index(ceiling)
    try:
        target_idx = HIERARCHY.index(target_role_id)
    except ValueError:
        return False
    return 0 <= target_idx <= ceiling_idx

async def make_transcript(channel: discord.TextChannel) -> io.BytesIO:
    lines = []
    async for msg in channel.history(limit=None, oldest_first=True):
        ts = msg.created_at.strftime("%Y-%m-%d %H:%M:%S UTC")
        lines.append(f"[{ts}] {msg.author} ({msg.author.id}): {msg.content}")
        for e in msg.embeds:
            if e.title:       lines.append(f"  [EMBED TITLE] {e.title}")
            if e.description: lines.append(f"  [EMBED DESC]  {e.description}")
            for f in e.fields:
                lines.append(f"  [{f.name}] {f.value}")
    return io.BytesIO("\n".join(lines).encode())

def ts_now() -> str:
    return discord.utils.utcnow().strftime("%A, %B %d, %Y %I:%M %p")

def mm_overwrites(guild: discord.Guild, opener: discord.Member) -> dict:
    ow = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        opener: discord.PermissionOverwrite(read_messages=True, send_messages=True),
    }
    for rid in TICKET_STAFF:
        r = guild.get_role(rid)
        if r:
            ow[r] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
    return ow

def app_overwrites(guild: discord.Guild, opener: discord.Member) -> dict:
    ow = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        opener: discord.PermissionOverwrite(read_messages=True, send_messages=True),
    }
    for rid in ADMIN_ROLES:
        r = guild.get_role(rid)
        if r:
            ow[r] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
    return ow

async def do_close(interaction: discord.Interaction):
    if not has_role(interaction.user, TICKET_STAFF):
        await interaction.response.send_message("No permission.", ephemeral=True)
        return
    ch = interaction.channel
    buf = await make_transcript(ch)
    tr_ch = interaction.guild.get_channel(CH["transcript_ch"])
    if tr_ch:
        embed = discord.Embed(color=0x2b2d31, title="📄 Ticket Transcript")
        embed.description = f"**Channel:** `{ch.name}`\n**Closed by:** {interaction.user.mention}"
        embed.set_footer(text=FOOTER)
        await tr_ch.send(embed=embed,
                         file=discord.File(buf, filename=f"transcript-{ch.name}.txt"))
    await interaction.response.send_message("Closing ticket in 5 seconds…")
    await asyncio.sleep(5)
    await ch.delete()

# ─── Bot Setup ─────────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
GUILD = discord.Object(id=GUILD_ID)

# ─── Persistent Views ──────────────────────────────────────────────────────────

class MMRequestView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Request Middleman", style=discord.ButtonStyle.primary,
                       emoji="🎫", custom_id="v:mm_request")
    async def request(self, interaction: discord.Interaction, btn: discord.ui.Button):
        guild  = interaction.guild
        cat    = guild.get_channel(CH["mm_ticket_cat"])
        if cat is None:
            await interaction.response.send_message("Ticket category not found.", ephemeral=True)
            return

        for c in cat.channels:
            if c.topic == str(interaction.user.id):
                await interaction.response.send_message(
                    f"You already have an open ticket: {c.mention}", ephemeral=True)
                return

        ch = await guild.create_text_channel(
            name=f"mm-{interaction.user.name}",
            category=cat,
            overwrites=mm_overwrites(guild, interaction.user),
            topic=str(interaction.user.id),
        )
        embed = discord.Embed(color=0x2b2d31, title="🎫 Middleman Ticket")
        embed.description = (
            f"{interaction.user.mention}, Thank you for using our middleman services.\n\n"
            "Please wait for a middleman to assist you.\n\n"
            "If you have any questions, please let a staff member know."
        )
        embed.set_footer(text=FOOTER)
        pings = " ".join(f"<@&{rid}>" for rid in MM_PING) + f" {interaction.user.mention}"
        await ch.send(content=pings, embed=embed, view=TicketView())
        await interaction.response.send_message(f"Ticket created: {ch.mention}", ephemeral=True)


class AppView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Apply / Ask for Help", style=discord.ButtonStyle.primary,
                       emoji="📋", custom_id="v:app_request")
    async def apply(self, interaction: discord.Interaction, btn: discord.ui.Button):
        guild = interaction.guild
        cat   = guild.get_channel(CH["app_ticket_cat"])
        if cat is None:
            await interaction.response.send_message("Ticket category not found.", ephemeral=True)
            return

        for c in cat.channels:
            if c.topic == str(interaction.user.id):
                await interaction.response.send_message(
                    f"You already have an open ticket: {c.mention}", ephemeral=True)
                return

        ch = await guild.create_text_channel(
            name=f"app-{interaction.user.name}",
            category=cat,
            overwrites=app_overwrites(guild, interaction.user),
            topic=str(interaction.user.id),
        )
        embed = discord.Embed(color=0x2b2d31, title="📋 Application Ticket")
        embed.description = (
            f"{interaction.user.mention}, thank you for reaching out!\n\n"
            "A staff member will be with you shortly.\n\n"
            "If you have any questions, please let a staff member know."
        )
        embed.set_footer(text=FOOTER_HELP)
        await ch.send(content="<@&1501252057259180153>", embed=embed, view=CloseOnlyView())
        await interaction.response.send_message(f"Ticket created: {ch.mention}", ephemeral=True)


class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Claim", style=discord.ButtonStyle.success,
                       emoji="🤚", custom_id="v:ticket_claim")
    async def claim(self, interaction: discord.Interaction, btn: discord.ui.Button):
        if not has_role(interaction.user, TICKET_STAFF):
            await interaction.response.send_message("No permission.", ephemeral=True)
            return
        btn.disabled = True
        await interaction.message.edit(view=self)
        embed = discord.Embed(color=0x57f287, title="✅ Ticket Claimed")
        embed.description = f"{interaction.user.mention} will be your Middleman for today."
        embed.set_footer(text=FOOTER)
        await interaction.response.send_message(embed=embed)

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger,
                       emoji="🔒", custom_id="v:ticket_close")
    async def close(self, interaction: discord.Interaction, btn: discord.ui.Button):
        await do_close(interaction)


class CloseOnlyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger,
                       emoji="🔒", custom_id="v:app_close")
    async def close(self, interaction: discord.Interaction, btn: discord.ui.Button):
        await do_close(interaction)


# ─── Trade Confirmation View (dynamic, stored in memory) ──────────────────────

class TradeView(discord.ui.View):
    def __init__(self, t1: int, t2: int, mm: int):
        super().__init__(timeout=None)
        self.t1        = t1
        self.t2        = t2
        self.mm        = mm
        self.confirmed: set = set()

        b1 = discord.ui.Button(
            label="✅ Confirm Trade (Trader 1)",
            style=discord.ButtonStyle.success,
            custom_id=f"trade_t1_{t1}_{t2}",
        )
        b2 = discord.ui.Button(
            label="✅ Confirm Trade (Trader 2)",
            style=discord.ButtonStyle.success,
            custom_id=f"trade_t2_{t1}_{t2}",
        )
        b1.callback = self._confirm_t1
        b2.callback = self._confirm_t2
        self.add_item(b1)
        self.add_item(b2)

    async def _confirm_t1(self, interaction: discord.Interaction):
        if interaction.user.id != self.t1:
            await interaction.response.send_message("You are not Trader 1.", ephemeral=True)
            return
        self.confirmed.add(self.t1)
        await self._refresh(interaction)

    async def _confirm_t2(self, interaction: discord.Interaction):
        if interaction.user.id != self.t2:
            await interaction.response.send_message("You are not Trader 2.", ephemeral=True)
            return
        self.confirmed.add(self.t2)
        await self._refresh(interaction)

    async def _refresh(self, interaction: discord.Interaction):
        guild = interaction.guild
        m1    = guild.get_member(self.t1)
        m2    = guild.get_member(self.t2)
        mm    = guild.get_member(self.mm)
        t1c   = self.t1 in self.confirmed
        t2c   = self.t2 in self.confirmed
        both  = t1c and t2c

        # Preserve trade details from original embed
        old     = interaction.message.embeds[0]
        details = old.fields[0].value if old.fields else "—"

        if both:
            embed = discord.Embed(color=0x57f287, title="✅ Trade Confirmed")
            embed.description = (
                f"{interaction.user.mention}, both traders have confirmed this trade. "
                "Please proceed with the rest of the trade."
            )
            embed.add_field(name="🔵 Trader 1",  value=m1.mention if m1 else str(self.t1), inline=True)
            embed.add_field(name="🔵 Trader 2",  value=m2.mention if m2 else str(self.t2), inline=True)
            embed.add_field(name="🛡️ Middleman", value=mm.mention if mm else str(self.mm), inline=False)
            embed.add_field(name="✅ Status",     value="Both traders confirmed", inline=False)
            embed.set_footer(text=FOOTER)
            for item in self.children:
                item.disabled = True
                item.label    = "Trade Confirmed"
            active_trades.pop(interaction.message.id, None)
        else:
            t1d = "🟢" if t1c else "🔴"
            t2d = "🟢" if t2c else "🔴"
            embed = discord.Embed(color=0x2b2d31, title="✅ Trade Confirmation")
            embed.add_field(name="Trade Details:", value=details, inline=False)
            embed.description = "In order to continue this trade, both traders should confirm the trade."
            embed.add_field(name="📊 Trade Information", value=details, inline=False)
            embed.add_field(name="🔵 Trader 1",  value=m1.mention if m1 else str(self.t1), inline=True)
            embed.add_field(name="🔵 Trader 2",  value=m2.mention if m2 else str(self.t2), inline=True)
            embed.add_field(name="🛡️ Middleman", value=mm.mention if mm else str(self.mm), inline=False)
            embed.add_field(name="⏳ Awaiting Confirmation",
                            value=f"{t1d} {m1.mention if m1 else str(self.t1)}\n"
                                  f"{t2d} {m2.mention if m2 else str(self.t2)}",
                            inline=False)
            embed.set_footer(text=FOOTER)
            for item in self.children:
                if "t1" in item.custom_id and t1c:
                    item.label, item.disabled = "Confirmed (Trader 1)", True
                if "t2" in item.custom_id and t2c:
                    item.label, item.disabled = "Confirmed (Trader 2)", True

        await interaction.message.edit(embed=embed, view=self)
        await interaction.response.defer()


# ─── Slash Commands ────────────────────────────────────────────────────────────

@bot.tree.command(name="add", description="Add a user to this ticket", guild=GUILD)
@app_commands.describe(user="User to add")
async def cmd_add(interaction: discord.Interaction, user: discord.Member):
    if not has_role(interaction.user, TICKET_STAFF):
        await interaction.response.send_message("No permission.", ephemeral=True)
        return
    await interaction.channel.set_permissions(user, read_messages=True, send_messages=True)
    embed = discord.Embed(color=0x57f287, title="✅ User Added to Ticket")
    embed.description = f"{user.mention} has been added to this ticket by {interaction.user.mention}"
    embed.set_footer(text=FOOTER)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="close", description="Close this ticket", guild=GUILD)
async def cmd_close(interaction: discord.Interaction):
    await do_close(interaction)


@bot.tree.command(name="transfer", description="Transfer this ticket to another middleman", guild=GUILD)
@app_commands.describe(user="Middleman to transfer to")
async def cmd_transfer(interaction: discord.Interaction, user: discord.Member):
    if not has_role(interaction.user, TICKET_STAFF):
        await interaction.response.send_message("No permission.", ephemeral=True)
        return
    await interaction.channel.set_permissions(user, read_messages=True, send_messages=True)
    embed = discord.Embed(color=0x2b2d31, title="🔄 Ticket Transferred")
    embed.description = f"This ticket has been transferred to {user.mention}"
    embed.set_footer(text=FOOTER)
    await interaction.response.send_message(content=user.mention, embed=embed)


@bot.tree.command(name="middleman", description="Show pet trade middleman info", guild=GUILD)
async def cmd_mm(interaction: discord.Interaction):
    embed = discord.Embed(color=0x2b2d31, title="🤝 Middleman Services")
    embed.add_field(name="Middleman Service",
                    value='• To request a middleman from this server, click the blue **"Request Middleman"** button on this message.',
                    inline=False)
    embed.add_field(name="How does middleman work?",
                    value="• Example: Trade is Frost Dragon for Corrupt.\n"
                          "• Trader #1 gives Frost Dragon to middleman.\n"
                          "• Trader #2 gives Corrupt to middleman.\n"
                          "• Middleman gives the respective pets to each trader.",
                    inline=False)
    embed.add_field(name="⚠️ DISCLAIMER!",
                    value="You must both agree on the deal before using a middleman. "
                          "Troll tickets will have consequences.",
                    inline=False)
    embed.set_footer(text=FOOTER)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="middleman2", description="Show Robux middleman info", guild=GUILD)
async def cmd_mm2(interaction: discord.Interaction):
    embed = discord.Embed(color=0x2b2d31, title="💰 Robux Middleman Services")
    embed.add_field(name="Robux Middleman Service",
                    value='• To request a middleman for a Robux trade, click the blue **"Request Middleman"** button.',
                    inline=False)
    embed.add_field(name="How does Robux middleman work?",
                    value="• Example: Trade is Robux for a pet.\n"
                          "• Trader #1 sends Robux to the middleman's Roblox account.\n"
                          "• Trader #2 gives the pet to middleman.\n"
                          "• Middleman sends Robux to Trader #2 and the pet to Trader #1.",
                    inline=False)
    embed.add_field(name="⚠️ DISCLAIMER!",
                    value="You must both agree on the deal before using a middleman. "
                          "Troll tickets will have consequences.",
                    inline=False)
    embed.set_footer(text=FOOTER)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="confirm", description="Start a trade confirmation between two traders", guild=GUILD)
@app_commands.describe(trader1="First trader", trader2="Second trader", details="Trade details")
async def cmd_confirm(interaction: discord.Interaction,
                      trader1: discord.Member, trader2: discord.Member, details: str):
    if not has_role(interaction.user, TICKET_STAFF):
        await interaction.response.send_message("No permission.", ephemeral=True)
        return

    view  = TradeView(t1=trader1.id, t2=trader2.id, mm=interaction.user.id)
    embed = discord.Embed(color=0x2b2d31, title="✅ Trade Confirmation")
    embed.add_field(name="Trade Details:", value=details, inline=False)
    embed.description = "In order to continue this trade, both traders should confirm the trade."
    embed.add_field(name="📊 Trade Information", value=details, inline=False)
    embed.add_field(name="🔵 Trader 1",  value=trader1.mention, inline=True)
    embed.add_field(name="🔵 Trader 2",  value=trader2.mention, inline=True)
    embed.add_field(name="🛡️ Middleman", value=interaction.user.mention, inline=False)
    embed.add_field(name="⏳ Awaiting Confirmation",
                    value=f"🔴 {trader1.mention}\n🔴 {trader2.mention}", inline=False)
    embed.set_footer(text=FOOTER)

    await interaction.response.send_message(
        content=f"{trader1.mention} {trader2.mention}", embed=embed, view=view)
    msg = await interaction.original_response()
    active_trades[msg.id] = view


@bot.tree.command(name="managerole", description="Promote or demote a user", guild=GUILD)
@app_commands.describe(action="add or remove", user="Target user", role="Role to give/take", reason="Reason")
@app_commands.choices(action=[
    app_commands.Choice(name="add",    value="add"),
    app_commands.Choice(name="remove", value="remove"),
])
async def cmd_managerole(interaction: discord.Interaction, action: str,
                         user: discord.Member, role: discord.Role, reason: str):
    if not can_manage_role(interaction.user, role.id):
        await interaction.response.send_message(
            "You don't have permission to manage that role.", ephemeral=True)
        return

    if action == "add":
        await user.add_roles(role, reason=reason)
        title, color = "Role Given ✅", 0x57f287
    else:
        await user.remove_roles(role, reason=reason)
        title, color = "Role Removed ❌", 0xed4245

    embed = discord.Embed(color=color, title=title)
    embed.add_field(name="Actioned By", value=f"{interaction.user} ({interaction.user.id})", inline=False)
    embed.add_field(name="Target User", value=f"{user} ({user.id})",                         inline=False)
    embed.add_field(name="Role",        value=role.name,                                      inline=False)
    embed.add_field(name="Reason",      value=reason,                                         inline=False)
    embed.add_field(name="Time",        value=ts_now(),                                       inline=False)
    embed.set_footer(text=FOOTER)

    await interaction.response.send_message(embed=embed)
    log_ch = interaction.guild.get_channel(CH["role_log"])
    if log_ch:
        await log_ch.send(embed=embed)


@bot.tree.command(name="manageban", description="Ban or unban a user", guild=GUILD)
@app_commands.describe(action="ban or unban", user="Target user", reason="Reason")
@app_commands.choices(action=[
    app_commands.Choice(name="ban",   value="ban"),
    app_commands.Choice(name="unban", value="unban"),
])
async def cmd_manageban(interaction: discord.Interaction, action: str,
                        user: discord.Member, reason: str):
    if not has_role(interaction.user, BAN_ROLES):
        await interaction.response.send_message("No permission.", ephemeral=True)
        return

    roles_owned = [r.name for r in user.roles if r.name != "@everyone"]

    if action == "ban":
        await user.ban(reason=reason)
        title, color = "User Banned 🚫", 0xed4245
    else:
        await interaction.guild.unban(discord.Object(id=user.id), reason=reason)
        title, color = "User Unbanned ✅", 0x57f287

    embed = discord.Embed(color=color, title=title)
    embed.add_field(name="Actioned By",  value=f"{interaction.user} ({interaction.user.id})",  inline=False)
    embed.add_field(name="Target User",  value=f"{user} ({user.id})",                           inline=False)
    embed.add_field(name="Roles Owned",  value=", ".join(roles_owned) if roles_owned else "None", inline=False)
    embed.add_field(name="Reason",       value=reason,                                           inline=False)
    embed.add_field(name="Time",         value=ts_now(),                                         inline=False)
    embed.set_footer(text=FOOTER)

    await interaction.response.send_message(embed=embed)
    log_ch = interaction.guild.get_channel(CH["ban_log"])
    if log_ch:
        await log_ch.send(embed=embed)


# ─── Setup Commands (admin only — run once to post the buttons) ────────────────

@bot.tree.command(name="setup_mm", description="Post the Request Middleman embed + button", guild=GUILD)
async def setup_mm(interaction: discord.Interaction):
    if not has_role(interaction.user, ADMIN_ROLES):
        await interaction.response.send_message("No permission.", ephemeral=True)
        return
    embed = discord.Embed(color=0x2b2d31, title="🤝 Middleman Services")
    embed.add_field(name="Middleman Service",
                    value='• To request a middleman from this server, click the blue **"Request Middleman"** button on this message.',
                    inline=False)
    embed.add_field(name="How does middleman work?",
                    value="• Example: Trade is Frost Dragon for Corrupt.\n"
                          "• Trader #1 gives Frost Dragon to middleman.\n"
                          "• Trader #2 gives Corrupt to middleman.\n"
                          "• Middleman gives the respective pets to each trader.",
                    inline=False)
    embed.add_field(name="⚠️ DISCLAIMER!",
                    value="You must both agree on the deal before using a middleman. "
                          "Troll tickets will have consequences.",
                    inline=False)
    embed.set_footer(text=FOOTER)
    await interaction.channel.send(embed=embed, view=MMRequestView())
    await interaction.response.send_message("Done!", ephemeral=True)


@bot.tree.command(name="setup_applications", description="Post the Applications embed + button", guild=GUILD)
async def setup_apps(interaction: discord.Interaction):
    if not has_role(interaction.user, ADMIN_ROLES):
        await interaction.response.send_message("No permission.", ephemeral=True)
        return
    embed = discord.Embed(color=0x2b2d31, title="📋 Applications")
    embed.description = (
        "Welcome to our application information portal!\n\n"
        "This is your hub for learning about opportunities and getting support in our community.\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    embed.add_field(
        name="🛡️ Apply for Moderator",
        value="Interested in becoming a moderator? We're looking for dedicated members to help "
              "keep our community safe and organized. Moderators help manage discussions, enforce "
              "rules, and assist fellow members. If you believe you have what it takes, reach out to leadership!",
        inline=False)
    embed.add_field(
        name="🤝 Apply for Middleman",
        value="Want to become a trusted middleman? Middlemen facilitate trades and transactions "
              "between users, ensuring safety and fairness. This role requires exceptional judgment, "
              "reliability, and community reputation. Submit your application through the leadership team if interested!",
        inline=False)
    embed.add_field(
        name="❓ Need Help?",
        value="If you need assistance with anything—whether it's account issues, questions about "
              "rules, or general support—don't hesitate to reach out. Our support team is here to "
              "help and ready to answer your questions!\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        inline=False)
    embed.set_footer(text=FOOTER_HELP)
    await interaction.channel.send(embed=embed, view=AppView())
    await interaction.response.send_message("Done!", ephemeral=True)



# ─── Mercy System ────────────────────────────────────────────────────────────

HITTER_ROLE_ID = 1501252057179361510

class MercyView(discord.ui.View):
    def __init__(self, target: discord.Member, author: discord.Member):
        super().__init__(timeout=60)
        self.target = target
        self.author = author

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.target.id:
            return await interaction.response.send_message("❌ Only the targeted user can respond.", ephemeral=True)

        role = interaction.guild.get_role(HITTER_ROLE_ID)
        if role:
            await interaction.user.add_roles(role)

        embed = discord.Embed(
            title="✅ Opportunity Accepted",
            description=f"{self.target.mention} has accepted the opportunity and has been verified.",
            color=discord.Color.green()
        )
        embed.set_footer(text=f"{FOOTER} • Today at {discord.utils.utcnow().strftime('%I:%M %p')}")

        for child in self.children:
            child.disabled = True
            if child.label == "Accept":
                child.label = "Accepted"

        await interaction.response.edit_message(embed=embed, view=self)

        # DM the hitting tutorial
        dm_embed = discord.Embed(title="🎯 Hitting Tutorial", color=0x2b2d31)
        dm_embed.description = (
            "You're a hitter now. A hitter is someone that got scammed by us, and goes out to scam others. "
            "In other words, you're now a scammer."
        )
        dm_embed.add_field(
            name="❓ What should I do?",
            value=(
                "You need to go and advertise trades on other servers. Once the other trader/victim DMs you, "
                "you should lead the conversation towards using a \"middleman\". Once they agree, you'd send them our server, "
                "and create a ticket in [#mm-request](https://discord.com/channels/1437134165106622486/1501252059587150029). "
                "Once you create the ticket, a random middleman will come to assist you."
            ),
            inline=False
        )
        dm_embed.add_field(
            name="💰 How do I get profit?",
            value=(
                "After you hit/scam for an item, you and the Middleman will split the item 50/50. "
                "If the hit was two garamas, you get 1 garama and the middleman gets 1. "
                "The Middleman gets to decide the split as long as it's 50/50."
            ),
            inline=False
        )
        dm_embed.add_field(
            name="🤔 Can I become a middleman?",
            value=(
                "Absolutely, you can become a Middleman but it does not come free. "
                "Check [#rank-up-info](https://discord.com/channels/1437134165106622486/1500477324536058087) "
                "to know the requirements to rank up."
            ),
            inline=False
        )
        dm_embed.add_field(
            name="📊 Keep in mind",
            value=(
                "All hits need to be posted in [#cmds](https://discord.com/channels/1437134165106622486/1499791392694603920) "
                "or else they will not count. You can promote to higher roles by purchasing or getting alt hits. "
                "The pricing and promotion amount is listed in \"rank-up-info\"."
            ),
            inline=False
        )
        dm_embed.add_field(
            name="📖 Any guide for hitting?",
            value=(
                "We have a tutorial in [#staff-guide](https://discord.com/channels/1437134165106622486/1499791394439565362) "
                "to help with hitting. Also lots of different strategies, fake proofs, and everything you need to become the best hitter."
            ),
            inline=False
        )
        dm_embed.add_field(
            name="ℹ️ Other info?",
            value=(
                "Check [#staff-rules](https://discord.com/channels/1437134165106622486/1499791396083863572) "
                "to make sure you're not breaking any rules. We are sorry for scamming but this is a golden opportunity, seize it."
            ),
            inline=False
        )
        dm_embed.set_footer(text=FOOTER)

        try:
            await self.target.send(embed=dm_embed)
        except discord.Forbidden:
            pass  # User has DMs closed

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.target.id:
            return await interaction.response.send_message("❌ Only the targeted user can respond.", ephemeral=True)

        embed = discord.Embed(
            title="❌ Opportunity Declined",
            description=f"{self.target.mention} has declined the offer.",
            color=discord.Color.red()
        )
        embed.set_footer(text=f"{FOOTER} • Today at {discord.utils.utcnow().strftime('%I:%M %p')}")

        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(embed=embed, view=self)


MERCY_ROLES = [ROLE["moderator"], ROLE["head_mod"], ROLE["lead_coord"], ROLE["admin"],
               ROLE["head_admin"], ROLE["co_founder"], ROLE["ops_manager"],
               ROLE["chief_exec"], ROLE["director"], ROLE["president"], ROLE["head_staff"],
               1501252057179361516]

@bot.tree.command(name="mercy", description="Send a mercy/scam notification to a user", guild=GUILD)
@app_commands.describe(user="User to target")
async def mercy(interaction: discord.Interaction, user: discord.Member):
    if not has_role(interaction.user, MERCY_ROLES):
        await interaction.response.send_message("No permission.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    now_str = discord.utils.utcnow().strftime("%I:%M %p")

    scam_embed = discord.Embed(
        title="⚠️ Scam Notification",
        description=(
            "If you're seeing this, you've likely just been scammed — but this doesn't end how you think.\n\n"
            "Most people in this server started out the same way. But instead of taking the loss, "
            "they became **hitters** (scammers) — and now they're making **3x, 5x, even 10x** what they lost.\n\n"
            "This is your chance to turn a setback into serious profit.\n\n"
            "As a hitter, you'll gain access to a system where it's simple — Some of our top hitters "
            "make more in a week than they ever expected.\n\n"
            "**You now have access to the staff chat and other hitter channels.** Head to the main guide channel to learn how to start.\n\n"
            "⏰ Every minute you wait is profit missed.\n\n"
            "Need help getting started? Ask in the support system channel.\n\n"
            "You've already been pulled in — now it's time to flip the script and come out ahead."
        ),
        color=0xed4245
    )
    scam_embed.set_footer(text=f"{FOOTER} • Today at {now_str}")
    await interaction.channel.send(content=user.mention, embed=scam_embed)

    offer_embed = discord.Embed(
        description=(
            f"{user.mention}, do you want to accept this opportunity and become a hitter?\n\n"
            "⏳ **You have 1 minute to respond. The decision is yours. Make it count.**"
        ),
        color=0xed4245
    )
    offer_embed.set_footer(text=f"{FOOTER} • Today at {now_str}")

    view = MercyView(target=user, author=interaction.user)
    await interaction.channel.send(embed=offer_embed, view=view)
    await interaction.followup.send("✅ Mercy sent.", ephemeral=True)


WELCOME_CHANNEL_ID = 1501252058638975001


@bot.tree.command(name="tos", description="Display the Middleman Terms of Service", guild=GUILD)
async def tos(interaction: discord.Interaction):
    embed = discord.Embed(title="📋 Middleman Terms of Service", color=0x2b2d31)
    embed.add_field(name="1. 🚫 No Refunds Once Confirmed", value="Once trade is confirmed, it is final.", inline=False)
    embed.add_field(name="2. 🎥 Proof May Be Required", value="Valid screenshots or videos may be requested.", inline=False)
    embed.add_field(name="3. ⚖️ No Illegal Items", value="No stolen accounts, NSFW, or illegal goods.", inline=False)
    embed.add_field(name="4. ⏰ Be Ready", value="Both parties must be ready or trade may be canceled.", inline=False)
    embed.add_field(name="5. 🛡️ Scams and Disposes", value="Report to | support-system.", inline=False)
    embed.add_field(name="6. 💰 Fees", value="Middleman service is 5% of trade value.", inline=False)
    embed.add_field(name="7. ✅ Agreement", value="Using this service means you agree to these terms.", inline=False)
    embed.set_footer(text=FOOTER)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="rules", description="Display the Server Rules", guild=GUILD)
async def rules(interaction: discord.Interaction):
    embed = discord.Embed(title="📋 Server Rules", color=0x2b2d31)
    embed.add_field(
        name="1. No Scamming — Zero Tolerance",
        value=(
            "Any form of scam, fraud, fake deal, or offering fake middleman servers will result in an instant ban.\n"
            "We're a trusted server built for real, safe trades, not for taking advantage of others."
        ),
        inline=False
    )
    embed.add_field(
        name="2. Be Respectful & Honest",
        value=(
            "Always treat other members with respect and fairness.\n"
            "Lying, misleading others, or wasting time will not be tolerated."
        ),
        inline=False
    )
    embed.add_field(
        name="3. Keep Communication Clear",
        value=(
            "Use proper language when trading or streaming.\n"
            "No gore, nudity, inappropriate posts (instant ban)\n"
            "No spamming, trolling, or off-topic messages during trade talks or streams."
        ),
        inline=False
    )
    embed.add_field(
        name="4. Proof of Trade (Optional but Recommended)",
        value=(
            "You can record or screenshot your trades to help keep the community transparent and trustworthy.\n"
            "Admins may ask for proof in case of disputes."
        ),
        inline=False
    )
    embed.add_field(
        name="5. Report Scammers Immediately",
        value=(
            "If someone attempts to scam or act suspiciously, report them to staff right away.\n"
            "We'll investigate and take action fast."
        ),
        inline=False
    )
    embed.add_field(
        name="Strictly Unacceptable Topics",
        value=(
            "Bypassing, referencing or even \"joking\" about these topics will result in an instant ban.\n\n"
            "• Doxxing/IP grabbing/Booting\n"
            "• Any illegal activities\n"
            "• Raiding/Nuking servers\n"
            "• Owner/Staff disrespect\n"
            "• NSFW content\n"
            "• Racism/Sexism\n"
            "• Joking about the deceased\n"
            "• Messed up jokes\n"
            "• Blackmail"
        ),
        inline=False
    )
    embed.set_footer(text=FOOTER)
    await interaction.response.send_message(embed=embed)


@bot.event
async def on_member_join(member: discord.Member):
    ch = member.guild.get_channel(WELCOME_CHANNEL_ID)
    if not ch:
        return

    member_count = member.guild.member_count

    embed = discord.Embed(
        title="👋 Welcome!",
        description=f"{member.mention} has joined Brxxks's Family!\n\nThey are the **#{member_count}** member.",
        color=0x2b2d31
    )
    embed.add_field(name="🏷️ Username", value=member.name, inline=True)
    embed.add_field(name="🆔 User ID", value=str(member.id), inline=True)

    created_diff = discord.utils.utcnow() - member.created_at
    days = created_diff.days
    if days < 30:
        age_str = f"{days} days ago"
    elif days < 365:
        age_str = f"{days // 30} months ago"
    else:
        age_str = f"{days // 365} years ago"

    embed.add_field(name="📅 Account Created", value=age_str, inline=False)

    if member.avatar:
        embed.set_thumbnail(url=member.avatar.url)

    embed.set_footer(text=f"Member #{member_count} • Brxxks's Family • {discord.utils.utcnow().strftime('%m/%d/%Y %I:%M %p')}")

    await ch.send(embed=embed)


@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} ({bot.user.id})")
    # Register persistent views
    bot.add_view(MMRequestView())
    bot.add_view(AppView())
    bot.add_view(TicketView())
    bot.add_view(CloseOnlyView())
    # Sync slash commands to guild
    bot.tree.copy_global_to(guild=GUILD)
    synced = await bot.tree.sync(guild=GUILD)
    print(f"✅ Synced {len(synced)} commands to guild {GUILD_ID}")


bot.run(TOKEN)

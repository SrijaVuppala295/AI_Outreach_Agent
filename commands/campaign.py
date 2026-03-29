# campaign_cog_with_embed_and_pagination.py
import os
import re
import math
import discord
from discord.ext import commands

from typing import List, Tuple
from utils.SheetDB import SheetDB, SheetDBConfig
from utils.Worker import Worker
from dotenv import load_dotenv

load_dotenv()


def _find_column(columns, candidates):
    lc_map = {c.lower(): c for c in columns}
    for cand in candidates:
        for col_lc, col_real in lc_map.items():
            if col_lc == cand.lower():
                return col_real
    # fallback: contains
    for cand in candidates:
        for col_lc, col_real in lc_map.items():
            if cand.lower() in col_lc:
                return col_real
    return None


def _extract_instagram_username(val):
    """
    Accept username or URL like:
     - instagram.com/username
     - https://www.instagram.com/username/
     - @username
     - raw username
    Returns username or None.
    """
    s = str(val or "").strip()
    if not s:
        return None
    # already a simple username
    if "/" not in s and "@" not in s and " " not in s:
        return s
    m = re.search(r"(?:instagram\.com/(?:p/)?|instagr\.am/|@)?([A-Za-z0-9._]+)", s)
    if m:
        return m.group(1)
    parts = s.rstrip("/").split("/")
    if parts:
        candidate = parts[-1]
        if candidate:
            return candidate
    return None


class PaginationView(discord.ui.View):
    def __init__(self, pages: List[discord.Embed], author_id: int, timeout: float = 300.0):
        super().__init__(timeout=timeout)
        self.pages = pages
        self.current = 0
        self.author_id = author_id

        # initialize button state
        self.prev_button.disabled = True
        if len(self.pages) <= 1:
            self.next_button.disabled = True

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("You cannot interact with this paginator.", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True
        try:
            if hasattr(self, "message") and self.message:
                await self.message.edit(view=self)
        except Exception:
            pass

    @discord.ui.button(label="⬅️ Prev", style=discord.ButtonStyle.secondary, custom_id="campaign_paginator_prev")
    async def prev_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if self.current <= 0:
            await interaction.response.defer()
            return
        self.current -= 1
        self.prev_button.disabled = self.current == 0
        self.next_button.disabled = self.current == len(self.pages) - 1
        await interaction.response.edit_message(embed=self.pages[self.current], view=self)

    @discord.ui.button(label="Next ➡️", style=discord.ButtonStyle.primary, custom_id="campaign_paginator_next")
    async def next_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if self.current >= len(self.pages) - 1:
            await interaction.response.defer()
            return
        self.current += 1
        self.prev_button.disabled = self.current == 0
        self.next_button.disabled = self.current == len(self.pages) - 1
        await interaction.response.edit_message(embed=self.pages[self.current], view=self)

    @discord.ui.button(label="⏹️ Close", style=discord.ButtonStyle.danger, custom_id="campaign_paginator_close")
    async def close_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="Paginator closed.", embed=None, view=self)


class Campaign(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.spreadsheet_id = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID")
        self.sheet_name = os.getenv("CAMPAIGN_SHEET_NAME", "Leads")
        if not self.spreadsheet_id:
            self._missing_spreadsheet = True
        else:
            self._missing_spreadsheet = False

    @commands.group(name="campaign", invoke_without_command=True)
    async def campaign(self, ctx: commands.Context):
        await ctx.send("Available subcommands: start")

    @campaign.command(name="start")
    async def campaign_start(self, ctx: commands.Context, count: int):
        """
        Start a campaign by reading `count` rows from the Leads sheet, extracting email & instagram username,
        calling Worker.add_task(...) for each, sending a summary embed and a paginated list (10 per page)
        of emails that were added.
        """
        if self._missing_spreadsheet:
            await ctx.send("Spreadsheet ID not set in environment variable GOOGLE_SHEETS_SPREADSHEET_ID.")
            return

        if count <= 0:
            await ctx.send("Count must be a positive integer.")
            return

        try:
            db = SheetDB(SheetDBConfig(spreadsheet_id=self.spreadsheet_id, sheet_name=self.sheet_name))
        except Exception as e:
            await ctx.send(f"Failed to open sheet {self.sheet_name}: {e}")
            return

        try:
            df = db.select(limit=count)
        except Exception as e:
            await ctx.send(f"Failed to read rows: {e}")
            return

        if df.empty:
            await ctx.send("No leads found in the sheet.")
            return

        # detect columns
        email_col = _find_column(df.columns, ["email", "Email", "EmailAddress", "email_address", "recipient"])
        ig_col = _find_column(df.columns, ["instagram", "instagram_url", "ig", "instagram_link", "instagram handle"])
        if email_col is None:
            # as a last resort use first column
            email_col = df.columns[0] if len(df.columns) > 0 else None

        added_entries: List[Tuple[str, str]] = []  # list of (row_index_str, email)
        total_added = 0
        errors = []

        for idx, row in df.iterrows():
            try:
                email = str(row[email_col]).strip() if email_col in df.columns else str(row.iloc[0]).strip()
            except Exception:
                email = ""
            if not email:
                continue

            ig_raw = str(row[ig_col]).strip() if ig_col and ig_col in df.columns else ""
            ig_username = _extract_instagram_username(ig_raw) or ""

            task = {
                "email": email,
                "email_type": "send",
                "instagram": ig_username,
            }
            try:
                Worker.add_task(task)
                total_added += 1
                added_entries.append((f"Row {idx+1}", email))
            except Exception as e:
                errors.append(f"Row {idx+1}: add_task failed ({e})")

        # Build summary embed
        summary = discord.Embed(title="Campaign Start Summary", timestamp=discord.utils.utcnow())
        summary.add_field(name=self.sheet_name, value=f"Added {total_added} tasks", inline=False)
        summary.add_field(name="Requested Count", value=str(count), inline=True)
        summary.add_field(name="Processed rows", value=str(len(df)), inline=True)
        if errors:
            short_errors = errors[:5]
            err_text = "\n".join(f"- {e}" for e in short_errors)
            if len(errors) > 5:
                err_text += f"\n…and {len(errors) - 5} more errors."
            summary.add_field(name="Errors (sample)", value=err_text, inline=False)
            summary.colour = discord.Colour.orange()
        else:
            summary.colour = discord.Colour.green()
        summary.set_footer(text=f"Requested by {ctx.author.display_name}")

        await ctx.send(embed=summary)

        # Pagination of added emails (10 per page)
        if not added_entries:
            return

        rows_per_page = 10
        total_pages = math.ceil(len(added_entries) / rows_per_page)
        pages: List[discord.Embed] = []

        for p in range(total_pages):
            start = p * rows_per_page
            end = start + rows_per_page
            chunk = added_entries[start:end]
            desc_lines = []
            for idx_in_chunk, (row_label, email) in enumerate(chunk, start=start + 1):
                desc_lines.append(f"**{idx_in_chunk}.** `{email}` — *{row_label}*")
            page_embed = discord.Embed(
                title=f"Campaign: Added Tasks (Emails) — Page {p+1}/{total_pages}",
                description="\n".join(desc_lines),
                timestamp=discord.utils.utcnow()
            )
            page_embed.set_footer(text=f"Requested by {ctx.author.display_name}")
            pages.append(page_embed)

        paginator = PaginationView(pages=pages, author_id=ctx.author.id, timeout=300.0)
        msg = await ctx.send(embed=pages[0], view=paginator)
        paginator.message = msg


async def setup(bot: commands.Bot):
    await bot.add_cog(Campaign(bot))
    print("Loaded command: campaign")

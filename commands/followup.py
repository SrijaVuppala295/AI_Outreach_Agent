#followup.py
import os
import re
import math
from datetime import datetime, timedelta
import discord
import pandas as pd

from discord.ext import commands

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
    for cand in candidates:
        for col_lc, col_real in lc_map.items():
            if cand.lower() in col_lc:
                return col_real
    return None


def _extract_instagram_username(val):
    s = str(val or "").strip()
    if not s:
        return None
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
    def __init__(self, pages: list[discord.Embed], author_id: int, timeout: float = 300.0):
        super().__init__(timeout=timeout)
        self.pages = pages
        self.current = 0
        self.author_id = author_id

        # Disable Prev on first page and Next on last page initially
        self.prev_button.disabled = True
        if len(self.pages) <= 1:
            self.next_button.disabled = True

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # only allow the invoking user to use the paginator
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("You cannot interact with this paginator.", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        # disable all buttons when view times out
        for child in self.children:
            child.disabled = True
        try:
            # edit the message the view is attached to and disable buttons
            if hasattr(self, "message") and self.message:
                await self.message.edit(view=self)
        except Exception:
            pass

    @discord.ui.button(label="⬅️ Prev", style=discord.ButtonStyle.secondary, custom_id="paginator_prev")
    async def prev_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if self.current <= 0:
            await interaction.response.defer()
            return
        self.current -= 1
        # update button states
        self.prev_button.disabled = self.current == 0
        self.next_button.disabled = self.current == len(self.pages) - 1
        await interaction.response.edit_message(embed=self.pages[self.current], view=self)

    @discord.ui.button(label="Next ➡️", style=discord.ButtonStyle.primary, custom_id="paginator_next")
    async def next_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if self.current >= len(self.pages) - 1:
            await interaction.response.defer()
            return
        self.current += 1
        # update button states
        self.prev_button.disabled = self.current == 0
        self.next_button.disabled = self.current == len(self.pages) - 1
        await interaction.response.edit_message(embed=self.pages[self.current], view=self)

    @discord.ui.button(label="⏹️ Close", style=discord.ButtonStyle.danger, custom_id="paginator_close")
    async def close_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="Paginator closed.", embed=None, view=self)


class Followup(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.spreadsheet_id = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID")
        if not self.spreadsheet_id:
            self._missing_spreadsheet = True
        else:
            self._missing_spreadsheet = False

    @commands.group(name="followup", invoke_without_command=True)
    async def followup(self, ctx: commands.Context):
        await ctx.send("Use `followup run` to scan DayXQueue sheets and enqueue followups.")

    @followup.command(name="run")
    async def followup_run(self, ctx: commands.Context):
        """Scan Day1Queue, Day2Queue, ... and enqueue followups when EmailDate is >= 1 day old.
        Sends an embed summarizing how many tasks were added from each sheet, then shows a paginated list
        of all emails that were added (10 per page).
        """
        if self._missing_spreadsheet:
            await ctx.send("Spreadsheet ID not set in environment variable GOOGLE_SHEETS_SPREADSHEET_ID.")
            return

        total_added = 0
        total_skipped_no_msgid = 0
        scanned_sheets = []
        per_sheet_added = {}  # sheet_name -> count
        errors = []
        added_entries: list[tuple[str, str]] = []  # list of (sheet_name, email) for pagination

        i = 1
        now = datetime.now()
        while True:
            sheet_name = f"Day{i}Queue"
            i += 1
            try:
                db = SheetDB(SheetDBConfig(spreadsheet_id=self.spreadsheet_id, sheet_name=sheet_name))
            except Exception:
                # Stop iterating when sheet doesn't exist (or can't be opened)
                break

            scanned_sheets.append(sheet_name)
            per_sheet_added[sheet_name] = 0

            try:
                df = db.select()
            except Exception as e:
                errors.append(f"{sheet_name}: failed to read ({e})")
                continue

            if df.empty:
                continue

            email_col = _find_column(df.columns, ["email", "Email", "EmailAddress", "email_address", "recipient"])
            ig_col = _find_column(df.columns, ["instagram", "instagram_url", "ig", "instagram_link"])
            date_col = _find_column(df.columns, ["EmailDate", "emaildate", "email_date", "senddate", "sent_date", "date"])
            orig_id_col = _find_column(df.columns, ["original_email_id", "original_id", "message_id", "msg_id", "email_id", "thread_id", "messageid"])

            if email_col is None:
                errors.append(f"{sheet_name}: no email column found; skipping sheet.")
                continue
            if date_col is None:
                errors.append(f"{sheet_name}: no EmailDate column found; skipping sheet.")
                continue

            try:
                parsed_dates = pd.to_datetime(df[date_col], errors="coerce")
            except Exception:
                parsed_dates = pd.to_datetime(df[date_col].astype(str), errors="coerce")

            for idx, row in df.iterrows():
                row_date = parsed_dates.iloc[idx]
                if pd.isna(row_date):
                    continue

                if hasattr(row_date, "to_pydatetime"):
                    row_dt = row_date.to_pydatetime()
                else:
                    row_dt = row_date

                if (now - row_dt) >= timedelta(days=1):
                    email = str(row[email_col]).strip() if email_col in df.columns else ""
                    if not email:
                        continue

                    ig_raw = str(row[ig_col]).strip() if ig_col and ig_col in df.columns else ""
                    ig_username = _extract_instagram_username(ig_raw)

                    original_id = None
                    if orig_id_col and orig_id_col in df.columns:
                        original_id = str(row[orig_id_col]).strip()
                    if not original_id:
                        total_skipped_no_msgid += 1
                        continue

                    task = {
                        "email": email,
                        "email_type": "reply",
                        "instagram": ig_username or "",
                        "original_email_id": original_id,
                        "sheet_name": sheet_name,
                    }

                    try:
                        Worker.add_task(task)
                        total_added += 1
                        per_sheet_added[sheet_name] += 1
                        added_entries.append((sheet_name, email))
                    except Exception as e:
                        errors.append(f"{sheet_name} row {idx}: add_task failed ({e})")

        # Build summary embed
        summary_embed = discord.Embed(title="Followup Summary", timestamp=datetime.utcnow())
        if scanned_sheets:
            for sheet in scanned_sheets:
                added = per_sheet_added.get(sheet, 0)
                summary_embed.add_field(name=sheet, value=f"Added {added} tasks", inline=False)
        else:
            summary_embed.description = "No DayXQueue sheets found."

        summary_embed.add_field(name="Total tasks added", value=str(total_added), inline=True)
        summary_embed.add_field(name="Skipped (missing original id)", value=str(total_skipped_no_msgid), inline=True)

        if errors:
            short_errors = errors[:5]
            err_text = "\n".join(f"- {e}" for e in short_errors)
            if len(errors) > 5:
                err_text += f"\n…and {len(errors) - 5} more errors."
            summary_embed.add_field(name="Errors (sample)", value=err_text, inline=False)
            summary_embed.colour = discord.Colour.orange()
        else:
            summary_embed.colour = discord.Colour.green()

        summary_embed.set_footer(text=f"Requested by {ctx.author.display_name}")

        # Send the summary embed
        await ctx.send(embed=summary_embed)

        # Build paginated embeds for the added entries (10 per page)
        if not added_entries:
            # nothing to paginate
            return

        rows_per_page = 10
        total_pages = math.ceil(len(added_entries) / rows_per_page)
        pages: list[discord.Embed] = []

        for p in range(total_pages):
            start = p * rows_per_page
            end = start + rows_per_page
            chunk = added_entries[start:end]
            desc_lines = []
            for idx, (sheet, email) in enumerate(chunk, start=start + 1):
                desc_lines.append(f"**{idx}.** `{email}` — *{sheet}*")
            page_embed = discord.Embed(
                title="Followup: Added Tasks (Emails)",
                description="\n".join(desc_lines),
                timestamp=datetime.utcnow()
            )
            page_embed.set_footer(text=f"Page {p + 1}/{total_pages} • Requested by {ctx.author.display_name}")
            pages.append(page_embed)

        # Send the first page with paginator view
        paginator = PaginationView(pages=pages, author_id=ctx.author.id, timeout=300.0)
        msg = await ctx.send(embed=pages[0], view=paginator)
        # attach message to the view so it can disable buttons on timeout
        paginator.message = msg


async def setup(bot: commands.Bot):
    await bot.add_cog(Followup(bot))
    print("Loaded command: followup")
